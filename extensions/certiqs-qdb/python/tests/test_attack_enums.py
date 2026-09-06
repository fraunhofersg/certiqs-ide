from app.qkd.attack_enums import parse_module_field, validate_attack_fields


def test_parse_module_field_single_value():
    tokens, error = parse_module_field("Transmitter")
    assert tokens == ["Transmitter"]
    assert error is None


def test_parse_module_field_csv_values():
    tokens, error = parse_module_field("Transmitter, Receiver")
    assert tokens == ["Transmitter", "Receiver"]
    assert error is None


def test_parse_module_field_invalid_value():
    tokens, error = parse_module_field("Transmitter, Nonsense")
    assert tokens is None
    assert "Nonsense" in error


def test_parse_module_field_none_and_empty():
    assert parse_module_field(None) == (None, None)
    assert parse_module_field("") == (None, None)


def test_parse_module_field_non_string():
    tokens, error = parse_module_field(123)
    assert tokens is None
    assert error == "module must be a string"


def test_validate_attack_fields_all_valid():
    assert validate_attack_fields({
        "module": "Transmitter", "attack_type": "Active", "feasibility": "Not practical",
        "expertise": "Expert", "opportunity": "Easy", "equipment": "Standard", "attack_rating": "High",
    }) is None


def test_validate_attack_fields_invalid_rating():
    error = validate_attack_fields({"attack_rating": "Super High"})
    assert error is not None
    assert "attack_rating" in error


def test_validate_attack_fields_module_error_wins_first():
    error = validate_attack_fields({"module": "Nonsense", "attack_rating": "Also Wrong"})
    assert "Invalid module value" in error
