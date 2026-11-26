"""Deterministic CS-27/CS-29 Structural Load-Case Envelope Combination Engine.

Computes exact Decimal superpositions across multi-subcase flight, ground, thermal,
ditching, and crash load conditions against direct or MMPDS-16/CMH-17 Arb-bounded
allowables, identifies governing load combinations per component, seals an advisory
record into the SHA-256 Merkle Ledger, and exports native live-formula .xlsx plus
Ed25519 DSSE & ISO QR signed PDF dossiers.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pymupdf
from evidence_calc.allowables import lookup_allowable
from evidence_calc.quantize import format_quantum
from evidence_kernel.attestation import sign_attestation_dsse
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record
from evidence_kernel.qrcode_iso import render_qr_png
from openpyxl import Workbook

from evidence_coverage.pdf_report import _DSSE_ATTACHMENT_NAME, _PUBKEY_ATTACHMENT_NAME
from evidence_coverage.quotation_exporter import (
    _ACCENT_FILL,
    _BOLD_FONT,
    _TITLE_FONT,
    _autofit_columns,
    _num_val,
    _resolve_signing_keypair,
    _sanitize_excel_text,
    _style_header_row,
)

ASSISTANCE_DISCLAIMER = "This tool assists a human reviewer. It does not determine compliance."
_Q2 = Decimal("0.01")
_Q4 = Decimal("0.0001")
_THREE = Decimal("3")
_FOUR = Decimal("4")
_HALF = Decimal("0.5")
_ONE = Decimal("1")
_ZERO = Decimal("0")


def _dec(val: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(val))
    except Exception as exc:
        raise ValueError(f"invalid_decimal:{name}") from exc
    if not d.is_finite():
        raise ValueError(f"non_finite:{name}")
    return d


def default_cs29_load_envelope_payload() -> dict[str, Any]:
    """Return a realistic baseline CS-29 rotorcraft load-case envelope specification."""
    return {
        "envelope_id": "ENV-H145-CS29-001",
        "basic_subcases": {
            "HOVER_1G": {
                "COMP-FRAME-220": {"sx_mpa": "42.0", "sy_mpa": "14.0", "txy_mpa": "18.5"},
                "COMP-SKID-FWD": {"sx_mpa": "36.0", "sy_mpa": "-12.0", "txy_mpa": "21.0"},
                "COMP-BOOM-SPLICE": {"sx_mpa": "58.0", "sy_mpa": "9.0", "txy_mpa": "31.0"},
            },
            "PULLUP_3G5": {
                "COMP-FRAME-220": {"sx_mpa": "72.0", "sy_mpa": "22.0", "txy_mpa": "29.0"},
                "COMP-SKID-FWD": {"sx_mpa": "48.0", "sy_mpa": "-15.0", "txy_mpa": "26.0"},
                "COMP-BOOM-SPLICE": {"sx_mpa": "84.0", "sy_mpa": "16.0", "txy_mpa": "41.0"},
            },
            "YAW_LAT": {
                "COMP-FRAME-220": {"sx_mpa": "25.0", "sy_mpa": "31.0", "txy_mpa": "44.0"},
                "COMP-SKID-FWD": {"sx_mpa": "62.0", "sy_mpa": "19.0", "txy_mpa": "38.0"},
                "COMP-BOOM-SPLICE": {"sx_mpa": "39.0", "sy_mpa": "-24.0", "txy_mpa": "52.0"},
            },
            "HARD_LAND": {
                "COMP-FRAME-220": {"sx_mpa": "64.0", "sy_mpa": "-28.0", "txy_mpa": "33.0"},
                "COMP-SKID-FWD": {"sx_mpa": "118.0", "sy_mpa": "-42.0", "txy_mpa": "46.0"},
                "COMP-BOOM-SPLICE": {"sx_mpa": "49.0", "sy_mpa": "11.0", "txy_mpa": "28.0"},
            },
        },
        "combinations": [
            {
                "combo_id": "LC-ULT-101",
                "description": "CS 29.337 Symmetric Pull-Up Ultimate",
                "basis": "ULTIMATE",
                "cs_reference": "CS 29.303 / 29.337",
                "safety_factor": "1.500",
                "fitting_factor": "1.150",
                "factors": {"HOVER_1G": "0.50", "PULLUP_3G5": "1.00", "YAW_LAT": "0.25"},
            },
            {
                "combo_id": "LC-ULT-102",
                "description": "CS 29.351 Yaw & Tailboom Side Gust Ultimate",
                "basis": "ULTIMATE",
                "cs_reference": "CS 29.351",
                "safety_factor": "1.500",
                "fitting_factor": "1.150",
                "factors": {"HOVER_1G": "0.80", "YAW_LAT": "1.10", "PULLUP_3G5": "0.35"},
            },
            {
                "combo_id": "LC-ULT-103",
                "description": "CS 29.473 / 29.725 Hard Skid Landing Reserve",
                "basis": "ULTIMATE",
                "cs_reference": "CS 29.725",
                "safety_factor": "1.500",
                "fitting_factor": "1.000",
                "factors": {"HOVER_1G": "0.33", "HARD_LAND": "1.00", "YAW_LAT": "0.20"},
            },
        ],
        "component_allowables": {
            "COMP-FRAME-220": {
                "component_name": "Main Cabin Frame STA 220",
                "material_lookup": {
                    "material_id": "AL-7075-T651",
                    "basis": "A",
                    "property_name": "fty_mpa",
                    "thickness_mm": "12.0",
                    "temp_c": "60",
                    "environment": "RTD",
                    "temp_uncertainty_c": "5",
                },
            },
            "COMP-SKID-FWD": {
                "component_name": "Skid Forward Cross-Tube Saddle",
                "material_lookup": {
                    "material_id": "TI-6AL-4V",
                    "basis": "A",
                    "property_name": "fty_mpa",
                    "thickness_mm": "8.0",
                    "temp_c": "60",
                    "environment": "RTD",
                    "temp_uncertainty_c": "5",
                },
            },
            "COMP-BOOM-SPLICE": {
                "component_name": "Tailboom Frame 4070 Splice",
                "material_lookup": {
                    "material_id": "15-5PH-H1025",
                    "basis": "A",
                    "property_name": "fty_mpa",
                    "thickness_mm": "6.0",
                    "temp_c": "75",
                    "environment": "RTD",
                    "temp_uncertainty_c": "5",
                },
            },
        },
    }


def _resolve_component_allowable(spec: dict[str, Any], comp_id: str) -> dict[str, Any]:
    comp_name = str(spec.get("component_name") or comp_id)
    mat_spec = spec.get("material_lookup")
    if isinstance(mat_spec, dict) and "material_id" in mat_spec:
        al = lookup_allowable(
            str(mat_spec["material_id"]),
            basis=str(mat_spec.get("basis", "A")),
            property_name=str(mat_spec.get("property_name", "fty_mpa")),
            thickness_mm=str(mat_spec.get("thickness_mm", "10")),
            temp_c=str(mat_spec.get("temp_c", "23")),
            environment=str(mat_spec.get("environment", "RTD")),
            include_intervals=True,
            temp_uncertainty_c=str(mat_spec.get("temp_uncertainty_c", "0")),
            thickness_uncertainty_mm=str(mat_spec.get("thickness_uncertainty_mm", "0")),
        )
        nom = Decimal(str(al["allowable_value_mpa"]))
        iv = (al.get("exact_intervals") or {}).get("allowable_value_mpa") or {}
        low = Decimal(str(iv.get("lower", al.get("certified_lower_bound_mpa", nom))))
        return {
            "component_id": comp_id,
            "component_name": comp_name,
            "allowable_mpa": nom,
            "allowable_arb_lower_mpa": min(nom, low),
            "material_id": str(al["material_id"]),
            "basis": str(al["basis"]),
            "catalog_sha256": str(al.get("catalog_sha256", "")),
        }
    if "allowable_mpa" not in spec:
        raise ValueError(f"missing_allowable:{comp_id}")
    nom = _dec(spec["allowable_mpa"], f"allowable_mpa:{comp_id}")
    if nom <= _ZERO:
        raise ValueError(f"non_positive_allowable:{comp_id}")
    return {
        "component_id": comp_id,
        "component_name": comp_name,
        "allowable_mpa": nom,
        "allowable_arb_lower_mpa": nom,
        "material_id": str(spec.get("material_id") or "DIRECT"),
        "basis": str(spec.get("basis") or "SPEC"),
        "catalog_sha256": "",
    }


def combine_structural_load_envelopes(
    envelope_id: str,
    basic_subcases: dict[str, dict[str, dict[str, Any]]],
    combinations: list[dict[str, Any]],
    component_allowables: dict[str, dict[str, Any]],
    *,
    ledger: Ledger | None = None,
    tenant_id: str = "demo",
    actor_id: str = "stress-office",
) -> dict[str, Any]:
    """Run exact Decimal linear load-case superposition across components and seal Ledger."""
    if not basic_subcases or not combinations or not component_allowables:
        raise ValueError("empty_load_envelope_inputs")

    resolved_allowables = {
        comp_id: _resolve_component_allowable(spec, comp_id)
        for comp_id, spec in sorted(component_allowables.items())
    }

    matrix_rows: list[dict[str, Any]] = []
    per_component: dict[str, dict[str, Any]] = {}
    global_min_ms: Decimal | None = None
    global_gov_comp = ""
    global_gov_combo = ""

    with localcontext() as ctx:
        ctx.prec = 55
        for comp_id, al_info in resolved_allowables.items():
            best_row: dict[str, Any] | None = None
            comp_min_ms: Decimal | None = None
            comp_min_arb_ms: Decimal | None = None

            for combo in combinations:
                combo_id = str(combo["combo_id"])
                sf = _dec(combo.get("safety_factor", "1.500"), f"safety_factor:{combo_id}")
                ff = _dec(combo.get("fitting_factor", "1.000"), f"fitting_factor:{combo_id}")
                if sf <= _ZERO or ff <= _ZERO:
                    raise ValueError(f"invalid_factor:{combo_id}")
                factors = dict(combo.get("factors") or {})
                if not factors:
                    raise ValueError(f"empty_combo_factors:{combo_id}")

                sx = _ZERO
                sy = _ZERO
                txy = _ZERO
                for sub_id, mult_raw in factors.items():
                    if sub_id not in basic_subcases:
                        raise ValueError(f"unknown_subcase:{sub_id}")
                    comp_sub = basic_subcases[sub_id].get(comp_id)
                    if not isinstance(comp_sub, dict):
                        raise ValueError(f"missing_component_in_subcase:{sub_id}:{comp_id}")
                    mult = _dec(mult_raw, f"factor:{combo_id}:{sub_id}")
                    sx += mult * _dec(comp_sub["sx_mpa"], f"sx:{sub_id}:{comp_id}")
                    sy += mult * _dec(comp_sub["sy_mpa"], f"sy:{sub_id}:{comp_id}")
                    txy += mult * _dec(comp_sub["txy_mpa"], f"txy:{sub_id}:{comp_id}")

                mean_s = (sx + sy) * _HALF
                diff_half = (sx - sy) * _HALF
                radius = ((diff_half * diff_half) + (txy * txy)).sqrt()
                sigma_1 = mean_s + radius
                sigma_2 = mean_s - radius
                sigma_vm = ((sx * sx) - (sx * sy) + (sy * sy) + (_THREE * txy * txy)).sqrt()
                factored_demand = sigma_vm * sf * ff

                if factored_demand <= _ZERO:
                    rf = Decimal("999.0000")
                    ms = Decimal("998.0000")
                    ms_arb = ms
                else:
                    rf = al_info["allowable_mpa"] / factored_demand
                    ms = rf - _ONE
                    ms_arb = (al_info["allowable_arb_lower_mpa"] / factored_demand) - _ONE

                row = {
                    "component_id": comp_id,
                    "component_name": al_info["component_name"],
                    "combo_id": combo_id,
                    "combo_description": str(combo.get("description") or combo_id),
                    "basis": str(combo.get("basis") or "ULTIMATE"),
                    "cs_reference": str(combo.get("cs_reference") or "CS 29.303"),
                    "safety_factor": format_quantum(sf, Decimal("0.001")),
                    "fitting_factor": format_quantum(ff, Decimal("0.001")),
                    "sx_mpa": format_quantum(sx, _Q2),
                    "sy_mpa": format_quantum(sy, _Q2),
                    "txy_mpa": format_quantum(txy, _Q2),
                    "sigma_1_mpa": format_quantum(sigma_1, _Q2),
                    "sigma_2_mpa": format_quantum(sigma_2, _Q2),
                    "tau_max_mpa": format_quantum(radius, _Q2),
                    "von_mises_mpa": format_quantum(sigma_vm, _Q2),
                    "factored_stress_mpa": format_quantum(factored_demand, _Q2),
                    "allowable_mpa": format_quantum(al_info["allowable_mpa"], _Q2),
                    "allowable_arb_lower_mpa": format_quantum(
                        al_info["allowable_arb_lower_mpa"], _Q2
                    ),
                    "material_id": al_info["material_id"],
                    "reserve_factor": format_quantum(rf, _Q4),
                    "margin_of_safety": format_quantum(ms, _Q4),
                    "arb_lower_ms": format_quantum(ms_arb, _Q4),
                    "margin_positive": ms >= _ZERO,
                }
                matrix_rows.append(row)

                if comp_min_ms is None or ms < comp_min_ms:
                    comp_min_ms = ms
                    comp_min_arb_ms = ms_arb
                    best_row = row
                if global_min_ms is None or ms < global_min_ms:
                    global_min_ms = ms
                    global_gov_comp = comp_id
                    global_gov_combo = combo_id

            assert best_row is not None and comp_min_ms is not None and comp_min_arb_ms is not None
            per_component[comp_id] = {
                "component_id": comp_id,
                "component_name": al_info["component_name"],
                "material_id": al_info["material_id"],
                "allowable_mpa": format_quantum(al_info["allowable_mpa"], _Q2),
                "governing_combo_id": best_row["combo_id"],
                "governing_cs_reference": best_row["cs_reference"],
                "governing_von_mises_mpa": best_row["von_mises_mpa"],
                "governing_factored_stress_mpa": best_row["factored_stress_mpa"],
                "governing_reserve_factor": best_row["reserve_factor"],
                "governing_ms": format_quantum(comp_min_ms, _Q4),
                "governing_arb_lower_ms": format_quantum(comp_min_arb_ms, _Q4),
                "margin_positive": comp_min_ms >= _ZERO,
            }

    passed_comp = sum(1 for item in per_component.values() if item["margin_positive"])
    failed_comp = len(per_component) - passed_comp
    gov_ms_str = format_quantum(global_min_ms or _ZERO, _Q4)
    overall_status = (
        "ALL_ENVELOPES_POSITIVE_MS" if failed_comp == 0 else "NEGATIVE_ENVELOPE_MARGIN_DETECTED"
    )

    digest_payload = {
        "envelope_id": envelope_id,
        "global_ms_min": gov_ms_str,
        "governing_component": global_gov_comp,
        "governing_combo_id": global_gov_combo,
        "matrix_count": len(matrix_rows),
        "components": list(per_component.values()),
    }
    env_sha = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    result: dict[str, Any] = {
        "label": "ASSUMPTION",
        "not_a_certification_method": True,
        "assistance_disclaimer": ASSISTANCE_DISCLAIMER,
        "envelope_id": envelope_id,
        "subcase_count": len(basic_subcases),
        "combination_count": len(combinations),
        "component_count": len(per_component),
        "evaluated_pairs_count": len(matrix_rows),
        "passed_component_count": passed_comp,
        "failed_component_count": failed_comp,
        "global_ms_min": gov_ms_str,
        "governing_component": global_gov_comp,
        "governing_combo_id": global_gov_combo,
        "overall_status": overall_status,
        "component_envelopes": list(per_component.values()),
        "combination_catalog": [
            {
                "combo_id": str(c["combo_id"]),
                "description": str(c.get("description") or c["combo_id"]),
                "basis": str(c.get("basis") or "ULTIMATE"),
                "cs_reference": str(c.get("cs_reference") or "CS 29.303"),
                "safety_factor": str(c.get("safety_factor", "1.500")),
                "fitting_factor": str(c.get("fitting_factor", "1.000")),
            }
            for c in combinations
        ],
        "matrix_rows": matrix_rows,
        "envelope_sha256": env_sha,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if ledger is not None:
        src_proj = project_source(
            f"load-env-{envelope_id}",
            f"https://aeroregu.local/envelopes/{envelope_id}",
            "ASSUMPTION",
        )
        env_rec = make_envelope(
            sources=[src_proj],
            method_version="load_envelope_combiner@1.0.0",
            inputs={
                "envelope_id": envelope_id,
                "component_count": str(len(per_component)),
                "combination_count": str(len(combinations)),
                "envelope_sha256": env_sha,
            },
            confidence="deterministic",
            result={
                "global_ms_min": gov_ms_str,
                "governing_component": global_gov_comp,
                "governing_combo_id": global_gov_combo,
                "overall_status": overall_status,
            },
        )
        ev_hash = record(
            ledger,
            {
                "event_type": "calc",
                "tenant_id": ledger.tenant_id,
                "actor_id": actor_id,
                "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "payload": {
                    "record_kind": "load_envelope_combination",
                    "envelope_id": envelope_id,
                    "global_ms_min": gov_ms_str,
                    "governing_component": global_gov_comp,
                    "governing_combo_id": global_gov_combo,
                    "overall_status": overall_status,
                    "envelope_sha256": env_sha,
                },
                "envelope": env_rec,
            },
        )
        result["ledger_event_hash"] = ev_hash
        result["merkle_root"] = ledger.merkle_root()
    else:
        result["merkle_root"] = env_sha

    return result


def export_load_envelope_xlsx(
    report: dict[str, Any],
    *,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export multi-tab live-formula Excel (.xlsx) Load-Case Envelope workbook (CWE-1236 safe)."""
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "1_Envelope_Summary"
    ws_comb = wb.create_sheet("2_Load_Combinations")
    ws_comp = wb.create_sheet("3_Component_Envelopes")
    ws_mat = wb.create_sheet("4_Full_Matrix")

    formula_count = 0

    # TAB 2: Load Combinations
    comb_hdr = [
        "Combo ID",
        "Description",
        "Basis",
        "CS Reference",
        "Safety Factor",
        "Fitting Factor",
    ]
    ws_comb.append(comb_hdr)
    _style_header_row(ws_comb, 1, len(comb_hdr))
    ws_comb.freeze_panes = "A2"
    for c in report.get("combination_catalog") or []:
        ws_comb.append(
            [
                _sanitize_excel_text(c.get("combo_id", "")),
                _sanitize_excel_text(c.get("description", "")),
                _sanitize_excel_text(c.get("basis", "")),
                _sanitize_excel_text(c.get("cs_reference", "")),
                _num_val(c.get("safety_factor")),
                _num_val(c.get("fitting_factor")),
            ]
        )
    _autofit_columns(ws_comb)

    # TAB 3: Component Governing Envelopes
    comp_hdr = [
        "Component ID",
        "Component Name",
        "Material",
        "Allowable (MPa)",
        "Governing Combo",
        "Factored Demand (MPa)",
        "Reserve Factor",
        "Governing MS",
        "Arb Lower MS",
        "Status",
    ]
    ws_comp.append(comp_hdr)
    _style_header_row(ws_comp, 1, len(comp_hdr))
    ws_comp.freeze_panes = "A2"
    comp_rows = list(report.get("component_envelopes") or [])
    for idx, item in enumerate(comp_rows, start=2):
        ws_comp.append(
            [
                _sanitize_excel_text(item.get("component_id", "")),
                _sanitize_excel_text(item.get("component_name", "")),
                _sanitize_excel_text(item.get("material_id", "")),
                _num_val(item.get("allowable_mpa")),
                _sanitize_excel_text(item.get("governing_combo_id", "")),
                _num_val(item.get("governing_factored_stress_mpa")),
                _num_val(item.get("governing_reserve_factor")),
                _num_val(item.get("governing_ms")),
                _num_val(item.get("governing_arb_lower_ms")),
                f'=IF(H{idx}>=0,"POSITIVE_MS","NEGATIVE_MS")',
            ]
        )
        formula_count += 1
        for c_i in (7, 8, 9):
            ws_comp.cell(row=idx, column=c_i).number_format = "0.0000"

    comp_last = max(2, 1 + len(comp_rows))
    comp_tot = comp_last + 1
    ws_comp.append(
        [
            "ENVELOPE MIN / SUMMARY",
            f"=COUNTA(A2:A{comp_last})",
            "",
            f"=MIN(D2:D{comp_last})",
            "",
            f"=MAX(F2:F{comp_last})",
            f"=MIN(G2:G{comp_last})",
            f"=MIN(H2:H{comp_last})",
            f"=MIN(I2:I{comp_last})",
            f'=IF(COUNTIF(J2:J{comp_last},"NEGATIVE_MS")>0,"NEGATIVE_FLAG","ALL_POSITIVE")',
        ]
    )
    formula_count += 7
    for c_i in range(1, len(comp_hdr) + 1):
        ws_comp.cell(row=comp_tot, column=c_i).font = _BOLD_FONT
        ws_comp.cell(row=comp_tot, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_comp)

    # TAB 4: Full Matrix
    mat_hdr = [
        "Component ID",
        "Combo ID",
        "Basis",
        "Sigma_x (MPa)",
        "Sigma_y (MPa)",
        "Tau_xy (MPa)",
        "Von Mises (MPa)",
        "Factored (MPa)",
        "Allowable (MPa)",
        "MS",
        "Gate",
    ]
    ws_mat.append(mat_hdr)
    _style_header_row(ws_mat, 1, len(mat_hdr))
    ws_mat.freeze_panes = "A2"
    mat_rows = list(report.get("matrix_rows") or [])
    for idx, m in enumerate(mat_rows, start=2):
        ws_mat.append(
            [
                _sanitize_excel_text(m.get("component_id", "")),
                _sanitize_excel_text(m.get("combo_id", "")),
                _sanitize_excel_text(m.get("basis", "")),
                _num_val(m.get("sx_mpa")),
                _num_val(m.get("sy_mpa")),
                _num_val(m.get("txy_mpa")),
                _num_val(m.get("von_mises_mpa")),
                _num_val(m.get("factored_stress_mpa")),
                _num_val(m.get("allowable_mpa")),
                _num_val(m.get("margin_of_safety")),
                f'=IF(J{idx}>=0,"PASS","NEGATIVE")',
            ]
        )
        formula_count += 1
        ws_mat.cell(row=idx, column=10).number_format = "0.0000"
    mat_last = max(2, 1 + len(mat_rows))
    ws_mat.append(
        [
            "MATRIX MIN MS",
            f"=COUNTA(A2:A{mat_last})",
            "",
            "",
            "",
            "",
            f"=MAX(G2:G{mat_last})",
            f"=MAX(H2:H{mat_last})",
            "",
            f"=MIN(J2:J{mat_last})",
            f'=COUNTIF(K2:K{mat_last},"NEGATIVE")',
        ]
    )
    formula_count += 5
    _autofit_columns(ws_mat)

    # TAB 1: Summary
    ws_sum.append(["AeroRegu — Structural Load-Case Envelope Combiner", "", ""])
    ws_sum["A1"].font = _TITLE_FONT
    ws_sum.append(["ADVISORY NOTICE", ASSISTANCE_DISCLAIMER, ""])
    ws_sum.append(["Metric", "Live Formula / Value", "Source"])
    _style_header_row(ws_sum, 3, 3)

    summary_rows = [
        ("Envelope ID", _sanitize_excel_text(report.get("envelope_id", "")), "Metadata"),
        ("Components Evaluated", f"='3_Component_Envelopes'!B{comp_tot}", "Live Envelopes"),
        ("Total (Comp x Combo) Pairs", f"='4_Full_Matrix'!B{mat_last + 1}", "Live Matrix"),
        (
            "Governing Component",
            _sanitize_excel_text(report.get("governing_component", "")),
            "Critical",
        ),
        (
            "Governing Load Combination",
            _sanitize_excel_text(report.get("governing_combo_id", "")),
            "Critical",
        ),
        ("Global Minimum MS", f"='3_Component_Envelopes'!H{comp_tot}", "Live Envelopes"),
        ("Minimum Arb Lower MS", f"='3_Component_Envelopes'!I{comp_tot}", "Live Arb"),
        ("Minimum Reserve Factor (RF)", f"='3_Component_Envelopes'!G{comp_tot}", "Live Envelopes"),
        ("Envelope Gate", f"='3_Component_Envelopes'!J{comp_tot}", "Live Gate"),
        ("Ledger Merkle Root", _sanitize_excel_text(report.get("merkle_root", "")), "Audit Trail"),
    ]
    for r_i, (lbl, val, src) in enumerate(summary_rows, start=4):
        ws_sum.append([lbl, val, src])
        if isinstance(val, str) and val.startswith("="):
            formula_count += 1
            ws_sum.cell(row=r_i, column=2).number_format = "0.0000"
    _autofit_columns(ws_sum)

    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()
    out_str: str | None = None
    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(xlsx_bytes)
        out_str = str(out_p)
    return {
        "xlsx_bytes": xlsx_bytes,
        "xlsx_sha256": hashlib.sha256(xlsx_bytes).hexdigest(),
        "sheet_names": wb.sheetnames,
        "formula_count": formula_count,
        "output_path": out_str,
    }


def export_load_envelope_pdf(
    report: dict[str, Any],
    *,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export Ed25519 DSSE + ISO QR signed PDF Load-Case Envelope report."""
    priv_pem, pub_pem = _resolve_signing_keypair(private_key_pem, public_key_pem)
    merkle = str(report.get("merkle_root") or report.get("envelope_sha256") or ("0" * 64))
    eid = str(report.get("envelope_id") or "ENV-CS29-001")

    attestation_payload = {
        "schema": "evidence-layer/load-envelope@1.0.0",
        "envelope_id": eid,
        "component_count": int(report.get("component_count") or 0),
        "combination_count": int(report.get("combination_count") or 0),
        "global_ms_min": str(report.get("global_ms_min") or "0.0000"),
        "governing_component": str(report.get("governing_component") or ""),
        "governing_combo_id": str(report.get("governing_combo_id") or ""),
        "overall_status": str(report.get("overall_status") or ""),
        "merkle_root": merkle,
    }
    dsse_envelope = sign_attestation_dsse(attestation_payload, priv_pem)
    dsse_bytes = json.dumps(dsse_envelope, sort_keys=True, indent=2).encode("utf-8")
    sig_raw = base64.b64decode(dsse_envelope["signatures"][0]["sig"])
    sig_sha256 = hashlib.sha256(sig_raw).hexdigest()

    qr_payload = "aeroregu-env:" + json.dumps(
        {
            "v": 1,
            "e": eid[:16],
            "m": merkle[:16],
            "s": sig_sha256[:16],
            "ms": str(report.get("global_ms_min") or "")[:10],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    qr_png = render_qr_png(qr_payload, scale=8, border=6)

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    banner_rgb = (15 / 255, 23 / 255, 42 / 255)
    page.draw_rect(pymupdf.Rect(32, 28, 563, 92), color=banner_rgb, fill=banner_rgb)
    page.insert_text(
        (44, 54),
        f"AeroRegu - Signed CS-29 Load Envelope Summary ({eid})",
        fontsize=12.5,
        color=(1, 1, 1),
    )
    page.insert_text((44, 74), ASSISTANCE_DISCLAIMER, fontsize=8.2, color=(0.82, 0.88, 0.96))
    page.insert_image(pymupdf.Rect(452, 108, 556, 212), stream=qr_png)

    lines = [
        f"Envelope ID: {eid}  |  Status: {report.get('overall_status')}",
        (
            f"Components: {report.get('component_count')}  |  "
            f"Combinations: {report.get('combination_count')}  |  "
            f"Pairs: {report.get('evaluated_pairs_count')}"
        ),
        (
            f"Global Min MS: {report.get('global_ms_min')} at "
            f"{report.get('governing_component')} ({report.get('governing_combo_id')})"
        ),
        f"Ledger Merkle Root: {merkle[:48]}...",
    ]
    y = 124
    for ln in lines:
        page.insert_text((38, y), ln[:92], fontsize=9.0, color=(0.1, 0.14, 0.22))
        y += 16

    y += 14
    page.insert_text((38, y), "Component Governing Load-Case Envelopes", fontsize=11.0)
    y += 16
    for comp in (report.get("component_envelopes") or [])[:24]:
        if y > 790:
            break
        rf_val = comp.get("reserve_factor", comp.get("governing_reserve_factor", ""))
        row_s = (
            f"{comp['component_id'][:18]} | Combo={comp['governing_combo_id'][:12]} | "
            f"Factored={comp['governing_factored_stress_mpa']} | Allow={comp['allowable_mpa']} | "
            f"RF={rf_val} | "
            f"MS={comp['governing_ms']} (ArbLo={comp['governing_arb_lower_ms']})"
        )
        page.insert_text((40, y), row_s[:95], fontsize=7.8, color=(0.14, 0.18, 0.26))
        y += 13

    doc.embfile_add(
        _DSSE_ATTACHMENT_NAME,
        dsse_bytes,
        filename=_DSSE_ATTACHMENT_NAME,
        desc="DSSE v1 Ed25519 Load-Case Envelope Attestation",
    )
    doc.embfile_add(
        _PUBKEY_ATTACHMENT_NAME,
        pub_pem,
        filename=_PUBKEY_ATTACHMENT_NAME,
        desc="Ed25519 Verification Public Key (PEM)",
    )
    doc.set_metadata(
        {
            "title": f"AeroRegu Signed Load Envelope ({eid})",
            "subject": f"merkle={merkle}",
            "keywords": qr_payload,
            "creator": "aeroregu-load-envelope-exporter",
        }
    )
    pdf_bytes = doc.tobytes(deflate=True)
    doc.close()

    out_str: str | None = None
    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(pdf_bytes)
        out_str = str(out_p)
    return {
        "pdf_bytes": pdf_bytes,
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "merkle_root": merkle,
        "qr_payload": qr_payload,
        "dsse_envelope": dsse_envelope,
        "public_key_pem": pub_pem.decode("ascii"),
        "output_path": out_str,
    }
