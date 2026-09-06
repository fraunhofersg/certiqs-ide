"""Platform operations: service registry, health probes, process / compose control."""

from certiqs_sim.ops.supervisor import PlatformSupervisor, get_supervisor

__all__ = ["PlatformSupervisor", "get_supervisor"]
