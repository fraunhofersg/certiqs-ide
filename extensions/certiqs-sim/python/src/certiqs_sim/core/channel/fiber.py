"""Reference fibre channel backed by a real NetSquid ``QuantumChannel``."""

from __future__ import annotations

from netsquid.components import QuantumChannel
from netsquid.components.models.delaymodels import FibreDelayModel

from certiqs_sim.core.channel.noise import FiberNoiseModel
from certiqs_sim.core.config_models import FiberConfig
from certiqs_sim.core.linalg import C_M_PER_S


class FiberChannel:
    """Fibre channel: quantum evolution + propagation delay inside NetSquid.

    The quantum evolution (rotation, PMD, depolarization) is performed by the
    attached :class:`FiberNoiseModel` and the propagation delay by
    ``FibreDelayModel`` — both inside NetSquid's engine.  Transmission /
    efficiency (``eta``) is kept analytic and folded into the detector POVM (as in
    the reference) so the joint 2-qubit state is never randomly destroyed.
    """

    def __init__(self, name: str, config: FiberConfig, side: str):
        self.name = name
        self.config = config
        self.side = side
        c_km_per_s = C_M_PER_S / 1000.0 / max(config.fiber_group_index, 1e-9)
        self.qchannel = QuantumChannel(
            name=f"qchannel_{name}",
            length=max(float(config.length_km), 0.0),
            models={
                "quantum_noise_model": FiberNoiseModel(config),
                "delay_model": FibreDelayModel(c=c_km_per_s),
            },
        )

    def sync_netsquid(self) -> None:
        """Push live config changes (length / group index) into NetSquid.

        NetSquid stores channel length in ``properties['length']``. Assigning
        ``qchannel.length = …`` only creates a Python instance attribute and
        does **not** update the property map that ``FibreDelayModel`` reads.
        """
        length = max(float(self.config.length_km), 0.0)
        self.qchannel.properties["length"] = length
        # Drop a shadowed attribute left by older callers / mistaken assigns.
        if "length" in getattr(self.qchannel, "__dict__", {}):
            del self.qchannel.__dict__["length"]
        delay_model = self.qchannel.models.get("delay_model")
        if isinstance(delay_model, FibreDelayModel):
            delay_model.properties["c"] = (
                C_M_PER_S / 1000.0 / max(self.config.fiber_group_index, 1e-9)
            )

    def propagation_delay_ps(self) -> float:
        length_m = self.config.length_km * 1000.0
        delay_s = self.config.fiber_group_index * length_m / C_M_PER_S
        return delay_s * 1e12

    def transmission_probability(self) -> float:
        total_loss_db = self.config.total_loss_db()
        eta = (10 ** (-total_loss_db / 10.0)) * self.config.coupling_efficiency
        return min(max(eta, 0.0), 1.0)


__all__ = ["FiberChannel"]
