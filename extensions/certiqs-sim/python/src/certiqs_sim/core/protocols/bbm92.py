"""BBM92 entanglement-based QKD protocol plugin."""

from __future__ import annotations

from typing import Any

from certiqs_sim.core.keyrate import asymptotic_bbm92_secret_key_fraction
from certiqs_sim.core.protocols.base import Protocol, register_protocol


@register_protocol
class BBM92Protocol(Protocol):
    """BBM92: entangled Phi+ pairs, passive basis choice, same-basis sifting."""

    name = "bbm92"

    def configure(self, manifest: Any) -> None:
        protocol = manifest.protocol.get("protocol", {})
        # BBM92 sifting keeps same-basis coincidences; a config may explicitly
        # disable that for diagnostics via `sifting.keep_same_basis_only`.
        self.keep_same_basis_only = bool(
            protocol.get("sifting", {}).get("keep_same_basis_only", True)
        )
        self.multi_click_policy = str(
            protocol.get("double_click_policy")
            or protocol.get("coincidence", {}).get("multi_click_policy", "discard_event")
        )

    def is_sifted(
        self,
        alice_event: dict[str, Any],
        bob_event: dict[str, Any],
        coincidence: bool,
    ) -> bool:
        if not coincidence:
            return False
        if self.keep_same_basis_only:
            return alice_event["basis"] == bob_event["basis"]
        return True

    def secret_key_fraction(self, qber: float | None) -> float:
        return asymptotic_bbm92_secret_key_fraction(qber)


__all__ = ["BBM92Protocol"]
