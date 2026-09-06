"""Faked-state (detector-control) attack for entanglement-based QKD.

Behaviour-preserving port of the reference ``attack.py``.  Eve sits between the
fibre channel and Bob's receiver, intercepts every photon heading to Bob,
measures it with a Bob-like ``OpticalReceiver``, then sends a classical bright
pulse that selectively triggers Bob's blinded detector — controlling the bit Bob
registers while keeping QBER artificially low.  Alice's side is untouched.
"""

from __future__ import annotations

import copy
import random
from collections import Counter
from dataclasses import dataclass
from typing import Any

from certiqs_sim.core.attacks.base import register_attack

# (basis, bit) <-> polarisation label
_BB_TO_LABEL: dict[tuple[str, int], str] = {
    ("Z", 0): "H",
    ("Z", 1): "V",
    ("X", 0): "D",
    ("X", 1): "A",
}


@dataclass
class AttackConfig:
    """All tuneable parameters for the faked-state attack."""

    enabled: bool = False
    eve_detection_efficiency: float = 0.95
    extra_loss_db: float = 1.0
    trigger_success_prob: float = 0.98
    wrong_basis_suppression_prob: float = 0.95
    induced_error_prob: float = 0.005
    passive_basis_choice: bool = True


class FakedStateAttack:
    """Intercept-and-resend with detector blinding.

    Call ``intercept_and_resend`` in place of Bob's ``realize_event``.  The method
    signature and return type are identical so the twin swaps them with one ``if``.
    """

    def __init__(self, config: AttackConfig, eve_receiver: Any) -> None:
        self.config = config
        self.eve_receiver = eve_receiver
        self.stats: Counter = Counter()
        self._matched_pairs: list[tuple[int, int]] = []

    def intercept_and_resend(
        self,
        eve_signal_label: str,
        base_time_ps: float,
        window_ps: float,
        sync_jitter_ps_rms: float,
    ) -> tuple[str, dict[str, Any] | None]:
        self.stats["intercepted"] += 1

        _eve_label, eve_event = self.eve_receiver.realize_event(
            signal_label=eve_signal_label,
            base_time_ps=base_time_ps,
            window_ps=window_ps,
            sync_jitter_ps_rms=sync_jitter_ps_rms,
        )

        if eve_event is None:
            self.stats["eve_no_click"] += 1
            return "no_click", None

        self.stats["eve_clicked"] += 1
        eve_basis: str = eve_event["basis"]
        eve_bit: int = eve_event["bit"]

        if self.config.passive_basis_choice:
            # Passive 50:50 basis choice (default): Bob deterministically clicks
            # in *Eve's* basis with *Eve's* bit; the mismatch is resolved in
            # sifting against Alice, not at Bob's detector.
            if random.random() >= self.config.trigger_success_prob:
                self.stats["trigger_failed"] += 1
                return "no_click", None

            self.stats["triggered"] += 1
            bob_basis = eve_basis
            if random.random() < self.config.induced_error_prob:
                bob_bit = 1 - eve_bit
                self.stats["errors_induced"] += 1
            else:
                bob_bit = eve_bit

            label = _BB_TO_LABEL[(bob_basis, bob_bit)]
            event = self._make_faked_event(
                bob_basis,
                bob_bit,
                label,
                base_time_ps,
                "faked_state",
                eve_basis=eve_basis,
                eve_bit=eve_bit,
            )
            self._matched_pairs.append((eve_bit, bob_bit))
            self.stats["resent"] += 1
            return label, event

        # Active basis choice: Bob picks a basis; a mismatch is suppressed.
        bob_basis = random.choice(["Z", "X"])
        if eve_basis == bob_basis:
            self.stats["basis_matched"] += 1

            if random.random() >= self.config.trigger_success_prob:
                self.stats["trigger_failed"] += 1
                return "no_click", None

            self.stats["triggered"] += 1

            if random.random() < self.config.induced_error_prob:
                bob_bit = 1 - eve_bit
                self.stats["errors_induced"] += 1
            else:
                bob_bit = eve_bit

            label = _BB_TO_LABEL[(bob_basis, bob_bit)]
            event = self._make_faked_event(
                bob_basis,
                bob_bit,
                label,
                base_time_ps,
                "faked_state",
                eve_basis=eve_basis,
                eve_bit=eve_bit,
            )
            self._matched_pairs.append((eve_bit, bob_bit))
            self.stats["resent"] += 1
            return label, event

        self.stats["basis_mismatched"] += 1

        if random.random() < self.config.wrong_basis_suppression_prob:
            self.stats["suppressed"] += 1
            return "no_click", None

        self.stats["leak_click"] += 1
        bob_bit = random.randint(0, 1)
        label = _BB_TO_LABEL[(bob_basis, bob_bit)]
        event = self._make_faked_event(
            bob_basis,
            bob_bit,
            label,
            base_time_ps,
            "faked_state_leak",
            eve_basis=eve_basis,
            eve_bit=eve_bit,
        )
        self.stats["resent"] += 1
        return label, event

    @staticmethod
    def _make_faked_event(
        basis: str,
        bit: int,
        label: str,
        base_time_ps: float,
        cause: str,
        eve_basis: str,
        eve_bit: int,
    ) -> dict[str, Any]:
        return {
            "timestamp_ps": round(base_time_ps),
            "ideal_arrival_time_ps": round(base_time_ps),
            "channel_id": -99,  # sentinel: faked-state channel
            "basis": basis,
            "bit": bit,
            "state": label,
            "cause": cause,
            "detector_efficiency": 1.0,
            "dark_count_hz": 0.0,
            "jitter_ps_rms": 0.0,
            "dead_time_ns": 0.0,
            "afterpulse_prob": 0.0,
            "valid": 1,
            "eve_basis": eve_basis,
            "eve_bit": eve_bit,
        }

    def eve_bob_agreement(self) -> float:
        if not self._matched_pairs:
            return 0.0
        agree = sum(1 for (eb, bb) in self._matched_pairs if eb == bb)
        return agree / len(self._matched_pairs)

    def suppression_fraction(self) -> float:
        mismatched = self.stats["basis_mismatched"]
        if mismatched == 0:
            return 0.0
        return self.stats["suppressed"] / mismatched

    def attack_success_probability(self) -> float:
        clicked = self.stats["eve_clicked"]
        if clicked == 0:
            return 0.0
        return self.stats["triggered"] / clicked

    def reset(self) -> None:
        self.stats.clear()
        self._matched_pairs.clear()


@register_attack("faked_state")
def build_faked_state_attack(twin: Any, params: dict[str, Any]) -> FakedStateAttack | None:
    """Install (or clear) a faked-state attack on ``twin`` and return it.

    Eve uses a deep copy of Bob's current optics with efficiency overridden.
    Disabling clears ``twin.attack``.  This is the single source of truth for how
    the attack is wired, shared by the live runtime and the security-eval service.
    """
    from certiqs_sim.core.detectors import OpticalReceiver

    if not bool(params.get("enabled", False)):
        twin.attack = None
        return None

    cfg = AttackConfig(
        enabled=True,
        eve_detection_efficiency=float(params.get("eve_eff", 0.95)),
        extra_loss_db=float(params.get("extra_loss", 1.0)),
        trigger_success_prob=float(params.get("trigger_prob", 0.98)),
        wrong_basis_suppression_prob=float(params.get("suppression", 0.95)),
        induced_error_prob=float(params.get("induced_error", 0.005)),
        passive_basis_choice=bool(params.get("passive_basis_choice", True)),
    )
    eve_config = copy.deepcopy(twin.bob.config)
    for det in eve_config.detectors.values():
        det.efficiency = cfg.eve_detection_efficiency
        det.dark_count_hz = 0.0
        det.afterpulse_prob = 0.0
    attack = FakedStateAttack(cfg, OpticalReceiver(eve_config))
    twin.attack = attack
    return attack


__all__ = ["AttackConfig", "FakedStateAttack", "build_faked_state_attack"]
