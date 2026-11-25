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
    if method_id == "clt_laminate_abd_stiffness":
        return evaluate_clt_laminate_abd_intervals(inputs, staged_outputs)
    if method_id == "rotor_blade_centrifugal_bending":
        return evaluate_rotor_blade_cf_intervals(inputs, staged_outputs)
    if method_id == "ground_resonance_coleman_screen":
        return evaluate_ground_resonance_intervals(inputs, staged_outputs)
    if method_id == "cs29_crashworthiness_561_562_load":
        return evaluate_cs29_crashworthiness_intervals(inputs, staged_outputs)
    if method_id == "multirow_bolt_load_distribution":
        return evaluate_multirow_bolt_intervals(inputs, staged_outputs)
    if method_id == "larc04_composite_failure":
        return evaluate_larc04_intervals(inputs, staged_outputs)
    if method_id == "cs29_bird_strike_penetration_screen":
        return evaluate_cs29_bird_strike_intervals(inputs, staged_outputs)
    if method_id == "campbell_rotor_harmonic_clearance":
        return evaluate_campbell_clearance_intervals(inputs, staged_outputs)
    if method_id == "tailboom_boxbeam_combined_stress":
        return evaluate_tailboom_boxbeam_intervals(inputs, staged_outputs)
    if method_id == "statistical_ab_basis_tolerance_bound":
        return evaluate_statistical_ab_basis_intervals(inputs, staged_outputs)
    if method_id == "bolt_prying_combined_tension_shear":
        return evaluate_bolt_prying_intervals(inputs, staged_outputs)
    if method_id == "goland_reissner_adhesive_peel_shear":
        return evaluate_goland_reissner_intervals(inputs, staged_outputs)
    if method_id == "orthotropic_composite_plate_buckling":
        return evaluate_orthotropic_plate_buckling_intervals(inputs, staged_outputs)
    if method_id == "skin_stringer_crippling_interaction":
        return evaluate_skin_stringer_intervals(inputs, staged_outputs)
    if method_id == "walker_mean_stress_crack_growth":
        return evaluate_walker_crack_intervals(inputs, staged_outputs)
    if method_id in STRESS_MANUAL_RUNNERS:
        return evaluate_stress_manual_intervals(method_id, inputs, staged_outputs)
    if card is not None and card.get("plugin") and card.get("formulas"):
        from evidence_calc.plugins import evaluate_declarative_intervals

        return evaluate_declarative_intervals(card, inputs, staged_outputs, _drift_entry)
    return {}


def _arb_mid_dec(ball: arb) -> Decimal:
    return Decimal(ball.mid().str(30, radius=False))


def _solve_arb_linear_system(matrix: list[list[arb]], rhs: list[arb]) -> list[arb]:
    """Solve dense NxN linear system over 50-digit FLINT Arb balls."""
    ctx.dps = _BALL_DPS
    n = len(rhs)
    aug = [list(matrix[r]) + [rhs[r]] for r in range(n)]
    for col in range(n):
        piv_row = col
        piv_abs = abs(_arb_mid_dec(aug[col][col]))
        for r in range(col + 1, n):
            cand = abs(_arb_mid_dec(aug[r][col]))
            if cand > piv_abs:
                piv_abs = cand
                piv_row = r
        if piv_row != col:
            aug[col], aug[piv_row] = aug[piv_row], aug[col]
        piv = aug[col][col]
        for c in range(col, n + 1):
            aug[col][c] = aug[col][c] / piv
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col]
            for c in range(col, n + 1):
                aug[r][c] = aug[r][c] - factor * aug[col][c]
    return [aug[r][n] for r in range(n)]


def evaluate_clt_laminate_abd_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    thetas = [_arb_from_decimal_text(str(inputs[f"theta_{k}_deg"])) for k in range(1, 5)]
    t_ply = _arb_from_decimal_text(str(inputs["ply_thickness_mm"]))
    e1 = _arb_from_decimal_text(str(inputs["e1_mpa"]))
    e2 = _arb_from_decimal_text(str(inputs["e2_mpa"]))
    g12 = _arb_from_decimal_text(str(inputs["g12_mpa"]))
    nu12 = _arb_from_decimal_text(str(inputs["nu12"]))
    nx = _arb_from_decimal_text(str(inputs["nx_n_per_mm"]))
    ny = _arb_from_decimal_text(str(inputs["ny_n_per_mm"]))
    nxy = _arb_from_decimal_text(str(inputs["nxy_n_per_mm"]))
    mx = _arb_from_decimal_text(str(inputs["mx_n_mm_per_mm"]))
    xt = _arb_from_decimal_text(str(inputs["xt_mpa"]))
    yt = _arb_from_decimal_text(str(inputs["yt_mpa"]))
    s12_allow = _arb_from_decimal_text(str(inputs["s12_mpa"]))

    nu21 = nu12 * e2 / e1
    denom = arb(1) - nu12 * nu21
    q11 = e1 / denom
    q22 = e2 / denom
    q12 = nu12 * e2 / denom
    q66 = g12

    total_h = arb(4) * t_ply
    half_h = total_h / arb(2)
    a_mat = [[arb(0), arb(0), arb(0)] for _ in range(3)]
    b_mat = [[arb(0), arb(0), arb(0)] for _ in range(3)]
    d_mat = [[arb(0), arb(0), arb(0)] for _ in range(3)]
    pi_val = arb.pi()
    rad_scale = pi_val / arb(180)
    ply_data: list[tuple[arb, arb, arb, arb]] = []

    for idx, th in enumerate(thetas):
        z0 = -half_h + arb(idx) * t_ply
        z1 = z0 + t_ply
        rad = th * rad_scale
        c = rad.cos()
        s = rad.sin()
        c2, s2, sc = c * c, s * s, s * c
        c4, s4 = c2 * c2, s2 * s2
        qbar_11 = q11 * c4 + arb(2) * (q12 + arb(2) * q66) * s2 * c2 + q22 * s4
        qbar_12 = (q11 + q22 - arb(4) * q66) * s2 * c2 + q12 * (s4 + c4)
        qbar_22 = q11 * s4 + arb(2) * (q12 + arb(2) * q66) * s2 * c2 + q22 * c4
        qbar_16 = (q11 - q12 - arb(2) * q66) * sc * c2 + (q12 - q22 + arb(2) * q66) * s2 * sc
        qbar_26 = (q11 - q12 - arb(2) * q66) * s2 * sc + (q12 - q22 + arb(2) * q66) * sc * c2
        qbar_66 = (q11 + q22 - arb(2) * q12 - arb(2) * q66) * s2 * c2 + q66 * (s4 + c4)
        qb = [
            [qbar_11, qbar_12, qbar_16],
            [qbar_12, qbar_22, qbar_26],
            [qbar_16, qbar_26, qbar_66],
        ]
        dz1 = z1 - z0
        dz2 = (z1 * z1 - z0 * z0) / arb(2)
        dz3 = (z1 * z1 * z1 - z0 * z0 * z0) / arb(3)
        for i in range(3):
            for j in range(3):
                a_mat[i][j] = a_mat[i][j] + qb[i][j] * dz1
                b_mat[i][j] = b_mat[i][j] + qb[i][j] * dz2
                d_mat[i][j] = d_mat[i][j] + qb[i][j] * dz3
        ply_data.append((c, s, z0, z1))

    max_b = max((abs(b_mat[i][j]) for i in range(3) for j in range(3)), key=_arb_mid_dec)
    abd = [[arb(0) for _ in range(6)] for _ in range(6)]
    for i in range(3):
        for j in range(3):
            abd[i][j] = a_mat[i][j]
            abd[i][j + 3] = b_mat[i][j]
            abd[i + 3][j] = b_mat[i][j]
            abd[i + 3][j + 3] = d_mat[i][j]
    sol = _solve_arb_linear_system(abd, [nx, ny, nxy, mx, arb(0), arb(0)])
    eps0, kappa = sol[:3], sol[3:]

    a_inv_c0 = _solve_arb_linear_system(a_mat, [arb(1), arb(0), arb(0)])
    a_inv_c1 = _solve_arb_linear_system(a_mat, [arb(0), arb(1), arb(0)])
    a_inv_c2 = _solve_arb_linear_system(a_mat, [arb(0), arb(0), arb(1)])
    ex_eff = arb(1) / (total_h * a_inv_c0[0])
    ey_eff = arb(1) / (total_h * a_inv_c1[1])
    gxy_eff = arb(1) / (total_h * a_inv_c2[2])
    nuxy_eff = -(a_inv_c0[1] / a_inv_c0[0])

    fi_cands: list[arb] = []
    for c, s, z0, z1 in ply_data:
        c2, s2, sc = c * c, s * s, s * c
        for z_pt in (z0, z1):
            ex = eps0[0] + z_pt * kappa[0]
            ey = eps0[1] + z_pt * kappa[1]
            gxy = eps0[2] + z_pt * kappa[2]
            e1_l = c2 * ex + s2 * ey + sc * gxy
            e2_l = s2 * ex + c2 * ey - sc * gxy
            g12_l = -arb(2) * sc * ex + arb(2) * sc * ey + (c2 - s2) * gxy
            sig1 = q11 * e1_l + q12 * e2_l
            sig2 = q12 * e1_l + q22 * e2_l
            tau12 = q66 * g12_l
            fi_cands.append(((sig1 / xt) ** 2 + (sig2 / yt) ** 2 + (tau12 / s12_allow) ** 2).sqrt())
    max_fi = max(fi_cands, key=_arb_mid_dec)
    ms = (arb(1) / max_fi) - arb(1)

    return {
        "a11_n_per_mm": _drift_entry(a_mat[0][0], str(staged_outputs["a11_n_per_mm"])),
        "a22_n_per_mm": _drift_entry(a_mat[1][1], str(staged_outputs["a22_n_per_mm"])),
        "a66_n_per_mm": _drift_entry(a_mat[2][2], str(staged_outputs["a66_n_per_mm"])),
        "d11_n_mm": _drift_entry(d_mat[0][0], str(staged_outputs["d11_n_mm"])),
        "d22_n_mm": _drift_entry(d_mat[1][1], str(staged_outputs["d22_n_mm"])),
        "d66_n_mm": _drift_entry(d_mat[2][2], str(staged_outputs["d66_n_mm"])),
        "max_abs_b_coupling": _drift_entry(max_b, str(staged_outputs["max_abs_b_coupling"])),
        "ex_eff_mpa": _drift_entry(ex_eff, str(staged_outputs["ex_eff_mpa"])),
        "ey_eff_mpa": _drift_entry(ey_eff, str(staged_outputs["ey_eff_mpa"])),
        "gxy_eff_mpa": _drift_entry(gxy_eff, str(staged_outputs["gxy_eff_mpa"])),
        "nuxy_eff": _drift_entry(nuxy_eff, str(staged_outputs["nuxy_eff"])),
        "midplane_strain_x": _drift_entry(eps0[0], str(staged_outputs["midplane_strain_x"])),
        "midplane_strain_y": _drift_entry(eps0[1], str(staged_outputs["midplane_strain_y"])),
        "midplane_shear_xy": _drift_entry(eps0[2], str(staged_outputs["midplane_shear_xy"])),
        "curvature_x_per_mm": _drift_entry(kappa[0], str(staged_outputs["curvature_x_per_mm"])),
        "max_ply_failure_index": _drift_entry(max_fi, str(staged_outputs["max_ply_failure_index"])),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_rotor_blade_cf_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    m_b = _arb_from_decimal_text(str(inputs["blade_mass_kg"]))
    om = _arb_from_decimal_text(str(inputs["rotor_omega_rad_s"]))
    rcg = _arb_from_decimal_text(str(inputs["cg_radius_m"]))
    area = _arb_from_decimal_text(str(inputs["root_area_mm2"]))
    z_m = _arb_from_decimal_text(str(inputs["root_section_modulus_mm3"]))
    mf = abs(_arb_from_decimal_text(str(inputs["flap_bending_moment_n_m"])))
    ml = abs(_arb_from_decimal_text(str(inputs["lag_bending_moment_n_m"])))
    ftu = _arb_from_decimal_text(str(inputs["ultimate_tensile_mpa"]))
    send = _arb_from_decimal_text(str(inputs["endurance_limit_mpa"]))
    sf = _arb_from_decimal_text(str(inputs["safety_factor"]))

    cf = m_b * om * om * rcg
    s_cf = cf / area
    s_f = (mf * arb(1000)) / z_m
    s_l = (ml * arb(1000)) / z_m
    s_m = s_cf
    s_a = (s_f * s_f + s_l * s_l).sqrt()
    s_pk = s_m + s_a
    s_ms = (ftu / (s_pk * sf)) - arb(1)
    g_rf = arb(1) / ((s_m / ftu) + (s_a / send))
    f_ms = (g_rf / sf) - arb(1)

    return {
        "centrifugal_force_n": _drift_entry(cf, str(staged_outputs["centrifugal_force_n"])),
        "centrifugal_stress_mpa": _drift_entry(s_cf, str(staged_outputs["centrifugal_stress_mpa"])),
        "flap_bending_stress_mpa": _drift_entry(
            s_f, str(staged_outputs["flap_bending_stress_mpa"])
        ),
        "lag_bending_stress_mpa": _drift_entry(s_l, str(staged_outputs["lag_bending_stress_mpa"])),
        "steady_mean_stress_mpa": _drift_entry(s_m, str(staged_outputs["steady_mean_stress_mpa"])),
        "alternating_stress_mpa": _drift_entry(s_a, str(staged_outputs["alternating_stress_mpa"])),
        "peak_combined_stress_mpa": _drift_entry(
            s_pk, str(staged_outputs["peak_combined_stress_mpa"])
        ),
        "static_margin_of_safety": _drift_entry(
            s_ms, str(staged_outputs["static_margin_of_safety"])
        ),
        "goodman_reserve_factor": _drift_entry(g_rf, str(staged_outputs["goodman_reserve_factor"])),
        "fatigue_margin_of_safety": _drift_entry(
            f_ms, str(staged_outputs["fatigue_margin_of_safety"])
        ),
    }


def evaluate_ground_resonance_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    om = _arb_from_decimal_text(str(inputs["rotor_omega_rad_s"]))
    wl = _arb_from_decimal_text(str(inputs["blade_lead_lag_freq_rad_s"]))
    wf = _arb_from_decimal_text(str(inputs["fuselage_mode_freq_rad_s"]))
    zl = _arb_from_decimal_text(str(inputs["blade_lag_damping_ratio"]))
    zf = _arb_from_decimal_text(str(inputs["fuselage_damping_ratio"]))
    mu = _arb_from_decimal_text(str(inputs["mass_coupling_ratio"]))
    fac = _arb_from_decimal_text(str(inputs["min_damping_margin_factor"]))

    nu = wl / om
    reg = abs(om - wl)
    coal = wf + wl
    sep = (abs(om - coal) / coal) * arb(100)
    d_act = zl * zf
    d_thr = (mu / arb(4)) * (om / (wl + wf))
    s_rat = d_act / d_thr
    s_ms = (s_rat / fac) - arb(1)

    return {
        "lag_freq_ratio_nu": _drift_entry(nu, str(staged_outputs["lag_freq_ratio_nu"])),
        "regressive_lag_freq_rad_s": _drift_entry(
            reg, str(staged_outputs["regressive_lag_freq_rad_s"])
        ),
        "coalescence_rotor_speed_rad_s": _drift_entry(
            coal, str(staged_outputs["coalescence_rotor_speed_rad_s"])
        ),
        "speed_separation_pct": _drift_entry(sep, str(staged_outputs["speed_separation_pct"])),
        "damping_product_actual": _drift_entry(
            d_act, str(staged_outputs["damping_product_actual"])
        ),
        "coleman_damping_threshold": _drift_entry(
            d_thr, str(staged_outputs["coleman_damping_threshold"])
        ),
        "damping_stability_ratio": _drift_entry(
            s_rat, str(staged_outputs["damping_stability_ratio"])
        ),
        "stability_margin_of_safety": _drift_entry(
            s_ms, str(staged_outputs["stability_margin_of_safety"])
        ),
    }


def evaluate_cs29_crashworthiness_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    mass = _arb_from_decimal_text(str(inputs["occupant_seat_mass_kg"]))
    dv = _arb_from_decimal_text(str(inputs["delta_v_m_s"]))
    tr = _arb_from_decimal_text(str(inputs["rise_time_s"]))
    nb = _arb_from_decimal_text(str(inputs["attachment_bolt_count"]))
    allow = _arb_from_decimal_text(str(inputs["bolt_allowable_load_n"]))
    ff = _arb_from_decimal_text(str(inputs["floor_fitting_factor"]))
    g0 = _arb_from_decimal_text("9.80665")

    uf = mass * g0 * arb(20) * ff
    ud = mass * g0 * arb(20) * ff
    us = mass * g0 * arb(10) * ff
    pk_g = dv / (g0 * tr)
    dyn = mass * (dv / tr) * ff
    gov = max([uf, ud, dyn], key=_arb_mid_dec)
    per_b = gov / nb
    ms = (allow / per_b) - arb(1)

    return {
        "ultimate_forward_load_n": _drift_entry(uf, str(staged_outputs["ultimate_forward_load_n"])),
        "ultimate_downward_load_n": _drift_entry(
            ud, str(staged_outputs["ultimate_downward_load_n"])
        ),
        "ultimate_sideward_load_n": _drift_entry(
            us, str(staged_outputs["ultimate_sideward_load_n"])
        ),
        "cs29_562_peak_g": _drift_entry(pk_g, str(staged_outputs["cs29_562_peak_g"])),
        "dynamic_pulse_load_n": _drift_entry(dyn, str(staged_outputs["dynamic_pulse_load_n"])),
        "governing_design_load_n": _drift_entry(
            gov, str(staged_outputs["governing_design_load_n"])
        ),
        "per_attachment_load_n": _drift_entry(per_b, str(staged_outputs["per_attachment_load_n"])),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_multirow_bolt_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    p_tot = _arb_from_decimal_text(str(inputs["total_applied_load_n"]))
    pitch = _arb_from_decimal_text(str(inputs["pitch_mm"]))
    width = _arb_from_decimal_text(str(inputs["width_mm"]))
    t1 = _arb_from_decimal_text(str(inputs["plate1_thickness_mm"]))
    t2 = _arb_from_decimal_text(str(inputs["plate2_thickness_mm"]))
    e1 = _arb_from_decimal_text(str(inputs["plate1_modulus_mpa"]))
    e2 = _arb_from_decimal_text(str(inputs["plate2_modulus_mpa"]))
    d = _arb_from_decimal_text(str(inputs["bolt_diameter_mm"]))
    eb = _arb_from_decimal_text(str(inputs["bolt_modulus_mpa"]))
    fbru = _arb_from_decimal_text(str(inputs["bearing_allowable_mpa"]))

    geom = ((t1 + t2) / (arb(2) * d)) ** (arb(2) / arb(3))
    compl = (
        (arb(1) / (t1 * e1))
        + (arb(1) / (t2 * e2))
        + (arb(1) / (arb(2) * t1 * eb))
        + (arb(1) / (arb(2) * t2 * eb))
    )
    cf = geom * arb(3) * compl
    cp1 = pitch / (e1 * width * t1)
    cp2 = pitch / (e2 * width * t2)
    mat = [
        [cf + cp1 + cp2, -cf, arb(0)],
        [cp2, cf + cp2, -(cf + cp1)],
        [arb(1), arb(1), arb(1)],
    ]
    p1, p2, p3 = _solve_arb_linear_system(mat, [cp1 * p_tot, arb(0), p_tot])
    pk_load = max([p1, p2, p3], key=_arb_mid_dec)
    pk_frac = pk_load / p_tot
    t_min = min([t1, t2], key=_arb_mid_dec)
    pk_brg = pk_load / (d * t_min)
    byp2 = p_tot - p1 - p2
    ms = (fbru / pk_brg) - arb(1)

    return {
        "huth_flexibility_mm_per_n": _drift_entry(
            cf, str(staged_outputs["huth_flexibility_mm_per_n"])
        ),
        "row1_load_n": _drift_entry(p1, str(staged_outputs["row1_load_n"])),
        "row2_load_n": _drift_entry(p2, str(staged_outputs["row2_load_n"])),
        "row3_load_n": _drift_entry(p3, str(staged_outputs["row3_load_n"])),
        "peak_row_load_fraction": _drift_entry(
            pk_frac, str(staged_outputs["peak_row_load_fraction"])
        ),
        "peak_bearing_stress_mpa": _drift_entry(
            pk_brg, str(staged_outputs["peak_bearing_stress_mpa"])
        ),
        "bypass_load_row2_n": _drift_entry(byp2, str(staged_outputs["bypass_load_row2_n"])),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_larc04_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    sig1 = _arb_from_decimal_text(str(inputs["sigma_1_mpa"]))
    sig2 = _arb_from_decimal_text(str(inputs["sigma_2_mpa"]))
    tau12 = _arb_from_decimal_text(str(inputs["tau_12_mpa"]))
    xt = _arb_from_decimal_text(str(inputs["x_t_mpa"]))
    xc = _arb_from_decimal_text(str(inputs["x_c_mpa"]))
    yt = _arb_from_decimal_text(str(inputs["y_t_mpa"]))
    yc = _arb_from_decimal_text(str(inputs["y_c_mpa"]))
    sl = _arb_from_decimal_text(str(inputs["s_l_mpa"]))
    alpha0 = _arb_from_decimal_text(str(inputs["alpha_0_deg"]))
    eta_l = _arb_from_decimal_text(str(inputs["eta_l"]))
    g12 = _arb_from_decimal_text(str(inputs["g_12_mpa"]))
    phi0 = _arb_from_decimal_text(str(inputs["phi_0_deg"]))

    rad_scale = arb.pi() / arb(180)
    s1_d = Decimal(str(inputs["sigma_1_mpa"]))
    s2_d = Decimal(str(inputs["sigma_2_mpa"]))

    fi_ft = (sig1 / xt) if s1_d > Decimal("0") else arb(0)

    if s1_d < Decimal("0"):
        abs_s1 = -sig1
        phi_kink = phi0 * g12 / (g12 - abs_s1)
        phi_r = phi_kink * rad_scale
        c_p = phi_r.cos()
        s_p = phi_r.sin()
        c2p = (arb(2) * phi_r).cos()
        s2p = (arb(2) * phi_r).sin()
        abs_t12 = abs(tau12)
        tau12m = abs_t12 * c2p + (abs_s1 + sig2) * s_p * c_p
        sig2m = sig1 * s_p * s_p + sig2 * c_p * c_p - abs_t12 * s2p
        s2m_neg = sig2m if _arb_mid_dec(sig2m) < Decimal("0") else arb(0)
        tau_keff = abs(tau12m) + eta_l * s2m_neg
        if _arb_mid_dec(tau_keff) < Decimal("0"):
            tau_keff = arb(0)
        fi_fc = max([abs_s1 / xc, tau_keff / sl], key=_arb_mid_dec)
    else:
        phi_kink = phi0
        fi_fc = arb(0)

    fi_mt = ((sig2 / yt) ** 2 + (tau12 / sl) ** 2).sqrt() if s2_d > Decimal("0") else arb(0)

    a0_r = alpha0 * rad_scale
    a2_r = arb(2) * a0_r
    eta_t = -arb(1) / (a2_r.sin() / a2_r.cos())
    c_a = a0_r.cos()
    s_a = a0_r.sin()
    st = yc * c_a * (s_a - eta_t * c_a)
    if s2_d < Decimal("0"):
        sig_n = sig2 * c_a * c_a
        tau_t = -sig2 * s_a * c_a
        tau_l = abs(tau12) * c_a
        t_eff_t = abs(tau_t) + eta_t * sig_n
        if _arb_mid_dec(t_eff_t) < Decimal("0"):
            t_eff_t = arb(0)
        t_eff_l = tau_l + eta_l * sig_n
        if _arb_mid_dec(t_eff_l) < Decimal("0"):
            t_eff_l = arb(0)
        fi_mc = ((t_eff_t / st) ** 2 + (t_eff_l / sl) ** 2).sqrt()
    else:
        fi_mc = arb(0)

    gov_fi = max([fi_ft, fi_fc, fi_mt, fi_mc], key=_arb_mid_dec)
    ms = arb(99) if _arb_mid_dec(gov_fi) <= Decimal("1e-12") else ((arb(1) / gov_fi) - arb(1))

    return {
        "eta_t_transverse": _drift_entry(eta_t, str(staged_outputs["eta_t_transverse"])),
        "transverse_shear_strength_st_mpa": _drift_entry(
            st, str(staged_outputs["transverse_shear_strength_st_mpa"])
        ),
        "kink_angle_deg": _drift_entry(phi_kink, str(staged_outputs["kink_angle_deg"])),
        "fi_fiber_tension": _drift_entry(fi_ft, str(staged_outputs["fi_fiber_tension"])),
        "fi_fiber_compression": _drift_entry(fi_fc, str(staged_outputs["fi_fiber_compression"])),
        "fi_matrix_tension": _drift_entry(fi_mt, str(staged_outputs["fi_matrix_tension"])),
        "fi_matrix_compression": _drift_entry(fi_mc, str(staged_outputs["fi_matrix_compression"])),
        "governing_failure_index": _drift_entry(
            gov_fi, str(staged_outputs["governing_failure_index"])
        ),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_cs29_bird_strike_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    m_b = _arb_from_decimal_text(str(inputs["bird_mass_kg"]))
    vel = _arb_from_decimal_text(str(inputs["impact_velocity_m_s"]))
    rho = _arb_from_decimal_text(str(inputs["bird_density_kg_m3"]))
    diam = _arb_from_decimal_text(str(inputs["bird_diameter_mm"]))
    t_p = _arb_from_decimal_text(str(inputs["panel_thickness_mm"]))
    tau_a = _arb_from_decimal_text(str(inputs["panel_shear_allowable_mpa"]))
    sf = _arb_from_decimal_text(str(inputs["safety_factor"]))

    pi_val = arb.pi()
    ke = (m_b * vel * vel) / arb(2)
    p_stag = (rho * vel * vel) / (arb(2) * arb(1000000))
    radius = diam / arb(2)
    area = pi_val * radius * radius
    f_eq = p_stag * area
    req_t = (f_eq * sf) / (pi_val * diam * tau_a)
    app_tau = f_eq / (pi_val * diam * t_p)
    ms = (t_p / req_t) - arb(1)

    return {
        "kinetic_energy_j": _drift_entry(ke, str(staged_outputs["kinetic_energy_j"])),
        "stagnation_pressure_mpa": _drift_entry(
            p_stag, str(staged_outputs["stagnation_pressure_mpa"])
        ),
        "impact_area_mm2": _drift_entry(area, str(staged_outputs["impact_area_mm2"])),
        "equivalent_impact_force_n": _drift_entry(
            f_eq, str(staged_outputs["equivalent_impact_force_n"])
        ),
        "applied_plug_shear_mpa": _drift_entry(
            app_tau, str(staged_outputs["applied_plug_shear_mpa"])
        ),
        "required_thickness_mm": _drift_entry(req_t, str(staged_outputs["required_thickness_mm"])),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_campbell_clearance_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    w_min = _arb_from_decimal_text(str(inputs["omega_min_rpm"]))
    w_max = _arb_from_decimal_text(str(inputs["omega_max_rpm"]))
    b_int = int(Decimal(str(inputs["blade_count"])))
    f_str = _arb_from_decimal_text(str(inputs["structural_freq_hz"]))
    min_clr = _arb_from_decimal_text(str(inputs["min_clearance_pct"]))

    one_p_max = w_max / arb(60)
    bp_min = (arb(b_int) * w_min) / arb(60)
    bp_max = (arb(b_int) * w_max) / arb(60)

    orders = (1, b_int, 2 * b_int, 3 * b_int)
    min_sep: arb | None = None
    gov_ord = 1
    f_str_d = Decimal(str(inputs["structural_freq_hz"]))
    w_min_d = Decimal(str(inputs["omega_min_rpm"]))
    w_max_d = Decimal(str(inputs["omega_max_rpm"]))
    for k in orders:
        k_a = arb(k)
        f_lo = (k_a * w_min) / arb(60)
        f_hi = (k_a * w_max) / arb(60)
        f_lo_d = (Decimal(k) * w_min_d) / Decimal("60")
        f_hi_d = (Decimal(k) * w_max_d) / Decimal("60")
        if f_str_d < f_lo_d:
            sep = ((f_lo - f_str) / f_lo) * arb(100)
        elif f_str_d > f_hi_d:
            sep = ((f_str - f_hi) / f_hi) * arb(100)
        else:
            sep = arb(0)
        if min_sep is None or _arb_mid_dec(sep) < _arb_mid_dec(min_sep):
            min_sep = sep
            gov_ord = k
    assert min_sep is not None
    clr_m = min_sep - min_clr

    return {
        "one_p_max_hz": _drift_entry(one_p_max, str(staged_outputs["one_p_max_hz"])),
        "bp_min_hz": _drift_entry(bp_min, str(staged_outputs["bp_min_hz"])),
        "bp_max_hz": _drift_entry(bp_max, str(staged_outputs["bp_max_hz"])),
        "governing_harmonic_order": _drift_entry(
            arb(gov_ord), str(staged_outputs["governing_harmonic_order"])
        ),
        "min_separation_pct": _drift_entry(min_sep, str(staged_outputs["min_separation_pct"])),
        "clearance_margin_pct": _drift_entry(clr_m, str(staged_outputs["clearance_margin_pct"])),
    }


def evaluate_tailboom_boxbeam_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    bm = abs(_arb_from_decimal_text(str(inputs["bending_moment_n_m"])))
    tq = abs(_arb_from_decimal_text(str(inputs["torque_n_m"])))
    vs = abs(_arb_from_decimal_text(str(inputs["transverse_shear_n"])))
    width = _arb_from_decimal_text(str(inputs["box_width_mm"]))
    height = _arb_from_decimal_text(str(inputs["box_height_mm"]))
    thk = _arb_from_decimal_text(str(inputs["skin_thickness_mm"]))
    cap_a = _arb_from_decimal_text(str(inputs["cap_area_mm2"]))
    fy = _arb_from_decimal_text(str(inputs["yield_allowable_mpa"]))
    tau_cr = _arb_from_decimal_text(str(inputs["shear_buckling_allowable_mpa"]))
    sf = _arb_from_decimal_text(str(inputs["safety_factor"]))

    h_half = height / arb(2)
    i_xx = (
        (arb(4) * cap_a * h_half * h_half)
        + ((thk * (height**3)) / arb(6))
        + (arb(2) * width * thk * h_half * h_half)
    )
    sig_b = (bm * arb(1000) * h_half) / i_xx
    tau_t = (tq * arb(1000)) / (arb(2) * width * height * thk)
    tau_w = vs / (arb(2) * height * thk)
    tau_tot = tau_t + tau_w
    vm = (sig_b * sig_b + arb(3) * tau_tot * tau_tot).sqrt()
    vm_ms = (fy / (sf * vm)) - arb(1)
    sb_ms = (tau_cr / (sf * tau_tot)) - arb(1)
    gov_ms = min([vm_ms, sb_ms], key=_arb_mid_dec)

    return {
        "section_inertia_ixx_mm4": _drift_entry(
            i_xx, str(staged_outputs["section_inertia_ixx_mm4"])
        ),
        "bending_stress_mpa": _drift_entry(sig_b, str(staged_outputs["bending_stress_mpa"])),
        "torsion_shear_stress_mpa": _drift_entry(
            tau_t, str(staged_outputs["torsion_shear_stress_mpa"])
        ),
        "web_shear_stress_mpa": _drift_entry(tau_w, str(staged_outputs["web_shear_stress_mpa"])),
        "total_shear_stress_mpa": _drift_entry(
            tau_tot, str(staged_outputs["total_shear_stress_mpa"])
        ),
        "von_mises_stress_mpa": _drift_entry(vm, str(staged_outputs["von_mises_stress_mpa"])),
        "von_mises_ms": _drift_entry(vm_ms, str(staged_outputs["von_mises_ms"])),
        "shear_buckling_ms": _drift_entry(sb_ms, str(staged_outputs["shear_buckling_ms"])),
        "governing_ms": _drift_entry(gov_ms, str(staged_outputs["governing_ms"])),
    }


def evaluate_statistical_ab_basis_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    n_a = _arb_from_decimal_text(str(inputs["sample_count"]))
    mean_v = _arb_from_decimal_text(str(inputs["sample_mean_mpa"]))
    std_v = _arb_from_decimal_text(str(inputs["sample_std_mpa"]))
    sig_des = _arb_from_decimal_text(str(inputs["design_stress_mpa"]))

    ln_n = n_a.log()
    k_b = (
        _arb_from_decimal_text("1.282")
        + (
            _arb_from_decimal_text("0.958")
            - _arb_from_decimal_text("0.520") * ln_n
            + _arb_from_decimal_text("3.19") / n_a
        ).exp()
    )
    k_a = (
        _arb_from_decimal_text("2.326")
        + (
            _arb_from_decimal_text("1.340")
            - _arb_from_decimal_text("0.522") * ln_n
            + _arb_from_decimal_text("3.87") / n_a
        ).exp()
    )
    b_basis = mean_v - k_b * std_v
    a_basis = mean_v - k_a * std_v
    cv_pct = (std_v / mean_v) * arb(100)
    ms_a = (a_basis / sig_des) - arb(1)

    return {
        "k_b_factor": _drift_entry(k_b, str(staged_outputs["k_b_factor"])),
        "k_a_factor": _drift_entry(k_a, str(staged_outputs["k_a_factor"])),
        "b_basis_mpa": _drift_entry(b_basis, str(staged_outputs["b_basis_mpa"])),
        "a_basis_mpa": _drift_entry(a_basis, str(staged_outputs["a_basis_mpa"])),
        "coeff_variation_pct": _drift_entry(cv_pct, str(staged_outputs["coeff_variation_pct"])),
        "margin_vs_a_basis": _drift_entry(ms_a, str(staged_outputs["margin_vs_a_basis"])),
    }


def evaluate_bolt_prying_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    p_t = _arb_from_decimal_text(str(inputs["applied_tension_n"]))
    v_s = abs(_arb_from_decimal_text(str(inputs["applied_shear_n"])))
    m_b = abs(_arb_from_decimal_text(str(inputs["applied_bending_n_mm"])))
    a_mm = _arb_from_decimal_text(str(inputs["prying_lever_a_mm"]))
    b_mm = _arb_from_decimal_text(str(inputs["prying_lever_b_mm"]))
    t_fl = _arb_from_decimal_text(str(inputs["flange_thickness_mm"]))
    allow_t = _arb_from_decimal_text(str(inputs["bolt_tensile_allowable_n"]))
    allow_s = _arb_from_decimal_text(str(inputs["bolt_shear_allowable_n"]))
    allow_b = _arb_from_decimal_text(str(inputs["bolt_bending_allowable_n_mm"]))
    sf = _arb_from_decimal_text(str(inputs["safety_factor"]))

    q_cand = (b_mm / (arb(2) * a_mm)) * (arb(10) / (t_fl + arb(10)))
    q_pry = min([_arb_from_decimal_text("0.65"), q_cand], key=_arb_mid_dec)
    pry_force = p_t * q_pry
    tot_t = p_t + pry_force
    r_t = tot_t / allow_t
    r_b = m_b / allow_b
    r_s = v_s / allow_s
    idx = ((r_t + r_b) ** 2 + (r_s * r_s)).sqrt()
    ms = arb(99) if _arb_mid_dec(idx) <= Decimal("1e-12") else ((arb(1) / (sf * idx)) - arb(1))

    return {
        "prying_factor_q": _drift_entry(q_pry, str(staged_outputs["prying_factor_q"])),
        "prying_force_n": _drift_entry(pry_force, str(staged_outputs["prying_force_n"])),
        "total_bolt_tension_n": _drift_entry(tot_t, str(staged_outputs["total_bolt_tension_n"])),
        "tension_ratio": _drift_entry(r_t, str(staged_outputs["tension_ratio"])),
        "shear_ratio": _drift_entry(r_s, str(staged_outputs["shear_ratio"])),
        "combined_interaction_index": _drift_entry(
            idx, str(staged_outputs["combined_interaction_index"])
        ),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_goland_reissner_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    load_w = _arb_from_decimal_text(str(inputs["tensile_load_per_width_n_mm"]))
    l_ov = _arb_from_decimal_text(str(inputs["overlap_length_mm"]))
    t_adh = _arb_from_decimal_text(str(inputs["adherend_thickness_mm"]))
    e_adh = _arb_from_decimal_text(str(inputs["adherend_modulus_mpa"]))
    t_glue = _arb_from_decimal_text(str(inputs["adhesive_thickness_mm"]))
    e_glue = _arb_from_decimal_text(str(inputs["adhesive_modulus_mpa"]))
    g_glue = _arb_from_decimal_text(str(inputs["adhesive_shear_modulus_mpa"]))
    peel_allow = _arb_from_decimal_text(str(inputs["peel_allowable_mpa"]))
    shear_allow = _arb_from_decimal_text(str(inputs["shear_allowable_mpa"]))
    sf = _arb_from_decimal_text(str(inputs["safety_factor"]))

    c_half = l_ov / arb(2)
    u2c = (c_half / t_adh) * ((arb(3) * load_w) / (arb(2) * e_adh * t_adh)).sqrt()
    tanh_u = arb(1) if _arb_mid_dec(u2c) >= Decimal("20") else u2c.tanh()
    k_gr = arb(1) / (arb(1) + arb(2) * arb(2).sqrt() * tanh_u)
    tau_avg = load_w / l_ov
    beta_s = ((arb(8) * g_glue * t_adh) / (e_adh * t_glue)).sqrt() * (c_half / t_adh)
    peak_shear = tau_avg * (
        arb(1)
        + _arb_from_decimal_text("0.25") * (arb(1) + arb(3) * k_gr) * (arb(1) + beta_s / arb(4))
    )
    gamma_p = ((arb(6) * e_glue * t_adh) / (e_adh * t_glue)).sqrt()
    peak_peel = (load_w / t_adh) * k_gr * _arb_from_decimal_text("0.5") * gamma_p
    idx = ((peak_peel / peel_allow) ** 2 + (peak_shear / shear_allow) ** 2).sqrt()
    ms = (arb(1) / (sf * idx)) - arb(1)

    return {
        "gr_bending_factor_k": _drift_entry(k_gr, str(staged_outputs["gr_bending_factor_k"])),
        "average_shear_mpa": _drift_entry(tau_avg, str(staged_outputs["average_shear_mpa"])),
        "peak_shear_mpa": _drift_entry(peak_shear, str(staged_outputs["peak_shear_mpa"])),
        "peak_peel_mpa": _drift_entry(peak_peel, str(staged_outputs["peak_peel_mpa"])),
        "combined_interaction_index": _drift_entry(
            idx, str(staged_outputs["combined_interaction_index"])
        ),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_orthotropic_plate_buckling_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    nx = _arb_from_decimal_text(str(inputs["nx_comp_n_per_mm"]))
    ny = _arb_from_decimal_text(str(inputs["ny_comp_n_per_mm"]))
    nxy = abs(_arb_from_decimal_text(str(inputs["nxy_shear_n_per_mm"])))
    len_a = _arb_from_decimal_text(str(inputs["plate_length_a_mm"]))
    wid_b = _arb_from_decimal_text(str(inputs["plate_width_b_mm"]))
    d11 = _arb_from_decimal_text(str(inputs["d11_n_mm"]))
    d22 = _arb_from_decimal_text(str(inputs["d22_n_mm"]))
    d12 = _arb_from_decimal_text(str(inputs["d12_n_mm"]))
    d66 = _arb_from_decimal_text(str(inputs["d66_n_mm"]))
    sf = _arb_from_decimal_text(str(inputs["safety_factor"]))

    h_eff = d12 + arb(2) * d66
    d_sqrt = (d11 * d22).sqrt()
    pi_sq = arb.pi() ** 2
    nx_cr = (arb(2) * pi_sq / (wid_b * wid_b)) * (d_sqrt + h_eff)
    ny_cr = (arb(2) * pi_sq / (len_a * len_a)) * (d_sqrt + h_eff)
    theta_s = d_sqrt / h_eff
    k_s = _arb_from_decimal_text("3.2") + _arb_from_decimal_text("2.1") / (
        theta_s + _arb_from_decimal_text("0.5")
    )
    d_fourth = (d11 * (d22**3)).sqrt().sqrt()
    nxy_cr = (arb(4) * k_s / (wid_b * wid_b)) * d_fourth

    nx_pos = nx if _arb_mid_dec(nx) > Decimal("0") else arb(0)
    ny_pos = ny if _arb_mid_dec(ny) > Decimal("0") else arb(0)
    r_x = nx_pos / nx_cr
    r_y = ny_pos / ny_cr
    r_xy = nxy / nxy_cr
    idx = r_x + r_y + (r_xy * r_xy)
    ms = arb(99) if _arb_mid_dec(idx) <= Decimal("1e-12") else ((arb(1) / (sf * idx)) - arb(1))

    return {
        "nx_critical_n_per_mm": _drift_entry(nx_cr, str(staged_outputs["nx_critical_n_per_mm"])),
        "ny_critical_n_per_mm": _drift_entry(ny_cr, str(staged_outputs["ny_critical_n_per_mm"])),
        "nxy_critical_n_per_mm": _drift_entry(nxy_cr, str(staged_outputs["nxy_critical_n_per_mm"])),
        "orthotropy_param_theta": _drift_entry(
            theta_s, str(staged_outputs["orthotropy_param_theta"])
        ),
        "combined_interaction_index": _drift_entry(
            idx, str(staged_outputs["combined_interaction_index"])
        ),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_skin_stringer_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    p_app = _arb_from_decimal_text(str(inputs["applied_compression_n"]))
    l_pan = _arb_from_decimal_text(str(inputs["panel_length_mm"]))
    pitch = _arb_from_decimal_text(str(inputs["stringer_pitch_mm"]))
    t_sk = _arb_from_decimal_text(str(inputs["skin_thickness_mm"]))
    a_str = _arb_from_decimal_text(str(inputs["stringer_area_mm2"]))
    f_cc = _arb_from_decimal_text(str(inputs["stringer_crippling_mpa"]))
    i_pan = _arb_from_decimal_text(str(inputs["panel_inertia_mm4"]))
    c_fix = _arb_from_decimal_text(str(inputs["end_fixity_c"]))
    em = _arb_from_decimal_text(str(inputs["modulus_mpa"]))
    f_y = _arb_from_decimal_text(str(inputs["skin_yield_mpa"]))
    sf = _arb_from_decimal_text(str(inputs["safety_factor"]))

    w_vk = _arb_from_decimal_text("1.9") * t_sk * (em / f_y).sqrt()
    w_eff = min([pitch, w_vk], key=_arb_mid_dec)
    a_eff = a_str + w_eff * t_sk
    sig_cc = (a_str * f_cc + w_eff * t_sk * f_y) / a_eff
    rho_g = (i_pan / a_eff).sqrt()
    slend = l_pan / (rho_g * c_fix.sqrt())
    pi_sq = arb.pi() ** 2
    lam_c = (arb(2) * pi_sq * em / sig_cc).sqrt()
    if _arb_mid_dec(slend) <= _arb_mid_dec(lam_c):
        sig_cr = sig_cc * (arb(1) - (sig_cc * slend * slend) / (arb(4) * pi_sq * em))
        regime = arb(1)
    else:
        sig_cr = (pi_sq * em) / (slend * slend)
        regime = arb(2)
    sig_app = p_app / a_eff
    ms = (sig_cr / (sf * sig_app)) - arb(1)

    return {
        "effective_skin_width_mm": _drift_entry(
            w_eff, str(staged_outputs["effective_skin_width_mm"])
        ),
        "effective_panel_area_mm2": _drift_entry(
            a_eff, str(staged_outputs["effective_panel_area_mm2"])
        ),
        "weighted_crippling_cutoff_mpa": _drift_entry(
            sig_cc, str(staged_outputs["weighted_crippling_cutoff_mpa"])
        ),
        "effective_slenderness": _drift_entry(slend, str(staged_outputs["effective_slenderness"])),
        "column_regime_code": _drift_entry(regime, str(staged_outputs["column_regime_code"])),
        "critical_panel_stress_mpa": _drift_entry(
            sig_cr, str(staged_outputs["critical_panel_stress_mpa"])
        ),
        "applied_panel_stress_mpa": _drift_entry(
            sig_app, str(staged_outputs["applied_panel_stress_mpa"])
        ),
        "margin_of_safety": _drift_entry(ms, str(staged_outputs["margin_of_safety"])),
    }


def evaluate_walker_crack_intervals(
    inputs: dict[str, Any],
    staged_outputs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    ctx.dps = _BALL_DPS
    a0_mm = _arb_from_decimal_text(str(inputs["initial_crack_a0_mm"]))
    sig_max = _arb_from_decimal_text(str(inputs["sigma_max_mpa"]))
    r_rat = _arb_from_decimal_text(str(inputs["stress_ratio_r"]))
    beta = _arb_from_decimal_text(str(inputs["geometry_factor_beta"]))
    k_ic = _arb_from_decimal_text(str(inputs["fracture_toughness_kic_mpa_sqrt_m"]))
    w_c = _arb_from_decimal_text(str(inputs["walker_c"]))
    w_m = _arb_from_decimal_text(str(inputs["walker_m"]))
    w_gamma = _arb_from_decimal_text(str(inputs["walker_gamma"]))
    req_cyc = _arb_from_decimal_text(str(inputs["required_cycles"]))
    sf = _arb_from_decimal_text(str(inputs["scatter_factor"]))

    pi_val = arb.pi()
    a0_m = a0_mm / arb(1000)
    ac_m = ((k_ic / (beta * sig_max)) ** 2) / pi_val
    ac_mm = ac_m * arb(1000)
    ds_eff = sig_max * ((arb(1) - r_rat).log() * w_gamma).exp()
    dk_eff_0 = beta * ds_eff * (pi_val * a0_m).sqrt()
    p_exp = arb(1) - (w_m / arb(2))
    denom_const = w_c * (((beta * ds_eff * pi_val.sqrt()).log()) * w_m).exp()
    life_cycles = (((ac_m.log() * p_exp).exp()) - ((a0_m.log() * p_exp).exp())) / (
        p_exp * denom_const
    )
    insp_cyc = life_cycles / sf
    ms_life = (insp_cyc / req_cyc) - arb(1)

    return {
        "critical_crack_ac_mm": _drift_entry(ac_mm, str(staged_outputs["critical_crack_ac_mm"])),
        "walker_effective_stress_mpa": _drift_entry(
            ds_eff, str(staged_outputs["walker_effective_stress_mpa"])
        ),
        "initial_delta_k_eff_mpa_sqrt_m": _drift_entry(
            dk_eff_0, str(staged_outputs["initial_delta_k_eff_mpa_sqrt_m"])
        ),
        "unfactored_life_cycles": _drift_entry(
            life_cycles, str(staged_outputs["unfactored_life_cycles"])
        ),
        "safe_inspection_interval_cycles": _drift_entry(
            insp_cyc, str(staged_outputs["safe_inspection_interval_cycles"])
        ),
        "life_margin_of_safety": _drift_entry(
            ms_life, str(staged_outputs["life_margin_of_safety"])
        ),
    }


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
