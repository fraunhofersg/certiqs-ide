"""Countermeasure registry.

A countermeasure factory takes ``(twin, params)`` and installs the countermeasure
on the twin (``twin.self_test = ...``), returning the countermeasure object.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

CountermeasureFactory = Callable[[Any, dict[str, Any]], Any]

COUNTERMEASURE_REGISTRY: dict[str, CountermeasureFactory] = {}


def register_countermeasure(name: str) -> Callable[[CountermeasureFactory], CountermeasureFactory]:
    def _decorator(factory: CountermeasureFactory) -> CountermeasureFactory:
        COUNTERMEASURE_REGISTRY[name.lower()] = factory
        return factory

    return _decorator


def get_countermeasure_factory(name: str) -> CountermeasureFactory:
    key = str(name).lower()
    if key not in COUNTERMEASURE_REGISTRY:
        raise KeyError(
            f"Unknown countermeasure {name!r}. Registered: {sorted(COUNTERMEASURE_REGISTRY)}"
        )
    return COUNTERMEASURE_REGISTRY[key]


def list_countermeasures() -> list[str]:
    return sorted(COUNTERMEASURE_REGISTRY)


__all__ = [
    "COUNTERMEASURE_REGISTRY",
    "CountermeasureFactory",
    "get_countermeasure_factory",
    "list_countermeasures",
    "register_countermeasure",
]
