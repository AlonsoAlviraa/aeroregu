"""Deterministic adversarial numerical & engineering mutation fuzzer ("Red-Team de Calculo")."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.registry import list_method_ids, load_card, run_method
from evidence_calc.units import conversion_interval, units_compatible

UNIT_MUTATION_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("newton", "kilonewton", "kN_vs_N"),
    ("megapascal", "pound_force_per_square_inch", "psi_vs_MPa"),
    ("kilogram", "pound", "lb_vs_kg"),
    ("meter", "millimeter", "mm_vs_m"),
)

_MS_OUTPUT_KEYS = (
    "margin_of_safety",
    "combined_ms",
    "column_ms",
    "plate_ms",
    "fatigue_ms",
    "tsai_wu_ms",
    "hashin_ms",
)


def _extract_primary_ms(outputs: dict[str, Any]) -> Decimal | None:
    vals: list[Decimal] = []
    for key in _MS_OUTPUT_KEYS:
        if key in outputs and outputs[key] not in (None, ""):
            try:
                vals.append(Decimal(str(outputs[key])))
            except InvalidOperation:
                pass
    if vals:
        return min(vals)
    # Fallback heuristics for bolt_screen, hover_power_screen, rigid_body_point_mass
    if "utilization_ratio" in outputs:
        try:
            u = Decimal(str(outputs["utilization_ratio"]))
            if u > 0:
                return (Decimal("1") / u) - Decimal("1")
        except InvalidOperation:
            pass
    if "power_required_kw" in outputs and "power_available_kw" in outputs:
        try:
            req = Decimal(str(outputs["power_required_kw"]))
            avail = Decimal(str(outputs["power_available_kw"]))
            if req > 0:
                return (avail / req) - Decimal("1")
        except InvalidOperation:
            pass
    if "margin_kw" in outputs and "power_required_kw" in outputs:
        try:
            req = Decimal(str(outputs["power_required_kw"]))
            m = Decimal(str(outputs["margin_kw"]))
            if req > 0:
                return m / req
        except InvalidOperation:
            pass
    if "active_thrust_margin_n" in outputs and "required_vertical_n" in outputs:
        try:
            req = Decimal(str(outputs["required_vertical_n"]))
            margin = Decimal(str(outputs["active_thrust_margin_n"]))
            if abs(req) > 0:
                return margin / abs(req)
        except InvalidOperation:
            pass
    return None


def _run_safe(method_id: str, inputs: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        res = run_method(
            method_id,
            inputs,
            normalize_units=bool(inputs.get("_input_units")),
            include_intervals=False,
        )
        return res, None
    except AbstainError as exc:
        return None, exc.reason
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        return None, str(exc)


def _default_probe_inputs(method_id: str) -> dict[str, Any]:
    if method_id == "margin_of_safety":
        return {
            "applied_load_n": "12000.000",
            "allowable_load_n": "24000.000",
            "reserve_factor": "1.500",
            "fitting_factor": "1.150",
        }
    if method_id == "bolt_screen":
        return {
            "shear_force_n": "4500.000",
            "tensile_force_n": "3200.000",
            "area_mm2": "78.540",
            "shear_allowable_mpa": "180.000",
            "tensile_allowable_mpa": "260.000",
            "safety_factor": "1.500",
        }
    if method_id == "hover_power_screen":
        return {
            "thrust_n": "9500.000",
            "disk_area_m2": "12.500",
            "air_density_kg_m3": "1.225",
            "figure_of_merit": "0.700",
            "power_available_kw": "250.000",
        }
    if method_id == "rigid_body_point_mass":
        return {
            "mass_kg": "950.000",
            "load_factor": "1.000",
            "cg_x_m": "0.020",
            "unit_x_m": ["-1.200", "-1.200", "1.200", "1.200"],
            "unit_active": [True, True, True, True],
            "gravity_m_s2": "9.807",
        }
    if method_id == "column_plate_buckling":
        return {
            "applied_compression_n": "18000.000",
            "column_length_mm": "420.000",
            "end_fixity_k": "1.000",
            "area_mm2": "320.000",
            "inertia_mm4": "18500.000",
            "youngs_modulus_mpa": "71000.000",
            "yield_strength_mpa": "420.000",
            "poissons_ratio": "0.330",
            "plate_width_b_mm": "40.000",
            "plate_thickness_t_mm": "2.500",
        }
    if method_id == "palmgren_miner_fatigue":
        return {
            "block_applied_cycles": ["50000", "12000"],
            "block_allowable_cycles": ["200000", "45000"],
            "scatter_factor": "4.000",
        }
    if method_id == "composite_failure_criteria":
        return {
            "sigma_1_mpa": "320.000",
            "sigma_2_mpa": "18.000",
            "tau_12_mpa": "22.000",
            "xt_mpa": "1450.000",
            "xc_mpa": "1050.000",
            "yt_mpa": "52.000",
            "yc_mpa": "195.000",
            "s12_mpa": "68.000",
            "f12_star": "-0.500",
        }
    card = load_card(method_id)
    ex = card.get("examples")
    if isinstance(ex, list) and ex and isinstance(ex[0], dict):
        return dict(ex[0].get("inputs") or ex[0])
    return {}


def fuzz_method(
    method_id: str,
    base_inputs: dict[str, Any] | None = None,
    *,
    hot_wet_knockdown: Decimal = Decimal("0.78"),
) -> dict[str, Any]:
    """Run adversarial numerical, unit, sign, thermal & redundancy mutations against one card."""
    card = load_card(method_id)
    inputs = dict(base_inputs or _default_probe_inputs(method_id))
    input_units_spec: dict[str, str] = dict(card.get("input_units") or {})

    baseline_res, baseline_err = _run_safe(method_id, inputs)
    baseline_ms = _extract_primary_ms(baseline_res["outputs"]) if baseline_res is not None else None

    findings: list[dict[str, Any]] = []
    min_ms_seen: Decimal | None = baseline_ms

    # 1. Unit confusion probes (kN vs N, psi vs MPa, lb vs kg, mm vs m)
    for field_name, canonical_unit in input_units_spec.items():
        if field_name not in inputs:
            continue
        raw_val = inputs[field_name]
        if isinstance(raw_val, list):
            continue
        for left_u, right_u, label in UNIT_MUTATION_PAIRS:
            alt_unit: str | None = None
            if canonical_unit == left_u:
                alt_unit = right_u
            elif canonical_unit == right_u:
                alt_unit = left_u
            if alt_unit is None:
                continue
            factor = conversion_interval(alt_unit, canonical_unit)
            if not isinstance(factor, Decimal):
                continue

            # Probe A: Pass declared unit override -> engine MUST scale accurately or fail safely
            scaled_probe = dict(inputs)
            existing_overrides = dict(inputs.get("_input_units") or {})
            existing_overrides[field_name] = alt_unit
            scaled_probe["_input_units"] = existing_overrides
            probe_res, probe_err = _run_safe(method_id, scaled_probe)
            probe_ms = _extract_primary_ms(probe_res["outputs"]) if probe_res else None

            # Probe B: Check if cross-dimensional wrong unit raises AbstainError as expected
            # without omitting unit conversion or losing magnitude factor.
            incompatible_probe = dict(inputs)
            bad_overrides = dict(inputs.get("_input_units") or {})
            bad_overrides[field_name] = "kelvin" if canonical_unit != "kelvin" else "newton"
            incompatible_probe["_input_units"] = bad_overrides
            _, inc_err = _run_safe(method_id, incompatible_probe)

            guarded = inc_err in {"unit_mismatch", "missing_input_units"}
            distorted_ms = probe_ms is not None and (
                probe_ms < Decimal("0")
                or (baseline_ms is not None and abs(probe_ms - baseline_ms) > Decimal("0.20"))
            )
            if distorted_ms or not guarded:
                sev = "CRITICAL" if (probe_ms is not None and probe_ms < Decimal("0")) else "HIGH"
                if probe_ms is not None and (min_ms_seen is None or probe_ms < min_ms_seen):
                    min_ms_seen = probe_ms
                findings.append(
                    {
                        "attack_vector": f"unit_mutation:{label}",
                        "field": field_name,
                        "severity": sev,
                        "guarded_incompatible_unit": guarded,
                        "abstain_reason": probe_err or inc_err,
                        "baseline_ms": str(baseline_ms) if baseline_ms is not None else None,
                        "mutated_ms": str(probe_ms) if probe_ms is not None else None,
                        "conversion_factor": str(factor),
                        "before": {
                            "field": field_name,
                            "unit": canonical_unit,
                            "ms": str(baseline_ms),
                        },
                        "after": {
                            "field": field_name,
                            "mutated_unit": alt_unit,
                            "ms": str(probe_ms),
                        },
                        "summary": (
                            f"Unit confusion {label} on '{field_name}' drives MS to {probe_ms}"
                            if probe_ms is not None
                            else f"Unit guard triggered '{probe_err or inc_err}' on '{field_name}'"
                        ),
                    }
                )

    # 2. Moment & CG / Stress sign inversions
    sign_fields = [
        k
        for k in inputs
        if any(tok in k for tok in ("cg_", "moment", "sigma_", "tau_", "load_factor"))
        and not isinstance(inputs[k], list)
    ]
    for sf in sign_fields:
        try:
            val_dec = Decimal(str(inputs[sf]))
        except InvalidOperation:
            continue
        if val_dec == 0:
            continue
        flipped = dict(inputs)
        flipped[sf] = str(-val_dec)
        res_flip, err_flip = _run_safe(method_id, flipped)
        ms_flip = _extract_primary_ms(res_flip["outputs"]) if res_flip else None
        is_drop = ms_flip is not None and (
            ms_flip < Decimal("0")
            or (baseline_ms is not None and ms_flip < baseline_ms - Decimal("0.05"))
        )
        if is_drop or err_flip == "outside_validity":
            if ms_flip is not None and (min_ms_seen is None or ms_flip < min_ms_seen):
                min_ms_seen = ms_flip
            sev = "CRITICAL" if (ms_flip is not None and ms_flip < Decimal("0")) else "HIGH"
            findings.append(
                {
                    "attack_vector": "moment_sign_inversion",
                    "field": sf,
                    "severity": sev,
                    "abstain_reason": err_flip,
                    "baseline_ms": str(baseline_ms) if baseline_ms is not None else None,
                    "mutated_ms": str(ms_flip) if ms_flip is not None else None,
                    "before": {sf: str(val_dec), "ms": str(baseline_ms)},
                    "after": {sf: str(-val_dec), "ms": str(ms_flip)},
                    "summary": (
                        f"Sign inversion {sf}: {val_dec} -> {-val_dec} drops MS to {ms_flip}"
                        if ms_flip is not None
                        else f"Sign inversion {sf} caused outside_validity abstain"
                    ),
                }
            )

    # 3. Thermal / Hot-Wet Limit Knockdown (-55C / +85C material degradation + 1.5x limit spike)
    thermal_mutated = dict(inputs)
    thermal_changed = False
    for k, v in inputs.items():
        if isinstance(v, list):
            continue
        if any(
            tok in k
            for tok in (
                "allowable",
                "yield_strength",
                "youngs_modulus",
                "xt_",
                "xc_",
                "yt_",
                "yc_",
                "s12_",
            )
        ):
            try:
                thermal_mutated[k] = str(
                    (Decimal(str(v)) * hot_wet_knockdown).quantize(Decimal("0.001"))
                )
                thermal_changed = True
            except InvalidOperation:
                pass
        elif "load_factor" == k:
            thermal_mutated[k] = "3.500"
            thermal_changed = True
        elif "applied_load_n" == k or "applied_compression_n" == k or "thrust_n" == k:
            try:
                thermal_mutated[k] = str(
                    (Decimal(str(v)) * Decimal("1.35")).quantize(Decimal("0.001"))
                )
                thermal_changed = True
            except InvalidOperation:
                pass

    if thermal_changed:
        res_th, err_th = _run_safe(method_id, thermal_mutated)
        ms_th = _extract_primary_ms(res_th["outputs"]) if res_th else None
        if (ms_th is not None and ms_th < Decimal("0.15")) or err_th is not None:
            if ms_th is not None and (min_ms_seen is None or ms_th < min_ms_seen):
                min_ms_seen = ms_th
            sev = "CRITICAL" if (ms_th is not None and ms_th < Decimal("0")) or err_th else "HIGH"
            findings.append(
                {
                    "attack_vector": "thermal_hot_wet_limit",
                    "field": "environmental_knockdown",
                    "severity": sev,
                    "abstain_reason": err_th,
                    "baseline_ms": str(baseline_ms) if baseline_ms is not None else None,
                    "mutated_ms": str(ms_th) if ms_th is not None else None,
                    "before": {"condition": "RTD_ambient", "ms": str(baseline_ms)},
                    "after": {"condition": "HotWet_85C_knockdown_0.78", "ms": str(ms_th)},
                    "summary": (
                        f"Hot/Wet knockdown + load spike drops MS {baseline_ms} -> {ms_th}"
                        if ms_th is not None
                        else f"Hot/Wet knockdown hit limit ({err_th})"
                    ),
                }
            )

    # 4. Redundancy loss (OEI / station outage / non-redundant fitting factor)
    if "unit_active" in inputs and isinstance(inputs["unit_active"], list):
        active_list = list(inputs["unit_active"])
        if sum(1 for x in active_list if x) > 1:
            degraded = dict(inputs)
            first_true = active_list.index(True)
            active_list[first_true] = False
            degraded["unit_active"] = active_list
            degraded["load_factor"] = "2.500"
            res_oei, err_oei = _run_safe(method_id, degraded)
            ms_oei = _extract_primary_ms(res_oei["outputs"]) if res_oei else None
            if (ms_oei is not None and ms_oei < Decimal("0.10")) or err_oei is not None:
                if ms_oei is not None and (min_ms_seen is None or ms_oei < min_ms_seen):
                    min_ms_seen = ms_oei
                findings.append(
                    {
                        "attack_vector": "redundancy_loss_oei",
                        "field": "unit_active",
                        "severity": "CRITICAL",
                        "abstain_reason": err_oei,
                        "baseline_ms": str(baseline_ms) if baseline_ms is not None else None,
                        "mutated_ms": str(ms_oei) if ms_oei is not None else None,
                        "before": {"active_units": sum(1 for x in inputs["unit_active"] if x)},
                        "after": {
                            "active_units": sum(1 for x in active_list if x),
                            "load_factor": "2.500",
                        },
                        "summary": (
                            f"Loss of redundant unit #{first_true + 1} under 2.5g failed: "
                            f"{err_oei or ms_oei}"
                        ),
                    }
                )
    elif "fitting_factor" in inputs:
        degraded = dict(inputs)
        degraded["fitting_factor"] = "1.330"
        res_ff, err_ff = _run_safe(method_id, degraded)
        ms_ff = _extract_primary_ms(res_ff["outputs"]) if res_ff else None
        if (
            ms_ff is not None and (ms_ff < Decimal("0") or (baseline_ms and ms_ff < baseline_ms))
        ) or err_ff:
            if ms_ff is not None and (min_ms_seen is None or ms_ff < min_ms_seen):
                min_ms_seen = ms_ff
            findings.append(
                {
                    "attack_vector": "redundancy_loss_fitting_escalation",
                    "field": "fitting_factor",
                    "severity": "CRITICAL"
                    if (ms_ff is not None and ms_ff < Decimal("0"))
                    else "MEDIUM",
                    "abstain_reason": err_ff,
                    "baseline_ms": str(baseline_ms) if baseline_ms is not None else None,
                    "mutated_ms": str(ms_ff) if ms_ff is not None else None,
                    "before": {
                        "fitting_factor": str(inputs["fitting_factor"]),
                        "ms": str(baseline_ms),
                    },
                    "after": {"fitting_factor": "1.330", "ms": str(ms_ff)},
                    "summary": f"Casting/uncertain redundancy FF 1.330 drops MS to {ms_ff}",
                }
            )

    findings.sort(
        key=lambda f: (
            0 if f["severity"] == "CRITICAL" else (1 if f["severity"] == "HIGH" else 2),
            Decimal(str(f["mutated_ms"])) if f.get("mutated_ms") is not None else Decimal("-999"),
        )
    )
    return {
        "method_id": method_id,
        "baseline_error": baseline_err,
        "baseline_ms": str(baseline_ms) if baseline_ms is not None else None,
        "min_ms_found": str(min_ms_seen) if min_ms_seen is not None else None,
        "finding_count": len(findings),
        "critical_count": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "findings": findings,
    }


def fuzz_all_methods(method_ids: list[str] | None = None) -> dict[str, Any]:
    """Run deterministic adversarial mutation suites across selected or all registered cards."""
    targets = method_ids or list_method_ids()
    per_method: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    for mid in targets:
        report = fuzz_method(mid)
        per_method.append(report)
        for item in report["findings"]:
            all_findings.append({"method_id": mid, **item})

    all_findings.sort(
        key=lambda f: (
            0 if f["severity"] == "CRITICAL" else (1 if f["severity"] == "HIGH" else 2),
            Decimal(str(f["mutated_ms"])) if f.get("mutated_ms") is not None else Decimal("-999"),
        )
    )
    return {
        "methods_fuzzed": len(targets),
        "total_findings": len(all_findings),
        "critical_findings": sum(1 for f in all_findings if f["severity"] == "CRITICAL"),
        "per_method": per_method,
        "ranked_findings": all_findings,
    }


__all__ = ["UNIT_MUTATION_PAIRS", "fuzz_method", "fuzz_all_methods", "units_compatible"]
