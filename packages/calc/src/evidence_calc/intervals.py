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
    mid_dec = Decimal(ball.mid().str(40, radius=False))
    rad_dec = Decimal(ball.rad().str(15, radius=False))
    # Pad outward for base-10 formatting truncation at 40/15 sig digits so bounds never narrow.
    sig_ulp = max(Decimal("1e-35"), abs(mid_dec) * Decimal("1e-35"))
    outward_rad = rad_dec * Decimal("1.000001") + sig_ulp
    lower_dec = (mid_dec - outward_rad).quantize(scale, rounding=ROUND_FLOOR)
    upper_dec = (mid_dec + outward_rad).quantize(scale, rounding=ROUND_CEILING)
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


def evaluate_margin_of_safety_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate margin_of_safety without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    applied = _arb_from_decimal_text(str(inputs["applied_load_n"]))
    allowable = _arb_from_decimal_text(str(inputs["allowable_load_n"]))
    rf = _arb_from_decimal_text(str(inputs["reserve_factor"]))
    ff = _arb_from_decimal_text(str(inputs["fitting_factor"]))

    design_load = applied * rf * ff
    ms = (allowable / design_load) - arb(1)
    rf_achieved = allowable / (ff * applied)
    utilization = design_load / allowable

    return {
        "design_load_required_n": _drift_entry(
            design_load, str(staged_outputs["design_load_required_n"])
        ),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
        "reserve_factor_achieved": _drift_entry(
            rf_achieved, str(staged_outputs["reserve_factor_achieved"])
        ),
        "utilization_ratio": _drift_entry(utilization, str(staged_outputs["utilization_ratio"])),
    }


def evaluate_column_buckling_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate column_plate_buckling without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    p_app = _arb_from_decimal_text(str(inputs["applied_compression_n"]))
    length = _arb_from_decimal_text(str(inputs["column_length_mm"]))
    fixity = _arb_from_decimal_text(str(inputs["end_fixity_k"]))
    area = _arb_from_decimal_text(str(inputs["area_mm2"]))
    inertia = _arb_from_decimal_text(str(inputs["inertia_mm4"]))
    modulus = _arb_from_decimal_text(str(inputs["youngs_modulus_mpa"]))
    sigma_y = _arb_from_decimal_text(str(inputs["yield_strength_mpa"]))
    nu = _arb_from_decimal_text(str(inputs["poissons_ratio"]))
    b_mm = _arb_from_decimal_text(str(inputs["plate_width_b_mm"]))
    t_mm = _arb_from_decimal_text(str(inputs["plate_thickness_t_mm"]))
    kc = _arb_from_decimal_text(str(inputs["plate_buckling_coeff_kc"]))
    sigma_cc = _arb_from_decimal_text(str(inputs["crippling_cutoff_mpa"]))

    rho = (inertia / area).sqrt()
    leff = fixity * length
    slenderness = leff / rho
    pi_sq = arb.pi() ** 2
    lambda_c = ((arb(2) * pi_sq * modulus) / sigma_y).sqrt()

    if Decimal(str(staged_outputs["slenderness_ratio"])) >= Decimal(
        str(staged_outputs["transition_slenderness"])
    ):
        sigma_col = (pi_sq * modulus) / (slenderness * slenderness)
    else:
        sigma_col = sigma_y * (
            arb(1) - (sigma_y * slenderness * slenderness) / (arb(4) * pi_sq * modulus)
        )
    if Decimal(str(staged_outputs["column_buckling_stress_mpa"])) == Decimal("0"):
        sigma_col = arb(0)

    t_over_b = t_mm / b_mm
    sigma_plate_elastic = (kc * pi_sq * modulus * t_over_b * t_over_b) / (
        arb(12) * (arb(1) - nu * nu)
    )
    if Decimal(str(staged_outputs["plate_buckling_stress_mpa"])) >= Decimal(
        str(inputs["crippling_cutoff_mpa"])
    ):
        sigma_plate = sigma_cc
    else:
        sigma_plate = sigma_plate_elastic

    if Decimal(str(staged_outputs["plate_buckling_stress_mpa"])) < Decimal(
        str(staged_outputs["column_buckling_stress_mpa"])
    ):
        sigma_crit = sigma_plate
    else:
        sigma_crit = sigma_col
    p_crit = sigma_crit * area
    ms = (p_crit / p_app) - arb(1)

    return {
        "radius_of_gyration_mm": _drift_entry(rho, str(staged_outputs["radius_of_gyration_mm"])),
        "slenderness_ratio": _drift_entry(slenderness, str(staged_outputs["slenderness_ratio"])),
        "transition_slenderness": _drift_entry(
            lambda_c, str(staged_outputs["transition_slenderness"])
        ),
        "column_buckling_stress_mpa": _drift_entry(
            sigma_col, str(staged_outputs["column_buckling_stress_mpa"])
        ),
        "plate_buckling_stress_mpa": _drift_entry(
            sigma_plate, str(staged_outputs["plate_buckling_stress_mpa"])
        ),
        "governing_critical_stress_mpa": _drift_entry(
            sigma_crit, str(staged_outputs["governing_critical_stress_mpa"])
        ),
        "critical_buckling_load_n": _drift_entry(
            p_crit, str(staged_outputs["critical_buckling_load_n"])
        ),
        "buckling_ms": _drift_entry(ms, str(staged_outputs["buckling_ms"])),
    }


def evaluate_palmgren_miner_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate palmgren_miner_fatigue without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    raw_damage = arb(0)
    for n_val, cap_val in zip(inputs["cycles_applied"], inputs["cycles_to_failure"], strict=True):
        raw_damage += _arb_from_decimal_text(str(n_val)) / _arb_from_decimal_text(str(cap_val))
    scatter = _arb_from_decimal_text(str(inputs["scatter_factor"]))
    limit = _arb_from_decimal_text(str(inputs["damage_limit"]))
    factored = scatter * raw_damage
    life_factor = limit / factored
    ms = life_factor - arb(1)
    return {
        "cumulative_damage_raw": _drift_entry(
            raw_damage, str(staged_outputs["cumulative_damage_raw"])
        ),
        "factored_damage": _drift_entry(factored, str(staged_outputs["factored_damage"])),
        "life_factor": _drift_entry(life_factor, str(staged_outputs["life_factor"])),
        "fatigue_ms": _drift_entry(ms, str(staged_outputs["fatigue_ms"])),
    }


def evaluate_composite_failure_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate composite_failure_criteria without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    s1 = _arb_from_decimal_text(str(inputs["sigma_1_mpa"]))
    s2 = _arb_from_decimal_text(str(inputs["sigma_2_mpa"]))
    t12 = _arb_from_decimal_text(str(inputs["tau_12_mpa"]))
    xt = _arb_from_decimal_text(str(inputs["xt_mpa"]))
    xc = _arb_from_decimal_text(str(inputs["xc_mpa"]))
    yt = _arb_from_decimal_text(str(inputs["yt_mpa"]))
    yc = _arb_from_decimal_text(str(inputs["yc_mpa"]))
    s12 = _arb_from_decimal_text(str(inputs["s12_mpa"]))
    f12_star = _arb_from_decimal_text(str(inputs["f12_star"]))

    f1 = (arb(1) / xt) - (arb(1) / xc)
    f2 = (arb(1) / yt) - (arb(1) / yc)
    f11 = arb(1) / (xt * xc)
    f22 = arb(1) / (yt * yc)
    f66 = arb(1) / (s12 * s12)
    f12 = f12_star * (f11 * f22).sqrt()

    tw_b = f1 * s1 + f2 * s2
    tw_a = (f11 * s1 * s1) + (f22 * s2 * s2) + (f66 * t12 * t12) + (arb(2) * f12 * s1 * s2)
    fi_tw = tw_a + tw_b
    if Decimal(str(tw_a.mid().str(20, radius=False))) > 0:
        rf_tw = (-tw_b + (tw_b * tw_b + arb(4) * tw_a).sqrt()) / (arb(2) * tw_a)
    else:
        rf_tw = arb(1) / tw_b
    ms_tw = rf_tw - arb(1)

    s1_dec = Decimal(str(inputs["sigma_1_mpa"]))
    s2_dec = Decimal(str(inputs["sigma_2_mpa"]))
    fi_ft = ((s1 / xt) ** 2 + (t12 / s12) ** 2) if s1_dec >= 0 else arb(0)
    fi_fc = ((-s1 / xc) ** 2) if s1_dec < 0 else arb(0)
    fi_mt = ((s2 / yt) ** 2 + (t12 / s12) ** 2) if s2_dec >= 0 else arb(0)
    if s2_dec < 0:
        two_s12 = arb(2) * s12
        mc_a = (s2 / two_s12) ** 2 + (t12 / s12) ** 2
        mc_b = (((yc / two_s12) ** 2) - arb(1)) * (s2 / yc)
        fi_mc_raw = mc_a + mc_b
        fi_mc = (
            arb(0)
            if Decimal(str(staged_outputs["hashin_matrix_compression_index"])) == 0
            else fi_mc_raw
        )
        rf_mc = (-mc_b + (mc_b * mc_b + arb(4) * mc_a).sqrt()) / (arb(2) * mc_a)
    else:
        fi_mc = arb(0)
        rf_mc = None

    candidates: list[tuple[Decimal, arb, arb]] = []
    if s1_dec >= 0 and Decimal(str(fi_ft.mid().str(20, radius=False))) > 0:
        rf_ft = arb(1) / fi_ft.sqrt()
        candidates.append((Decimal(str(rf_ft.mid().str(20, radius=False))), rf_ft, fi_ft))
    if s1_dec < 0 and Decimal(str(fi_fc.mid().str(20, radius=False))) > 0:
        rf_fc = arb(1) / fi_fc.sqrt()
        candidates.append((Decimal(str(rf_fc.mid().str(20, radius=False))), rf_fc, fi_fc))
    if s2_dec >= 0 and Decimal(str(fi_mt.mid().str(20, radius=False))) > 0:
        rf_mt = arb(1) / fi_mt.sqrt()
        candidates.append((Decimal(str(rf_mt.mid().str(20, radius=False))), rf_mt, fi_mt))
    if rf_mc is not None:
        candidates.append((Decimal(str(rf_mc.mid().str(20, radius=False))), rf_mc, fi_mc))

    _, rf_hashin, fi_hashin = min(candidates, key=lambda item: item[0])
    ms_hashin = rf_hashin - arb(1)

    return {
        "tsai_wu_failure_index": _drift_entry(fi_tw, str(staged_outputs["tsai_wu_failure_index"])),
        "tsai_wu_reserve_factor": _drift_entry(
            rf_tw, str(staged_outputs["tsai_wu_reserve_factor"])
        ),
        "tsai_wu_ms": _drift_entry(ms_tw, str(staged_outputs["tsai_wu_ms"])),
        "hashin_fiber_tension_index": _drift_entry(
            fi_ft, str(staged_outputs["hashin_fiber_tension_index"])
        ),
        "hashin_fiber_compression_index": _drift_entry(
            fi_fc, str(staged_outputs["hashin_fiber_compression_index"])
        ),
        "hashin_matrix_tension_index": _drift_entry(
            fi_mt, str(staged_outputs["hashin_matrix_tension_index"])
        ),
        "hashin_matrix_compression_index": _drift_entry(
            fi_mc, str(staged_outputs["hashin_matrix_compression_index"])
        ),
        "hashin_governing_index": _drift_entry(
            fi_hashin, str(staged_outputs["hashin_governing_index"])
        ),
        "hashin_reserve_factor": _drift_entry(
            rf_hashin, str(staged_outputs["hashin_reserve_factor"])
        ),
        "hashin_ms": _drift_entry(ms_hashin, str(staged_outputs["hashin_ms"])),
    }


def evaluate_method_intervals(
    method_id: str,
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
    *,
    card: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Dispatch exact FLINT/Arb unrounded evaluation for built-in and plugin cards."""
    if method_id == "bolt_screen":
        return evaluate_bolt_screen_intervals(inputs, staged_outputs)
    if method_id == "hover_power_screen":
        return evaluate_hover_power_intervals(inputs, staged_outputs)
    if method_id == "rigid_body_point_mass":
        return evaluate_rigid_body_intervals(inputs, staged_outputs)
    if method_id == "margin_of_safety":
        return evaluate_margin_of_safety_intervals(inputs, staged_outputs)
    if method_id == "column_plate_buckling":
        return evaluate_column_buckling_intervals(inputs, staged_outputs)
    if method_id == "palmgren_miner_fatigue":
        return evaluate_palmgren_miner_intervals(inputs, staged_outputs)
    if method_id == "composite_failure_criteria":
        return evaluate_composite_failure_intervals(inputs, staged_outputs)
    if card is not None and card.get("plugin") and card.get("formulas"):
        from evidence_calc.plugins import evaluate_declarative_intervals

        return evaluate_declarative_intervals(card, inputs, staged_outputs, _drift_entry)
    return {}
