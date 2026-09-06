"""SPDC entangled-pair source (statistics ported from the reference)."""

from __future__ import annotations

import random
from typing import Any

import numpy as np

from certiqs_sim.core.config_models import SourceConfig
from certiqs_sim.core.linalg import I4, rho_phi_plus


class EntangledSource:
    """SPDC entangled-pair source.

    NetSquid has no SPDC pair-probability / multi-pair model, so the emission
    decision (Poisson pair count, Werner visibility mixing) stays here.  The
    resulting density matrix is later *assigned* to real NetSquid qubits by the
    twin, after which NetSquid evolves them through the channels.
    """

    def __init__(self, name: str, config: SourceConfig):
        self.name = name
        self.config = config
        if self.config.bell_state.lower() != "phi_plus":
            raise ValueError(
                "This version currently implements the phi_plus Bell state from the YAML schema."
            )

    def _single_pair_density_matrix(self) -> np.ndarray:
        w = float(self.config.intrinsic_visibility)
        w = min(max(w, 0.0), 1.0)
        return w * rho_phi_plus + (1.0 - w) * I4 / 4.0

    def emit(self) -> tuple[np.ndarray | None, dict[str, Any]]:
        mu = max(0.0, float(self.config.pair_generation_probability_per_pulse))
        if self.config.multi_pair_model.lower() == "poisson":
            pair_count = int(np.random.poisson(mu))
        else:
            pair_count = int(random.random() < mu)

        meta = {"pair_count": pair_count, "multi_pair": pair_count > 1}
        if pair_count <= 0:
            return None, meta
        if pair_count == 1:
            return self._single_pair_density_matrix(), meta

        visibility_scale = 1.0 / pair_count
        rho_eff = (
            visibility_scale * self._single_pair_density_matrix()
            + (1.0 - visibility_scale) * I4 / 4.0
        )
        return rho_eff, meta


__all__ = ["EntangledSource"]
