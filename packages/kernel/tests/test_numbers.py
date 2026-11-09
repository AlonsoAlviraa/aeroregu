from evidence_kernel.numbers import stray_physical_numbers


def test_a_requirement_identifier_is_not_a_physical_number() -> None:
    assert stray_physical_numbers({"requirement_id": "CS-27.301"}, set()) == []
    assert stray_physical_numbers({"requirement_id": "CS-29.301"}, set()) == []


def test_a_negative_decimal_is_still_a_physical_number() -> None:
    assert stray_physical_numbers("mass -1.5 kg", set()) == ["-1.5"]


def test_a_bare_integer_is_a_physical_number() -> None:
    assert stray_physical_numbers({"note": "800"}, set()) == ["800"]
    assert stray_physical_numbers("the load is 800 N", set()) == ["800"]
    assert stray_physical_numbers("the load is -800 N", set()) == ["-800"]


def test_an_allowed_integer_copy_is_not_stray() -> None:
    assert stray_physical_numbers({"note": "800"}, {"800"}) == []


def test_indexes_units_and_evidence_ids_are_not_physical_numbers() -> None:
    assert stray_physical_numbers({"span_start": "0", "span_end": "12"}, set()) == []
    assert stray_physical_numbers({"unit": "1"}, set()) == []
    assert stray_physical_numbers({"unit": "meter / second ** 2"}, set()) == []
    assert stray_physical_numbers({"evidence_id": "ev-1"}, set()) == []
