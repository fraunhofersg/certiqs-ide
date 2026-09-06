"""CA-QKD component layer: model registry, factory-driven assembly, catalog.

Implements the configuration backbone for the active config set
(``config/bbm92-generic``). Material under ``guide/`` is design background only.
"""

from certiqs_sim.core.components.registry import (
    ComponentModelSpec,
    get_model_for_class,
    list_component_models,
    register_component_model,
)

__all__ = [
    "ComponentModelSpec",
    "get_model_for_class",
    "list_component_models",
    "register_component_model",
]
