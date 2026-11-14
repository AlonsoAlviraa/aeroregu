"""Classical aeronautical structural sizing runners in deterministic Decimal math."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum, parse_limited_decimal, quantize

_PI = Decimal("3.141592653589793238462643383279502884197")
_ONE = Decimal("1")
_TWO = Decimal("2")
_FOUR = Decimal("4")
_TWELVE = Decimal("12")


def _require_fields(inputs: dict[str, Any], required: list[str]) -> None:
    if not isinstance(inputs, dict):
        raise AbstainError("missing_input")
    for key in required:
        if key not in inputs or inputs[key] in (None, ""):
            raise AbstainError("missing_input")


def _wrap_result(
    card: dict[str, Any],
    outputs: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    res: dict[str, Any] = {
        "method_id": card["method_id"],
        "method_version": card["method_version"],
        "outputs": outputs,
        "sources": card["sources"],
        "card_title": card["title"],
        "label": card["label"],
    }
    if diagnostics:
        res["diagnostics"] = diagnostics
    return res


def run_margin_of_safety(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Compute classical MS = Allowable / (RF * FF * Load) - 1 with CS-27.625 Fitting Factor."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(card["quantum"])
    limits = card["limits"]

    applied = parse_limited_decimal(inputs["applied_load_n"], limits["applied_load_n"])
    allowable = parse_limited_decimal(inputs["allowable_load_n"], limits["allowable_load_n"])
    rf = parse_limited_decimal(inputs["reserve_factor"], limits["reserve_factor"])
    ff = parse_limited_decimal(inputs["fitting_factor"], limits["fitting_factor"])

    factored_design = quantize(applied * rf * ff, quantum)
    denominator = rf * ff * applied
    if denominator <= 0:
        raise AbstainError("outside_validity")

    ms = quantize((allowable / denominator) - _ONE, quantum)
    rf_achieved = quantize(allowable / (ff * applied), quantum)
    utilization = quantize(denominator / allowable, quantum)

    outputs = {
        "design_load_required_n": format_quantum(factored_design, quantum),
        "margin_of_safety": format_quantum(ms, quantum),
        "reserve_factor_achieved": format_quantum(rf_achieved, quantum),
        "utilization_ratio": format_quantum(utilization, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={
            "positive_margin": ms >= Decimal("0"),
            "cs_27_625_ff_minimum": "1.150",
        },
    )


def run_column_plate_buckling(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Compute Euler-Johnson column transition + local plate buckling / crippling MS."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(card["quantum"])
    limits = card["limits"]

    p_app = parse_limited_decimal(inputs["applied_compression_n"], limits["applied_compression_n"])
    length = parse_limited_decimal(inputs["column_length_mm"], limits["column_length_mm"])
    fixity = parse_limited_decimal(inputs["end_fixity_k"], limits["end_fixity_k"])
    area = parse_limited_decimal(inputs["area_mm2"], limits["area_mm2"])
    inertia = parse_limited_decimal(inputs["inertia_mm4"], limits["inertia_mm4"])
    modulus = parse_limited_decimal(inputs["youngs_modulus_mpa"], limits["youngs_modulus_mpa"])
    sigma_y = parse_limited_decimal(inputs["yield_strength_mpa"], limits["yield_strength_mpa"])
    nu = parse_limited_decimal(inputs["poissons_ratio"], limits["poissons_ratio"])
    b_mm = parse_limited_decimal(inputs["plate_width_b_mm"], limits["plate_width_b_mm"])
    t_mm = parse_limited_decimal(inputs["plate_thickness_t_mm"], limits["plate_thickness_t_mm"])
    kc = parse_limited_decimal(inputs["plate_buckling_coeff_kc"], limits["plate_buckling_coeff_kc"])
    sigma_cc = parse_limited_decimal(inputs["crippling_cutoff_mpa"], limits["crippling_cutoff_mpa"])

    rho = (inertia / area).sqrt()
    leff = fixity * length
    slenderness = leff / rho
    pi_sq = _PI * _PI
    lambda_c = ((_TWO * pi_sq * modulus) / sigma_y).sqrt()

    if slenderness >= lambda_c:
        sigma_col = (pi_sq * modulus) / (slenderness * slenderness)
        column_mode = "euler"
    else:
        sigma_col = sigma_y * (
            _ONE - (sigma_y * slenderness * slenderness) / (_FOUR * pi_sq * modulus)
        )
        column_mode = "johnson"

    if sigma_col < 0:
        sigma_col = Decimal("0")

    t_over_b = t_mm / b_mm
    sigma_plate_elastic = (kc * pi_sq * modulus * t_over_b * t_over_b) / (
        _TWELVE * (_ONE - nu * nu)
    )
    sigma_plate = min(sigma_plate_elastic, sigma_cc)
    sigma_crit = min(sigma_col, sigma_plate)
    p_crit = sigma_crit * area
    ms_buckling = (p_crit / p_app) - _ONE

    governing = "local_plate_crippling" if sigma_plate < sigma_col else f"{column_mode}_column"

    outputs = {
        "radius_of_gyration_mm": format_quantum(rho, quantum),
        "slenderness_ratio": format_quantum(slenderness, quantum),
        "transition_slenderness": format_quantum(lambda_c, quantum),
        "column_buckling_stress_mpa": format_quantum(sigma_col, quantum),
        "plate_buckling_stress_mpa": format_quantum(sigma_plate, quantum),
        "governing_critical_stress_mpa": format_quantum(sigma_crit, quantum),
        "critical_buckling_load_n": format_quantum(p_crit, quantum),
        "buckling_ms": format_quantum(ms_buckling, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={
            "column_regime": column_mode,
            "governing_mode": governing,
        },
    )


def run_palmgren_miner_fatigue(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Compute Palmgren-Miner cumulative damage D = sum(n_i / N_i) with CS-27.571 scatter."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(card["quantum"])
    limits = card["limits"]

    n_list = inputs["cycles_applied"]
    cap_list = inputs["cycles_to_failure"]
    if not isinstance(n_list, list) or not isinstance(cap_list, list):
        raise AbstainError("outside_validity")
    max_len = int(limits["cycles_applied"].get("max_count", 1000))
    if not n_list or len(n_list) != len(cap_list) or len(n_list) > max_len:
        raise AbstainError("outside_validity")

    scatter = parse_limited_decimal(inputs["scatter_factor"], limits["scatter_factor"])
    damage_limit = parse_limited_decimal(inputs["damage_limit"], limits["damage_limit"])

    raw_damage = Decimal("0")
    block_damages: list[str] = []
    for n_raw, cap_raw in zip(n_list, cap_list, strict=True):
        n_val = parse_limited_decimal(str(n_raw), limits["cycles_applied"])
        cap_val = parse_limited_decimal(str(cap_raw), limits["cycles_to_failure"])
        d_i = n_val / cap_val
        raw_damage += d_i
        block_damages.append(format_quantum(d_i, quantum))

    factored_damage = scatter * raw_damage
    if factored_damage <= 0:
        raise AbstainError("outside_validity")
    life_factor = damage_limit / factored_damage
    ms_fatigue = life_factor - _ONE

    outputs = {
        "cumulative_damage_raw": format_quantum(raw_damage, quantum),
        "factored_damage": format_quantum(factored_damage, quantum),
        "life_factor": format_quantum(life_factor, quantum),
        "fatigue_ms": format_quantum(ms_fatigue, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={
            "block_count": len(n_list),
            "block_damages": block_damages,
        },
    )


def run_composite_failure_criteria(inputs: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """Compute Tsai-Wu and 4-mode Hashin orthotropic ply failure indices, RFs, and MS."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(card["quantum"])
    limits = card["limits"]

    s1 = parse_limited_decimal(inputs["sigma_1_mpa"], limits["sigma_1_mpa"])
    s2 = parse_limited_decimal(inputs["sigma_2_mpa"], limits["sigma_2_mpa"])
    t12 = parse_limited_decimal(inputs["tau_12_mpa"], limits["tau_12_mpa"])
    xt = parse_limited_decimal(inputs["xt_mpa"], limits["xt_mpa"])
    xc = parse_limited_decimal(inputs["xc_mpa"], limits["xc_mpa"])
    yt = parse_limited_decimal(inputs["yt_mpa"], limits["yt_mpa"])
    yc = parse_limited_decimal(inputs["yc_mpa"], limits["yc_mpa"])
    s12 = parse_limited_decimal(inputs["s12_mpa"], limits["s12_mpa"])
    f12_star = parse_limited_decimal(inputs["f12_star"], limits["f12_star"])

    f1 = (_ONE / xt) - (_ONE / xc)
    f2 = (_ONE / yt) - (_ONE / yc)
    f11 = _ONE / (xt * xc)
    f22 = _ONE / (yt * yc)
    f66 = _ONE / (s12 * s12)
    f12 = f12_star * (f11 * f22).sqrt()

    tw_b = f1 * s1 + f2 * s2
    tw_a = (f11 * s1 * s1) + (f22 * s2 * s2) + (f66 * t12 * t12) + (_TWO * f12 * s1 * s2)
    if tw_a < 0:
        raise AbstainError("outside_validity")
    fi_tw = tw_a + tw_b

    if tw_a == 0 and tw_b == 0:
        raise AbstainError("outside_validity")
    if tw_a > 0:
        rf_tw = (-tw_b + (tw_b * tw_b + _FOUR * tw_a).sqrt()) / (_TWO * tw_a)
    elif tw_b > 0:
        rf_tw = _ONE / tw_b
    else:
        raise AbstainError("outside_validity")
    ms_tw = rf_tw - _ONE

    # Hashin 1980 2D directional modes solved by exact governing Reserve Factor
    zero = Decimal("0")
    active_rfs: list[tuple[str, Decimal, Decimal]] = []

    fi_ft = ((s1 / xt) * (s1 / xt) + (t12 / s12) * (t12 / s12)) if s1 >= 0 else zero
    if fi_ft > 0:
        active_rfs.append(("fiber_tension", _ONE / fi_ft.sqrt(), fi_ft))

    fi_fc = ((-s1 / xc) * (-s1 / xc)) if s1 < 0 else zero
    if fi_fc > 0:
        active_rfs.append(("fiber_compression", _ONE / fi_fc.sqrt(), fi_fc))

    fi_mt = ((s2 / yt) * (s2 / yt) + (t12 / s12) * (t12 / s12)) if s2 >= 0 else zero
    if fi_mt > 0:
        active_rfs.append(("matrix_tension", _ONE / fi_mt.sqrt(), fi_mt))

    if s2 < 0:
        two_s12 = _TWO * s12
        mc_a = (s2 / two_s12) * (s2 / two_s12) + (t12 / s12) * (t12 / s12)
        mc_b = (((yc / two_s12) * (yc / two_s12)) - _ONE) * (s2 / yc)
        fi_mc_raw = mc_a + mc_b
        fi_mc = fi_mc_raw if fi_mc_raw > 0 else zero
        if mc_a > 0:
            rf_mc = (-mc_b + (mc_b * mc_b + _FOUR * mc_a).sqrt()) / (_TWO * mc_a)
            active_rfs.append(("matrix_compression", rf_mc, fi_mc))
    else:
        fi_mc = zero

    if not active_rfs:
        raise AbstainError("outside_validity")

    gov_mode, rf_hashin, fi_hashin = min(active_rfs, key=lambda item: item[1])
    ms_hashin = rf_hashin - _ONE

    outputs = {
        "tsai_wu_failure_index": format_quantum(fi_tw, quantum),
        "tsai_wu_reserve_factor": format_quantum(rf_tw, quantum),
        "tsai_wu_ms": format_quantum(ms_tw, quantum),
        "hashin_fiber_tension_index": format_quantum(fi_ft, quantum),
        "hashin_fiber_compression_index": format_quantum(fi_fc, quantum),
        "hashin_matrix_tension_index": format_quantum(fi_mt, quantum),
        "hashin_matrix_compression_index": format_quantum(fi_mc, quantum),
        "hashin_governing_index": format_quantum(fi_hashin, quantum),
        "hashin_reserve_factor": format_quantum(rf_hashin, quantum),
        "hashin_ms": format_quantum(ms_hashin, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={"hashin_governing_mode": gov_mode},
    )
