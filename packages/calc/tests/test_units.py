from __future__ import annotations

from decimal import Decimal

import pytest
from evidence_calc.errors import AbstainError
from evidence_calc.registry import load_card, run_method
from evidence_calc.units import convert_inputs_to_card_units


def test_convert_inputs_to_card_units_kn_to_n_and_run_method() -> None:
    card = load_card("bolt_screen")
    inputs = {
        "shear_force_n": "3.000",
        "tensile_force_n": "4.000",
        "area_mm2": "80.000",
        "shear_allowable_mpa": "250.000",
        "tensile_allowable_mpa": "250.000",
        "_input_units": {
            "shear_force_n": "kN",
            "tensile_force_n": "kN",
            "area_mm2": "mm^2",
            "shear_allowable_mpa": "MPa",
            "tensile_allowable_mpa": "MPa",
        },
    }
    converted, conversions = convert_inputs_to_card_units(inputs, card)
    assert Decimal(converted["shear_force_n"]) == Decimal("3000.000")
    assert Decimal(converted["tensile_force_n"]) == Decimal("4000.000")
    assert len(conversions) == 2
    assert {item["field"] for item in conversions} == {"shear_force_n", "tensile_force_n"}

    ran = run_method("bolt_screen", inputs, normalize_units=True)
    assert ran["outputs"]["shear_stress_mpa"] == "37.500"
    assert ran["outputs"]["tensile_stress_mpa"] == "50.000"
    assert ran["outputs"]["interaction_ratio"] == "0.250"
    assert ran["normalized_inputs"]["shear_force_n"].startswith("3000")
    assert len(ran["unit_conversions"]) == 2


def test_convert_inputs_rejects_incompatible_dimension() -> None:
    card = load_card("bolt_screen")
    bad_inputs = {
        "shear_force_n": "3.000",
        "tensile_force_n": "4.000",
        "area_mm2": "80.000",
        "shear_allowable_mpa": "250.000",
        "tensile_allowable_mpa": "250.000",
        "_input_units": {
            "shear_force_n": "meter",
        },
    }
    with pytest.raises(AbstainError) as exc:
        convert_inputs_to_card_units(bad_inputs, card)
    assert exc.value.reason == "unit_mismatch"


def test_aerospace_unit_aliases_convert_cleanly() -> None:
    from decimal import Decimal

    from evidence_calc.units import conversion_interval, units_compatible

    assert units_compatible("kt", "m/s")
    assert units_compatible("km/h", "knot")
    assert units_compatible("fpm", "m/s")
    assert units_compatible("kgf", "lbf")
    assert units_compatible("ft*lbf", "N·m")
    assert units_compatible("nmi", "ft")
    factor = conversion_interval("daN", "N")
    assert factor == Decimal("10")
