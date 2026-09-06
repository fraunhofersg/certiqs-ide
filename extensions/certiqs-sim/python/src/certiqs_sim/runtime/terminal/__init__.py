"""Simulation prompt terminal — catalog-driven input state machine."""

from __future__ import annotations

from certiqs_sim.runtime.terminal.assist import Assistor, DeterministicAssistor
from certiqs_sim.runtime.terminal.catalog import (
    ServiceCatalog,
    ServiceEntry,
    build_service_catalog,
)
from certiqs_sim.runtime.terminal.intents import TerminalContext
from certiqs_sim.runtime.terminal.machine import (
    EXAMPLE_PROMPTS,
    InputStateMachine,
    example_prompts,
    run_sim_prompt,
)

__all__ = [
    "EXAMPLE_PROMPTS",
    "Assistor",
    "DeterministicAssistor",
    "InputStateMachine",
    "ServiceCatalog",
    "ServiceEntry",
    "TerminalContext",
    "build_service_catalog",
    "example_prompts",
    "run_sim_prompt",
]
