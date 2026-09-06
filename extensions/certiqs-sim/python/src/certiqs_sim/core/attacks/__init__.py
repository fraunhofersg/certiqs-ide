"""Implementation-attack library + registry.

Attacks operate purely on detector labels and event dicts, so they are engine-
agnostic.  ``faked_state`` is the first attack; blinding / time-shift /
Trojan-horse can be added by registering another factory.
"""

from __future__ import annotations

from certiqs_sim.core.attacks.base import (
    ATTACK_REGISTRY,
    get_attack_factory,
    list_attacks,
    register_attack,
)
from certiqs_sim.core.attacks.faked_state import AttackConfig, FakedStateAttack

__all__ = [
    "ATTACK_REGISTRY",
    "AttackConfig",
    "FakedStateAttack",
    "get_attack_factory",
    "list_attacks",
    "register_attack",
]
