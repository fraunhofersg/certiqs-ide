"""Read-only helpers for configuration set directories under ``config_root``.

Never creates, copies, or mutates YAML files — only discovers existing
subdirectories that contain at least one ``*.y*ml`` document.
"""

from __future__ import annotations

from pathlib import Path


def iter_config_sets(config_root: Path) -> list[str]:
    """Sorted subdirectory names that look like valid configuration sets."""
    root = Path(config_root)
    if not root.is_dir():
        return []
    names: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and list(child.glob("*.y*ml")):
            names.append(child.name)
    return names


def resolve_config_name(
    config_root: Path,
    requested: str | None = None,
    *,
    preferred: str = "",
) -> str:
    """Resolve a config set name from disk without creating directories or files."""
    available = iter_config_sets(config_root)
    if not available:
        raise FileNotFoundError(f"No configuration sets found under {config_root}")

    if requested:
        if requested in available:
            return requested
        raise FileNotFoundError(
            f"Unknown config '{requested}' under {config_root}. "
            f"Available: {', '.join(available)}"
        )

    if preferred and preferred in available:
        return preferred

    return available[0]


__all__ = ["iter_config_sets", "resolve_config_name"]
