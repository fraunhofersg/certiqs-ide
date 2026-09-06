"""Attack registry.

An attack factory takes ``(twin, params)`` and installs the attack on the twin
(``twin.attack = ...``), returning the attack object.  This lets the
security-evaluation service build attacks by name from a campaign manifest.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

AttackFactory = Callable[[Any, dict[str, Any]], Any]

ATTACK_REGISTRY: dict[str, AttackFactory] = {}


def register_attack(name: str) -> Callable[[AttackFactory], AttackFactory]:
    def _decorator(factory: AttackFactory) -> AttackFactory:
        ATTACK_REGISTRY[name.lower()] = factory
        return factory

    return _decorator


def get_attack_factory(name: str) -> AttackFactory:
    key = str(name).lower()
    if key not in ATTACK_REGISTRY:
        raise KeyError(f"Unknown attack {name!r}. Registered: {sorted(ATTACK_REGISTRY)}")
    return ATTACK_REGISTRY[key]


def list_attacks() -> list[str]:
    return sorted(ATTACK_REGISTRY)


__all__ = [
    "ATTACK_REGISTRY",
    "AttackFactory",
    "get_attack_factory",
    "list_attacks",
    "register_attack",
]
