"""Protocol plugin interface + registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class Protocol(ABC):
    """A QKD protocol plugin.

    A plugin encapsulates everything the engine should *not* hard-code about a
    specific protocol: how detection events are sifted into key bits, and the
    asymptotic secret-key fraction as a function of QBER.
    """

    #: Short protocol identifier, e.g. ``"bbm92"``.
    name: str = "abstract"

    def __init__(self, manifest: Any | None = None) -> None:
        self.keep_same_basis_only: bool = True
        self.multi_click_policy: str = "discard_event"
        if manifest is not None:
            self.configure(manifest)

    def configure(self, manifest: Any) -> None:  # noqa: B027
        """Read protocol settings from a :class:`YAMLManifest`. Optional override hook."""

    @abstractmethod
    def is_sifted(
        self,
        alice_event: dict[str, Any],
        bob_event: dict[str, Any],
        coincidence: bool,
    ) -> bool:
        """Return True if a coincident event pair contributes a sifted key bit."""

    @abstractmethod
    def secret_key_fraction(self, qber: float | None) -> float:
        """Asymptotic secret-key fraction r(QBER) for a quick live estimate."""


_REGISTRY: dict[str, type[Protocol]] = {}


def register_protocol(cls: type[Protocol]) -> type[Protocol]:
    """Class decorator that registers a protocol plugin by its ``name``."""
    _REGISTRY[cls.name.lower()] = cls
    return cls


def get_protocol(name: str, manifest: Any | None = None) -> Protocol:
    key = str(name).lower()
    if key not in _REGISTRY:
        raise KeyError(f"Unknown protocol {name!r}. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[key](manifest)


def list_protocols() -> list[str]:
    return sorted(_REGISTRY)


__all__ = [
    "Protocol",
    "get_protocol",
    "list_protocols",
    "register_protocol",
]

# Re-exported for typing convenience.
ProtocolFactory = Callable[[Any | None], Protocol]
