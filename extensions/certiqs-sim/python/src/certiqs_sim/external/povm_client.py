"""Client for the ``rx-povm`` theory microservice.

Maps a :class:`~certiqs_sim.core.config_models.ReceiverConfig` onto the service's
``ReceiverModel`` and turns the streamed ``BuildPovm`` response into the 2x2
single-photon POVM elements the twin measures with.

Conventions confirmed against the live service (``GetCapabilities`` reports
``supported_receiver_dimensions: "4x2"``):

* ``instrument_matrix_g`` is 4x2 — rows are the detector modes (H, V, +, -),
  columns the input polarisation modes (H, V).  Row *i* holds the *amplitudes*
  mapping an input polarisation to detector *i*, so ``G**G <= I`` expresses
  optical loss.
* Semantics are ``PRE_DETECTOR_OPTICAL``: G carries the optical network only
  (channel transmission, coupler, basis BS routing, PBS, HWP).  Per-detector
  quantum efficiency travels separately in ``DetectorParameters``.
* For a lossless ideal receiver the service returns ``E_H = 0.5|H><H|`` etc.,
  summing to the identity — structurally identical to the local analytic model.

Two deliberate modelling notes:

* **PBS leakage is coherent here.**  The local analytic model mixes projectors
  incoherently (``(1-eps) P_H + eps P_V``).  A linear instrument matrix can only
  express *amplitude* leakage, which additionally carries a cross term.  A real
  polarising beamsplitter is a coherent device, so the G form is the more
  physical of the two; the difference is quantified by the validation sweep.
* **HWP angle jitter is not resampled per shot.**  The local model draws a fresh
  Gaussian angle error on every call.  Doing that here would mean one gRPC round
  trip per shot, so the nominal angle is used.  The shipped configuration sets
  declare no retardance error, making this exact for them; a warning is logged
  when a non-zero sigma is configured.
"""

from __future__ import annotations

import hashlib
import math
import struct
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from certiqs_sim.core.config_models import ReceiverConfig
from certiqs_sim.core.linalg import db_to_efficiency, hermitian_psd_clip
from certiqs_sim.telemetry.logging import get_logger

_log = get_logger("certiqs.povm")

#: Service outcome enum value -> the twin's click label.
_OUTCOME_VALUE_TO_LABEL: dict[int, str] = {
    1: "no_click",
    2: "H",
    3: "V",
    4: "D",
    5: "A",
    6: "multi_click",
}

#: The four click outcomes, in the order the receiver model declares them.
_DETECTOR_OUTCOME_VALUES: tuple[int, ...] = (2, 3, 4, 5)
_LABEL_FOR_DETECTOR_OUTCOME: dict[str, int] = {"H": 2, "V": 3, "D": 4, "A": 5}


class PovmServiceError(RuntimeError):
    """Raised when the POVM service cannot supply usable POVM elements."""


# ── protobuf <-> numpy ────────────────────────────────────────────────────────
def matrix_to_proto(matrix: np.ndarray) -> Any:
    from qkd.security.theory.common.v1 import common_pb2

    arr = np.asarray(matrix, dtype=np.complex128)
    rows, cols = arr.shape
    floats = np.empty(rows * cols * 2, dtype=np.float64)
    floats[0::2] = arr.real.reshape(-1)
    floats[1::2] = arr.imag.reshape(-1)
    payload = struct.pack(f"<{rows * cols * 2}d", *floats.tolist())
    return common_pb2.ComplexMatrix(
        rows=rows,
        columns=cols,
        payload=payload,
        sha256_checksum=hashlib.sha256(payload).digest(),
    )


def matrix_from_proto(cm: Any) -> np.ndarray:
    count = int(cm.rows) * int(cm.columns)
    if count == 0:
        return np.zeros((int(cm.rows), int(cm.columns)), dtype=np.complex128)
    floats = np.array(struct.unpack(f"<{count * 2}d", cm.payload), dtype=np.float64)
    return (floats[0::2] + 1j * floats[1::2]).reshape(int(cm.rows), int(cm.columns))


# ── receiver-model construction ───────────────────────────────────────────────
def build_instrument_matrix(cfg: ReceiverConfig, transmission_eta: float) -> np.ndarray:
    """Build the 4x4 pre-detector optical matrix G for ``cfg``.

    Rows are the detector modes (H, V, +, -); columns are the four input modes
    ``[signal_H, signal_V, led_H, led_V]``.  The basis-choice beamsplitter has two
    input ports: the signal arrives on one, and the self-test LED is injected into
    the other (normally-vacuum) port.  The lossless limit of this construction
    reproduces :func:`certiqs_sim.external.examples.ideal_bb84_g_optical` exactly,
    and the service requires the 4x4 form whenever the LED state is thermal.

    Port amplitudes follow the standard lossless-beamsplitter relations, so the
    signal transmits to the Z arm with ``sqrt(r_z)`` and reflects to the X arm with
    ``sqrt(r_x)``, while the LED port does the reverse and picks up the relative
    sign that keeps G unitary in the lossless limit.

    Channel transmission and the input coupler apply to the signal port only — the
    LED sits inside the receiver, downstream of both.  Detector quantum efficiency
    is *not* folded in; it is sent separately so the service applies it itself.
    """
    path_eta_in = db_to_efficiency(cfg.input_coupler_loss_db)
    path_eta_bs = db_to_efficiency(cfg.basis_bs_insertion_loss_db)
    path_eta_z = db_to_efficiency(cfg.z_pbs_loss_db)
    path_eta_x = db_to_efficiency(cfg.x_pbs_loss_db)

    norm = max(cfg.basis_bs_ratio_z + cfg.basis_bs_ratio_x, 1e-12)
    rz_arm = cfg.basis_bs_ratio_z / norm
    rx_arm = cfg.basis_bs_ratio_x / norm

    sig_common = min(max(float(transmission_eta) * path_eta_in * path_eta_bs, 0.0), 1.0)
    led_common = min(max(path_eta_bs, 0.0), 1.0)

    if abs(float(cfg.angle_error_deg_sigma)) > 1e-12:
        _log.warning(
            "povm_hwp_jitter_ignored",
            receiver=cfg.name,
            angle_error_deg_sigma=float(cfg.angle_error_deg_sigma),
        )
    theta = 2.0 * math.radians(cfg.angle_deg_x_hwp)
    d_bra = np.array([math.cos(theta), math.sin(theta)], dtype=np.complex128)
    a_bra = np.array([-math.sin(theta), math.cos(theta)], dtype=np.complex128)

    h_bra = np.array([1.0, 0.0], dtype=np.complex128)
    v_bra = np.array([0.0, 1.0], dtype=np.complex128)

    eps_z = min(max(float(cfg.eps_z), 0.0), 1.0)
    eps_x = min(max(float(cfg.eps_x), 0.0), 1.0)
    kz, lz = math.sqrt(1.0 - eps_z), math.sqrt(eps_z)
    kx, lx = math.sqrt(1.0 - eps_x), math.sqrt(eps_x)

    # Amplitude reaching each arm from each input port.
    sig_to_z = math.sqrt(max(rz_arm * sig_common * path_eta_z, 0.0))
    sig_to_x = math.sqrt(max(rx_arm * sig_common * path_eta_x, 0.0))
    led_to_z = math.sqrt(max(rx_arm * led_common * path_eta_z, 0.0))
    led_to_x = -math.sqrt(max(rz_arm * led_common * path_eta_x, 0.0))

    # Polarisation response of each detector within its arm.
    z_h = kz * h_bra + lz * v_bra
    z_v = lz * h_bra + kz * v_bra
    x_d = kx * d_bra + lx * a_bra
    x_a = lx * d_bra + kx * a_bra

    def row(arm_response: np.ndarray, sig_amp: float, led_amp: float) -> np.ndarray:
        return np.concatenate([sig_amp * arm_response, led_amp * arm_response])

    return np.array(
        [
            row(z_h, sig_to_z, led_to_z),  # H detector
            row(z_v, sig_to_z, led_to_z),  # V detector
            row(x_d, sig_to_x, led_to_x),  # + (D) detector
            row(x_a, sig_to_x, led_to_x),  # - (A) detector
        ],
        dtype=np.complex128,
    )


def dark_count_probability(dark_count_hz: float, window_ps: float) -> float:
    """Per-gate dark-count probability, matching the local receiver's model."""
    window_s = max(0.0, float(window_ps)) * 1e-12
    p = 1.0 - math.exp(-max(0.0, float(dark_count_hz)) * window_s)
    return min(max(p, 0.0), 1.0)


def build_receiver_model(
    cfg: ReceiverConfig,
    transmission_eta: float,
    *,
    coincidence_window_ps: float,
    model_id: str = "certiqs-bbm92",
) -> Any:
    """Assemble the service ``ReceiverModel`` for a receiver configuration."""
    from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb

    g = build_instrument_matrix(cfg, transmission_eta)
    detectors = []
    for label in ("H", "V", "D", "A"):
        det = cfg.detectors[label]
        detectors.append(
            pb.DetectorParameters(
                outcome=_LABEL_FOR_DETECTOR_OUTCOME[label],
                detection_efficiency=min(max(float(det.efficiency), 0.0), 1.0),
                dark_count_probability=dark_count_probability(
                    det.dark_count_hz, coincidence_window_ps
                ),
            )
        )

    return pb.ReceiverModel(
        model_id=model_id,
        instrument_matrix_g=matrix_to_proto(g),
        matrix_semantics=pb.INSTRUMENT_MATRIX_SEMANTICS_PRE_DETECTOR_OPTICAL,
        detectors=detectors,
        optical_model_identifier="certiqs_bbm92_receiver",
        detector_model_identifier="threshold",
    )


def build_led_state(cfg: ReceiverConfig, *, firing: bool) -> Any:
    """``LedState`` for the self-test emitter — thermal when firing, else vacuum."""
    from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb

    if not firing or not cfg.led.enabled:
        return pb.LedState(type=pb.LED_STATE_TYPE_VACUUM)
    n_h, n_v = cfg.led.per_mode_means()
    return pb.LedState(type=pb.LED_STATE_TYPE_THERMAL, n_h=n_h, n_v=n_v)


# ── the client ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PovmSet:
    """Single-photon POVM elements keyed by the twin's click labels."""

    elements: dict[str, np.ndarray]
    completeness_residual: float

    def as_measurement_povm(self) -> dict[str, np.ndarray]:
        """The mapping ``OpticalReceiver.povm_elements`` returns."""
        return dict(self.elements)


class RxPovmClient:
    """Thread-safe, caching client for the rx-povm service.

    The twin asks for POVM elements once per shot but the underlying parameters
    only change between windows, so results are memoised on the full parameter
    fingerprint; a window therefore costs one round trip, not one per shot.
    """

    def __init__(
        self,
        target: str,
        *,
        timeout_s: float = 120.0,
        max_photon_number: int = 1,
        reduction_method: str = "analytic",
    ) -> None:
        self.target = target
        self.timeout_s = float(timeout_s)
        self.max_photon_number = int(max_photon_number)
        self.reduction_method = reduction_method
        self._channel: Any = None
        self._stub: Any = None
        self._cache: dict[tuple, PovmSet] = {}
        self._lock = threading.Lock()

    # -- connection -----------------------------------------------------------
    def _get_stub(self) -> Any:
        if self._stub is None:
            import grpc

            from qkd.security.theory.rxpovm.v1 import rx_povm_pb2_grpc as pbg

            self._channel = grpc.insecure_channel(self.target)
            self._stub = pbg.RxPovmServiceStub(self._channel)
        return self._stub

    def close(self) -> None:
        with self._lock:
            if self._channel is not None:
                self._channel.close()
            self._channel = None
            self._stub = None

    def capabilities(self) -> Any:
        from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb

        return self._get_stub().GetCapabilities(
            pb.GetCapabilitiesRequest(), timeout=self.timeout_s
        )

    def validate(self, model: Any) -> Any:
        from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb

        return self._get_stub().ValidateReceiverModel(
            pb.ValidateReceiverModelRequest(receiver_model=model), timeout=self.timeout_s
        )

    # -- POVM retrieval -------------------------------------------------------
    @staticmethod
    def _fingerprint(
        cfg: ReceiverConfig,
        transmission_eta: float,
        coincidence_window_ps: float,
        led_firing: bool,
    ) -> tuple:
        dets = tuple(
            (
                label,
                round(float(cfg.detectors[label].efficiency), 12),
                round(float(cfg.detectors[label].dark_count_hz), 9),
            )
            for label in ("H", "V", "D", "A")
        )
        led = (
            bool(cfg.led.enabled and led_firing),
            round(float(cfg.led.mean_photon_number), 9),
        )
        return (
            cfg.name,
            round(float(transmission_eta), 12),
            round(float(cfg.basis_bs_ratio_z), 12),
            round(float(cfg.basis_bs_ratio_x), 12),
            round(float(cfg.input_coupler_loss_db), 9),
            round(float(cfg.basis_bs_insertion_loss_db), 9),
            round(float(cfg.z_pbs_loss_db), 9),
            round(float(cfg.x_pbs_loss_db), 9),
            round(float(cfg.eps_z), 12),
            round(float(cfg.eps_x), 12),
            round(float(cfg.angle_deg_x_hwp), 9),
            round(float(coincidence_window_ps), 9),
            dets,
            led,
        )

    def povm_elements(
        self,
        cfg: ReceiverConfig,
        transmission_eta: float,
        *,
        coincidence_window_ps: float,
        led_firing: bool = False,
        include_dark_counts: bool = False,
    ) -> PovmSet:
        """Fetch (or replay from cache) the single-photon POVM for ``cfg``.

        ``include_dark_counts`` stays False by default: the twin's own detector
        stage owns dark counts, afterpulsing and dead time, so folding them in
        here as well would double-count them.
        """
        key = self._fingerprint(cfg, transmission_eta, coincidence_window_ps, led_firing) + (
            bool(include_dark_counts),
        )
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit

        result = self._fetch(
            cfg,
            transmission_eta,
            coincidence_window_ps=coincidence_window_ps,
            led_firing=led_firing,
            include_dark_counts=include_dark_counts,
        )
        with self._lock:
            self._cache[key] = result
        return result

    def _fetch(
        self,
        cfg: ReceiverConfig,
        transmission_eta: float,
        *,
        coincidence_window_ps: float,
        led_firing: bool,
        include_dark_counts: bool,
    ) -> PovmSet:
        import grpc

        from qkd.security.theory.rxpovm.v1 import rx_povm_pb2 as pb

        model = build_receiver_model(
            cfg, transmission_eta, coincidence_window_ps=coincidence_window_ps
        )
        request = pb.BuildPovmRequest(
            receiver_model=model,
            maximum_photon_number=self.max_photon_number,
            include_dark_count_postprocessing=bool(include_dark_counts),
            include_exact_eigenvalues=False,
            led_state=build_led_state(cfg, firing=led_firing),
            reduction_method=self.reduction_method,
        )

        elements: dict[str, np.ndarray] = {}
        residual = 0.0
        try:
            for response in self._get_stub().BuildPovm(request, timeout=self.timeout_s):
                which = response.WhichOneof("payload")
                if which == "block":
                    block = response.block
                    if int(block.photon_number) != 1:
                        continue
                    label = _OUTCOME_VALUE_TO_LABEL.get(int(block.outcome))
                    if label is None:
                        continue
                    elements[label] = hermitian_psd_clip(matrix_from_proto(block.matrix))
                elif which == "summary":
                    residual = float(
                        dict(response.summary.completeness_residual_by_photon_number).get(1, 0.0)
                    )
        except grpc.RpcError as exc:  # pragma: no cover - network failure path
            raise PovmServiceError(
                f"rx-povm BuildPovm failed ({exc.code()}): {exc.details()}"
            ) from exc

        missing = {"H", "V", "D", "A"} - set(elements)
        if missing:
            raise PovmServiceError(
                f"rx-povm returned no n=1 block for outcome(s) {sorted(missing)}"
            )

        # The twin's joint sampler needs a no-click element so the outcome
        # distribution normalises; derive it when the service omits it.
        if "no_click" not in elements:
            total = sum(elements[label] for label in ("H", "V", "D", "A"))
            elements["no_click"] = hermitian_psd_clip(np.eye(2, dtype=complex) - total)

        return PovmSet(elements=elements, completeness_residual=residual)


def attach_povm_backend(
    twin: Any,
    *,
    backend: str = "auto",
    target: str = "127.0.0.1:50051",
    timeout_s: float = 120.0,
    strict: bool = False,
    cutoff_dim: int = 1,
) -> Any:
    """Attach the requested POVM source to a twin's receivers.

    ``auto`` prefers the in-process ``receiver_lib`` backend when it is
    importable and falls back to the gRPC service, so an ordinary run needs no
    container.  ``local`` and ``service`` pin one source explicitly.

    Returns the attached backend, or ``None`` when nothing is usable and
    ``strict`` is False — in which case the receivers keep the local analytic
    model they were built with.
    """
    from certiqs_sim.external import povm_local

    choice = (backend or "auto").lower()
    if choice not in ("auto", "local", "service"):
        raise ValueError(f"Unknown POVM backend {backend!r} (expected auto|local|service)")

    if choice in ("auto", "local"):
        if povm_local.is_available():
            return povm_local.attach_local_povm(twin, cutoff_dim=cutoff_dim, strict=strict)
        if choice == "local":
            message = (
                "POVM backend 'local' requested but receiver_lib is not importable; "
                "install its requirements with: pip install -e '.[povm-local]'"
            )
            if strict:
                raise PovmServiceError(message)
            _log.warning("povm_local_unavailable", detail=message)
            return None
        _log.info("povm_local_unavailable_falling_back_to_service", target=target)

    return attach_povm_service(twin, target=target, timeout_s=timeout_s, strict=strict)


def attach_povm_service(
    twin: Any,
    *,
    target: str,
    timeout_s: float = 120.0,
    strict: bool = False,
) -> RxPovmClient:
    """Route a twin's receivers through the rx-povm service.

    Both station receivers share one client so the POVM cache is shared too.
    Eve's receiver (when a faked-state attack is installed) deliberately keeps
    the local analytic model: it represents the attacker's own hardware, not the
    receiver under evaluation.
    """
    client = RxPovmClient(target, timeout_s=timeout_s)
    window_ps = float(getattr(twin.timing, "coincidence_window_ps", 0.0))
    for receiver in (twin.alice, twin.bob):
        receiver.povm_provider = client
        receiver.povm_strict = strict
        receiver.coincidence_window_ps = window_ps
    _log.info(
        "povm_service_attached",
        target=target,
        strict=strict,
        coincidence_window_ps=window_ps,
    )
    return client


__all__ = [
    "PovmServiceError",
    "PovmSet",
    "RxPovmClient",
    "attach_povm_backend",
    "attach_povm_service",
    "build_instrument_matrix",
    "build_led_state",
    "build_receiver_model",
    "dark_count_probability",
    "matrix_from_proto",
    "matrix_to_proto",
]
