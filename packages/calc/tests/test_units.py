from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method


def test_compatible_units_still_run() -> None:
    ran = run_method(
        "bolt_screen",
        {
            "shear_force_n": "3000.000",
            "tensile_force_n": "4000.000",
            "area_mm2": "80.000",
            "shear_allowable_mpa": "250.000",
            "tensile_allowable_mpa": "250.000",
        },
    )
    assert "interaction_ratio" in ran["outputs"]


def test_conversion_interval_for_a_multiplicative_unit() -> None:
    from decimal import Decimal

    from evidence_calc.units import conversion_interval

    assert conversion_interval("meter", "meter") == Decimal("1")
    foot = conversion_interval("meter", "foot")
    exact = Decimal(1250) / Decimal(381)
    floated = Decimal("3.2808398950131235")
    assert isinstance(foot, Decimal)
    assert abs(foot - exact) < abs(floated - exact)
    assert conversion_interval("meter", "second") == "incompatible"
    assert conversion_interval("°C", "K") is None


def test_meter_is_length() -> None:
    from evidence_calc.units import dimension_exponents

    assert dimension_exponents("meter") == {"L": 1}
    assert dimension_exponents("not-a-unit") is None


def test_incompatible_unit_abstains() -> None:
    try:
        run_method(
            "rigid_body_point_mass",
            {
                "mass_kg": "800.000",
                "gravity_m_s2": "9.810",
                "load_factor": "1.500",
                "cg_x_m": "0.000",
                "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
                "unit_operative": [True, True, True, True],
                "_input_units": {"mass_kg": "meter"},
            },
        )
    except AbstainError as exc:
        assert exc.reason == "unit_mismatch"
        return
    raise AssertionError("expected unit_mismatch")
