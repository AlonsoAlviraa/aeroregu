from __future__ import annotations

from decimal import Decimal

import pytest
from evidence_calc.errors import AbstainError
from evidence_calc.registry import load_card, run_method
from hypothesis import given
from hypothesis import strategies as st

HOVER = {
    "thrust_n": "9800.000",
    "disk_area_m2": "10.000",
    "air_density_kg_m3": "1.225",
    "figure_of_merit": "0.700",
    "power_available_kw": "350.000",
}


def test_hover_card_is_not_a_certification_method() -> None:
    card = load_card("hover_power_screen")
    assert card["label"] == "ASSUMPTION"
    assert card["not_a_certification_method"] is True
    assert "not a certification method" in card["note"]


def test_exact_hover_power_vector() -> None:
    outputs = run_method("hover_power_screen", HOVER)["outputs"]
    assert outputs["disk_loading_pa"] == "980.000"
    assert outputs["induced_velocity_m_s"] == "20.000"
    assert outputs["ideal_power_kw"] == "196.000"
    assert outputs["shaft_power_kw"] == "280.000"
    assert outputs["power_margin_ratio"] == "0.200"


def test_hover_area_zero_and_unit_mismatch_abstain() -> None:
    zero_area = {**HOVER, "disk_area_m2": "0.000"}
    with pytest.raises(AbstainError) as caught_area:
        run_method("hover_power_screen", zero_area)
    assert caught_area.value.reason == "area_zero"

    bad_units = {
        **HOVER,
        "_input_units": {"thrust_n": "kilowatt"},
    }
    with pytest.raises(AbstainError) as caught_unit:
        run_method("hover_power_screen", bad_units)
    assert caught_unit.value.reason == "unit_mismatch"


@given(
    thrust=st.integers(min_value=500, max_value=50000),
    area=st.integers(min_value=1, max_value=100),
    fm_milli=st.integers(min_value=350, max_value=900),
)
def test_property_shaft_power_exceeds_ideal_power(thrust: int, area: int, fm_milli: int) -> None:
    inputs = {
        "thrust_n": f"{thrust}.000",
        "disk_area_m2": f"{area}.000",
        "air_density_kg_m3": "1.225",
        "figure_of_merit": f"0.{fm_milli:03d}",
        "power_available_kw": "5000.000",
    }
    outputs = run_method("hover_power_screen", inputs)["outputs"]
    assert Decimal(outputs["shaft_power_kw"]) >= Decimal(outputs["ideal_power_kw"])
    assert Decimal(outputs["disk_loading_pa"]) > 0
