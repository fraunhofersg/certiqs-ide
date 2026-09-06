"""Backward-compatible shim — implementation lives in ``runtime.terminal``."""

from __future__ import annotations

from certiqs_sim.runtime.terminal import (
    EXAMPLE_PROMPTS,
    example_prompts,
    run_sim_prompt,
)

__all__ = ["EXAMPLE_PROMPTS", "example_prompts", "run_sim_prompt"]
