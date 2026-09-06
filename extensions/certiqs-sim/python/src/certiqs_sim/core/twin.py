"""Protocol-agnostic NetSquid-backed quantum-channel twin.

This is the refactor of the original ``BBM92DigitalTwin``: the class no longer
hard-codes BBM92.  Protocol-specific rules (sifting, secret-key fraction) come
from a :class:`~certiqs_sim.core.protocols.base.Protocol` plugin, so the same
engine drives BBM92 today and BB84/E91 once those plugins are registered.

NetSquid is non-reentrant, so exactly one twin runs per process.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import netsquid as ns
import netsquid.qubits.qubitapi as qapi
import numpy as np
from netsquid.components.component import Message
from netsquid.qubits.qformalism import QFormalism

from certiqs_sim.core.channel import EntangledSource, FiberChannel
from certiqs_sim.core.config_models import TimingConfig
from certiqs_sim.core.detectors import OpticalReceiver
from certiqs_sim.core.linalg import (
    hermitian_psd_clip,
    kron,
    normalize_probabilities,
    sample_from_probs,
)
from certiqs_sim.core.manifest import YAMLManifest
from certiqs_sim.core.protocols.base import Protocol
from certiqs_sim.core.protocols.bbm92 import BBM92Protocol

# Density-matrix formalism so channel noise is applied as an exact CPTP map.
ns.set_qstate_formalism(QFormalism.DM)


class QuantumChannelTwin:
    def __init__(
        self,
        source: EntangledSource,
        chan_to_alice: FiberChannel,
        chan_to_bob: FiberChannel,
        alice: OpticalReceiver,
        bob: OpticalReceiver,
        timing: TimingConfig,
        manifest: YAMLManifest,
        protocol: Protocol | None = None,
    ):
        self.source = source
        self.chan_to_alice = chan_to_alice
        self.chan_to_bob = chan_to_bob
        self.alice = alice
        self.bob = bob
        self.timing = timing
        self.manifest = manifest
        self.protocol: Protocol = protocol or BBM92Protocol(manifest)

        # Optional faked-state attack / self-testing countermeasure (set externally).
        self.attack: Any = None
        self.self_test: Any = None
        self._selftest_busy_prob = 0.0

        # Provenance (set by the factory builder): resolved-manifest hash + dir.
        self.manifest_sha256: str | None = None
        self.config_dir: str | None = None

        self.keep_same_basis_only = self.protocol.keep_same_basis_only
        self.multi_click_policy = self.protocol.multi_click_policy
        self.pulse_period_ps = 1e12 / self.source.config.repetition_rate_hz
        self.current_epoch = 0

        self._arrived_a: Any | None = None
        self._arrived_b: Any | None = None
        self.chan_to_alice.qchannel.ports["recv"].bind_output_handler(self._on_recv_alice)
        self.chan_to_bob.qchannel.ports["recv"].bind_output_handler(self._on_recv_bob)

    # ── NetSquid plumbing ─────────────────────────────────────────────────
    def _on_recv_alice(self, message: Message) -> None:
        self._arrived_a = message.items[0]

    def _on_recv_bob(self, message: Message) -> None:
        self._arrived_b = message.items[0]

    def _evolve_pair_through_netsquid(self, rho_ab: np.ndarray) -> np.ndarray:
        qubit_a, qubit_b = qapi.create_qubits(2)
        qapi.assign_qstate([qubit_a, qubit_b], rho_ab)

        self._arrived_a = None
        self._arrived_b = None
        self.chan_to_alice.qchannel.ports["send"].tx_input(Message([qubit_a]))
        self.chan_to_bob.qchannel.ports["send"].tx_input(Message([qubit_b]))
        ns.sim_run()

        rho_after = qapi.reduced_dm([self._arrived_a, self._arrived_b])
        qapi.discard(self._arrived_a)
        qapi.discard(self._arrived_b)
        self._arrived_a = None
        self._arrived_b = None
        return hermitian_psd_clip(rho_after)

    def _joint_measurement_probabilities(
        self,
        rho_ab: np.ndarray,
        alice_povm: Mapping[str, np.ndarray],
        bob_povm: Mapping[str, np.ndarray],
    ) -> dict[tuple[str, str], float]:
        probs: dict[tuple[str, str], float] = {}
        for a_label, E_a in alice_povm.items():
            for b_label, E_b in bob_povm.items():
                p = float(np.real(np.trace(kron(E_a, E_b) @ rho_ab)))
                probs[(a_label, b_label)] = max(0.0, p)
        return normalize_probabilities(probs)

    def _apply_selftest_busy(
        self, a_out: Any, a_ev: Any, b_out: Any, b_ev: Any
    ) -> tuple[Any, Any, Any, Any]:
        busy = self._selftest_busy_prob
        if busy > 0.0:
            if a_ev is not None and random.random() < busy:
                a_out, a_ev = "no_click", None
            if b_ev is not None and random.random() < busy:
                b_out, b_ev = "no_click", None
        return a_out, a_ev, b_out, b_ev

    def _coincidence_and_sift(
        self, alice_event: dict[str, Any] | None, bob_event: dict[str, Any] | None
    ) -> tuple[bool, bool]:
        coincidence = False
        sifted = False
        if alice_event and bob_event:
            # The startup timing-alignment calibration (08_control_and_calibration)
            # removes the deterministic arm-delay difference; with asymmetric fibre
            # lengths the raw timestamps would otherwise never coincide.
            static_offset_ps = (
                self.chan_to_alice.propagation_delay_ps()
                - self.chan_to_bob.propagation_delay_ps()
            )
            dt = abs(
                (alice_event["timestamp_ps"] - bob_event["timestamp_ps"]) - static_offset_ps
            )
            coincidence = dt <= self.timing.coincidence_window_ps
            sifted = self.protocol.is_sifted(alice_event, bob_event, coincidence)
        return coincidence, sifted

    def run_shot(self) -> dict[str, Any]:
        epoch_id = self.current_epoch
        self.current_epoch += 1
        base_time_ps = epoch_id * self.pulse_period_ps

        attack = self.attack
        attack_active = attack is not None and attack.config.enabled

        rho_ab, src_meta = self.source.emit()

        if rho_ab is None:
            delay_a = self.chan_to_alice.propagation_delay_ps()
            delay_b = self.chan_to_bob.propagation_delay_ps()

            alice_outcome, alice_event = self.alice.realize_event(
                signal_label="no_pair",
                base_time_ps=base_time_ps + delay_a,
                window_ps=self.timing.coincidence_window_ps,
                sync_jitter_ps_rms=self.timing.time_sync_jitter_ps_rms,
            )

            if attack_active:
                bob_outcome, bob_event = attack.intercept_and_resend(
                    eve_signal_label="no_pair",
                    base_time_ps=base_time_ps + delay_b,
                    window_ps=self.timing.coincidence_window_ps,
                    sync_jitter_ps_rms=self.timing.time_sync_jitter_ps_rms,
                )
            else:
                bob_outcome, bob_event = self.bob.realize_event(
                    signal_label="no_pair",
                    base_time_ps=base_time_ps + delay_b,
                    window_ps=self.timing.coincidence_window_ps,
                    sync_jitter_ps_rms=self.timing.time_sync_jitter_ps_rms,
                )

            alice_outcome, alice_event, bob_outcome, bob_event = self._apply_selftest_busy(
                alice_outcome, alice_event, bob_outcome, bob_event
            )
            if alice_event is not None:
                alice_event["epoch_id"] = epoch_id
            if bob_event is not None:
                bob_event["epoch_id"] = epoch_id

            coincidence, sifted = self._coincidence_and_sift(alice_event, bob_event)

            return {
                "epoch_id": epoch_id,
                "alice": alice_outcome,
                "bob": bob_outcome,
                "alice_event": alice_event,
                "bob_event": bob_event,
                "coincidence": coincidence,
                "sifted": sifted,
                "source": src_meta,
            }

        # ── A pair was emitted: NetSquid evolves it through the channels ──────
        rho_after = self._evolve_pair_through_netsquid(rho_ab)
        eta_a = self.chan_to_alice.transmission_probability()
        eta_b = self.chan_to_bob.transmission_probability()
        delay_a = self.chan_to_alice.propagation_delay_ps()
        delay_b = self.chan_to_bob.propagation_delay_ps()
        alice_povm = self.alice.povm_elements(eta_a)

        if attack_active:
            extra_eta = 10.0 ** (-attack.config.extra_loss_db / 10.0)
            eve_eta = eta_b * extra_eta
            eve_povm = attack.eve_receiver.povm_elements(eve_eta)

            alice_signal_label, eve_signal_label = sample_from_probs(
                self._joint_measurement_probabilities(rho_after, alice_povm, eve_povm)
            )

            alice_outcome, alice_event = self.alice.realize_event(
                signal_label=alice_signal_label,
                base_time_ps=base_time_ps + delay_a,
                window_ps=self.timing.coincidence_window_ps,
                sync_jitter_ps_rms=self.timing.time_sync_jitter_ps_rms,
            )
            bob_outcome, bob_event = attack.intercept_and_resend(
                eve_signal_label=eve_signal_label,
                base_time_ps=base_time_ps + delay_b,
                window_ps=self.timing.coincidence_window_ps,
                sync_jitter_ps_rms=self.timing.time_sync_jitter_ps_rms,
            )
        else:
            bob_povm = self.bob.povm_elements(eta_b)
            alice_signal_label, bob_signal_label = sample_from_probs(
                self._joint_measurement_probabilities(rho_after, alice_povm, bob_povm)
            )

            alice_outcome, alice_event = self.alice.realize_event(
                signal_label=alice_signal_label,
                base_time_ps=base_time_ps + delay_a,
                window_ps=self.timing.coincidence_window_ps,
                sync_jitter_ps_rms=self.timing.time_sync_jitter_ps_rms,
            )
            bob_outcome, bob_event = self.bob.realize_event(
                signal_label=bob_signal_label,
                base_time_ps=base_time_ps + delay_b,
                window_ps=self.timing.coincidence_window_ps,
                sync_jitter_ps_rms=self.timing.time_sync_jitter_ps_rms,
            )

        alice_outcome, alice_event, bob_outcome, bob_event = self._apply_selftest_busy(
            alice_outcome, alice_event, bob_outcome, bob_event
        )
        if alice_event is not None:
            alice_event["epoch_id"] = epoch_id
        if bob_event is not None:
            bob_event["epoch_id"] = epoch_id

        coincidence, sifted = self._coincidence_and_sift(alice_event, bob_event)

        return {
            "epoch_id": epoch_id,
            "alice": alice_outcome,
            "bob": bob_outcome,
            "alice_event": alice_event,
            "bob_event": bob_event,
            "coincidence": coincidence,
            "sifted": sifted,
            "source": src_meta,
        }

    def run_window(
        self,
        num_shots: int = 1000,
        collect_sifted: bool = False,
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Run ``num_shots`` synchronous epochs and return aggregate metrics.

        When ``collect_sifted`` is True, the raw sifted bit arrays for Alice and
        Bob are included in the result — the post-processing layer consumes these
        blocks for error correction, privacy amplification and finite-key bounds.

        ``should_stop`` is polled every 256 shots so a stop request does not wait
        for the full window to finish.
        """
        joint_counts: Counter = Counter()
        single_counts: Counter = Counter()
        basis_counts: Counter = Counter()
        detector_cause_counts: Counter = Counter()
        sifted_bits_alice: list[int] = []
        sifted_bits_bob: list[int] = []
        coincidence_count = 0
        multi_pair_epochs = 0

        attack = self.attack
        attack_active = attack is not None and attack.config.enabled
        if attack_active:
            attack.reset()

        selftest = self.self_test
        selftest_active = selftest is not None and selftest.config.enabled
        self._selftest_busy_prob = (
            selftest.duty_loss()
            if (selftest_active and selftest.config.apply_to_detection)
            else 0.0
        )

        bob_detection_count = 0
        eve_known_sifted = 0
        shots_done = 0

        for shot_idx in range(num_shots):
            if shot_idx % 256 == 0:
                if should_stop and should_stop():
                    break
                # Briefly release the GIL so API/status/streaming threads stay
                # responsive; the CPU-bound shot loop starves them otherwise
                # (adds well under 2% to the window duration).
                time.sleep(0.0002)
            res = self.run_shot()
            shots_done += 1
            joint_counts[(res["alice"], res["bob"])] += 1
            single_counts[f"alice:{res['alice']}"] += 1
            single_counts[f"bob:{res['bob']}"] += 1
            if res["source"].get("multi_pair"):
                multi_pair_epochs += 1
            if res["coincidence"]:
                coincidence_count += 1

            aev = res["alice_event"]
            bev = res["bob_event"]
            if aev:
                basis_counts[f"alice:{aev['basis']}"] += 1
                detector_cause_counts[f"alice:{aev.get('cause', 'unknown')}"] += 1
            if bev:
                bob_detection_count += 1
                basis_counts[f"bob:{bev['basis']}"] += 1
                detector_cause_counts[f"bob:{bev.get('cause', 'unknown')}"] += 1
            if res["sifted"] and aev and bev:
                sifted_bits_alice.append(int(aev["bit"]))
                sifted_bits_bob.append(int(bev["bit"]))
                if attack_active and "eve_bit" in bev and int(bev["eve_bit"]) == int(aev["bit"]):
                    eve_known_sifted += 1

        qber = None
        if sifted_bits_alice:
            errors = sum(
                int(a != b) for a, b in zip(sifted_bits_alice, sifted_bits_bob, strict=True)
            )
            qber = errors / len(sifted_bits_alice)

        sifted_n = len(sifted_bits_alice)
        eve_knowledge_fraction = (
            eve_known_sifted / sifted_n if (attack_active and sifted_n) else 0.0
        )
        bob_detection_rate = bob_detection_count / shots_done if shots_done else 0.0

        secret_fraction = self.protocol.secret_key_fraction(qber)
        key_rate_per_pulse = (sifted_n / shots_done) * secret_fraction if shots_done else 0.0
        secret_key_bits = round(sifted_n * secret_fraction)

        results: dict[str, Any] = {
            "protocol": self.protocol.name,
            "shots": shots_done,
            "epoch_end": self.current_epoch,
            "sim_time_ns": float(ns.sim_time()),
            "joint_counts": dict(sorted(joint_counts.items())),
            "single_counts": dict(sorted(single_counts.items())),
            "basis_counts": dict(sorted(basis_counts.items())),
            "detector_cause_counts": dict(sorted(detector_cause_counts.items())),
            "sifted_key_bits": sifted_n,
            "qber": qber,
            "secret_fraction": secret_fraction,
            "key_rate_per_pulse": key_rate_per_pulse,
            "secret_key_bits": secret_key_bits,
            "coincidences": coincidence_count,
            "multi_pair_epochs": multi_pair_epochs,
            "coincidence_window_ps": self.timing.coincidence_window_ps,
            "bob_detection_rate": bob_detection_rate,
            "attack_enabled": attack_active,
            "attack_stats": dict(attack.stats) if attack_active else {},
            "eve_knowledge_fraction": eve_knowledge_fraction,
            "suppression_fraction": (attack.suppression_fraction() if attack_active else 0.0),
            "attack_success_prob": (attack.attack_success_probability() if attack_active else 0.0),
        }

        if collect_sifted:
            results["sifted_bits_alice"] = sifted_bits_alice
            results["sifted_bits_bob"] = sifted_bits_bob

        if selftest_active:
            results.update(selftest.run(blinded=attack_active))
        else:
            results["selftest_enabled"] = False
            results["selftest_alarm"] = 0

        return results

    # Backwards-compatible alias matching the reference API name.
    def run(self, num_shots: int = 1000) -> dict[str, Any]:
        return self.run_window(num_shots)


def build_twin_from_yaml_directory(
    yaml_dir: Path, protocol_name: str = "bbm92"
) -> QuantumChannelTwin:
    """Factory-driven assembly via the component-model registry.

    Components are discovered by their declared ``component:`` class and built
    through :mod:`certiqs_sim.core.components` — see the CA-QKD concept doc.
    """
    from certiqs_sim.core.components.builder import build_twin_from_config

    return build_twin_from_config(Path(yaml_dir), protocol_name)


__all__ = ["QuantumChannelTwin", "build_twin_from_yaml_directory"]
