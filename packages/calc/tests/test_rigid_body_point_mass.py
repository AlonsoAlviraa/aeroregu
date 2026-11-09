from decimal import Decimal

import pytest
from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum
from evidence_calc.registry import load_card, run_method
from hypothesis import given, settings
from hypothesis import strategies as st

VECTOR = {
    "mass_kg": "800.000",
    "gravity_m_s2": "10.000",
    "load_factor": "1.000",
    "cg_x_m": "0.000",
    "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
    "unit_operative": [True, True, True, True],
}


def test_altitude_is_not_an_input() -> None:
    card = load_card("rigid_body_point_mass")
    assert "altitude_m" not in card["inputs"]
    assert "altitude_m" not in card["input_units"]
    inputs = {key: value for key, value in VECTOR.items() if key != "altitude_m"}
    outputs = run_method("rigid_body_point_mass", inputs)["outputs"]
    assert outputs["required_vertical_force_n"] == "8000.000"
    assert outputs["moment_about_cg_n_m"] == "0.000"


def test_card_is_a_screening_illustration() -> None:
    card = load_card("rigid_body_point_mass")
    assert card["label"] == "ASSUMPTION"
    assert card["title"] == "project-defined screening illustration"
    assert "not a handbook" in card["law_note"]
    assert "Newton" in card["law_note"]


def test_exact_vector() -> None:
    ran = run_method("rigid_body_point_mass", VECTOR)
    outputs = ran["outputs"]
    assert ran["method_version"] == "rigid_body_point_mass@1.0.0"
    assert outputs["weight_n"] == "8000.000"
    assert outputs["required_vertical_force_n"] == "8000.000"
    assert outputs["unit_force_n"] == ["2000.000", "2000.000", "2000.000", "2000.000"]
    assert outputs["vertical_residual_n"] == "0.000"
    assert outputs["moment_about_cg_n_m"] == "0.000"
    again = run_method("rigid_body_point_mass", dict(reversed(list(VECTOR.items()))))
    assert again["outputs"] == outputs


def test_one_inoperative_unit_balances() -> None:
    inputs = dict(VECTOR)
    inputs["unit_operative"] = [True, True, True, False]
    outputs = run_method("rigid_body_point_mass", inputs)["outputs"]
    assert outputs["unit_force_n"] == ["2666.667", "2666.667", "2666.666", "0.000"]
    assert outputs["vertical_residual_n"] == "0.000"


def test_missing_input_abstains_without_a_number() -> None:
    inputs = dict(VECTOR)
    del inputs["mass_kg"]
    with pytest.raises(AbstainError) as caught:
        run_method("rigid_body_point_mass", inputs)
    assert caught.value.reason == "missing_input"


def test_outside_validity_abstains() -> None:
    inputs = dict(VECTOR)
    inputs["mass_kg"] = "6000.000"
    with pytest.raises(AbstainError) as caught:
        run_method("rigid_body_point_mass", inputs)
    assert caught.value.reason == "outside_validity"


@settings(max_examples=25, deadline=None)
@given(
    mass=st.decimals(
        min_value=Decimal("1"),
        max_value=Decimal("5000"),
        places=3,
        allow_nan=False,
        allow_infinity=False,
    ),
    load=st.decimals(
        min_value=Decimal("-2"),
        max_value=Decimal("4"),
        places=3,
        allow_nan=False,
        allow_infinity=False,
    ),
    failed=st.sampled_from([None, 0, 1, 2, 3]),
)
def test_vertical_force_balance_within_one_quantum(
    mass: Decimal, load: Decimal, failed: int | None
) -> None:
    operative = [True, True, True, True]
    if failed is not None:
        operative[failed] = False
    inputs = {
        "mass_kg": format_quantum(mass, Decimal("0.001")),
        "gravity_m_s2": "9.810",
        "load_factor": format_quantum(load, Decimal("0.001")),
        "cg_x_m": "0.000",
        "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
        "unit_operative": operative,
    }
    outputs = run_method("rigid_body_point_mass", inputs)["outputs"]
    residual = Decimal(outputs["vertical_residual_n"])
    assert residual.copy_abs() <= Decimal("0.001")
    forces = [Decimal(item) for item in outputs["unit_force_n"]]
    required = Decimal(outputs["required_vertical_force_n"])
    assert abs(sum(forces) - required) <= Decimal("0.001")
