"""Hierarchical CA-QKD topology — system engineering layer above flat subsystem YAML."""

from certiqs_sim.core.topology.adapter import (
    topology_to_flat_documents,
    topology_to_simulation_graph,
)
from certiqs_sim.core.topology.loader import (
    is_package_config,
    load_node_package,
    load_topology,
)
from certiqs_sim.core.topology.validate import (
    validate_node_package,
    validate_topology,
)

from certiqs_sim.core.topology.virtual_model import build_virtual_topology

__all__ = [
    "is_package_config",
    "load_node_package",
    "load_topology",
    "topology_to_flat_documents",
    "topology_to_simulation_graph",
    "validate_node_package",
    "validate_topology",
    "build_virtual_topology",
]
