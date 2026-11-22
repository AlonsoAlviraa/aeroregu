"""Deterministic Decimal quotation costing and 3-point PERT workpackage estimation."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum, parse_limited_decimal

_ONE = Decimal("1")
_FOUR = Decimal("4")
_SIX = Decimal("6")
_HUNDRED = Decimal("100")
_Z_P80 = Decimal("0.84162123")
_Z_P90 = Decimal("1.28155157")


def _require_fields(inputs: dict[str, Any], required: list[str]) -> None:
    if not isinstance(inputs, dict):
        raise AbstainError("missing_input")
    for key in required:
        if key not in inputs or inputs[key] in (None, ""):
            raise AbstainError("missing_input")


def _wrap_result(
    card: dict[str, Any],
    outputs: dict[str, str],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    res: dict[str, Any] = {
        "method_id": str(card["method_id"]),
        "method_version": str(card["method_version"]),
        "outputs": outputs,
        "sources": list(card["sources"]),
        "card_title": str(card["title"]),
        "label": str(card["label"]),
    }
    if diagnostics:
        res["diagnostics"] = diagnostics
    return res


def run_aerospace_quotation_costing(
    inputs: dict[str, Any],
    card: dict[str, Any],
) -> dict[str, Any]:
    """Compute exact Decimal manufacturing, material, NRE, overhead, contingency, and margin."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(str(card["quantum"]))
    limits = card["limits"]

    qty = parse_limited_decimal(inputs["part_quantity"], limits["part_quantity"])
    if qty != qty.to_integral_value() or qty <= 0:
        raise AbstainError("outside_validity")

    mass_kg = parse_limited_decimal(inputs["finished_mass_kg"], limits["finished_mass_kg"])
    btf = parse_limited_decimal(inputs["buy_to_fly_ratio"], limits["buy_to_fly_ratio"])
    mat_cost_kg = parse_limited_decimal(
        inputs["material_unit_cost_eur_kg"], limits["material_unit_cost_eur_kg"]
    )
    mach_hrs = parse_limited_decimal(
        inputs["machining_hours_per_part"], limits["machining_hours_per_part"]
    )
    mach_rate = parse_limited_decimal(
        inputs["machining_rate_eur_hr"], limits["machining_rate_eur_hr"]
    )
    eng_hrs = parse_limited_decimal(
        inputs["engineering_setup_hours"], limits["engineering_setup_hours"]
    )
    eng_rate = parse_limited_decimal(
        inputs["engineering_rate_eur_hr"], limits["engineering_rate_eur_hr"]
    )
    ndt_part = parse_limited_decimal(
        inputs["ndt_qa_cost_per_part_eur"], limits["ndt_qa_cost_per_part_eur"]
    )
    tooling_nre = parse_limited_decimal(inputs["tooling_nre_eur"], limits["tooling_nre_eur"])
    risk_pct = parse_limited_decimal(inputs["risk_contingency_pct"], limits["risk_contingency_pct"])
    overhead_pct = parse_limited_decimal(inputs["overhead_pct"], limits["overhead_pct"])
    target_margin_pct = parse_limited_decimal(
        inputs["target_margin_pct"], limits["target_margin_pct"]
    )

    with localcontext() as ctx:
        ctx.prec = 50
        margin_denom = _ONE - (target_margin_pct / _HUNDRED)
        if margin_denom <= 0:
            raise AbstainError("outside_validity")

        raw_mass_per_part = mass_kg * btf
        material_total = raw_mass_per_part * mat_cost_kg * qty
        manufacturing_total = mach_hrs * mach_rate * qty
        engineering_nre_total = (eng_hrs * eng_rate) + tooling_nre
        ndt_qa_total = ndt_part * qty

        direct_subtotal = (
            material_total + manufacturing_total + engineering_nre_total + ndt_qa_total
        )
        overhead_cost = direct_subtotal * (overhead_pct / _HUNDRED)
        risk_contingency = direct_subtotal * (risk_pct / _HUNDRED)
        total_cost_baseline = direct_subtotal + overhead_cost + risk_contingency

        quoted_total = total_cost_baseline / margin_denom
        quoted_unit = quoted_total / qty
        gross_margin = quoted_total - total_cost_baseline
        achieved_margin = (
            (gross_margin / quoted_total) * _HUNDRED if quoted_total > 0 else Decimal("0")
        )

    outputs = {
        "raw_material_mass_per_part_kg": format_quantum(raw_mass_per_part, quantum),
        "material_cost_total_eur": format_quantum(material_total, quantum),
        "manufacturing_cost_total_eur": format_quantum(manufacturing_total, quantum),
        "engineering_nre_total_eur": format_quantum(engineering_nre_total, quantum),
        "ndt_qa_total_eur": format_quantum(ndt_qa_total, quantum),
        "direct_cost_subtotal_eur": format_quantum(direct_subtotal, quantum),
        "overhead_cost_eur": format_quantum(overhead_cost, quantum),
        "risk_contingency_eur": format_quantum(risk_contingency, quantum),
        "total_cost_baseline_eur": format_quantum(total_cost_baseline, quantum),
        "quoted_total_price_eur": format_quantum(quoted_total, quantum),
        "quoted_unit_price_eur": format_quantum(quoted_unit, quantum),
        "gross_margin_eur": format_quantum(gross_margin, quantum),
        "achieved_margin_pct": format_quantum(achieved_margin, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={
            "part_quantity": str(qty),
            "material_share_of_direct_pct": format_quantum(
                (material_total / direct_subtotal) * _HUNDRED
                if direct_subtotal > 0
                else Decimal("0"),
                quantum,
            ),
            "nre_per_part_eur": format_quantum(engineering_nre_total / qty, quantum),
        },
    )


def run_engineering_workpackage_quote(
    inputs: dict[str, Any],
    card: dict[str, Any],
) -> dict[str, Any]:
    """Compute 3-point PERT P50/P80/P90 engineering & verification workpackage quotation."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(str(card["quantum"]))
    limits = card["limits"]

    notes_count = parse_limited_decimal(inputs["calc_notes_count"], limits["calc_notes_count"])
    fem_count = parse_limited_decimal(inputs["fem_models_count"], limits["fem_models_count"])
    if notes_count != notes_count.to_integral_value() or fem_count != fem_count.to_integral_value():
        raise AbstainError("outside_validity")

    h_opt = parse_limited_decimal(
        inputs["hours_per_calc_note_optimistic"], limits["hours_per_calc_note_optimistic"]
    )
    h_likely = parse_limited_decimal(
        inputs["hours_per_calc_note_likely"], limits["hours_per_calc_note_likely"]
    )
    h_pess = parse_limited_decimal(
        inputs["hours_per_calc_note_pessimistic"], limits["hours_per_calc_note_pessimistic"]
    )
    if not (h_opt <= h_likely <= h_pess):
        raise AbstainError("outside_validity")

    h_fem = parse_limited_decimal(inputs["hours_per_fem_model"], limits["hours_per_fem_model"])
    cve_ratio = parse_limited_decimal(inputs["cve_review_ratio"], limits["cve_review_ratio"])
    senior_rate = parse_limited_decimal(inputs["senior_rate_eur_hr"], limits["senior_rate_eur_hr"])
    cve_rate = parse_limited_decimal(inputs["cve_rate_eur_hr"], limits["cve_rate_eur_hr"])
    surcharge = parse_limited_decimal(
        inputs["software_compute_surcharge_eur"], limits["software_compute_surcharge_eur"]
    )
    rework_pct = parse_limited_decimal(
        inputs["rework_contingency_pct"], limits["rework_contingency_pct"]
    )
    target_margin_pct = parse_limited_decimal(
        inputs["target_margin_pct"], limits["target_margin_pct"]
    )

    if notes_count == 0 and fem_count == 0:
        raise AbstainError("outside_validity")

    with localcontext() as ctx:
        ctx.prec = 50
        margin_denom = _ONE - (target_margin_pct / _HUNDRED)
        if margin_denom <= 0:
            raise AbstainError("outside_validity")

        pert_expected = (h_opt + _FOUR * h_likely + h_pess) / _SIX
        pert_stddev = (h_pess - h_opt) / _SIX
        notes_sigma_total = notes_count.sqrt() * pert_stddev if notes_count > 0 else Decimal("0")

        fem_total_hours = fem_count * h_fem
        total_hours_p50 = (notes_count * pert_expected) + fem_total_hours
        total_hours_p80 = total_hours_p50 + (_Z_P80 * notes_sigma_total)
        total_hours_p90 = total_hours_p50 + (_Z_P90 * notes_sigma_total)

        cve_hours_p50 = total_hours_p50 * cve_ratio
        cve_hours_p80 = total_hours_p80 * cve_ratio
        cve_hours_p90 = total_hours_p90 * cve_ratio

        labor_p50 = (total_hours_p50 * senior_rate) + (cve_hours_p50 * cve_rate)
        labor_p80 = (total_hours_p80 * senior_rate) + (cve_hours_p80 * cve_rate)
        labor_p90 = (total_hours_p90 * senior_rate) + (cve_hours_p90 * cve_rate)

        rework_factor = _ONE + (rework_pct / _HUNDRED)
        rework_reserve_p80 = labor_p80 * (rework_pct / _HUNDRED)

        total_cost_p50 = (labor_p50 * rework_factor) + surcharge
        total_cost_p80 = labor_p80 + rework_reserve_p80 + surcharge
        total_cost_p90 = (labor_p90 * rework_factor) + surcharge

        price_p50 = total_cost_p50 / margin_denom
        price_p80 = total_cost_p80 / margin_denom
        price_p90 = total_cost_p90 / margin_denom

        achieved_margin = (
            ((price_p80 - total_cost_p80) / price_p80) * _HUNDRED if price_p80 > 0 else Decimal("0")
        )

    outputs = {
        "pert_expected_hours_per_note": format_quantum(pert_expected, quantum),
        "pert_stddev_hours_per_note": format_quantum(pert_stddev, quantum),
        "total_engineering_hours_p50": format_quantum(total_hours_p50, quantum),
        "total_engineering_hours_p80": format_quantum(total_hours_p80, quantum),
        "total_engineering_hours_p90": format_quantum(total_hours_p90, quantum),
        "cve_review_hours": format_quantum(cve_hours_p80, quantum),
        "labor_cost_p50_eur": format_quantum(labor_p50, quantum),
        "labor_cost_p80_eur": format_quantum(labor_p80, quantum),
        "rework_reserve_eur": format_quantum(rework_reserve_p80, quantum),
        "total_cost_p80_eur": format_quantum(total_cost_p80, quantum),
        "quoted_price_p50_eur": format_quantum(price_p50, quantum),
        "quoted_price_p80_eur": format_quantum(price_p80, quantum),
        "quoted_price_p90_eur": format_quantum(price_p90, quantum),
        "achieved_margin_pct": format_quantum(achieved_margin, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={
            "pert_spread_p90_minus_p50_eur": format_quantum(price_p90 - price_p50, quantum),
            "fem_total_hours": format_quantum(fem_total_hours, quantum),
        },
    )


def run_rotorcraft_archetype_quote(
    inputs: dict[str, Any],
    card: dict[str, Any],
) -> dict[str, Any]:
    """Compute Decimal effort, Part 21 CVE floor, overhead, contingency, and tranche split."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(str(card["quantum"]))
    limits = card["limits"]

    cad_h = parse_limited_decimal(inputs["cad_hours"], limits["cad_hours"])
    loads_h = parse_limited_decimal(inputs["loads_hours"], limits["loads_hours"])
    stress_h = parse_limited_decimal(inputs["stress_hours"], limits["stress_hours"])
    fdt_dyn_h = parse_limited_decimal(inputs["fdt_dyn_hours"], limits["fdt_dyn_hours"])
    systems_h = parse_limited_decimal(inputs["systems_hours"], limits["systems_hours"])
    test_h = parse_limited_decimal(inputs["test_hours"], limits["test_hours"])
    cve_h = parse_limited_decimal(inputs["cve_hours"], limits["cve_hours"])
    proto_h = parse_limited_decimal(inputs["proto_hours"], limits["proto_hours"])

    cad_r = parse_limited_decimal(inputs["cad_rate"], limits["cad_rate"])
    loads_r = parse_limited_decimal(inputs["loads_rate"], limits["loads_rate"])
    stress_r = parse_limited_decimal(inputs["stress_rate"], limits["stress_rate"])
    fdt_dyn_r = parse_limited_decimal(inputs["fdt_dyn_rate"], limits["fdt_dyn_rate"])
    systems_r = parse_limited_decimal(inputs["systems_rate"], limits["systems_rate"])
    test_r = parse_limited_decimal(inputs["test_rate"], limits["test_rate"])
    cve_r = parse_limited_decimal(inputs["cve_rate"], limits["cve_rate"])
    proto_r = parse_limited_decimal(inputs["proto_rate"], limits["proto_rate"])

    cert_factor = parse_limited_decimal(inputs["cert_basis_factor"], limits["cert_basis_factor"])
    mat_factor = parse_limited_decimal(
        inputs["material_complexity_factor"], limits["material_complexity_factor"]
    )
    cosysmo_factor = parse_limited_decimal(
        inputs["cosysmo_driver_factor"], limits["cosysmo_driver_factor"]
    )
    pvt_factor = parse_limited_decimal(
        inputs["pvt_compression_factor"], limits["pvt_compression_factor"]
    )

    hpc_h = parse_limited_decimal(inputs["hpc_hours"], limits["hpc_hours"])
    hpc_r = parse_limited_decimal(inputs["hpc_rate"], limits["hpc_rate"])
    travel_hw = parse_limited_decimal(inputs["travel_hardware_eur"], limits["travel_hardware_eur"])
    overhead_pct = parse_limited_decimal(inputs["overhead_pct"], limits["overhead_pct"])
    contingency_pct = parse_limited_decimal(inputs["contingency_pct"], limits["contingency_pct"])
    margin_pct = parse_limited_decimal(inputs["margin_pct"], limits["margin_pct"])
    fixed_share_pct = parse_limited_decimal(
        inputs["fixed_price_share_pct"], limits["fixed_price_share_pct"]
    )
    cve_min_ratio_pct = parse_limited_decimal(
        inputs["cve_min_ratio_pct"], limits["cve_min_ratio_pct"]
    )

    raw_hours_total = cad_h + loads_h + stress_h + fdt_dyn_h + systems_h + test_h + cve_h + proto_h
    if raw_hours_total <= 0:
        raise AbstainError("outside_validity")

    with localcontext() as ctx:
        ctx.prec = 50
        margin_denom = _ONE - (margin_pct / _HUNDRED)
        if margin_denom <= 0:
            raise AbstainError("outside_validity")

        core_eng_scale = cert_factor * mat_factor * cosysmo_factor
        cad_s = cad_h * core_eng_scale
        loads_s = loads_h * core_eng_scale
        stress_s = stress_h * core_eng_scale
        fdt_dyn_s = fdt_dyn_h * core_eng_scale
        systems_s = systems_h * core_eng_scale
        test_s = test_h * cert_factor * pvt_factor
        proto_s = proto_h * mat_factor

        scaled_eng_hours = cad_s + loads_s + stress_s + fdt_dyn_s + systems_s + test_s + proto_s
        if scaled_eng_hours <= 0:
            raise AbstainError("outside_validity")

        cve_input_scaled = cve_h * cert_factor * cosysmo_factor
        cve_floor = scaled_eng_hours * (cve_min_ratio_pct / _HUNDRED)
        cve_floor_enforced = cve_input_scaled < cve_floor
        cve_scaled_hours = cve_floor if cve_floor_enforced else cve_input_scaled

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
        overhead_eur = direct_cost * (overhead_pct / _HUNDRED)
        contingency_eur = (direct_cost + overhead_eur) * (contingency_pct / _HUNDRED)
        total_cost = direct_cost + overhead_eur + contingency_eur

        quote_price = total_cost / margin_denom
        margin_eur = quote_price - total_cost
        fixed_tranche = quote_price * (fixed_share_pct / _HUNDRED)
        capped_tm_tranche = quote_price - fixed_tranche
        cve_share_pct = (cve_scaled_hours / total_scaled_hours) * _HUNDRED
        gross_margin_pct = (
            (margin_eur / quote_price) * _HUNDRED if quote_price > 0 else Decimal("0")
        )

    outputs = {
        "raw_hours_total": format_quantum(raw_hours_total, quantum),
        "scaled_engineering_hours": format_quantum(scaled_eng_hours, quantum),
        "cve_scaled_hours": format_quantum(cve_scaled_hours, quantum),
        "total_scaled_hours": format_quantum(total_scaled_hours, quantum),
        "blended_hourly_rate_eur": format_quantum(blended_rate, quantum),
        "direct_labor_cost_eur": format_quantum(direct_labor, quantum),
        "hpc_compute_cost_eur": format_quantum(hpc_cost, quantum),
        "direct_cost_eur": format_quantum(direct_cost, quantum),
        "overhead_eur": format_quantum(overhead_eur, quantum),
        "contingency_eur": format_quantum(contingency_eur, quantum),
        "total_cost_eur": format_quantum(total_cost, quantum),
        "margin_eur": format_quantum(margin_eur, quantum),
        "quote_price_eur": format_quantum(quote_price, quantum),
        "fixed_price_tranche_eur": format_quantum(fixed_tranche, quantum),
        "capped_tm_tranche_eur": format_quantum(capped_tm_tranche, quantum),
        "cve_share_pct": format_quantum(cve_share_pct, quantum),
        "gross_margin_pct": format_quantum(gross_margin_pct, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={
            "cve_floor_enforced": cve_floor_enforced,
            "core_engineering_scale_factor": format_quantum(core_eng_scale, quantum),
        },
    )


def run_rotorcraft_historical_calibration(
    inputs: dict[str, Any],
    card: dict[str, Any],
) -> dict[str, Any]:
    """Calibrate prior PERT triples with empirical P10/P50/P90 burned hours and IDP features."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(str(card["quantum"]))
    limits = card["limits"]

    prior_opt = parse_limited_decimal(
        inputs["prior_optimistic_hours"], limits["prior_optimistic_hours"]
    )
    prior_ml = parse_limited_decimal(
        inputs["prior_most_likely_hours"], limits["prior_most_likely_hours"]
    )
    prior_pess = parse_limited_decimal(
        inputs["prior_pessimistic_hours"], limits["prior_pessimistic_hours"]
    )
    emp_p10 = parse_limited_decimal(inputs["empirical_p10_hours"], limits["empirical_p10_hours"])
    emp_p50 = parse_limited_decimal(inputs["empirical_p50_hours"], limits["empirical_p50_hours"])
    emp_p90 = parse_limited_decimal(inputs["empirical_p90_hours"], limits["empirical_p90_hours"])

    if prior_opt > prior_ml or prior_ml > prior_pess:
        raise AbstainError("outside_validity")
    if emp_p10 > emp_p50 or emp_p50 > emp_p90:
        raise AbstainError("outside_validity")

    sample_n = parse_limited_decimal(inputs["sample_size"], limits["sample_size"])
    full_n = parse_limited_decimal(inputs["credibility_full_n"], limits["credibility_full_n"])
    overrun_ratio = parse_limited_decimal(
        inputs["historical_overrun_ratio"], limits["historical_overrun_ratio"]
    )
    feat_factor = parse_limited_decimal(
        inputs["idp_feature_complexity_factor"], limits["idp_feature_complexity_factor"]
    )
    base_cont_pct = parse_limited_decimal(
        inputs["base_contingency_pct"], limits["base_contingency_pct"]
    )
    broken_rate_pct = parse_limited_decimal(
        inputs["broken_assumption_rate_pct"], limits["broken_assumption_rate_pct"]
    )

    two = Decimal("2")
    quarter = Decimal("0.250")

    with localcontext() as ctx:
        ctx.prec = 50
        cred_w = _ONE if sample_n >= full_n else (sample_n / full_n)
        one_minus_w = _ONE - cred_w

        cal_opt = ((one_minus_w * prior_opt) + (cred_w * emp_p10)) * feat_factor
        ml_overrun_blend = (_ONE + overrun_ratio) / two
        cal_ml = ((one_minus_w * prior_ml) + (cred_w * emp_p50)) * feat_factor * ml_overrun_blend
        cal_pess = ((one_minus_w * prior_pess) + (cred_w * emp_p90)) * feat_factor * overrun_ratio

        if cal_opt > cal_ml or cal_ml > cal_pess:
            raise AbstainError("outside_validity")

        cal_expected = (cal_opt + (_FOUR * cal_ml) + cal_pess) / _SIX
        cal_sigma = (cal_pess - cal_opt) / _SIX
        cal_p80 = cal_expected + (_Z_P80 * cal_sigma)
        cal_p90 = cal_expected + (_Z_P90 * cal_sigma)
        cal_cont_pct = base_cont_pct + (cred_w * broken_rate_pct * quarter)

        prior_expected = (prior_opt + (_FOUR * prior_ml) + prior_pess) / _SIX
        drift_pct = (
            ((cal_expected - prior_expected) / prior_expected) * _HUNDRED
            if prior_expected > 0
            else Decimal("0")
        )

    outputs = {
        "credibility_weight": format_quantum(cred_w, quantum),
        "calibrated_optimistic_hours": format_quantum(cal_opt, quantum),
        "calibrated_most_likely_hours": format_quantum(cal_ml, quantum),
        "calibrated_pessimistic_hours": format_quantum(cal_pess, quantum),
        "calibrated_pert_expected_hours": format_quantum(cal_expected, quantum),
        "calibrated_pert_p80_hours": format_quantum(cal_p80, quantum),
        "calibrated_pert_p90_hours": format_quantum(cal_p90, quantum),
        "calibrated_contingency_pct": format_quantum(cal_cont_pct, quantum),
        "prior_vs_calibrated_drift_pct": format_quantum(drift_pct, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={
            "prior_pert_expected_hours": format_quantum(prior_expected, quantum),
            "calibrated_sigma_hours": format_quantum(cal_sigma, quantum),
        },
    )


def run_aerospace_multiyear_cashflow_learning(
    inputs: dict[str, Any],
    card: dict[str, Any],
) -> dict[str, Any]:
    """Compute Wright/Crawford learning curves, multi-year inflation, cashflow, WC cost & NPV."""
    _require_fields(inputs, list(card["required"]))
    quantum = Decimal(str(card["quantum"]))
    limits = card["limits"]

    t1 = parse_limited_decimal(inputs["first_unit_cost_eur"], limits["first_unit_cost_eur"])
    unit_count = parse_limited_decimal(inputs["unit_count"], limits["unit_count"])
    lr_pct = parse_limited_decimal(inputs["learning_rate_pct"], limits["learning_rate_pct"])
    crawford_w_pct = parse_limited_decimal(
        inputs["crawford_weight_pct"], limits["crawford_weight_pct"]
    )
    program_years = parse_limited_decimal(inputs["program_years"], limits["program_years"])
    inf_pct = parse_limited_decimal(inputs["annual_inflation_pct"], limits["annual_inflation_pct"])
    target_margin_pct = parse_limited_decimal(
        inputs["target_margin_pct"], limits["target_margin_pct"]
    )
    wacc_pct = parse_limited_decimal(inputs["wacc_annual_pct"], limits["wacc_annual_pct"])
    pay_days = parse_limited_decimal(inputs["payment_terms_days"], limits["payment_terms_days"])

    m_ko = parse_limited_decimal(inputs["milestone_ko_pct"], limits["milestone_ko_pct"])
    m_pdr = parse_limited_decimal(inputs["milestone_pdr_pct"], limits["milestone_pdr_pct"])
    m_cdr = parse_limited_decimal(inputs["milestone_cdr_pct"], limits["milestone_cdr_pct"])
    m_test = parse_limited_decimal(inputs["milestone_test_pct"], limits["milestone_test_pct"])
    m_cve = parse_limited_decimal(inputs["milestone_cve_pct"], limits["milestone_cve_pct"])

    for int_val in (unit_count, program_years, pay_days):
        if int_val != int_val.to_integral_value():
            raise AbstainError("outside_validity")

    n_units = int(unit_count)
    n_years = int(program_years)
    n_days = int(pay_days)
    milestone_sum = m_ko + m_pdr + m_cdr + m_test + m_cve
    if (milestone_sum - _HUNDRED).copy_abs() > Decimal("0.01"):
        raise AbstainError("outside_validity")

    two = Decimal("2")
    twelve = Decimal("12")
    zero = Decimal("0")
    ln_two = two.ln()

    with localcontext() as ctx:
        ctx.prec = 50
        margin_denom = _ONE - (target_margin_pct / _HUNDRED)
        if margin_denom <= zero:
            raise AbstainError("outside_validity")

        lr_ratio = lr_pct / _HUNDRED
        b_exp = lr_ratio.ln() / ln_two

        n_dec = Decimal(n_units)
        wright_cum_avg = t1 * (b_exp * n_dec.ln()).exp() if n_units > 1 else t1
        wright_total = n_dec * wright_cum_avg
        if n_units > 1:
            n_prev = Decimal(n_units - 1)
            wright_prev_total = n_prev * t1 * (b_exp * n_prev.ln()).exp()
            wright_last = wright_total - wright_prev_total
        else:
            wright_last = t1

        crawford_total = zero
        crawford_last = t1
        for k in range(1, n_units + 1):
            u_cost = t1 * (b_exp * Decimal(k).ln()).exp() if k > 1 else t1
            crawford_total += u_cost
            crawford_last = u_cost

        w_crawford = crawford_w_pct / _HUNDRED
        active_base = ((_ONE - w_crawford) * wright_total) + (w_crawford * crawford_total)

        inf_rate = inf_pct / _HUNDRED
        annual_base = active_base / Decimal(n_years)
        year_costs: list[Decimal] = []
        annual_schedule: list[dict[str, str]] = []
        for y in range(n_years):
            esc_factor_y = (_ONE + inf_rate) ** y
            y_cost = annual_base * esc_factor_y
            year_costs.append(y_cost)
            annual_schedule.append(
                {
                    "year_index": str(y + 1),
                    "year_label": f"Y{y + 1}",
                    "base_cost_eur": format_quantum(annual_base, quantum),
                    "escalation_factor": format_quantum(esc_factor_y, Decimal("0.000001")),
                    "escalated_cost_eur": format_quantum(y_cost, quantum),
                }
            )

        escalated_total = sum(year_costs, zero)
        inflation_escalation = escalated_total - active_base
        eff_escalation_factor = escalated_total / active_base if active_base > zero else _ONE
        quoted_price = escalated_total / margin_denom

        total_program_months = 12 * n_years
        lag_months = (n_days + 29) // 30
        horizon_months = total_program_months + lag_months

        outflows: list[Decimal] = [zero] * (horizon_months + 1)
        inflows: list[Decimal] = [zero] * (horizon_months + 1)
        for m in range(1, total_program_months + 1):
            y_idx = (m - 1) // 12
            outflows[m] = year_costs[y_idx] / twelve

        milestone_specs = (
            ("KO", 1, m_ko),
            ("PDR", max(1, (total_program_months * 25 + 50) // 100), m_pdr),
            ("CDR", max(1, (total_program_months * 50 + 50) // 100), m_cdr),
            ("Test", max(1, (total_program_months * 80 + 50) // 100), m_test),
            ("CVE_Signoff", total_program_months, m_cve),
        )
        milestone_events: list[dict[str, str]] = []
        for m_name, bill_m, pct in milestone_specs:
            cash_m = bill_m + lag_months
            amt = quoted_price * (pct / _HUNDRED)
            inflows[cash_m] += amt
            milestone_events.append(
                {
                    "milestone": m_name,
                    "billing_month": str(bill_m),
                    "cash_receipt_month": str(cash_m),
                    "share_pct": format_quantum(pct, Decimal("0.01")),
                    "amount_eur": format_quantum(amt, quantum),
                }
            )

        r_month = wacc_pct / Decimal("1200")
        cum_cash = zero
        peak_negative = zero
        wc_financing_cost = zero
        npv = zero
        monthly_schedule: list[dict[str, str]] = []

        for m in range(1, horizon_months + 1):
            net_m = inflows[m] - outflows[m]
            cum_cash += net_m
            deficit = -cum_cash if cum_cash < zero else zero
            if deficit > peak_negative:
                peak_negative = deficit
            fin_m = deficit * r_month
            wc_financing_cost += fin_m
            disc = (_ONE + r_month) ** m
            npv += net_m / disc
            monthly_schedule.append(
                {
                    "month": str(m),
                    "outflow_eur": format_quantum(outflows[m], quantum),
                    "inflow_eur": format_quantum(inflows[m], quantum),
                    "net_cashflow_eur": format_quantum(net_m, quantum),
                    "cumulative_cashflow_eur": format_quantum(cum_cash, quantum),
                    "working_capital_interest_eur": format_quantum(fin_m, quantum),
                }
            )

        net_margin_eur = quoted_price - escalated_total - wc_financing_cost
        net_margin_pct = (net_margin_eur / quoted_price) * _HUNDRED if quoted_price > zero else zero

    outputs = {
        "learning_exponent_b": format_quantum(b_exp, Decimal("0.000001")),
        "wright_cumulative_avg_unit_cost_eur": format_quantum(wright_cum_avg, quantum),
        "wright_total_base_cost_eur": format_quantum(wright_total, quantum),
        "wright_last_unit_cost_eur": format_quantum(wright_last, quantum),
        "crawford_total_base_cost_eur": format_quantum(crawford_total, quantum),
        "crawford_last_unit_cost_eur": format_quantum(crawford_last, quantum),
        "active_base_total_cost_eur": format_quantum(active_base, quantum),
        "inflation_escalation_eur": format_quantum(inflation_escalation, quantum),
        "effective_escalation_factor": format_quantum(eff_escalation_factor, Decimal("0.000001")),
        "escalated_total_cost_eur": format_quantum(escalated_total, quantum),
        "quoted_price_eur": format_quantum(quoted_price, quantum),
        "peak_negative_cashflow_eur": format_quantum(peak_negative, quantum),
        "working_capital_financing_cost_eur": format_quantum(wc_financing_cost, quantum),
        "net_present_value_eur": format_quantum(npv, quantum),
        "net_margin_after_financing_eur": format_quantum(net_margin_eur, quantum),
        "net_margin_after_financing_pct": format_quantum(net_margin_pct, quantum),
    }
    return _wrap_result(
        card,
        outputs,
        diagnostics={
            "unit_count": str(n_units),
            "program_years": str(n_years),
            "payment_lag_months": str(lag_months),
            "annual_escalation_schedule": annual_schedule,
            "milestone_billing_schedule": milestone_events,
            "monthly_cashflow_schedule": monthly_schedule,
        },
    )
