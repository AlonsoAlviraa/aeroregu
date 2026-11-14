from __future__ import annotations

from decimal import Decimal

from evidence_calc.registry import run_method
from hypothesis import given, settings
from hypothesis import strategies as st


def test_bolt_screen_exact_intervals_match_exact_vector() -> None:
    inputs = {
        "shear_force_n": "3000.000",
        "tensile_force_n": "4000.000",
        "area_mm2": "100.000",
        "shear_allowable_mpa": "250.000",
        "tensile_allowable_mpa": "250.000",
    }
    res = run_method("bolt_screen", inputs, include_intervals=True)
    intervals = res["exact_intervals"]
    inter = intervals["interaction_ratio"]
    assert Decimal(inter["lower"]) <= Decimal("0.200") <= Decimal(inter["upper"])
    assert Decimal(inter["quantization_drift"]) == Decimal("0.000000000")


def test_bolt_screen_measures_staged_rounding_drift() -> None:
    # Choose values that create rounding at stress -> ratio -> sqrt steps
    inputs = {
        "shear_force_n": "1000.000",
        "tensile_force_n": "1000.000",
        "area_mm2": "300.000",
        "shear_allowable_mpa": "200.000",
        "tensile_allowable_mpa": "200.000",
    }
    res = run_method("bolt_screen", inputs, include_intervals=True)
    intervals = res["exact_intervals"]
    inter = intervals["interaction_ratio"]
    assert Decimal(inter["lower"]) <= Decimal(inter["mid"]) <= Decimal(inter["upper"])
    assert Decimal(inter["quantization_drift"]) > Decimal("0")


def test_hover_and_rigid_body_exact_intervals() -> None:
    hover = {
        "thrust_n": "9800.000",
        "disk_area_m2": "10.000",
        "air_density_kg_m3": "1.225",
        "figure_of_merit": "0.700",
        "power_available_kw": "350.000",
    }
    hover_res = run_method("hover_power_screen", hover, include_intervals=True)
    h_iv = hover_res["exact_intervals"]
    assert Decimal(h_iv["induced_velocity_m_s"]["lower"]) <= Decimal("20.000")
    assert Decimal(h_iv["induced_velocity_m_s"]["upper"]) >= Decimal("20.000")
    assert Decimal(h_iv["shaft_power_kw"]["quantization_drift"]) == Decimal("0.000000000")

    rigid = {
        "mass_kg": "800.000",
        "gravity_m_s2": "10.000",
        "load_factor": "1.000",
        "cg_x_m": "0.000",
        "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
        "unit_operative": [True, True, True, True],
    }
    rigid_res = run_method("rigid_body_point_mass", rigid, include_intervals=True)
    r_iv = rigid_res["exact_intervals"]
    assert Decimal(r_iv["weight_n"]["mid"]) == Decimal("8000.000000")
    assert Decimal(r_iv["moment_about_cg_n_m"]["quantization_drift"]) == Decimal("0.000000000")


@settings(max_examples=20, deadline=None)
@given(
    shear=st.integers(min_value=100, max_value=50000),
    tensile=st.integers(min_value=100, max_value=50000),
    area=st.integers(min_value=10, max_value=500),
)
def test_property_flint_arb_sound_enclosure(shear: int, tensile: int, area: int) -> None:
    inputs = {
        "shear_force_n": f"{shear}.000",
        "tensile_force_n": f"{tensile}.000",
        "area_mm2": f"{area}.000",
        "shear_allowable_mpa": "250.000",
        "tensile_allowable_mpa": "250.000",
    }
    res = run_method("bolt_screen", inputs, include_intervals=True)
    for entry in res["exact_intervals"].values():
        assert Decimal(entry["lower"]) <= Decimal(entry["mid"]) <= Decimal(entry["upper"])


def test_arb_bounds_decimal_encloses_repeating_decimal_outwardly() -> None:
    from evidence_calc.intervals import _arb_bounds_decimal
    from flint import arb, ctx

    ctx.dps = 50
    one_third = arb(1) / arb(3)
    bounds = _arb_bounds_decimal(one_third, Decimal("0.000001"))
    assert Decimal(bounds["lower"]) == Decimal("0.333333")
    assert Decimal(bounds["upper"]) == Decimal("0.333334")
    assert Decimal(bounds["lower"]) < (Decimal(1) / Decimal(3)) < Decimal(bounds["upper"])
