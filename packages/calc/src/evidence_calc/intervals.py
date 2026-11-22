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

from evidence_calc.stress_manual import (
    STRESS_MANUAL_RUNNERS,
    evaluate_stress_manual_unrounded,
)

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
    ctx.dps = _BALL_DPS
    bounds = _arb_bounds_decimal(ball)
    exact_mid_dec = Decimal(ball.mid().str(40, radius=False))
    staged_dec = Decimal(staged_text)
    drift = (
        (staged_dec - exact_mid_dec).copy_abs().quantize(_DRIFT_QUANTUM, rounding=ROUND_HALF_EVEN)
    )
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


def evaluate_aerospace_quotation_costing_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate aerospace_quotation_costing without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    qty = _arb_from_decimal_text(str(inputs["part_quantity"]))
    mass_kg = _arb_from_decimal_text(str(inputs["finished_mass_kg"]))
    btf = _arb_from_decimal_text(str(inputs["buy_to_fly_ratio"]))
    mat_cost = _arb_from_decimal_text(str(inputs["material_unit_cost_eur_kg"]))
    mach_hrs = _arb_from_decimal_text(str(inputs["machining_hours_per_part"]))
    mach_rate = _arb_from_decimal_text(str(inputs["machining_rate_eur_hr"]))
    eng_hrs = _arb_from_decimal_text(str(inputs["engineering_setup_hours"]))
    eng_rate = _arb_from_decimal_text(str(inputs["engineering_rate_eur_hr"]))
    ndt_part = _arb_from_decimal_text(str(inputs["ndt_qa_cost_per_part_eur"]))
    tooling_nre = _arb_from_decimal_text(str(inputs["tooling_nre_eur"]))
    risk_pct = _arb_from_decimal_text(str(inputs["risk_contingency_pct"]))
    overhead_pct = _arb_from_decimal_text(str(inputs["overhead_pct"]))
    target_margin_pct = _arb_from_decimal_text(str(inputs["target_margin_pct"]))

    raw_mass = mass_kg * btf
    mat_total = raw_mass * mat_cost * qty
    mfg_total = mach_hrs * mach_rate * qty
    eng_nre_total = (eng_hrs * eng_rate) + tooling_nre
    ndt_total = ndt_part * qty
    direct_sub = mat_total + mfg_total + eng_nre_total + ndt_total
    overhead = direct_sub * (overhead_pct / arb(100))
    contingency = direct_sub * (risk_pct / arb(100))
    total_cost = direct_sub + overhead + contingency
    margin_denom = arb(1) - (target_margin_pct / arb(100))
    quoted_total = total_cost / margin_denom
    quoted_unit = quoted_total / qty
    gross_margin = quoted_total - total_cost
    achieved_margin = (
        (gross_margin / quoted_total) * arb(100)
        if Decimal(str(staged_outputs["quoted_total_price_eur"])) > Decimal("0")
        else arb(0)
    )

    return {
        "raw_material_mass_per_part_kg": _drift_entry(
            raw_mass, str(staged_outputs["raw_material_mass_per_part_kg"])
        ),
        "material_cost_total_eur": _drift_entry(
            mat_total, str(staged_outputs["material_cost_total_eur"])
        ),
        "manufacturing_cost_total_eur": _drift_entry(
            mfg_total, str(staged_outputs["manufacturing_cost_total_eur"])
        ),
        "engineering_nre_total_eur": _drift_entry(
            eng_nre_total, str(staged_outputs["engineering_nre_total_eur"])
        ),
        "ndt_qa_total_eur": _drift_entry(ndt_total, str(staged_outputs["ndt_qa_total_eur"])),
        "direct_cost_subtotal_eur": _drift_entry(
            direct_sub, str(staged_outputs["direct_cost_subtotal_eur"])
        ),
        "overhead_cost_eur": _drift_entry(overhead, str(staged_outputs["overhead_cost_eur"])),
        "risk_contingency_eur": _drift_entry(
            contingency, str(staged_outputs["risk_contingency_eur"])
        ),
        "total_cost_baseline_eur": _drift_entry(
            total_cost, str(staged_outputs["total_cost_baseline_eur"])
        ),
        "quoted_total_price_eur": _drift_entry(
            quoted_total, str(staged_outputs["quoted_total_price_eur"])
        ),
        "quoted_unit_price_eur": _drift_entry(
            quoted_unit, str(staged_outputs["quoted_unit_price_eur"])
        ),
        "gross_margin_eur": _drift_entry(gross_margin, str(staged_outputs["gross_margin_eur"])),
        "achieved_margin_pct": _drift_entry(
            achieved_margin, str(staged_outputs["achieved_margin_pct"])
        ),
    }


def evaluate_engineering_workpackage_quote_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate engineering_workpackage_quote without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    notes_count = _arb_from_decimal_text(str(inputs["calc_notes_count"]))
    h_opt = _arb_from_decimal_text(str(inputs["hours_per_calc_note_optimistic"]))
    h_likely = _arb_from_decimal_text(str(inputs["hours_per_calc_note_likely"]))
    h_pess = _arb_from_decimal_text(str(inputs["hours_per_calc_note_pessimistic"]))
    fem_count = _arb_from_decimal_text(str(inputs["fem_models_count"]))
    h_fem = _arb_from_decimal_text(str(inputs["hours_per_fem_model"]))
    cve_ratio = _arb_from_decimal_text(str(inputs["cve_review_ratio"]))
    senior_rate = _arb_from_decimal_text(str(inputs["senior_rate_eur_hr"]))
    cve_rate = _arb_from_decimal_text(str(inputs["cve_rate_eur_hr"]))
    surcharge = _arb_from_decimal_text(str(inputs["software_compute_surcharge_eur"]))
    rework_pct = _arb_from_decimal_text(str(inputs["rework_contingency_pct"]))
    target_margin_pct = _arb_from_decimal_text(str(inputs["target_margin_pct"]))

    pert_expected = (h_opt + arb(4) * h_likely + h_pess) / arb(6)
    pert_stddev = (h_pess - h_opt) / arb(6)
    if Decimal(str(inputs["calc_notes_count"])) > Decimal("0"):
        notes_sigma_total = notes_count.sqrt() * pert_stddev
    else:
        notes_sigma_total = arb(0)

    z80 = _arb_from_decimal_text("0.84162123")
    z90 = _arb_from_decimal_text("1.28155157")
    fem_total = fem_count * h_fem
    hours_p50 = (notes_count * pert_expected) + fem_total
    hours_p80 = hours_p50 + (z80 * notes_sigma_total)
    hours_p90 = hours_p50 + (z90 * notes_sigma_total)

    cve_p50 = hours_p50 * cve_ratio
    cve_p80 = hours_p80 * cve_ratio
    cve_p90 = hours_p90 * cve_ratio

    labor_p50 = (hours_p50 * senior_rate) + (cve_p50 * cve_rate)
    labor_p80 = (hours_p80 * senior_rate) + (cve_p80 * cve_rate)
    labor_p90 = (hours_p90 * senior_rate) + (cve_p90 * cve_rate)

    rework_factor = arb(1) + (rework_pct / arb(100))
    rework_p80 = labor_p80 * (rework_pct / arb(100))
    cost_p50 = (labor_p50 * rework_factor) + surcharge
    cost_p80 = labor_p80 + rework_p80 + surcharge
    cost_p90 = (labor_p90 * rework_factor) + surcharge

    margin_denom = arb(1) - (target_margin_pct / arb(100))
    price_p50 = cost_p50 / margin_denom
    price_p80 = cost_p80 / margin_denom
    price_p90 = cost_p90 / margin_denom
    achieved_margin = (
        ((price_p80 - cost_p80) / price_p80) * arb(100)
        if Decimal(str(staged_outputs["quoted_price_p80_eur"])) > Decimal("0")
        else arb(0)
    )

    return {
        "pert_expected_hours_per_note": _drift_entry(
            pert_expected, str(staged_outputs["pert_expected_hours_per_note"])
        ),
        "pert_stddev_hours_per_note": _drift_entry(
            pert_stddev, str(staged_outputs["pert_stddev_hours_per_note"])
        ),
        "total_engineering_hours_p50": _drift_entry(
            hours_p50, str(staged_outputs["total_engineering_hours_p50"])
        ),
        "total_engineering_hours_p80": _drift_entry(
            hours_p80, str(staged_outputs["total_engineering_hours_p80"])
        ),
        "total_engineering_hours_p90": _drift_entry(
            hours_p90, str(staged_outputs["total_engineering_hours_p90"])
        ),
        "cve_review_hours": _drift_entry(cve_p80, str(staged_outputs["cve_review_hours"])),
        "labor_cost_p50_eur": _drift_entry(labor_p50, str(staged_outputs["labor_cost_p50_eur"])),
        "labor_cost_p80_eur": _drift_entry(labor_p80, str(staged_outputs["labor_cost_p80_eur"])),
        "rework_reserve_eur": _drift_entry(rework_p80, str(staged_outputs["rework_reserve_eur"])),
        "total_cost_p80_eur": _drift_entry(cost_p80, str(staged_outputs["total_cost_p80_eur"])),
        "quoted_price_p50_eur": _drift_entry(
            price_p50, str(staged_outputs["quoted_price_p50_eur"])
        ),
        "quoted_price_p80_eur": _drift_entry(
            price_p80, str(staged_outputs["quoted_price_p80_eur"])
        ),
        "quoted_price_p90_eur": _drift_entry(
            price_p90, str(staged_outputs["quoted_price_p90_eur"])
        ),
        "achieved_margin_pct": _drift_entry(
            achieved_margin, str(staged_outputs["achieved_margin_pct"])
        ),
    }


def evaluate_rotorcraft_archetype_quote_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate rotorcraft_archetype_quote without intermediate rounding using Arb balls."""
    ctx.dps = _BALL_DPS
    cad_h = _arb_from_decimal_text(str(inputs["cad_hours"]))
    loads_h = _arb_from_decimal_text(str(inputs["loads_hours"]))
    stress_h = _arb_from_decimal_text(str(inputs["stress_hours"]))
    fdt_dyn_h = _arb_from_decimal_text(str(inputs["fdt_dyn_hours"]))
    systems_h = _arb_from_decimal_text(str(inputs["systems_hours"]))
    test_h = _arb_from_decimal_text(str(inputs["test_hours"]))
    cve_h = _arb_from_decimal_text(str(inputs["cve_hours"]))
    proto_h = _arb_from_decimal_text(str(inputs["proto_hours"]))

    cad_r = _arb_from_decimal_text(str(inputs["cad_rate"]))
    loads_r = _arb_from_decimal_text(str(inputs["loads_rate"]))
    stress_r = _arb_from_decimal_text(str(inputs["stress_rate"]))
    fdt_dyn_r = _arb_from_decimal_text(str(inputs["fdt_dyn_rate"]))
    systems_r = _arb_from_decimal_text(str(inputs["systems_rate"]))
    test_r = _arb_from_decimal_text(str(inputs["test_rate"]))
    cve_r = _arb_from_decimal_text(str(inputs["cve_rate"]))
    proto_r = _arb_from_decimal_text(str(inputs["proto_rate"]))

    cert_factor = _arb_from_decimal_text(str(inputs["cert_basis_factor"]))
    mat_factor = _arb_from_decimal_text(str(inputs["material_complexity_factor"]))
    cosysmo_factor = _arb_from_decimal_text(str(inputs["cosysmo_driver_factor"]))
    pvt_factor = _arb_from_decimal_text(str(inputs["pvt_compression_factor"]))

    hpc_h = _arb_from_decimal_text(str(inputs["hpc_hours"]))
    hpc_r = _arb_from_decimal_text(str(inputs["hpc_rate"]))
    travel_hw = _arb_from_decimal_text(str(inputs["travel_hardware_eur"]))
    overhead_pct = _arb_from_decimal_text(str(inputs["overhead_pct"]))
    contingency_pct = _arb_from_decimal_text(str(inputs["contingency_pct"]))
    margin_pct = _arb_from_decimal_text(str(inputs["margin_pct"]))
    fixed_share_pct = _arb_from_decimal_text(str(inputs["fixed_price_share_pct"]))
    cve_min_ratio_pct = _arb_from_decimal_text(str(inputs["cve_min_ratio_pct"]))

    raw_hours_total = cad_h + loads_h + stress_h + fdt_dyn_h + systems_h + test_h + cve_h + proto_h
    core_eng_scale = cert_factor * mat_factor * cosysmo_factor
    cad_s = cad_h * core_eng_scale
    loads_s = loads_h * core_eng_scale
    stress_s = stress_h * core_eng_scale
    fdt_dyn_s = fdt_dyn_h * core_eng_scale
    systems_s = systems_h * core_eng_scale
    test_s = test_h * cert_factor * pvt_factor
    proto_s = proto_h * mat_factor

    scaled_eng_hours = cad_s + loads_s + stress_s + fdt_dyn_s + systems_s + test_s + proto_s
    cve_input_scaled = cve_h * cert_factor * cosysmo_factor
    cve_floor = scaled_eng_hours * (cve_min_ratio_pct / arb(100))

    d_cad = Decimal(str(inputs["cad_hours"]))
    d_loads = Decimal(str(inputs["loads_hours"]))
    d_stress = Decimal(str(inputs["stress_hours"]))
    d_fdt = Decimal(str(inputs["fdt_dyn_hours"]))
    d_sys = Decimal(str(inputs["systems_hours"]))
    d_test = Decimal(str(inputs["test_hours"]))
    d_cve = Decimal(str(inputs["cve_hours"]))
    d_proto = Decimal(str(inputs["proto_hours"]))
    d_cert = Decimal(str(inputs["cert_basis_factor"]))
    d_mat = Decimal(str(inputs["material_complexity_factor"]))
    d_cos = Decimal(str(inputs["cosysmo_driver_factor"]))
    d_pvt = Decimal(str(inputs["pvt_compression_factor"]))
    d_floor_pct = Decimal(str(inputs["cve_min_ratio_pct"]))
    d_scale = d_cert * d_mat * d_cos
    d_eng = (
        ((d_cad + d_loads + d_stress + d_fdt + d_sys) * d_scale)
        + (d_test * d_cert * d_pvt)
        + (d_proto * d_mat)
    )
    d_cve_in = d_cve * d_cert * d_cos
    d_cve_fl = d_eng * (d_floor_pct / Decimal("100"))
    cve_scaled_hours = cve_floor if d_cve_in < d_cve_fl else cve_input_scaled

    total_scaled_hours = scaled_eng_hours + cve_scaled_hours
    direct_labor = (
        (cad_s * cad_r)
        + (loads_s * loads_r)
        + (stress_s * stress_r)
        + (fdt_dyn_s * fdt_dyn_r)
        + (systems_s * systems_r)
        + (test_s * test_r)
        + (proto_s * proto_r)
        + (cve_scaled_hours * cve_r)
    )
    blended_rate = direct_labor / total_scaled_hours
    hpc_cost = hpc_h * hpc_r
    direct_cost = direct_labor + hpc_cost + travel_hw
    overhead_eur = direct_cost * (overhead_pct / arb(100))
    contingency_eur = (direct_cost + overhead_eur) * (contingency_pct / arb(100))
    total_cost = direct_cost + overhead_eur + contingency_eur

    margin_denom = arb(1) - (margin_pct / arb(100))
    quote_price = total_cost / margin_denom
    margin_eur = quote_price - total_cost
    fixed_tranche = quote_price * (fixed_share_pct / arb(100))
    capped_tm_tranche = quote_price - fixed_tranche
    cve_share_pct = (cve_scaled_hours / total_scaled_hours) * arb(100)
    gross_margin_pct = (
        (margin_eur / quote_price) * arb(100)
        if Decimal(str(staged_outputs["quote_price_eur"])) > Decimal("0")
        else arb(0)
    )

    return {
        "raw_hours_total": _drift_entry(raw_hours_total, str(staged_outputs["raw_hours_total"])),
        "scaled_engineering_hours": _drift_entry(
            scaled_eng_hours, str(staged_outputs["scaled_engineering_hours"])
        ),
        "cve_scaled_hours": _drift_entry(cve_scaled_hours, str(staged_outputs["cve_scaled_hours"])),
        "total_scaled_hours": _drift_entry(
            total_scaled_hours, str(staged_outputs["total_scaled_hours"])
        ),
        "blended_hourly_rate_eur": _drift_entry(
            blended_rate, str(staged_outputs["blended_hourly_rate_eur"])
        ),
        "direct_labor_cost_eur": _drift_entry(
            direct_labor, str(staged_outputs["direct_labor_cost_eur"])
        ),
        "hpc_compute_cost_eur": _drift_entry(hpc_cost, str(staged_outputs["hpc_compute_cost_eur"])),
        "direct_cost_eur": _drift_entry(direct_cost, str(staged_outputs["direct_cost_eur"])),
        "overhead_eur": _drift_entry(overhead_eur, str(staged_outputs["overhead_eur"])),
        "contingency_eur": _drift_entry(contingency_eur, str(staged_outputs["contingency_eur"])),
        "total_cost_eur": _drift_entry(total_cost, str(staged_outputs["total_cost_eur"])),
        "margin_eur": _drift_entry(margin_eur, str(staged_outputs["margin_eur"])),
        "quote_price_eur": _drift_entry(quote_price, str(staged_outputs["quote_price_eur"])),
        "fixed_price_tranche_eur": _drift_entry(
            fixed_tranche, str(staged_outputs["fixed_price_tranche_eur"])
        ),
        "capped_tm_tranche_eur": _drift_entry(
            capped_tm_tranche, str(staged_outputs["capped_tm_tranche_eur"])
        ),
        "cve_share_pct": _drift_entry(cve_share_pct, str(staged_outputs["cve_share_pct"])),
        "gross_margin_pct": _drift_entry(gross_margin_pct, str(staged_outputs["gross_margin_pct"])),
    }


def evaluate_rotorcraft_historical_calibration_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate rotorcraft_historical_calibration without intermediate rounding via Arb balls."""
    ctx.dps = _BALL_DPS
    prior_opt = _arb_from_decimal_text(str(inputs["prior_optimistic_hours"]))
    prior_ml = _arb_from_decimal_text(str(inputs["prior_most_likely_hours"]))
    prior_pess = _arb_from_decimal_text(str(inputs["prior_pessimistic_hours"]))
    emp_p10 = _arb_from_decimal_text(str(inputs["empirical_p10_hours"]))
    emp_p50 = _arb_from_decimal_text(str(inputs["empirical_p50_hours"]))
    emp_p90 = _arb_from_decimal_text(str(inputs["empirical_p90_hours"]))

    sample_n = _arb_from_decimal_text(str(inputs["sample_size"]))
    full_n = _arb_from_decimal_text(str(inputs["credibility_full_n"]))
    overrun_ratio = _arb_from_decimal_text(str(inputs["historical_overrun_ratio"]))
    feat_factor = _arb_from_decimal_text(str(inputs["idp_feature_complexity_factor"]))
    base_cont_pct = _arb_from_decimal_text(str(inputs["base_contingency_pct"]))
    broken_rate_pct = _arb_from_decimal_text(str(inputs["broken_assumption_rate_pct"]))

    d_sample = Decimal(str(inputs["sample_size"]))
    d_full = Decimal(str(inputs["credibility_full_n"]))
    cred_w = arb(1) if d_sample >= d_full else (sample_n / full_n)
    one_minus_w = arb(1) - cred_w

    cal_opt = ((one_minus_w * prior_opt) + (cred_w * emp_p10)) * feat_factor
    ml_overrun_blend = (arb(1) + overrun_ratio) / arb(2)
    cal_ml = ((one_minus_w * prior_ml) + (cred_w * emp_p50)) * feat_factor * ml_overrun_blend
    cal_pess = ((one_minus_w * prior_pess) + (cred_w * emp_p90)) * feat_factor * overrun_ratio

    cal_expected = (cal_opt + (arb(4) * cal_ml) + cal_pess) / arb(6)
    cal_sigma = (cal_pess - cal_opt) / arb(6)
    z80 = _arb_from_decimal_text("0.84162123")
    z90 = _arb_from_decimal_text("1.28155157")
    cal_p80 = cal_expected + (z80 * cal_sigma)
    cal_p90 = cal_expected + (z90 * cal_sigma)
    cal_cont_pct = base_cont_pct + (cred_w * broken_rate_pct * _arb_from_decimal_text("0.250"))

    prior_expected = (prior_opt + (arb(4) * prior_ml) + prior_pess) / arb(6)
    d_prior_exp = (
        Decimal(str(inputs["prior_optimistic_hours"]))
        + (Decimal("4") * Decimal(str(inputs["prior_most_likely_hours"])))
        + Decimal(str(inputs["prior_pessimistic_hours"]))
    ) / Decimal("6")
    drift_pct = (
        ((cal_expected - prior_expected) / prior_expected) * arb(100)
        if d_prior_exp > Decimal("0")
        else arb(0)
    )

    return {
        "credibility_weight": _drift_entry(cred_w, str(staged_outputs["credibility_weight"])),
        "calibrated_optimistic_hours": _drift_entry(
            cal_opt, str(staged_outputs["calibrated_optimistic_hours"])
        ),
        "calibrated_most_likely_hours": _drift_entry(
            cal_ml, str(staged_outputs["calibrated_most_likely_hours"])
        ),
        "calibrated_pessimistic_hours": _drift_entry(
            cal_pess, str(staged_outputs["calibrated_pessimistic_hours"])
        ),
        "calibrated_pert_expected_hours": _drift_entry(
            cal_expected, str(staged_outputs["calibrated_pert_expected_hours"])
        ),
        "calibrated_pert_p80_hours": _drift_entry(
            cal_p80, str(staged_outputs["calibrated_pert_p80_hours"])
        ),
        "calibrated_pert_p90_hours": _drift_entry(
            cal_p90, str(staged_outputs["calibrated_pert_p90_hours"])
        ),
        "calibrated_contingency_pct": _drift_entry(
            cal_cont_pct, str(staged_outputs["calibrated_contingency_pct"])
        ),
        "prior_vs_calibrated_drift_pct": _drift_entry(
            drift_pct, str(staged_outputs["prior_vs_calibrated_drift_pct"])
        ),
    }


def evaluate_aerospace_multiyear_cashflow_learning_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate aerospace_multiyear_cashflow_learning via 50-digit Arb balls."""
    ctx.dps = _BALL_DPS
    t1 = _arb_from_decimal_text(str(inputs["first_unit_cost_eur"]))
    n_units = int(Decimal(str(inputs["unit_count"])))
    lr_pct = _arb_from_decimal_text(str(inputs["learning_rate_pct"]))
    crawford_w_pct = _arb_from_decimal_text(str(inputs["crawford_weight_pct"]))
    n_years = int(Decimal(str(inputs["program_years"])))
    inf_pct = _arb_from_decimal_text(str(inputs["annual_inflation_pct"]))
    target_margin_pct = _arb_from_decimal_text(str(inputs["target_margin_pct"]))
    wacc_pct = _arb_from_decimal_text(str(inputs["wacc_annual_pct"]))
    n_days = int(Decimal(str(inputs["payment_terms_days"])))

    m_ko = _arb_from_decimal_text(str(inputs["milestone_ko_pct"]))
    m_pdr = _arb_from_decimal_text(str(inputs["milestone_pdr_pct"]))
    m_cdr = _arb_from_decimal_text(str(inputs["milestone_cdr_pct"]))
    m_test = _arb_from_decimal_text(str(inputs["milestone_test_pct"]))
    m_cve = _arb_from_decimal_text(str(inputs["milestone_cve_pct"]))

    b_exp = (lr_pct / arb(100)).log() / arb(2).log()
    wright_cum_avg = t1 * (b_exp * arb(n_units).log()).exp() if n_units > 1 else t1
    wright_total = arb(n_units) * wright_cum_avg
    if n_units > 1:
        wright_prev = arb(n_units - 1) * t1 * (b_exp * arb(n_units - 1).log()).exp()
        wright_last = wright_total - wright_prev
    else:
        wright_last = t1

    crawford_total = arb(0)
    crawford_last = t1
    for k in range(1, n_units + 1):
        u_cost = t1 * (b_exp * arb(k).log()).exp() if k > 1 else t1
        crawford_total = crawford_total + u_cost
        crawford_last = u_cost

    w_crawford = crawford_w_pct / arb(100)
    active_base = ((arb(1) - w_crawford) * wright_total) + (w_crawford * crawford_total)

    inf_rate = inf_pct / arb(100)
    annual_base = active_base / arb(n_years)
    year_costs: list[arb] = []
    for y in range(n_years):
        year_costs.append(annual_base * ((arb(1) + inf_rate) ** y))

    escalated_total = arb(0)
    for yc in year_costs:
        escalated_total = escalated_total + yc
    inflation_esc = escalated_total - active_base
    eff_esc_factor = escalated_total / active_base
    margin_denom = arb(1) - (target_margin_pct / arb(100))
    quoted_price = escalated_total / margin_denom

    total_program_months = 12 * n_years
    lag_months = (n_days + 29) // 30
    horizon_months = total_program_months + lag_months

    outflows = [arb(0)] * (horizon_months + 1)
    inflows = [arb(0)] * (horizon_months + 1)
    for m in range(1, total_program_months + 1):
        outflows[m] = year_costs[(m - 1) // 12] / arb(12)

    milestone_specs = (
        (1, m_ko),
        (max(1, (total_program_months * 25 + 50) // 100), m_pdr),
        (max(1, (total_program_months * 50 + 50) // 100), m_cdr),
        (max(1, (total_program_months * 80 + 50) // 100), m_test),
        (total_program_months, m_cve),
    )
    for bill_m, pct in milestone_specs:
        cash_m = bill_m + lag_months
        inflows[cash_m] = inflows[cash_m] + quoted_price * (pct / arb(100))

    r_month = wacc_pct / arb(1200)
    cum_cash = arb(0)
    peak_negative = arb(0)
    peak_neg_mid = Decimal("0")
    wc_financing = arb(0)
    npv = arb(0)

    for m in range(1, horizon_months + 1):
        net_m = inflows[m] - outflows[m]
        cum_cash = cum_cash + net_m
        cum_mid = Decimal(cum_cash.mid().str(30, radius=False))
        if cum_mid < Decimal("0"):
            deficit = -cum_cash
            neg_mid = -cum_mid
            if neg_mid > peak_neg_mid:
                peak_neg_mid = neg_mid
                peak_negative = deficit
            wc_financing = wc_financing + (deficit * r_month)
        npv = npv + (net_m / ((arb(1) + r_month) ** m))

    net_margin_eur = quoted_price - escalated_total - wc_financing
    net_margin_pct = (net_margin_eur / quoted_price) * arb(100)

    return {
        "learning_exponent_b": _drift_entry(b_exp, str(staged_outputs["learning_exponent_b"])),
        "wright_cumulative_avg_unit_cost_eur": _drift_entry(
            wright_cum_avg, str(staged_outputs["wright_cumulative_avg_unit_cost_eur"])
        ),
        "wright_total_base_cost_eur": _drift_entry(
            wright_total, str(staged_outputs["wright_total_base_cost_eur"])
        ),
        "wright_last_unit_cost_eur": _drift_entry(
            wright_last, str(staged_outputs["wright_last_unit_cost_eur"])
        ),
        "crawford_total_base_cost_eur": _drift_entry(
            crawford_total, str(staged_outputs["crawford_total_base_cost_eur"])
        ),
        "crawford_last_unit_cost_eur": _drift_entry(
            crawford_last, str(staged_outputs["crawford_last_unit_cost_eur"])
        ),
        "active_base_total_cost_eur": _drift_entry(
            active_base, str(staged_outputs["active_base_total_cost_eur"])
        ),
        "inflation_escalation_eur": _drift_entry(
            inflation_esc, str(staged_outputs["inflation_escalation_eur"])
        ),
        "effective_escalation_factor": _drift_entry(
            eff_esc_factor, str(staged_outputs["effective_escalation_factor"])
        ),
        "escalated_total_cost_eur": _drift_entry(
            escalated_total, str(staged_outputs["escalated_total_cost_eur"])
        ),
        "quoted_price_eur": _drift_entry(quoted_price, str(staged_outputs["quoted_price_eur"])),
        "peak_negative_cashflow_eur": _drift_entry(
            peak_negative, str(staged_outputs["peak_negative_cashflow_eur"])
        ),
        "working_capital_financing_cost_eur": _drift_entry(
            wc_financing, str(staged_outputs["working_capital_financing_cost_eur"])
        ),
        "net_present_value_eur": _drift_entry(npv, str(staged_outputs["net_present_value_eur"])),
        "net_margin_after_financing_eur": _drift_entry(
            net_margin_eur, str(staged_outputs["net_margin_after_financing_eur"])
        ),
        "net_margin_after_financing_pct": _drift_entry(
            net_margin_pct, str(staged_outputs["net_margin_after_financing_pct"])
        ),
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
    if method_id == "aerospace_quotation_costing":
        return evaluate_aerospace_quotation_costing_intervals(inputs, staged_outputs)
    if method_id == "engineering_workpackage_quote":
        return evaluate_engineering_workpackage_quote_intervals(inputs, staged_outputs)
    if method_id == "rotorcraft_archetype_quote":
        return evaluate_rotorcraft_archetype_quote_intervals(inputs, staged_outputs)
    if method_id == "rotorcraft_historical_calibration":
        return evaluate_rotorcraft_historical_calibration_intervals(inputs, staged_outputs)
    if method_id == "aerospace_multiyear_cashflow_learning":
        return evaluate_aerospace_multiyear_cashflow_learning_intervals(inputs, staged_outputs)
    if method_id in STRESS_MANUAL_RUNNERS:
        return evaluate_stress_manual_intervals(method_id, inputs, staged_outputs)
    if card is not None and card.get("plugin") and card.get("formulas"):
        from evidence_calc.plugins import evaluate_declarative_intervals

        return evaluate_declarative_intervals(card, inputs, staged_outputs, _drift_entry)
    return {}


def evaluate_stress_manual_intervals(
    method_id: str,
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate 50-digit unrounded Arb intervals for Stress Office manual methods."""
    ctx.dps = _BALL_DPS
    unrounded = evaluate_stress_manual_unrounded(method_id, inputs)
    intervals: dict[str, dict[str, Any]] = {}
    for key, staged_val in staged_outputs.items():
        if key in unrounded:
            ball = _arb_from_decimal_text(format(unrounded[key], "f"))
            intervals[key] = _drift_entry(ball, str(staged_val))
            continue
        try:
            Decimal(str(staged_val))
        except Exception:
            continue
        ball = _arb_from_decimal_text(str(staged_val))
        intervals[key] = _drift_entry(ball, str(staged_val))
    return intervals
