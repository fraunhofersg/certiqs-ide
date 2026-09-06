"""Command handlers for the simulation terminal state machine."""

from __future__ import annotations

from certiqs_sim.runtime.terminal.handlers import attack as attack_handler
from certiqs_sim.runtime.terminal.handlers import container as container_handler
from certiqs_sim.runtime.terminal.handlers import help as help_handler
from certiqs_sim.runtime.terminal.handlers import params as params_handler
from certiqs_sim.runtime.terminal.handlers import provenance as provenance_handler
from certiqs_sim.runtime.terminal.handlers import selftest as selftest_handler
from certiqs_sim.runtime.terminal.handlers import status as status_handler

__all__ = [
    "attack_handler",
    "container_handler",
    "help_handler",
    "params_handler",
    "provenance_handler",
    "selftest_handler",
    "status_handler",
]
