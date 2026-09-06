"""Apply runtime topology edits back to the config YAML files.

The topology UI lets an operator reposition connectors and rewire cross-node
connections on the fly. This module persists those edits to the authoring YAML,
taking a timestamped backup of every touched file first (unless disabled) and
validating the resulting config; on validation failure the backup is restored.

Two edit kinds are supported:

``set_connector``
    Move/restyle one port's connector. Locates the port by id in a node's
    ``boundary_ports`` map or a module/component ``ports`` map and merges the
    provided ``connector`` fields (``position``/``size``/``style``/``color``).

``rewire_connection``
    Repoint one endpoint of a cross-node link declared under
    ``network/*.yaml`` ``bindings``. Matches the binding by its old
    ``from_port``/``to_port`` pair and rewrites the changed endpoint, keeping
    orientation and recomputing the owning package when resolvable.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BACKUP_DIRNAME = ".backups"
_CONNECTOR_FIELDS = ("position", "size", "style", "color")
_VALID_POSITIONS = frozenset({"top", "bottom", "left", "right"})
_VALID_SIZES = frozenset({"small", "normal"})
_VALID_STYLES = frozenset({"default", "color"})


class ConfigEditError(ValueError):
    """Raised when an edit cannot be located or would produce invalid config."""


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)


def _iter_config_yaml_files(config_dir: Path) -> list[Path]:
    """Every YAML file under the config set, excluding the backup tree."""
    files: list[Path] = []
    for path in sorted(config_dir.rglob("*.y*ml")):
        if BACKUP_DIRNAME in path.relative_to(config_dir).parts:
            continue
        files.append(path)
    return files


# ── connector location ────────────────────────────────────────────────────
def _connector_in_node_doc(doc: dict[str, Any], port_id: str) -> dict[str, Any] | None:
    boundary = doc.get("boundary_ports")
    if isinstance(boundary, dict):
        spec = boundary.get(port_id)
        if isinstance(spec, dict):
            return spec
    return None


def _iter_port_specs_in_doc(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """All (port_id, spec) pairs in a modules/components doc.

    A port is addressable by its explicit ``interface_id`` or its map key.
    """
    found: list[tuple[str, dict[str, Any]]] = []
    for collection_key in ("modules", "components"):
        collection = doc.get(collection_key)
        if not isinstance(collection, list):
            continue
        for entry in collection:
            if not isinstance(entry, dict):
                continue
            ports = entry.get("ports")
            if not isinstance(ports, dict):
                continue
            for port_name, spec in ports.items():
                if not isinstance(spec, dict):
                    continue
                found.append((str(spec.get("interface_id") or port_name), spec))
                if spec.get("interface_id"):
                    found.append((str(port_name), spec))
    return found


def _merge_connector(spec: dict[str, Any], connector: dict[str, Any]) -> bool:
    """Merge connector fields into a port spec. Returns True if changed."""
    current = spec.get("connector")
    if not isinstance(current, dict):
        current = {}
    merged = dict(current)
    for field in _CONNECTOR_FIELDS:
        if field in connector and connector[field] is not None:
            merged[field] = connector[field]
    if merged == current and isinstance(spec.get("connector"), dict):
        return False
    spec["connector"] = merged
    return True


def _validate_connector(connector: dict[str, Any]) -> None:
    position = connector.get("position")
    if position is not None and position not in _VALID_POSITIONS:
        raise ConfigEditError(
            f"invalid connector position '{position}' (allowed: {sorted(_VALID_POSITIONS)})"
        )
    size = connector.get("size")
    if size is not None and size not in _VALID_SIZES:
        raise ConfigEditError(f"invalid connector size '{size}'")
    style = connector.get("style")
    if style is not None and style not in _VALID_STYLES:
        raise ConfigEditError(f"invalid connector style '{style}'")


# ── package resolution (for rewire) ────────────────────────────────────────
def _build_port_package_map(config_dir: Path) -> dict[str, str]:
    """Map every boundary/module/component port id to its owning package id."""
    mapping: dict[str, str] = {}
    for node_path in sorted(config_dir.rglob("node.yaml")):
        if BACKUP_DIRNAME in node_path.relative_to(config_dir).parts:
            continue
        doc = _read_yaml(node_path)
        package_id = str(doc.get("package_id") or "")
        if not package_id:
            continue
        pkg_dir = node_path.parent
        boundary = doc.get("boundary_ports")
        if isinstance(boundary, dict):
            for port_id in boundary:
                mapping[str(port_id)] = package_id
        for sibling in sorted(pkg_dir.rglob("modules.yaml")):
            if BACKUP_DIRNAME in sibling.relative_to(config_dir).parts:
                continue
            for port_id, _spec in _iter_port_specs_in_doc(_read_yaml(sibling)):
                mapping.setdefault(port_id, package_id)
    return mapping


def _build_known_ports(config_dir: Path, all_files: list[Path]) -> set[str]:
    """Every addressable port id, plus endpoints already used by bindings."""
    known: set[str] = set()
    for path in all_files:
        doc = _read_yaml(path)
        boundary = doc.get("boundary_ports")
        if isinstance(boundary, dict):
            known.update(str(k) for k in boundary)
        for port_id, _spec in _iter_port_specs_in_doc(doc):
            known.add(port_id)
        bindings = doc.get("bindings")
        if isinstance(bindings, list):
            for binding in bindings:
                if isinstance(binding, dict):
                    known.add(str(binding.get("from_port") or ""))
                    known.add(str(binding.get("to_port") or ""))
    known.discard("")
    return known


# ── edit application ───────────────────────────────────────────────────────
class _PendingChanges:
    """Accumulates in-memory doc mutations keyed by file path before writing."""

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self._docs: dict[Path, dict[str, Any]] = {}
        self.touched: set[Path] = set()

    def doc(self, path: Path) -> dict[str, Any]:
        if path not in self._docs:
            self._docs[path] = _read_yaml(path)
        return self._docs[path]

    def mark(self, path: Path) -> None:
        self.touched.add(path)

    def write_all(self) -> None:
        for path in self.touched:
            _write_yaml(path, self._docs[path])


def _apply_set_connector(
    edit: dict[str, Any],
    pending: _PendingChanges,
    node_files: list[Path],
    module_files: list[Path],
) -> None:
    port_id = str(edit.get("port_id") or "").strip()
    if not port_id:
        raise ConfigEditError("set_connector edit missing 'port_id'")
    connector = edit.get("connector")
    if not isinstance(connector, dict):
        raise ConfigEditError(f"set_connector edit for '{port_id}' missing 'connector'")
    _validate_connector(connector)

    for path in node_files:
        spec = _connector_in_node_doc(pending.doc(path), port_id)
        if spec is not None:
            if _merge_connector(spec, connector):
                pending.mark(path)
            return

    for path in module_files:
        for candidate_id, spec in _iter_port_specs_in_doc(pending.doc(path)):
            if candidate_id == port_id:
                if _merge_connector(spec, connector):
                    pending.mark(path)
                return

    raise ConfigEditError(f"could not locate port '{port_id}' in any node/module config")


def _apply_rewire(
    edit: dict[str, Any],
    pending: _PendingChanges,
    network_files: list[Path],
    port_package: dict[str, str],
    known_ports: set[str],
) -> None:
    old = edit.get("old") or {}
    new = edit.get("new") or {}
    old_from = str(old.get("from_port") or "").strip()
    old_to = str(old.get("to_port") or "").strip()
    new_from = str(new.get("from_port") or old_from).strip()
    new_to = str(new.get("to_port") or old_to).strip()
    if not old_from or not old_to:
        raise ConfigEditError("rewire_connection edit missing old 'from_port'/'to_port'")
    if new_from == old_from and new_to == old_to:
        return
    for endpoint in (new_from, new_to):
        if endpoint not in known_ports:
            raise ConfigEditError(f"rewire target port '{endpoint}' does not exist")

    old_pair = {old_from, old_to}
    for path in network_files:
        doc = pending.doc(path)
        bindings = doc.get("bindings")
        if not isinstance(bindings, list):
            continue
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            b_from = str(binding.get("from_port") or "")
            b_to = str(binding.get("to_port") or "")
            if {b_from, b_to} != old_pair:
                continue
            # Preserve orientation relative to the stored binding.
            if b_from == old_from:
                binding["from_port"] = new_from
                binding["to_port"] = new_to
            else:
                binding["from_port"] = new_to
                binding["to_port"] = new_from
            if binding["from_port"] in port_package:
                binding["from_package"] = port_package[binding["from_port"]]
            if binding["to_port"] in port_package:
                binding["to_package"] = port_package[binding["to_port"]]
            pending.mark(path)
            return

    raise ConfigEditError(
        f"could not locate a network binding for '{old_from}' → '{old_to}'"
    )


def _backup(config_dir: Path, files: set[Path]) -> str | None:
    if not files:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = config_dir / BACKUP_DIRNAME / stamp
    for path in sorted(files):
        rel = path.relative_to(config_dir)
        dest = backup_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
    return str(backup_root.relative_to(config_dir))


def _restore(config_dir: Path, backup_rel: str) -> None:
    backup_root = config_dir / backup_rel
    for src in backup_root.rglob("*.y*ml"):
        rel = src.relative_to(backup_root)
        shutil.copy2(src, config_dir / rel)


def apply_config_edits(
    config_dir: Path,
    edits: list[dict[str, Any]],
    *,
    backup: bool = True,
    validate: bool = True,
) -> dict[str, Any]:
    """Apply connector/rewire edits to a config set with optional backup.

    Returns a summary dict: ``changed_files`` (config-relative), ``backup_dir``
    (config-relative or ``None``), and ``applied`` (count).
    Raises :class:`ConfigEditError` if any edit cannot be located, or if the
    resulting config fails validation (after restoring the backup).
    """
    config_dir = Path(config_dir)
    if not isinstance(edits, list) or not edits:
        raise ConfigEditError("no edits provided")

    all_files = _iter_config_yaml_files(config_dir)
    node_files = [p for p in all_files if p.name == "node.yaml"]
    module_files = [p for p in all_files if p.name == "modules.yaml"]
    network_files = [p for p in all_files if p.parent.name == "network"]
    port_package = _build_port_package_map(config_dir)
    known_ports = _build_known_ports(config_dir, all_files)

    pending = _PendingChanges(config_dir)
    for edit in edits:
        kind = str(edit.get("kind") or "")
        if kind == "set_connector":
            _apply_set_connector(edit, pending, node_files, module_files)
        elif kind == "rewire_connection":
            _apply_rewire(edit, pending, network_files, port_package, known_ports)
        else:
            raise ConfigEditError(f"unknown edit kind '{kind}'")

    backup_rel = _backup(config_dir, pending.touched) if backup else None
    pending.write_all()

    if validate:
        try:
            _validate_config(config_dir)
        except Exception as exc:  # noqa: BLE001 - re-raised as edit error
            if backup_rel is not None:
                _restore(config_dir, backup_rel)
            raise ConfigEditError(f"edit rejected by validation: {exc}") from exc

    return {
        "changed_files": sorted(str(p.relative_to(config_dir)) for p in pending.touched),
        "backup_dir": backup_rel,
        "applied": len(edits),
    }


def _validate_config(config_dir: Path) -> None:
    from certiqs_sim.core.topology.loader import load_topology
    from certiqs_sim.core.topology.validate import assert_valid

    assert_valid(load_topology(config_dir))


__all__ = ["apply_config_edits", "ConfigEditError", "BACKUP_DIRNAME"]
