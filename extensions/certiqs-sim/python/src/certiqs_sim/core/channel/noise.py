"""Per-side fibre noise model executed inside NetSquid's engine.

Behaviour-preserving split of ``FiberNoiseModel`` from the original physics
module.  Each ``QuantumChannel`` carries exactly one side's qubit, so the
reference's *local* (one-subsystem) channel becomes a single-qubit operation.
"""

from __future__ import annotations

import math
from typing import Any

import netsquid.qubits.qubitapi as qapi
from netsquid.components.models.qerrormodels import QuantumErrorModel
from netsquid.qubits.operators import Operator

from certiqs_sim.core.config_models import FiberConfig
from certiqs_sim.core.linalg import random_su2, ry


class FiberNoiseModel(QuantumErrorModel):
    """Applies the reference ``FiberChannel`` evolution to a single qubit.

    The model reads its ``FiberConfig`` live, so parameter changes between
    simulation windows take effect immediately on the next transmission.  Order
    matches ``FiberChannel.apply``: rotation/drift -> PMD dephasing ->
    depolarization.  The Pauli channels use ``apply_pauli_noise`` which, in the
    DM formalism, is the exact CPTP map (identical to the reference).
    """

    def __init__(self, config: FiberConfig) -> None:
        super().__init__()
        self.config = config

    def _pmd_pauli_z_prob(self) -> float:
        pmd_ps = max(0.0, float(self.config.pmd_ps))
        tau_ps = max(1e-12, float(self.config.coherence_time_ps))
        coherence = math.exp(-0.5 * (pmd_ps / tau_ps) ** 2)
        return min(max((1.0 - coherence) / 2.0, 0.0), 1.0)

    def error_operation(self, qubits: Any, delta_time: float = 0.0, **kwargs: Any) -> None:
        cfg = self.config
        for qubit in qubits:
            if qubit is None:
                continue

            # 1) static rotation + random polarization drift
            if cfg.static_rotation_rad or cfg.drift_sigma_rad:
                U = random_su2(cfg.drift_sigma_rad) @ ry(cfg.static_rotation_rad)
                qapi.operate(qubit, Operator("fiber_rotation", U))

            # 2) PMD-induced Z dephasing  {I: 1-pz, Z: pz}
            pz = self._pmd_pauli_z_prob()
            if pz > 0.0:
                qapi.apply_pauli_noise(qubit, [1.0 - pz, 0.0, 0.0, pz])

            # 3) depolarization  {I: 1-p, X: p/3, Y: p/3, Z: p/3}
            # Base YAML term + length-accumulated residual decoherence.
            p_dep = min(
                max(
                    float(cfg.depolarization_prob)
                    + float(getattr(cfg, "depolarization_per_km", 0.0))
                    * max(float(cfg.length_km), 0.0),
                    0.0,
                ),
                1.0,
            )
            if p_dep > 0.0:
                qapi.apply_pauli_noise(qubit, [1.0 - p_dep, p_dep / 3.0, p_dep / 3.0, p_dep / 3.0])


__all__ = ["FiberNoiseModel"]
