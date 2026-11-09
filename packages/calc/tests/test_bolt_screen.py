from decimal import Decimal

import pytest
from evidence_calc.errors import AbstainError
from evidence_calc.registry import load_card, run_method

BOLT = {
    "shear_force_n": "3000.000",
    "tensile_force_n": "4000.000",
    "area_mm2": "100.000",
    "shear_allowable_mpa": "250.000",
    "tensile_allowable_mpa": "250.000",
}


def test_card_is_not_a_certification_method() -> None:
    card = load_card("bolt_screen")
    assert card["label"] == "ASSUMPTION"
    assert "screening illustration" in card["title"]
    assert "not a certification method" in card["note"]


def test_exact_interaction() -> None:
    outputs = run_method("bolt_screen", BOLT)["outputs"]
    assert outputs["shear_stress_mpa"] == "30.000"
    assert outputs["tensile_stress_mpa"] == "40.000"
    assert outputs["shear_ratio"] == "0.120"
    assert outputs["tensile_ratio"] == "0.160"
    assert outputs["interaction_ratio"] == "0.200"
    assert run_method("bolt_screen", BOLT)["outputs"] == outputs


def test_area_zero_abstains() -> None:
    inputs = dict(BOLT)
    inputs["area_mm2"] = "0.000"
    with pytest.raises(AbstainError) as caught:
        run_method("bolt_screen", inputs)
    assert caught.value.reason == "area_zero"


def test_bolt_screen_runs_without_thickness() -> None:
    card = load_card("bolt_screen")
    assert "thickness_mm" not in card["required"]
    assert "thickness_mm" not in card["limits"]
    assert "thickness_mm" not in card["input_units"]
    inputs = {key: value for key, value in BOLT.items() if key != "thickness_mm"}
    outputs = run_method("bolt_screen", inputs)["outputs"]
    assert outputs["shear_stress_mpa"] == "30.000"
    assert outputs["tensile_stress_mpa"] == "40.000"
    assert outputs["interaction_ratio"] == "0.200"


def test_interaction_is_on_the_quantum() -> None:
    outputs = run_method("bolt_screen", BOLT)["outputs"]
    ratio = Decimal(outputs["interaction_ratio"])
    assert ratio >= 0
    assert ratio == ratio.quantize(Decimal("0.001"))
