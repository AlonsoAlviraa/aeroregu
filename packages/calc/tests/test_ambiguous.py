import pytest
from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method
from evidence_eval.detect import assess
from evidence_eval.faults import clean_artifact
from evidence_eval.generate import _bolt

BOLT = {
    "shear_force_n": "3000.000",
    "tensile_force_n": "4000.000",
    "area_mm2": "100.000",
    "shear_allowable_mpa": "250.000",
    "tensile_allowable_mpa": "250.000",
}


def test_two_numbers_in_one_field_abstain() -> None:
    inputs = dict(BOLT)
    inputs["shear_force_n"] = "3000.000 or 4000.000"
    with pytest.raises(AbstainError) as caught:
        run_method("bolt_screen", inputs)
    assert caught.value.reason == "ambiguous_input"


def test_a_list_of_candidate_scalars_abstains() -> None:
    inputs = dict(BOLT)
    inputs["area_mm2"] = ["80.000", "100.000"]
    with pytest.raises(AbstainError) as caught:
        run_method("bolt_screen", inputs)
    assert caught.value.reason == "ambiguous_input"


def test_assess_routes_an_ambiguous_field_to_abstain() -> None:
    from decimal import Decimal

    artifact = clean_artifact("bolt_screen", _bolt(Decimal("3000")))
    artifact["inputs"]["shear_force_n"] = "3000.000 or 1.000"
    result = assess(artifact)
    assert result["verdict"] == "abstain"
    assert result["envelope"]["abstain"]["reason"] == "ambiguous_input"
    assert "result" not in result["envelope"]


def test_scientific_notation_and_max_exclusive_limits() -> None:
    from decimal import Decimal

    from evidence_calc.quantize import parse_limited_decimal, reject_ambiguous

    reject_ambiguous("1e-5")
    reject_ambiguous("-2.5E+3")
    with pytest.raises(AbstainError):
        reject_ambiguous("100-200")
    assert parse_limited_decimal("2.5e1", {"min": "0", "max_exclusive": "30"}) == Decimal("25")
    with pytest.raises(AbstainError) as caught:
        parse_limited_decimal("30", {"min": "0", "max_exclusive": "30"})
    assert caught.value.reason == "outside_validity"
