"""Component taxonomy + identity catalog + resolved component inventory.

Joins logical components from the active configuration set (e.g.
``config/bbm92-generic``) with the model registry and optional catalog
identity records. Design guides under ``guide/`` are background only and
are never read at runtime.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from certiqs_sim.core.components.registry import get_model_for_class

TAXONOMY_FILENAMES = (
    "shared/taxonomy.yaml",
    "19_component_taxonomy.yaml",
    "16_component_taxonomy.yaml",
)
CATALOG_FILENAMES = (
    "shared/catalog.yaml",
    "18_component_catalog.yaml",
    "15_component_catalog.yaml",
)


def _first_existing_yaml(filenames: tuple[str, ...], config_dir: Path | None) -> Path | None:
    for filename in filenames:
        for path in _candidate_paths(filename, config_dir):
            if path.is_file():
                return path
    return None


def load_taxonomy(config_dir: Path | None = None) -> dict[str, Any] | None:
    """Load the component taxonomy; returns the ``component_taxonomy`` mapping."""
    path = _first_existing_yaml(TAXONOMY_FILENAMES, config_dir)
    if path is None:
        return None
    data = _load_yaml(path)
    if "component_taxonomy" in data:
        return data["component_taxonomy"]
    legacy = data.get("legacy_taxonomy") or {}
    if isinstance(legacy, dict) and "component_taxonomy" in legacy:
        return legacy["component_taxonomy"]
    # Schema 3.1 config stubs use ``taxonomy:`` with a categories list.
    stub = data.get("taxonomy")
    if isinstance(stub, dict) and "categories" in stub:
        return stub
    return None


def load_catalog(config_dir: Path | None = None) -> dict[str, Any] | None:
    """Load the component identity catalog; returns ``component_catalog``."""
    path = _first_existing_yaml(CATALOG_FILENAMES, config_dir)
    if path is None:
        return None
    return _load_yaml(path).get("component_catalog")


def _candidate_paths(filename: str, config_dir: Path | None) -> list[Path]:
    """Resolve YAML only inside the active configuration set directory."""
    if config_dir is None:
        return []
    root = Path(config_dir)
    paths: list[Path] = [root / filename]
    # Legacy flat filenames at the config set root (e.g. 16_component_taxonomy.yaml).
    basename = Path(filename).name
    if basename != filename:
        paths.append(root / basename)
    return paths


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse to a mapping")
    return data


def taxonomy_index(taxonomy: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Index (category_id, subcategory_id) -> subcategory node (with icon etc.)."""
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for cat in (taxonomy or {}).get("categories", []):
        cat_id = cat.get("category_id", "")
        for sub in cat.get("subcategories", []):
            index[(cat_id, sub.get("subcategory_id", ""))] = {
                "category_name": cat.get("name"),
                "subcategory_name": sub.get("name"),
                "icon": sub.get("icon") or cat.get("icon"),
                "applicable_component_classes": sub.get("applicable_component_classes", []),
            }
    return index


def catalog_index(catalog: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index logical_component_id -> identity record from the catalog."""
    return {
        str(c.get("logical_component_id")): c
        for c in (catalog or {}).get("components", [])
        if c.get("logical_component_id")
    }


def manifest_sha256(config_dir: Path) -> str:
    """Deterministic hash of the resolved manifest (all YAML docs, parsed)."""
    docs: dict[str, Any] = {}
    for path in sorted(Path(config_dir).glob("*.y*ml")):
        docs[path.name] = _load_yaml(path)
    payload = json.dumps(docs, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_META_KEYS = {"component_class", "model_binding_id"}


def _settings_of(node: dict[str, Any]) -> dict[str, Any]:
    """Inline engineering parameters = everything except identity metadata."""
    return {k: v for k, v in node.items() if k not in _META_KEYS}


def _component_item(
    comp_id: str,
    comp: dict[str, Any],
    *,
    domain: str | None,
    subsystem: str | None,
    source_file: str,
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "logical_component_id": comp_id,
        "component_class": str(comp["component_class"]),
        "domain": domain,
        "subsystem": subsystem,
        "source_file": source_file,
        "settings": _settings_of(comp),
        "annotations": annotations or {},
        "declared_model_binding_id": comp.get("model_binding_id"),
    }


def _iter_instances(config_dir: Path) -> list[dict[str, Any]]:
    """Flatten every declared component across the schema-2.0 config docs.

    Covers: subsystem ``components:`` (with ``detector_array`` channel expansion),
    top-level ``components:`` (timing/digital), ``channels:``, ``post_processing:``
    stages, and ``countermeasures:`` that declare a ``component_class``.
    """
    items: list[dict[str, Any]] = []
    for path in sorted(Path(config_dir).glob("*.y*ml")):
        doc = _load_yaml(path)
        subsystem_node = doc.get("subsystem") or {}
        subsystem = subsystem_node.get("id") or subsystem_node.get("name")

        for comp_id, comp in (doc.get("components") or {}).items():
            if not isinstance(comp, dict) or "component_class" not in comp:
                continue
            if comp.get("component_class") == "detector_array":
                for det_id, det in (comp.get("channels") or {}).items():
                    if isinstance(det, dict) and "component_class" in det:
                        items.append(
                            _component_item(
                                str(det_id),
                                det,
                                domain="optical",
                                subsystem=subsystem,
                                source_file=path.name,
                                annotations={"detector_array": comp_id},
                            )
                        )
                continue
            items.append(
                _component_item(
                    str(comp_id),
                    comp,
                    domain="optical" if subsystem else "digital",
                    subsystem=subsystem,
                    source_file=path.name,
                )
            )

        for chan_id, chan in (doc.get("channels") or {}).items():
            if not isinstance(chan, dict) or "component_class" not in chan:
                continue
            items.append(
                _component_item(
                    str(chan_id),
                    chan,
                    domain="channel",
                    subsystem=None,
                    source_file=path.name,
                )
            )

        for section, domain in (("post_processing", "software"), ("countermeasures", "monitor")):
            for comp_id, comp in (doc.get(section) or {}).items():
                if not isinstance(comp, dict) or "component_class" not in comp:
                    continue
                items.append(
                    _component_item(
                        str(comp_id),
                        comp,
                        domain=domain,
                        subsystem=None,
                        source_file=path.name,
                    )
                )
    return items


def _iter_instances_from_docs(docs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten components from in-memory flat documents (adapter output)."""
    items: list[dict[str, Any]] = []
    for path_name, doc in docs.items():
        subsystem_node = doc.get("subsystem") or {}
        subsystem = subsystem_node.get("id") or subsystem_node.get("name")
        for comp_id, comp in (doc.get("components") or {}).items():
            if not isinstance(comp, dict) or "component_class" not in comp:
                continue
            if comp.get("component_class") == "detector_array":
                for det_id, det in (comp.get("channels") or {}).items():
                    if isinstance(det, dict) and "component_class" in det:
                        items.append(
                            _component_item(
                                str(det_id),
                                det,
                                domain="optical",
                                subsystem=subsystem,
                                source_file=path_name,
                                annotations={"detector_array": comp_id},
                            )
                        )
                continue
            items.append(
                _component_item(
                    str(comp_id),
                    comp,
                    domain="optical" if subsystem else "digital",
                    subsystem=subsystem,
                    source_file=path_name,
                )
            )
        for chan_id, chan in (doc.get("channels") or {}).items():
            if not isinstance(chan, dict) or "component_class" not in chan:
                continue
            items.append(
                _component_item(
                    str(chan_id),
                    chan,
                    domain="channel",
                    subsystem=None,
                    source_file=path_name,
                )
            )
        for section, domain in (("post_processing", "software"), ("countermeasures", "monitor")):
            for comp_id, comp in (doc.get(section) or {}).items():
                if not isinstance(comp, dict) or "component_class" not in comp:
                    continue
                items.append(
                    _component_item(
                        str(comp_id),
                        comp,
                        domain=domain,
                        subsystem=subsystem,
                        source_file=path_name,
                    )
                )
    return items


def build_component_inventory(config_dir: Path) -> dict[str, Any]:
    """Resolved component inventory for one config set.

    Joins: logical components (from the YAML manifest) x registry model
    binding x taxonomy classification x optional catalog identity record.
    """
    config_dir = Path(config_dir)
    taxonomy = load_taxonomy(config_dir)
    tax_index = taxonomy_index(taxonomy)
    identities = catalog_index(load_catalog(config_dir))

    structural_paths: dict[str, dict[str, str]] = {}
    sha_override: str | None = None
    try:
        from certiqs_sim.core.topology.loader import is_hierarchical_config, load_topology
        from certiqs_sim.core.topology.adapter import topology_to_flat_documents

        if is_hierarchical_config(config_dir):
            resolved = load_topology(config_dir)
            flat_docs = topology_to_flat_documents(resolved)
            sha_override = resolved.configuration_hash
            from certiqs_sim.core.topology.adapter import _FLAT_COMPONENT_IDS

            for comp_id in resolved.components:
                path = resolved.structural_path_for_component(comp_id)
                if not path:
                    continue
                path_dict = path.as_dict()
                structural_paths[comp_id] = path_dict
                flat_equiv = _FLAT_COMPONENT_IDS.get(comp_id, comp_id)
                structural_paths[flat_equiv] = path_dict
            items = _iter_instances_from_docs(flat_docs)
        else:
            items = _iter_instances(config_dir)
    except ImportError:
        items = _iter_instances(config_dir)

    components: list[dict[str, Any]] = []
    unmapped: list[str] = []
    for item in items:
        spec = get_model_for_class(item["component_class"])
        declared_binding = item.pop("declared_model_binding_id", None)
        logical_id = item["logical_component_id"]
        entry: dict[str, Any] = {
            **item,
            "model_binding_id": declared_binding or (spec.model_id if spec else None),
            "model_kind": spec.kind if spec else None,
            "classification": None,
            "identity": None,
            "structural_path": structural_paths.get(logical_id),
        }
        if spec:
            entry["classification"] = {
                "taxonomy_id": (taxonomy or {}).get("taxonomy_id", "caqkd_component_taxonomy"),
                "category_id": spec.category_id,
                "subcategory_id": spec.subcategory_id,
                **(tax_index.get((spec.category_id, spec.subcategory_id)) or {}),
            }
        else:
            unmapped.append(item["logical_component_id"])
        identity = identities.get(item["logical_component_id"])
        if identity:
            entry["identity"] = {
                "mapping_mode": identity.get("mapping_mode"),
                "product_identity": identity.get("product_identity"),
                "device_identity": identity.get("device_identity"),
                "digital_twin_identity": identity.get("digital_twin_identity"),
            }
        components.append(entry)

    return {
        "config_dir": str(config_dir),
        "manifest_sha256": sha_override or manifest_sha256(config_dir),
        "component_count": len(components),
        "unmapped_component_ids": unmapped,
        "components": components,
    }


def list_config_documents(config_dir: Path) -> dict[str, Any]:
    """List YAML documents available in one config set (recursive for schema 3.1)."""
    config_dir = Path(config_dir)
    manifest_path: Path | None = None
    for candidate in sorted(config_dir.glob("00_*.y*ml")):
        manifest_path = candidate
        break

    doc: dict[str, Any] = _load_yaml(manifest_path) if manifest_path else {}
    imports = [str(name) for name in doc.get("imports") or []]
    import_set = set(imports)
    on_disk = sorted(
        str(p.relative_to(config_dir))
        for p in config_dir.rglob("*.y*ml")
        if p.is_file() and not p.name.startswith(".")
    )

    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in imports:
        files.append({"name": name, "imported": True, "present": name in on_disk})
        seen.add(name)
    for name in on_disk:
        if name not in import_set:
            files.append({"name": name, "imported": False, "present": True})

    packages = doc.get("packages") or []
    return {
        "config_dir": str(config_dir),
        "manifest_file": manifest_path.name if manifest_path else None,
        "schema_version": doc.get("schema_version"),
        "manifest_name": doc.get("name") or (doc.get("manifest") or {}).get("name"),
        "manifest_description": doc.get("description") or (doc.get("manifest") or {}).get("description"),
        "packages": packages,
        "files": files,
    }


__all__ = [
    "build_component_inventory",
    "catalog_index",
    "list_config_documents",
    "load_catalog",
    "load_taxonomy",
    "manifest_sha256",
    "taxonomy_index",
]
