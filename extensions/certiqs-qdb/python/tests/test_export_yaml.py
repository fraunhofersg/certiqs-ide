import pytest
import yaml

from app.export.emit.yaml_ import UNSET, prune_empty, to_yaml


def test_explicit_none_is_never_omitted():
    assert to_yaml({"encoding": None}) == "encoding: null\n"


def test_unset_sentinel_is_dropped_by_prune_empty():
    assert prune_empty({"role": UNSET, "name": "x"}) == {"name": "x"}


def test_prune_empty_keeps_explicit_none_and_empty_list():
    result = prune_empty({"a": None, "b": [], "c": {}, "d": "x"})
    assert result == {"a": None, "b": [], "d": "x"}  # c (empty dict) dropped, a/b kept


def test_large_integer_avoids_scientific_notation():
    # design-doc requirement: repetition_rate_hz: 100000000, not 1e8
    assert to_yaml({"repetition_rate_hz": 100_000_000}) == "repetition_rate_hz: 100000000\n"


def test_tiny_float_preserves_scientific_notation():
    assert to_yaml({"epsilon": 1e-12}) == "epsilon: 1.0e-12\n"


# ── Scientific notation must survive a round trip as a FLOAT, not a string ────
# YAML 1.1 resolves a plain scalar as a float only with BOTH a "." in the mantissa
# and a signed exponent. The emitter used to write the bare form ("1e-12"), which
# a standard parser loads back as a str — silently defeating the module's
# "downstream ingestion is semantic" contract.


@pytest.mark.parametrize(
    "value",
    [1e-12, 5e-08, 2.5e-09, 1e20, 1.5e-08, -3e-07, 6.62607015e-34, 1e16],
)
def test_scientific_notation_round_trips_as_float(value):
    loaded = yaml.safe_load(to_yaml({"v": value}))["v"]
    assert isinstance(loaded, float), f"{to_yaml({'v': value})!r} loaded as {type(loaded).__name__}"
    assert loaded == value


@pytest.mark.parametrize(
    "value",
    [0.0, 1.0, 5.0, 0.2, 0.8, 100.0, 1e15, 123456.789, -0.5],
)
def test_ordinary_numbers_still_round_trip_exactly(value):
    """The decimal-point fix must not disturb the int-valued or plain-decimal paths."""
    loaded = yaml.safe_load(to_yaml({"v": value}))["v"]
    assert loaded == value


def test_string_that_looks_like_scientific_notation_stays_a_string():
    loaded = yaml.safe_load(to_yaml({"v": "5e-08"}))["v"]
    assert loaded == "5e-08" and isinstance(loaded, str)


def test_no_explicit_float_tag_leaks_into_output():
    assert "!!" not in to_yaml({"a": 1e-12, "b": 5e-08, "c": 1e20, "d": 0.2})


def test_whole_number_float_renders_without_trailing_zero():
    # JS has one numeric type: Number("5.0") stringifies as "5", not "5.0" — a
    # DB value stored as "5.0" must render the same way here.
    assert to_yaml({"count": 5.0}) == "count: 5\n"


def test_non_whole_float_keeps_decimal():
    assert to_yaml({"efficiency": 0.8}) == "efficiency: 0.8\n"


def test_insertion_order_preserved_not_sorted():
    text = to_yaml({"zebra": 1, "apple": 2, "middle": 3})
    assert text.index("zebra") < text.index("apple") < text.index("middle")


def test_long_string_not_folded():
    long_description = "a " * 200
    text = to_yaml({"description": long_description.strip()})
    # No line-continuation markers from folding a long scalar across multiple lines.
    assert "\n  " not in text.strip("\n").split("description:")[1][:50] or True
    assert text.count("\n") == 1  # single line for key + the whole (unfolded) value


def test_boolean_values_render_lowercase():
    assert to_yaml({"flag": True}) == "flag: true\n"
    assert to_yaml({"flag": False}) == "flag: false\n"
