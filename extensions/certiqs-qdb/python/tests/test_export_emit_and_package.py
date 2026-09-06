import zipfile
from io import BytesIO

import yaml

from app.export.emit.index import run_emitters
from app.export.package import package_zip, safe_name
from app.export.params.resolve import apply_resolved_values, collect_missing_parameters
from tests.test_export_build_and_validate import make_minimal_aggregate
from app.export.build import build_model


def test_safe_name_strips_special_characters():
    assert safe_name("Fraunhofer HHI QKD System #1!") == "fraunhofer-hhi-qkd-system-1"


def test_safe_name_none_falls_back_to_system():
    assert safe_name(None) == "system"


def test_safe_name_all_special_chars_falls_back_to_system():
    assert safe_name("###") == "system"


def test_run_emitters_produces_9_files_with_toplevel_first():
    built = build_model(make_minimal_aggregate())
    files = run_emitters(built.model, built.connections)
    assert len(files) == 9
    assert files[0].filename == "00_toplevel.yaml"
    assert {f.filename for f in files} == {
        "00_toplevel.yaml", "01_protocol.yaml", "02_source_central.yaml", "03_alice_node.yaml",
        "04_bob_node.yaml", "05_channels.yaml", "06_digital.yaml", "07_post_processing.yaml", "08_cosim.yaml",
    }


def test_run_emitters_toplevel_imports_are_sorted_and_match_emitted_filenames():
    built = build_model(make_minimal_aggregate())
    files = run_emitters(built.model, built.connections)
    toplevel = yaml.safe_load(files[0].content)
    concern_filenames = sorted(f.filename for f in files[1:])
    assert toplevel["imports"] == concern_filenames


def test_run_emitters_output_is_valid_yaml_for_every_file():
    built = build_model(make_minimal_aggregate())
    files = run_emitters(built.model, built.connections)
    for f in files:
        parsed = yaml.safe_load(f.content)
        assert parsed is not None, f"{f.filename} produced empty/invalid YAML"


def test_run_emitters_alice_file_contains_its_instance():
    built = build_model(make_minimal_aggregate())
    files = run_emitters(built.model, built.connections)
    alice_file = next(f for f in files if f.filename == "03_alice_node.yaml")
    parsed = yaml.safe_load(alice_file.content)
    instance_names = [i["name"] for i in parsed["instances"]]
    assert "alice_apd_h" in instance_names


def test_run_emitters_instance_with_null_role_omits_role_key():
    built = build_model(make_minimal_aggregate())
    files = run_emitters(built.model, built.connections)
    alice_file = next(f for f in files if f.filename == "03_alice_node.yaml")
    parsed = yaml.safe_load(alice_file.content)
    alice_instance = next(i for i in parsed["instances"] if i["name"] == "alice_apd_h")
    assert "role" not in alice_instance  # role was None on this component -> omitted, not null


def test_package_zip_contains_all_files_readable():
    built = build_model(make_minimal_aggregate())
    files = run_emitters(built.model, built.connections)
    # package_zip takes variant groups [(folder_prefix, files), ...]; the real
    # export bundles both ideal/ and characterised/ into one zip.
    groups = [("ideal", files), ("characterised", files)]
    zip_bytes = package_zip(groups)
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        expected = {f"{prefix}/{f.filename}" for prefix, group in groups for f in group}
        assert names == expected
        content = zf.read("ideal/01_protocol.yaml").decode("utf-8")
        assert "BBM92" in content


def test_collect_and_apply_missing_parameters_roundtrip():
    built = build_model(make_minimal_aggregate())
    missing = collect_missing_parameters(built.model)
    # efficiency was already supplied for both detectors, so only genuinely-missing
    # required specs (e.g. jitter is not required) should surface — spot check that
    # a known-present field is NOT flagged as missing.
    locations = {m.location for m in missing}
    assert "instance:alice_apd_h.efficiency" not in locations

    values = {m.location: m.spec.typical for m in missing}
    apply_resolved_values(built.model, missing, values)
    # After applying, re-collecting should find nothing left for those specific specs.
    still_missing = collect_missing_parameters(built.model)
    assert still_missing == []
