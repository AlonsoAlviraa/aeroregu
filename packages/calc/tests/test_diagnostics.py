from decimal import Decimal

from evidence_calc.diagnostics import _scale_decimals, classify_numeric_delta
from evidence_calc.registry import run_method

BOLT_INPUTS = {
    "shear_force_n": "3000.000",
    "tensile_force_n": "4000.000",
    "area_mm2": "80.000",
    "shear_allowable_mpa": "250.000",
    "tensile_allowable_mpa": "250.000",
    "thickness_mm": "5.000",
}

RIGID_INPUTS = {
    "mass_kg": "800.000",
    "gravity_m_s2": "10.000",
    "load_factor": "1.000",
    "cg_x_m": "0.200",
    "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
    "unit_operative": [True, True, True, True],
}


def test_classify_clean_and_unit_scale() -> None:
    recomputed = run_method("bolt_screen", BOLT_INPUTS)["outputs"]
    assert classify_numeric_delta("bolt_screen", BOLT_INPUTS, recomputed, recomputed) == "clean"

    scaled_inputs = dict(BOLT_INPUTS, shear_force_n="3.000")
    stated_unit_scale = run_method("bolt_screen", scaled_inputs)["outputs"]
    assert (
        classify_numeric_delta("bolt_screen", BOLT_INPUTS, stated_unit_scale, recomputed)
        == "unit_scale"
    )


def test_classify_sign_wrong_input_arithmetic_and_unexplained() -> None:
    recomputed = run_method("rigid_body_point_mass", RIGID_INPUTS)["outputs"]

    sign_inputs = dict(RIGID_INPUTS, cg_x_m="-0.200")
    stated_sign = run_method("rigid_body_point_mass", sign_inputs)["outputs"]
    assert (
        classify_numeric_delta("rigid_body_point_mass", RIGID_INPUTS, stated_sign, recomputed)
        == "sign"
    )

    swapped_inputs = dict(BOLT_INPUTS, shear_force_n="4000.000")
    stated_wrong = run_method("bolt_screen", swapped_inputs)["outputs"]
    recomputed_bolt = run_method("bolt_screen", BOLT_INPUTS)["outputs"]
    assert (
        classify_numeric_delta("bolt_screen", BOLT_INPUTS, stated_wrong, recomputed_bolt)
        == "wrong_input"
    )

    stated_arith = _scale_decimals(recomputed, Decimal("2"), Decimal("0.001"))
    assert (
        classify_numeric_delta("rigid_body_point_mass", RIGID_INPUTS, stated_arith, recomputed)
        == "arithmetic"
    )

    stated_unexplained = dict(recomputed, weight_n="1.250")
    assert (
        classify_numeric_delta(
            "rigid_body_point_mass", RIGID_INPUTS, stated_unexplained, recomputed
        )
        == "unexplained"
    )
