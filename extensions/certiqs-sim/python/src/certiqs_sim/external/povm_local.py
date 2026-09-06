"""In-process POVM backend built on ``receiver_lib``.

``receiver_lib`` (package ``simulation-rx-povm``) is the computational library
that the ``rx-povm`` microservice wraps.  When it is importable the twin can
compute receiver POVMs directly, with no container, no gRPC round trip and no
x86 emulation — the service path in :mod:`certiqs_sim.external.povm_client`
remains available and unchanged.

``receiver_lib`` is vendored at ``src/receiver_lib`` (see its ``VENDORED.md``),
so the source always ships with the project.  Its third-party requirements are
optional and heavy — ``pip install -e '.[povm-local]'`` — and everything here
degrades gracefully when they are absent.

Two details make this agree with the service exactly:

* **Detector efficiency is folded into G.**  The receiver model sent over gRPC
  uses ``PRE_DETECTOR_OPTICAL`` semantics, so the instrument matrix carries the
  optics only and per-detector efficiency travels separately in
  ``DetectorParameters``.  ``receiver_lib`` has no such split — it expects η
  already applied, scaling output row *y* by ``sqrt(η_y)`` exactly as its own
  :func:`receiver_lib.build_bb84_receiver_optics` does.  Skipping this step
  silently returns POVMs a factor 1/η too large.
* **The LED mean photon number is split evenly across polarisations**, so an
  unpolarised emitter of total n̄ becomes ``n_H = n_V = n̄/2`` — matching what the
  service does with :class:`~certiqs_sim.core.config_models.LedSaltConfig`.

Only the single-photon block is extracted, matching the service path: the twin
measures a two-qubit polarisation state, and dark counts, dead time and
afterpulsing stay in :meth:`OpticalReceiver.realize_event`.
"""

from __future__ import annotations

import threading
from typing import Any

import numpy as np

from certiqs_sim.core.config_models import ReceiverConfig
from certiqs_sim.core.linalg import hermitian_psd_clip
from certiqs_sim.external.povm_client import (
    PovmServiceError,
    PovmSet,
    build_instrument_matrix,
    dark_count_probability,
)
from certiqs_sim.telemetry.logging import get_logger

_log = get_logger("certiqs.povm.local")

#: Detector row order used by ``receiver_lib`` (rows 0..3 of G) mapped onto the
#: twin's click labels.  The library calls the diagonal basis +/- where the twin
#: calls it D/A.
_ROW_LABELS: tuple[str, ...] = ("H", "V", "D", "A")

#: ``receiver_lib`` outcome key -> twin click label.
_OUTCOME_KEY_TO_LABEL: dict[str, str] = {
    "noclick": "no_click",
    "single_click_H": "H",
    "single_click_V": "V",
    "single_click_+": "D",
    "single_click_-": "A",
    "multiclick": "multi_click",
}


def is_available() -> bool:
    """True when ``receiver_lib`` and its dependencies can be imported."""
    try:
        import receiver_lib  # noqa: F401
    except Exception:
        return False
    return True


def receiver_lib_version() -> str | None:
    try:
        import receiver_lib

        return str(getattr(receiver_lib, "__version__", "unknown"))
    except Exception:
        return None


def effective_instrument_matrix(
    cfg: ReceiverConfig, transmission_eta: float
) -> np.ndarray:
    """The 4x4 instrument matrix with per-detector quantum efficiency folded in.

    :func:`~certiqs_sim.external.povm_client.build_instrument_matrix` returns the
    pre-detector optical matrix.  ``receiver_lib`` expects efficiency already
    applied, as a ``sqrt(η_y)`` scaling of output row *y*.
    """
    g = build_instrument_matrix(cfg, transmission_eta)
    eta = np.array(
        [min(max(float(cfg.detectors[label].efficiency), 0.0), 1.0) for label in _ROW_LABELS],
        dtype=float,
    )
    return g * np.sqrt(eta)[:, None]


class LocalPovmBackend:
    """Compute receiver POVMs in-process via ``receiver_lib``.

    Exposes the same ``povm_elements`` surface as
    :class:`~certiqs_sim.external.povm_client.RxPovmClient` so the two are
    interchangeable behind ``OpticalReceiver.povm_provider``.
    """

    def __init__(self, *, cutoff_dim: int = 1, method: str = "analytic") -> None:
        if int(cutoff_dim) < 1:
            raise ValueError("cutoff_dim must be at least 1 to extract the n=1 block")
        self.cutoff_dim = int(cutoff_dim)
        self.method = method
        self._cache: dict[tuple, PovmSet] = {}
        self._lock = threading.Lock()

    # -- lifecycle parity with the gRPC client -------------------------------
    def close(self) -> None:
        with self._lock:
            self._cache.clear()

    # -- POVM retrieval -------------------------------------------------------
    def povm_elements(
        self,
        cfg: ReceiverConfig,
        transmission_eta: float,
        *,
        coincidence_window_ps: float,
        led_firing: bool = False,
        include_dark_counts: bool = False,
    ) -> PovmSet:
        from certiqs_sim.external.povm_client import RxPovmClient

        key = (
            *RxPovmClient._fingerprint(
                cfg, transmission_eta, coincidence_window_ps, led_firing
            ),
            bool(include_dark_counts),
            self.cutoff_dim,
            self.method,
        )
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit

        result = self._compute(
            cfg,
            transmission_eta,
            coincidence_window_ps=coincidence_window_ps,
            led_firing=led_firing,
            include_dark_counts=include_dark_counts,
        )
        with self._lock:
            self._cache[key] = result
        return result

    def _led_input_state(self, cfg: ReceiverConfig, *, firing: bool) -> Any:
        """Thermal ``States`` for an LED-on round, else None (vacuum)."""
        if not firing or not cfg.led.enabled:
            return None
        n_h, n_v = cfg.led.per_mode_means()
        if n_h <= 0.0 and n_v <= 0.0:
            return None

        from receiver_lib.states import States

        state = States()
        state.product(
            argsC={"type": "vacuum"},
            argsL={"type": "thermal", "n_H": n_h, "n_V": n_v},
        )
        return state

    def _compute(
        self,
        cfg: ReceiverConfig,
        transmission_eta: float,
        *,
        coincidence_window_ps: float,
        led_firing: bool,
        include_dark_counts: bool,
    ) -> PovmSet:
        try:
            from receiver_lib import LinearOptics, QutipPOVM_G
            from receiver_lib.povms import apply_dark_count_postprocessing
            from receiver_lib.states import make_mode_manager
        except Exception as exc:  # pragma: no cover - optional dependency
            raise PovmServiceError(
                "receiver_lib could not be imported; install its requirements with "
                "pip install -e '.[povm-local]'"
            ) from exc

        g_eff = effective_instrument_matrix(cfg, transmission_eta)
        try:
            optics = LinearOptics(N_out=4, N_C=2, N_L=2, custom_matrix=g_eff)
        except Exception as exc:
            raise PovmServiceError(f"receiver_lib rejected the instrument matrix: {exc}") from exc

        mode_manager = make_mode_manager(optics.N_C, optics.N_L)
        simulator = QutipPOVM_G(self.cutoff_dim, optics, mode_manager=mode_manager)

        common = {
            "active_modes": "channel_only",
            "led_input_state": self._led_input_state(cfg, firing=led_firing),
            "output_format": "numpy",
            "force_partial_trace": self.method == "partial_trace",
        }

        try:
            raw: dict[str, Any] = {
                "noclick": simulator.get_noclick_operator_qutip(
                    return_for_single_n=1, **common
                ),
                "multiclick": simulator.get_multiclick_operator_qutip(
                    return_for_single_n=1, **common
                ),
            }
            for index, label in enumerate(_ROW_LABELS):
                key = "single_click_" + ("+" if label == "D" else "-" if label == "A" else label)
                raw[key] = simulator.get_single_click_operator_qutip(
                    output_idx=index, return_for_single_n=1, **common
                )
        except Exception as exc:
            raise PovmServiceError(f"receiver_lib POVM evaluation failed: {exc}") from exc

        if include_dark_counts:
            rates = [
                dark_count_probability(cfg.detectors[label].dark_count_hz, coincidence_window_ps)
                for label in _ROW_LABELS
            ]
            raw = apply_dark_count_postprocessing(raw, rates)

        elements: dict[str, np.ndarray] = {}
        for outcome_key, matrix in raw.items():
            mapped = _OUTCOME_KEY_TO_LABEL.get(outcome_key)
            if mapped is None:
                continue
            elements[mapped] = hermitian_psd_clip(np.asarray(matrix, dtype=complex))

        missing = {"H", "V", "D", "A", "no_click"} - set(elements)
        if missing:
            raise PovmServiceError(
                f"receiver_lib returned no n=1 block for outcome(s) {sorted(missing)}"
            )

        # ``multi_click`` is kept as its own outcome rather than folded into
        # no-click, matching what the service returns. With the LED firing it
        # carries real weight — LED photons arriving alongside the signal fire a
        # second detector — and ``realize_event`` discards multi-clicks anyway,
        # so the two must not be merged here.
        total = sum(elements.values())
        residual = float(np.max(np.abs(total - np.eye(2))))

        return PovmSet(elements=elements, completeness_residual=residual)


def attach_local_povm(
    twin: Any,
    *,
    cutoff_dim: int = 1,
    strict: bool = False,
) -> LocalPovmBackend:
    """Route a twin's receivers through the in-process ``receiver_lib`` backend."""
    backend = LocalPovmBackend(cutoff_dim=cutoff_dim)
    window_ps = float(getattr(twin.timing, "coincidence_window_ps", 0.0))
    for receiver in (twin.alice, twin.bob):
        receiver.povm_provider = backend
        receiver.povm_strict = strict
        receiver.coincidence_window_ps = window_ps
    _log.info(
        "povm_local_attached",
        receiver_lib_version=receiver_lib_version(),
        cutoff_dim=cutoff_dim,
        strict=strict,
        coincidence_window_ps=window_ps,
    )
    return backend


__all__ = [
    "LocalPovmBackend",
    "attach_local_povm",
    "effective_instrument_matrix",
    "is_available",
    "receiver_lib_version",
]
