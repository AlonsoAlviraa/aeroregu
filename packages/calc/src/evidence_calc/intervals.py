"""Rigorous rational and arbitrary-precision ball/interval arithmetic via FLINT/Arb.

Computes unrounded intermediate expressions using python-flint (fmpq / arb) so
multi-stage quantize() drift can be bounded, audited, and certified with exact
lower/upper enclosures.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Any

from flint import arb, ctx, fmpq

_BALL_DPS = 50
_DISPLAY_QUANTUM = Decimal("0.000001")
_DRIFT_QUANTUM = Decimal("0.000000001")


def _arb_from_decimal_text(text: str) -> arb:
    """Convert an exact base-10 string cleanly to an arbitrary-precision ball."""
    ctx.dps = _BALL_DPS
    frac = Fraction(text)
    if frac.denominator == 1:
        return arb(int(frac.numerator))
    return arb(fmpq(int(frac.numerator), int(frac.denominator)))


def _arb_bounds_decimal(ball: arb, scale: Decimal = _DISPLAY_QUANTUM) -> dict[str, str]:
    """Extract sound Decimal lower/upper bounds and midpoint string from an Arb ball."""
    ctx.dps = _BALL_DPS
    mid_dec = Decimal(ball.mid().str(30, radius=False))
    rad_dec = Decimal(ball.rad().str(15, radius=False))
    lower_dec = (mid_dec - rad_dec).quantize(scale, rounding=ROUND_FLOOR)
    upper_dec = (mid_dec + rad_dec).quantize(scale, rounding=ROUND_CEILING)
    mid_quant = mid_dec.quantize(scale, rounding=ROUND_HALF_EVEN)
    return {
        "mid": format(mid_quant, "f"),
        "lower": format(lower_dec, "f"),
        "upper": format(upper_dec, "f"),
        "radius": format(rad_dec, "E"),
    }


def _drift_entry(ball: arb, staged_text: str) -> dict[str, Any]:
    """Build exact unrounded interval record plus drift relative to staged quantize output."""
    bounds = _arb_bounds_decimal(ball)
    mid_dec = Decimal(bounds["mid"])
    staged_dec = Decimal(staged_text)
    drift = (staged_dec - mid_dec).copy_abs().quantize(_DRIFT_QUANTUM, rounding=ROUND_HALF_EVEN)
    return {
        **bounds,
        "staged": staged_text,
        "quantization_drift": format(drift, "f"),
    }


def evaluate_bolt_screen_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate bolt_screen without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    area = _arb_from_decimal_text(str(inputs["area_mm2"]))
    shear = _arb_from_decimal_text(str(inputs["shear_force_n"]))
    tensile = _arb_from_decimal_text(str(inputs["tensile_force_n"]))
    shear_allow = _arb_from_decimal_text(str(inputs["shear_allowable_mpa"]))
    tensile_allow = _arb_from_decimal_text(str(inputs["tensile_allowable_mpa"]))

    shear_stress = shear / area
    tensile_stress = tensile / area
    shear_ratio = shear_stress / shear_allow
    tensile_ratio = tensile_stress / tensile_allow
    interaction = (shear_ratio * shear_ratio + tensile_ratio * tensile_ratio).sqrt()

    return {
        "shear_stress_mpa": _drift_entry(shear_stress, str(staged_outputs["shear_stress_mpa"])),
        "tensile_stress_mpa": _drift_entry(
            tensile_stress, str(staged_outputs["tensile_stress_mpa"])
        ),
        "shear_ratio": _drift_entry(shear_ratio, str(staged_outputs["shear_ratio"])),
        "tensile_ratio": _drift_entry(tensile_ratio, str(staged_outputs["tensile_ratio"])),
        "interaction_ratio": _drift_entry(interaction, str(staged_outputs["interaction_ratio"])),
    }


def evaluate_hover_power_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate hover_power_screen without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    area = _arb_from_decimal_text(str(inputs["disk_area_m2"]))
    thrust = _arb_from_decimal_text(str(inputs["thrust_n"]))
    rho = _arb_from_decimal_text(str(inputs["air_density_kg_m3"]))
    fm = _arb_from_decimal_text(str(inputs["figure_of_merit"]))
    p_avail = _arb_from_decimal_text(str(inputs["power_available_kw"]))

    disk_loading = thrust / area
    induced_velocity = (thrust / (arb(2) * rho * area)).sqrt()
    ideal_power = (thrust * induced_velocity) / arb(1000)
    shaft_power = ideal_power / fm
    power_margin = (p_avail - shaft_power) / p_avail

    return {
        "disk_loading_pa": _drift_entry(disk_loading, str(staged_outputs["disk_loading_pa"])),
        "induced_velocity_m_s": _drift_entry(
            induced_velocity, str(staged_outputs["induced_velocity_m_s"])
        ),
        "ideal_power_kw": _drift_entry(ideal_power, str(staged_outputs["ideal_power_kw"])),
        "shaft_power_kw": _drift_entry(shaft_power, str(staged_outputs["shaft_power_kw"])),
        "power_margin_ratio": _drift_entry(power_margin, str(staged_outputs["power_margin_ratio"])),
    }


def _fmpq_from_text(text: Any) -> fmpq:
    frac = Fraction(str(text))
    return fmpq(frac.numerator, frac.denominator)


def evaluate_rigid_body_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate rigid_body_point_mass without intermediate rounding via exact rational fmpq."""
    ctx.dps = _BALL_DPS
    mass = _fmpq_from_text(inputs["mass_kg"])
    g = _fmpq_from_text(inputs["gravity_m_s2"])
    lf = _fmpq_from_text(inputs["load_factor"])
    cg_x = _fmpq_from_text(inputs["cg_x_m"])
    operative = list(inputs["unit_operative"])
    unit_x = [_fmpq_from_text(item) for item in inputs["unit_x_m"]]

    weight_q = mass * g
    req_q = weight_q * lf
    active = sum(1 for flag in operative if flag)
    share_q = req_q / active
    forces_q = [share_q if flag else fmpq(0) for flag in operative]
    moment_q = sum(
        (force * (pos - cg_x) for force, pos in zip(forces_q, unit_x, strict=True)),
        fmpq(0),
    )

    return {
        "weight_n": _drift_entry(arb(weight_q), str(staged_outputs["weight_n"])),
        "required_vertical_force_n": _drift_entry(
            arb(req_q), str(staged_outputs["required_vertical_force_n"])
        ),
        "moment_about_cg_n_m": _drift_entry(
            arb(moment_q), str(staged_outputs["moment_about_cg_n_m"])
        ),
    }


def evaluate_method_intervals(
    method_id: str,
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Dispatch exact FLINT/Arb unrounded evaluation for a screening method."""
    if method_id == "bolt_screen":
        return evaluate_bolt_screen_intervals(inputs, staged_outputs)
    if method_id == "hover_power_screen":
        return evaluate_hover_power_intervals(inputs, staged_outputs)
    if method_id == "rigid_body_point_mass":
        return evaluate_rigid_body_intervals(inputs, staged_outputs)
    return {}
