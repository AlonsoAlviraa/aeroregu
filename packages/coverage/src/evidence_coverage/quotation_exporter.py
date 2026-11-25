"""Enterprise Quotation Exporter: Live-Formula Multi-Tab Excel (.xlsx) & Signed DSSE/QR PDF.

Produces OEM procurement-ready `.xlsx` workbooks with live Excel formulas (`=SUM`, `=IF`,
`=MIN`, `=MAX`, `=COUNTIF`, `=COUNTA`, cross-sheet references) and Ed25519 DSSE-signed PDF
dossiers with offline-verifiable ISO QR codes and visual `bbox` evidence thumbnails.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymupdf
from evidence_kernel.attestation import generate_ed25519_keypair, sign_attestation_dsse
from evidence_kernel.qrcode_iso import render_qr_png
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from evidence_coverage.pdf_report import (
    _DSSE_ATTACHMENT_NAME,
    _PUBKEY_ATTACHMENT_NAME,
    _render_bbox_thumbnail,
    verify_signed_pdf_report,
)

_HEADER_FILL = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
_SUBHEADER_FILL = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
_ACCENT_FILL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
_TITLE_FONT = Font(color="0F172A", bold=True, size=13)
_BOLD_FONT = Font(bold=True, size=10)


_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_excel_text(raw: Any) -> str:
    """Defend Excel cells against CWE-1236 CSV/spreadsheet formula injection."""
    text = str("" if raw is None else raw).replace("\x00", "")
    # Strip non-printable control chars (except tab/newline/CR) before neutralization check
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\t\n\r")
    if text and (
        text[0] in _FORMULA_INJECTION_PREFIXES or text.lstrip(" ")[0:1] in ("=", "+", "-", "@")
    ):
        return "'" + text
    return text


def _num_val(raw: Any, default: float = 0.0) -> float:
    try:
        return float(Decimal(str(raw)))
    except Exception:
        return default


def _style_header_row(ws: Any, row_idx: int, col_count: int) -> None:
    for col in range(1, col_count + 1):
        cell = ws.cell(row=row_idx, column=col)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _autofit_columns(ws: Any, *, min_width: int = 12, max_width: int = 44) -> None:
    for col_cells in ws.columns:
        col_letter = get_column_letter(col_cells[0].column)
        longest = 0
        for cell in col_cells:
            val_s = str(cell.value or "")
            if val_s.startswith("="):
                val_s = "123,456.78"
            longest = max(longest, len(val_s))
        ws.column_dimensions[col_letter].width = max(min_width, min(max_width, longest + 3))


def _normalize_wbs_dag(dossier: dict[str, Any]) -> dict[str, Any]:
    dag = dossier.get("composite_wbs_dag")
    if isinstance(dag, dict) and dag.get("nodes"):
        return dag
    arch = dossier.get("archetype") or {}
    det = dossier.get("deterministic_quote") or {}
    aid = str(arch.get("archetype_id") or "Q-STR-03")
    hrs = _num_val(det.get("total_scaled_hours") or 500)
    cost = _num_val(det.get("total_cost_eur") or 60000)
    price = _num_val(det.get("quote_price_eur") or 78000)
    dur = max(2.0, round(hrs / 100.0, 1))
    return {
        "node_count": 1,
        "edge_count": 0,
        "topological_order": [aid],
        "critical_path_archetypes": [aid],
        "project_duration_weeks": f"{dur:.1f}",
        "synergy_hours_saved": "0.000",
        "synergy_price_saved_eur": "0.000",
        "synergy_savings_pct": "0.00",
        "nodes": [
            {
                "archetype_id": aid,
                "family": arch.get("family") or "STRESS",
                "title": arch.get("title") or "Primary Rotorcraft Scope",
                "predecessors": [],
                "synergy_channels": [],
                "synergy_reduction_pct": "0.00",
                "standalone_hours": f"{hrs:.3f}",
                "net_hours": f"{hrs:.3f}",
                "net_cost_eur": f"{cost:.3f}",
                "net_price_eur": f"{price:.3f}",
                "duration_weeks": f"{dur:.1f}",
                "early_start_week": "0.0",
                "early_finish_week": f"{dur:.1f}",
                "late_start_week": "0.0",
                "late_finish_week": f"{dur:.1f}",
                "total_float_weeks": "0.0",
                "is_critical": True,
            }
        ],
    }


def _normalize_multiyear(dossier: dict[str, Any]) -> dict[str, Any]:
    my = dossier.get("multiyear_cashflow_learning")
    if isinstance(my, dict) and my.get("outputs"):
        return my
    pert = dossier.get("pert_envelope") or {}
    cost = _num_val(pert.get("cost_p80_eur") or 60000)
    price = _num_val(pert.get("price_p80_eur") or 78000)
    return {
        "inputs": {
            "first_unit_cost_eur": f"{cost:.3f}",
            "unit_count": "1",
            "learning_rate_pct": "85.000",
            "crawford_weight_pct": "50.000",
            "program_years": "1",
            "annual_inflation_pct": "3.200",
            "wacc_annual_pct": "7.500",
            "payment_terms_days": "30",
        },
        "outputs": {
            "learning_exponent_b": "-0.234465",
            "wright_total_base_cost_eur": f"{cost:.3f}",
            "crawford_total_base_cost_eur": f"{cost:.3f}",
            "active_base_total_cost_eur": f"{cost:.3f}",
            "escalated_total_cost_eur": f"{cost:.3f}",
            "quoted_price_eur": f"{price:.3f}",
            "peak_negative_cashflow_eur": f"{cost * 0.25:.3f}",
            "working_capital_financing_cost_eur": f"{cost * 0.01:.3f}",
            "net_present_value_eur": f"{(price - cost) * 0.92:.3f}",
            "net_margin_after_financing_pct": "21.000",
        },
        "diagnostics": {
            "annual_escalation_schedule": [
                {
                    "year_label": "Y1",
                    "base_cost_eur": f"{cost:.3f}",
                    "escalation_factor": "1.000000",
                    "escalated_cost_eur": f"{cost:.3f}",
                }
            ],
            "monthly_cashflow_schedule": [
                {
                    "month": str(m),
                    "outflow_eur": f"{cost / 12.0:.3f}",
                    "inflow_eur": f"{price * 0.30:.3f}" if m in (2, 7, 13) else "0.000",
                }
                for m in range(1, 14)
            ],
        },
    }


def export_quotation_xlsx(
    dossier: dict[str, Any],
    *,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate a live-formula 7-sheet Excel (.xlsx) workbook for OEM procurement review."""
    wb = Workbook()
    ws_exec = wb.active
    ws_exec.title = "Resumen Ejecutivo"
    ws_wbs = wb.create_sheet("WBS Multi-Arquetipo & CPM")
    ws_ctry = wb.create_sheet("Comparativa 9 Paises")
    ws_cf = wb.create_sheet("Flujo Caja & Aprendizaje")
    ws_asm = wb.create_sheet("Registro 45 Supuestos")
    ws_ctr = wb.create_sheet("Matriz Contractual")
    ws_knn = wb.create_sheet("Benchmark k-NN Historico")

    dag = _normalize_wbs_dag(dossier)
    my = _normalize_multiyear(dossier)
    comp = dossier.get("multi_country_comparison") or {
        "countries": [],
        "onshore_nearshore_hybrid": {},
    }
    assumptions_by_dim = dossier.get("assumptions_by_dimension") or {}
    contract_audit = dossier.get("contract_audit") or {
        "compliance_matrix": [],
        "overall_contract_gate": "SUPPORTED",
    }
    hcal = dossier.get("historical_calibration") or {}
    knn_rows = list(dossier.get("nearest_historical_quotes") or [])
    pert = dossier.get("pert_envelope") or {}
    z3_margin = dossier.get("formal_margin_proof") or {}
    z3_npv = dossier.get("formal_multiyear_npv_proof") or {}

    formula_count = 0

    # ------------------------------------------------------------------
    # TAB 2: WBS Multi-Arquetipo & CPM
    # ------------------------------------------------------------------
    wbs_headers = [
        "Archetype ID",
        "Family",
        "Standalone Hours",
        "Synergy Discount (frac)",
        "Net Hours",
        "Net Cost (EUR)",
        "Net Price (EUR)",
        "Duration (w)",
        "ES (w)",
        "EF (w)",
        "LS (w)",
        "LF (w)",
        "Total Float (w)",
        "Critical Path",
    ]
    ws_wbs.append(wbs_headers)
    _style_header_row(ws_wbs, 1, len(wbs_headers))
    ws_wbs.freeze_panes = "A2"

    nodes = dag.get("nodes") or []
    for idx, node in enumerate(nodes, start=2):
        syn_frac = _num_val(node.get("synergy_reduction_pct") or 0) / 100.0
        ws_wbs.append(
            [
                _sanitize_excel_text(node["archetype_id"]),
                _sanitize_excel_text(node.get("family", "")),
                _num_val(node["standalone_hours"]),
                syn_frac,
                f"=C{idx}*(1-D{idx})",
                _num_val(node["net_cost_eur"]),
                _num_val(node["net_price_eur"]),
                _num_val(node["duration_weeks"]),
                _num_val(node["early_start_week"]),
                f"=I{idx}+H{idx}",
                _num_val(node["late_start_week"]),
                f"=K{idx}+H{idx}",
                f"=K{idx}-I{idx}",
                f'=IF(M{idx}=0,"CRITICAL","FLOAT")',
            ]
        )
        formula_count += 5
        ws_wbs.cell(row=idx, column=4).number_format = "0.0%"
        for c_i in (3, 5, 6, 7):
            ws_wbs.cell(row=idx, column=c_i).number_format = "#,##0.00"
        for c_i in (8, 9, 10, 11, 12, 13):
            ws_wbs.cell(row=idx, column=c_i).number_format = "0.0"

    wbs_last = max(2, 1 + len(nodes))
    wbs_tot_row = wbs_last + 1
    ws_wbs.append(
        [
            "TOTAL / CRITICAL",
            "",
            f"=SUM(C2:C{wbs_last})",
            f"=IF(C{wbs_tot_row}>0,(C{wbs_tot_row}-E{wbs_tot_row})/C{wbs_tot_row},0)",
            f"=SUM(E2:E{wbs_last})",
            f"=SUM(F2:F{wbs_last})",
            f"=SUM(G2:G{wbs_last})",
            f"=MAX(J2:J{wbs_last})",
            "",
            f"=MAX(J2:J{wbs_last})",
            "",
            f"=MAX(L2:L{wbs_last})",
            f'=COUNTIF(N2:N{wbs_last},"CRITICAL")',
            "CRITICAL_NODES",
        ]
    )
    formula_count += 9
    for c_i in range(1, len(wbs_headers) + 1):
        ws_wbs.cell(row=wbs_tot_row, column=c_i).font = _BOLD_FONT
        ws_wbs.cell(row=wbs_tot_row, column=c_i).fill = _ACCENT_FILL
    ws_wbs.cell(row=wbs_tot_row, column=4).number_format = "0.0%"
    for c_i in (3, 5, 6, 7):
        ws_wbs.cell(row=wbs_tot_row, column=c_i).number_format = "#,##0.00"
    _autofit_columns(ws_wbs)

    # ------------------------------------------------------------------
    # TAB 3: Comparativa 9 Paises + Hybrid
    # ------------------------------------------------------------------
    ctry_headers = [
        "Country Code",
        "Country Name",
        "Cluster Hubs",
        "Blended Rate (EUR/h)",
        "Total Cost (EUR)",
        "Quote Price (EUR)",
        "Delta vs EU_DEFAULT",
        "CVE Share (%)",
        "Export Regime",
    ]
    ws_ctry.append(ctry_headers)
    _style_header_row(ws_ctry, 1, len(ctry_headers))
    ws_ctry.freeze_panes = "A2"

    ctry_rows = list(comp.get("countries") or [])
    eu_row_idx = 2
    for idx, row in enumerate(ctry_rows, start=2):
        if row.get("country_code") == "EU_DEFAULT":
            eu_row_idx = idx
            break

    for idx, row in enumerate(ctry_rows, start=2):
        ws_ctry.append(
            [
                _sanitize_excel_text(row["country_code"]),
                _sanitize_excel_text(row["country_name"]),
                _sanitize_excel_text(row.get("cluster_hubs", "")),
                _num_val(row["blended_hourly_rate_eur"]),
                _num_val(row["total_cost_eur"]),
                _num_val(row["quote_price_eur"]),
                f"=(F{idx}-$F${eu_row_idx})/$F${eu_row_idx}",
                _num_val(row.get("cve_share_pct") or 12) / 100.0,
                _sanitize_excel_text(row.get("export_control_regime", "")),
            ]
        )
        formula_count += 1
        for c_i in (4, 5, 6):
            ws_ctry.cell(row=idx, column=c_i).number_format = "#,##0.00"
        ws_ctry.cell(row=idx, column=7).number_format = "+0.0%;-0.0%;0.0%"
        ws_ctry.cell(row=idx, column=8).number_format = "0.0%"

    hyb = comp.get("onshore_nearshore_hybrid") or {}
    hyb_row = 2 + len(ctry_rows)
    if hyb:
        hyb_label = (
            f"{hyb.get('onshore_cve_country', 'EU_DEFAULT')} CVE + "
            f"{hyb.get('nearshore_execution_country', 'ES')}"
        )
        ws_ctry.append(
            [
                "HYBRID_ON_NEAR",
                _sanitize_excel_text(hyb_label),
                "Hybrid Sovereign EU/Nearshore",
                _num_val(hyb.get("blended_hourly_rate_eur")),
                _num_val(hyb.get("total_cost_eur")),
                _num_val(hyb.get("quote_price_eur")),
                f"=(F{hyb_row}-$F${eu_row_idx})/$F${eu_row_idx}",
                _num_val(12) / 100.0,
                _sanitize_excel_text(hyb.get("note", "")),
            ]
        )
        formula_count += 1
        for c_i in (4, 5, 6):
            ws_ctry.cell(row=hyb_row, column=c_i).number_format = "#,##0.00"
        ws_ctry.cell(row=hyb_row, column=7).number_format = "+0.0%;-0.0%;0.0%"
        ws_ctry.cell(row=hyb_row, column=8).number_format = "0.0%"

    ctry_last_data = 1 + len(ctry_rows) + (1 if hyb else 0)
    ctry_sum_row = ctry_last_data + 1
    ws_ctry.append(
        [
            "MIN / MAX",
            "Benchmark Spread",
            "",
            f"=AVERAGE(D2:D{ctry_last_data})",
            f"=MIN(E2:E{ctry_last_data})",
            f"=MIN(F2:F{ctry_last_data})",
            f"=MAX(F2:F{ctry_last_data})",
            "",
            "Lowest vs Highest Quote Price",
        ]
    )
    formula_count += 4
    ws_ctry.cell(row=ctry_sum_row, column=1).font = _BOLD_FONT
    for c_i in (4, 5, 6, 7):
        ws_ctry.cell(row=ctry_sum_row, column=c_i).number_format = "#,##0.00"
    _autofit_columns(ws_ctry)

    # ------------------------------------------------------------------
    # TAB 4: Flujo Caja & Aprendizaje
    # ------------------------------------------------------------------
    my_in = my.get("inputs") or {}
    my_out = my.get("outputs") or {}
    my_diag = my.get("diagnostics") or {}
    wacc_rate = _num_val(my_in.get("wacc_annual_pct") or 7.5) / 1200.0

    ws_cf.append(["Multi-Year Learning Curve & Escalation Summary", "", "", "", "", ""])
    ws_cf["A1"].font = _TITLE_FONT
    ws_cf.append(
        [
            "Parameter / Output",
            "Value",
            "Units",
            "Year",
            "Escalation Factor",
            "Escalated Cost (EUR)",
        ]
    )
    _style_header_row(ws_cf, 2, 6)

    summary_kv = [
        ("First Unit T1 Cost", _num_val(my_in.get("first_unit_cost_eur")), "EUR"),
        ("Lot Size (Units / MSN)", _num_val(my_in.get("unit_count") or 1), "units"),
        ("Learning Rate (%)", _num_val(my_in.get("learning_rate_pct") or 85), "%"),
        ("Wright Total Base Cost", _num_val(my_out.get("wright_total_base_cost_eur")), "EUR"),
        ("Crawford Total Base Cost", _num_val(my_out.get("crawford_total_base_cost_eur")), "EUR"),
        ("Active Base Total Cost", _num_val(my_out.get("active_base_total_cost_eur")), "EUR"),
        ("Escalated Total Cost", _num_val(my_out.get("escalated_total_cost_eur")), "EUR"),
        ("Multi-Year Quoted Price", _num_val(my_out.get("quoted_price_eur")), "EUR"),
        ("Net Present Value (NPV)", _num_val(my_out.get("net_present_value_eur")), "EUR"),
    ]
    ann_sched = list(my_diag.get("annual_escalation_schedule") or [])
    for i, (k_lbl, v_num, u_txt) in enumerate(summary_kv):
        r_idx = 3 + i
        y_item = ann_sched[i] if i < len(ann_sched) else None
        ws_cf.append(
            [
                k_lbl,
                v_num,
                u_txt,
                y_item["year_label"] if y_item else "",
                _num_val(y_item["escalation_factor"]) if y_item else "",
                _num_val(y_item["escalated_cost_eur"]) if y_item else "",
            ]
        )
        ws_cf.cell(row=r_idx, column=2).number_format = "#,##0.00"
        if y_item:
            ws_cf.cell(row=r_idx, column=6).number_format = "#,##0.00"

    cf_start_hdr = 14
    ws_cf.cell(
        row=cf_start_hdr - 1, column=1, value="Monthly Cash-Flow & Working Capital Schedule"
    ).font = _TITLE_FONT
    cf_headers = [
        "Month",
        "Monthly Outflow (EUR)",
        "Milestone Inflow (EUR)",
        "Net Cash Flow (EUR)",
        "Cumulative Cash (EUR)",
        "WC Financing Cost (EUR)",
    ]
    for col_i, h_txt in enumerate(cf_headers, start=1):
        ws_cf.cell(row=cf_start_hdr, column=col_i, value=h_txt)
    _style_header_row(ws_cf, cf_start_hdr, len(cf_headers))

    m_sched = list(my_diag.get("monthly_cashflow_schedule") or [])
    first_m_row = cf_start_hdr + 1
    for offset, m_item in enumerate(m_sched):
        r_i = first_m_row + offset
        ws_cf.cell(row=r_i, column=1, value=int(m_item["month"]))
        ws_cf.cell(row=r_i, column=2, value=_num_val(m_item["outflow_eur"]))
        ws_cf.cell(row=r_i, column=3, value=_num_val(m_item["inflow_eur"]))
        ws_cf.cell(row=r_i, column=4, value=f"=C{r_i}-B{r_i}")
        ws_cf.cell(row=r_i, column=5, value=f"=D{r_i}" if offset == 0 else f"=E{r_i - 1}+D{r_i}")
        ws_cf.cell(row=r_i, column=6, value=f"=IF(E{r_i}<0,-E{r_i}*{wacc_rate:.8f},0)")
        formula_count += 3
        for c_i in (2, 3, 4, 5, 6):
            ws_cf.cell(row=r_i, column=c_i).number_format = "#,##0.00"

    last_m_row = max(first_m_row, first_m_row + len(m_sched) - 1)
    cf_tot_row = last_m_row + 1
    ws_cf.cell(row=cf_tot_row, column=1, value="TOTAL / PEAK")
    ws_cf.cell(row=cf_tot_row, column=2, value=f"=SUM(B{first_m_row}:B{last_m_row})")
    ws_cf.cell(row=cf_tot_row, column=3, value=f"=SUM(C{first_m_row}:C{last_m_row})")
    ws_cf.cell(row=cf_tot_row, column=4, value=f"=SUM(D{first_m_row}:D{last_m_row})")
    ws_cf.cell(row=cf_tot_row, column=5, value=f"=MIN(E{first_m_row}:E{last_m_row})")
    ws_cf.cell(row=cf_tot_row, column=6, value=f"=SUM(F{first_m_row}:F{last_m_row})")
    formula_count += 5
    for c_i in range(1, 7):
        ws_cf.cell(row=cf_tot_row, column=c_i).font = _BOLD_FONT
        ws_cf.cell(row=cf_tot_row, column=c_i).fill = _ACCENT_FILL
        if c_i >= 2:
            ws_cf.cell(row=cf_tot_row, column=c_i).number_format = "#,##0.00"
    _autofit_columns(ws_cf)

    # ------------------------------------------------------------------
    # TAB 5: Registro 45 Supuestos
    # ------------------------------------------------------------------
    asm_headers = [
        "Assumption ID",
        "Dimension",
        "Label",
        "Title",
        "Statement",
        "Change-Order Trigger",
        "Risk If Violated",
    ]
    ws_asm.append(asm_headers)
    _style_header_row(ws_asm, 1, len(asm_headers))
    ws_asm.freeze_panes = "A2"

    asm_count = 0
    for dim, items in assumptions_by_dim.items():
        for it in items:
            asm_count += 1
            ws_asm.append(
                [
                    _sanitize_excel_text(it.get("assumption_id", "")),
                    _sanitize_excel_text(dim),
                    _sanitize_excel_text(it.get("label", "ASSUMPTION")),
                    _sanitize_excel_text(it.get("title", "")),
                    _sanitize_excel_text(it.get("statement", "")),
                    _sanitize_excel_text(it.get("change_order_trigger", "")),
                    _sanitize_excel_text(it.get("risk_if_violated", "")),
                ]
            )
    asm_last = max(2, 1 + asm_count)
    ws_asm.append(["TOTAL ASSUMPTIONS", f"=COUNTA(A2:A{asm_last})", "", "", "", "", ""])
    formula_count += 1
    _autofit_columns(ws_asm)

    # ------------------------------------------------------------------
    # TAB 6: Matriz Contractual
    # ------------------------------------------------------------------
    ctr_headers = [
        "Clause ID",
        "Category",
        "Status",
        "Poison Flags",
        "Clause Text",
        "Rationale",
        "Suggested Redline",
        "Linked Assumption",
    ]
    ws_ctr.append(ctr_headers)
    _style_header_row(ws_ctr, 1, len(ctr_headers))
    ws_ctr.freeze_panes = "A2"

    cl_rows = list(contract_audit.get("compliance_matrix") or [])
    for cl in cl_rows:
        ws_ctr.append(
            [
                _sanitize_excel_text(cl["clause_id"]),
                _sanitize_excel_text(cl["category"]),
                _sanitize_excel_text(cl["status"]),
                _sanitize_excel_text(", ".join(cl.get("poison_flags") or []) or "NONE"),
                _sanitize_excel_text(cl["text"]),
                _sanitize_excel_text(cl["rationale"]),
                _sanitize_excel_text(cl.get("suggested_redline") or ""),
                _sanitize_excel_text(cl.get("linked_assumption") or ""),
            ]
        )
    ctr_last = max(2, 1 + len(cl_rows))
    ctr_sum_row = ctr_last + 1
    ws_ctr.append(
        [
            "GATE SUMMARY",
            f'=IF(COUNTIF(C2:C{ctr_last},"REJECT_OR_ABSTAIN")>0,"REJECT_OR_ABSTAIN",IF(COUNTIF(C2:C{ctr_last},"CHANGE_ORDER_REQUIRED")>0,"CHANGE_ORDER_REQUIRED","SUPPORTED"))',
            f'=COUNTIF(C2:C{ctr_last},"SUPPORTED")',
            f'=COUNTIF(C2:C{ctr_last},"REJECT_OR_ABSTAIN")',
            f'=COUNTIF(C2:C{ctr_last},"CHANGE_ORDER_REQUIRED")',
            f'=COUNTIF(C2:C{ctr_last},"PARTIALLY_SUPPORTED_WITH_ASSUMPTION")',
            "Counts: Supported | Reject | ChangeOrder | Partial",
            "",
        ]
    )
    formula_count += 5
    _autofit_columns(ws_ctr)

    # ------------------------------------------------------------------
    # TAB 7: Benchmark k-NN Historico
    # ------------------------------------------------------------------
    knn_headers = [
        "Quote ID",
        "Archetype",
        "Quoted Hours",
        "Burned Hours",
        "Overrun %",
        "Country",
        "Material",
        "Similarity",
        "Outcome",
        "Broken Assumptions",
    ]
    ws_knn.append(knn_headers)
    _style_header_row(ws_knn, 1, len(knn_headers))
    ws_knn.freeze_panes = "A2"

    for idx, k_item in enumerate(knn_rows, start=2):
        ws_knn.append(
            [
                _sanitize_excel_text(k_item["quote_id"]),
                _sanitize_excel_text(k_item["archetype_id"]),
                _num_val(k_item["quoted_hours"]),
                _num_val(k_item["actual_burned_hours"]),
                f"=IF(C{idx}>0,(D{idx}-C{idx})/C{idx},0)",
                _sanitize_excel_text(k_item.get("country_code", "")),
                _sanitize_excel_text(k_item.get("material_family", "")),
                _num_val(k_item.get("similarity_score")),
                _sanitize_excel_text(k_item.get("outcome", "")),
                _sanitize_excel_text(
                    ", ".join(k_item.get("broken_assumption_ids") or ()) or "none"
                ),
            ]
        )
        formula_count += 1
        ws_knn.cell(row=idx, column=5).number_format = "+0.0%;-0.0%;0.0%"

    bt = hcal.get("backtesting") or {}
    ws_knn.append([])
    ws_knn.append(["Historical Calibration Summary", "Value"])
    ws_knn.append(["Pre-Calibration MAPE (%)", _num_val(bt.get("pre_calibration_mape_pct"))])
    ws_knn.append(["Post-Calibration MAPE (%)", _num_val(bt.get("post_calibration_mape_pct"))])
    ws_knn.append(
        [
            "Credibility Weight",
            _num_val((hcal.get("calibration_outputs") or {}).get("credibility_weight")),
        ]
    )
    _autofit_columns(ws_knn)

    # ------------------------------------------------------------------
    # TAB 1: Resumen Ejecutivo (Cross-Sheet Live Formula Dashboard)
    # ------------------------------------------------------------------
    ws_exec.append(["AeroRegu — Aerospace & Rotorcraft Executive Quotation Summary", "", ""])
    ws_exec["A1"].font = _TITLE_FONT
    ws_exec.append(
        [
            "ADVISORY NOTICE",
            (
                "ESTIMATE / ASSUMPTION decision-support aid only. "
                "Never determines regulatory compliance or certifies airworthiness."
            ),
            "",
        ]
    )
    ws_exec.append(["Metric / Governance Gate", "Live Formula / Value", "Source Sheet / Status"])
    _style_header_row(ws_exec, 3, 3)

    exec_rows = [
        ("RFQ Identifier", _sanitize_excel_text(dossier.get("rfq_id", "")), "Metadata"),
        ("Customer / OEM", _sanitize_excel_text(dossier.get("customer_name", "")), "Metadata"),
        (
            "Country Profile",
            _sanitize_excel_text(
                (dossier.get("country_profile") or {}).get("country_code", "EU_DEFAULT")
            ),
            "Rate Card",
        ),
        (
            "Critical Path Archetypes",
            _sanitize_excel_text(" -> ".join(dag.get("critical_path_archetypes") or [])),
            "WBS CPM",
        ),
        (
            "Project Critical Path Duration (Weeks)",
            f"='WBS Multi-Arquetipo & CPM'!J{wbs_tot_row}",
            "Live CPM Formula",
        ),
        (
            "WBS Standalone Hours",
            f"='WBS Multi-Arquetipo & CPM'!C{wbs_tot_row}",
            "Live WBS Formula",
        ),
        (
            "WBS Synergy Net Hours",
            f"='WBS Multi-Arquetipo & CPM'!E{wbs_tot_row}",
            "Live WBS Formula",
        ),
        (
            "WBS Synergy Savings (%)",
            f"='WBS Multi-Arquetipo & CPM'!D{wbs_tot_row}",
            "Live WBS Formula",
        ),
        (
            "Unit/Lot P80 Recommended Price (EUR)",
            _num_val(pert.get("price_p80_eur") or my_out.get("quoted_price_eur")),
            "PERT P80",
        ),
        (
            "Multi-Year Escalated Total Cost (EUR)",
            "='Flujo Caja & Aprendizaje'!B9",
            "Multi-Year Model",
        ),
        ("Multi-Year Quoted Price (EUR)", "='Flujo Caja & Aprendizaje'!B10", "Multi-Year Model"),
        (
            "Multi-Year Net Present Value (NPV EUR)",
            "='Flujo Caja & Aprendizaje'!B11",
            "Multi-Year Model",
        ),
        (
            "Peak Negative Cash Flow (EUR)",
            f"='Flujo Caja & Aprendizaje'!E{cf_tot_row}",
            "Live Cash-Flow Formula",
        ),
        (
            "Working Capital Financing Cost (EUR)",
            f"='Flujo Caja & Aprendizaje'!F{cf_tot_row}",
            "Live Cash-Flow Formula",
        ),
        (
            "Lowest 9-Country Price Benchmark (EUR)",
            f"='Comparativa 9 Paises'!F{ctry_sum_row}",
            "Live Benchmark Formula",
        ),
        (
            "Total Assumptions Locked (10 Axes)",
            f"='Registro 45 Supuestos'!B{asm_last + 1}",
            "Live Assumptions Count",
        ),
        ("Contractual Audit Gate", f"='Matriz Contractual'!B{ctr_sum_row}", "Live Contract Matrix"),
        (
            "Z3 SMT Unit Margin Proof",
            _sanitize_excel_text(z3_margin.get("status", "SKIPPED")),
            _sanitize_excel_text(z3_margin.get("proof_hash", "")[:16]),
        ),
        (
            "Z3 SMT Multi-Year NPV Proof",
            _sanitize_excel_text(z3_npv.get("status", "SKIPPED")),
            _sanitize_excel_text(z3_npv.get("proof_hash", "")[:16]),
        ),
        (
            "Merkle Ledger Root",
            _sanitize_excel_text(dossier.get("merkle_root", "")),
            _sanitize_excel_text(dossier.get("decision_status", "")),
        ),
    ]
    for idx, (m_lbl, val, note) in enumerate(exec_rows, start=4):
        ws_exec.append([m_lbl, val, note])
        if isinstance(val, str) and val.startswith("="):
            formula_count += 1
            if "(%)" in m_lbl:
                ws_exec.cell(row=idx, column=2).number_format = "0.0%"
            elif "EUR" in m_lbl:
                ws_exec.cell(row=idx, column=2).number_format = "#,##0.00"
            else:
                ws_exec.cell(row=idx, column=2).number_format = "#,##0.0"
        elif isinstance(val, float):
            ws_exec.cell(row=idx, column=2).number_format = "#,##0.00"
    _autofit_columns(ws_exec, max_width=64)

    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()
    xlsx_sha256 = hashlib.sha256(xlsx_bytes).hexdigest()

    out_str: str | None = None
    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(xlsx_bytes)
        out_str = str(out_p)

    return {
        "xlsx_bytes": xlsx_bytes,
        "xlsx_sha256": xlsx_sha256,
        "sheet_names": wb.sheetnames,
        "formula_count": formula_count,
        "output_path": out_str,
    }


def _resolve_signing_keypair(
    private_key_pem: bytes | None,
    public_key_pem: bytes | None,
) -> tuple[bytes, bytes]:
    """Load or generate Ed25519 signing keys for DSSE quotation/CCN PDF export."""
    if private_key_pem is None:
        return generate_ed25519_keypair()
    if public_key_pem is not None:
        return private_key_pem, public_key_pem
    from cryptography.hazmat.primitives import serialization

    priv_obj = serialization.load_pem_private_key(private_key_pem, password=None)
    pub_pem = priv_obj.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key_pem, pub_pem


def export_quotation_signed_pdf(
    dossier: dict[str, Any],
    *,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    pdf_sources: dict[str, bytes | Path] | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate an Ed25519 DSSE + ISO QR signed commercial-technical PDF quotation dossier."""
    priv_pem, pub_pem = _resolve_signing_keypair(private_key_pem, public_key_pem)

    dag = _normalize_wbs_dag(dossier)
    my = _normalize_multiyear(dossier)
    my_out = my.get("outputs") or {}
    pert = dossier.get("pert_envelope") or {}
    comp = dossier.get("multi_country_comparison") or {
        "countries": [],
        "onshore_nearshore_hybrid": {},
    }
    contract_audit = dossier.get("contract_audit") or {}
    idp = dossier.get("idp_physical_extraction") or {}
    deep_idp = idp.get("deep_metrics") or {}
    z3_margin = dossier.get("formal_margin_proof") or {}
    z3_npv = dossier.get("formal_multiyear_npv_proof") or {}
    merkle = str(dossier.get("merkle_root") or ("0" * 64))

    attestation_payload = {
        "schema": "evidence-layer/quotation-pdf-dossier@1.0.0",
        "rfq_id": str(dossier.get("rfq_id") or "RFQ-QUOTE"),
        "tenant_id": str(dossier.get("tenant_id") or "demo"),
        "merkle_root": merkle,
        "decision_status": str(dossier.get("decision_status") or "APPROVED_FOR_HUMAN_REVIEW"),
        "price_p80_eur": str(pert.get("price_p80_eur") or my_out.get("quoted_price_eur") or "0"),
        "multiyear_price_eur": str(my_out.get("quoted_price_eur") or "0"),
        "multiyear_npv_eur": str(my_out.get("net_present_value_eur") or "0"),
        "z3_margin_status": str(z3_margin.get("status") or "SKIPPED"),
        "z3_npv_status": str(z3_npv.get("status") or "SKIPPED"),
        "contract_gate": str(contract_audit.get("overall_contract_gate") or "SUPPORTED"),
        "critical_path": list(dag.get("critical_path_archetypes") or []),
    }
    dsse_envelope = sign_attestation_dsse(attestation_payload, priv_pem)
    dsse_bytes = json.dumps(dsse_envelope, sort_keys=True, indent=2).encode("utf-8")
    sig_raw = base64.b64decode(dsse_envelope["signatures"][0]["sig"])
    sig_sha256 = hashlib.sha256(sig_raw).hexdigest()

    qr_payload = "aeroregu-quote:" + json.dumps(
        {
            "v": 1,
            "r": str(dossier.get("rfq_id") or "")[:20],
            "m": merkle[:16],
            "s": sig_sha256[:16],
            "p": str(my_out.get("quoted_price_eur") or "")[:16],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    qr_png = render_qr_png(qr_payload, scale=8, border=6)

    doc = pymupdf.open()
    # PAGE 1: Executive Commercial-Technical Summary, QR, DSSE & Z3 Gates
    p1 = doc.new_page(width=595, height=842)
    banner_rgb = (15 / 255, 23 / 255, 42 / 255)
    p1.draw_rect(pymupdf.Rect(32, 28, 563, 94), color=banner_rgb, fill=banner_rgb)
    p1.insert_text(
        (44, 54),
        "AeroRegu - Signed Aerospace Quotation Dossier",
        fontsize=14,
        color=(1, 1, 1),
    )
    p1.insert_text(
        (44, 74),
        "ASSUMPTION / ESTIMATE aid for engineering managers & Part 21J CVEs. Never certifies.",
        fontsize=8.2,
        color=(0.82, 0.88, 0.96),
    )

    p1.draw_rect(
        pymupdf.Rect(366, 102, 566, 302), color=(0.85, 0.88, 0.92), fill=(1, 1, 1), width=0.6
    )
    p1.insert_image(pymupdf.Rect(370, 106, 562, 298), stream=qr_png)
    p1.insert_text(
        (386, 314), "Offline ISO QR + Ed25519 DSSE", fontsize=7.5, color=(0.2, 0.25, 0.35)
    )

    meta_lines = [
        f"RFQ ID: {dossier.get('rfq_id')}  |  Customer: {dossier.get('customer_name')}",
        f"Country: {(dossier.get('country_profile') or {}).get('country_code', 'EU_DEFAULT')}  |  "
        f"Decision: {dossier.get('decision_status')}",
        f"Critical Path ({dag.get('project_duration_weeks')} w): "
        + " -> ".join(dag.get("critical_path_archetypes") or []),
        f"Synergy Saved: {dag.get('synergy_hours_saved')} h ({dag.get('synergy_savings_pct')}%)",
        f"Unit/Lot P80 Price: {pert.get('price_p80_eur')} EUR",
        f"Multi-Year Price: {my_out.get('quoted_price_eur')} EUR",
        f"Multi-Year NPV: {my_out.get('net_present_value_eur')} EUR  |  "
        f"Peak Neg CF: -{my_out.get('peak_negative_cashflow_eur')} EUR",
        f"Z3 Margin Gate: {z3_margin.get('status', 'SKIPPED')}  |  "
        f"Z3 Multi-Year NPV: {z3_npv.get('status', 'SKIPPED')}",
        f"Contract Gate: {contract_audit.get('overall_contract_gate', 'SUPPORTED')} "
        f"(Poisons: {contract_audit.get('poison_clauses_count', 0)})",
        f"Merkle Root: {merkle[:32]}...",
        f"DSSE Sig SHA-256: {sig_sha256[:32]}...",
    ]
    y_c = 120
    for line in meta_lines:
        p1.insert_text((36, y_c), line[:62], fontsize=8.8, color=(0.1, 0.14, 0.22))
        y_c += 16

    y_c = max(y_c + 16, 336)
    p1.insert_text(
        (36, y_c),
        "Composite WBS DAG & Critical Path Schedule",
        fontsize=11,
        color=(0.06, 0.1, 0.18),
    )
    y_c += 16
    for node in (dag.get("nodes") or [])[:18]:
        crit_tag = (
            "CRITICAL" if node.get("is_critical") else f"Float {node.get('total_float_weeks')}w"
        )
        row_txt = (
            f"{node['archetype_id']} [{node['family']}]  Net: {node['net_hours']}h  "
            f"ES={node['early_start_week']}w EF={node['early_finish_week']}w  "
            f"({crit_tag})  Price={node['net_price_eur']} EUR"
        )
        p1.insert_text((40, y_c), row_txt[:96], fontsize=8.0, color=(0.15, 0.2, 0.28))
        y_c += 13

    # PAGE 2: 9-Country Comparison, Contractual Matrix & Deep IDP Sizing
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((36, 44), "9-Country Rate Comparison & Onshore/Nearshore Hybrid", fontsize=11.5)
    y2 = 64
    for r in (comp.get("countries") or [])[:10]:
        delta_eu = r.get("delta_vs_eu_default_pct", "0.00")
        p2.insert_text(
            (40, y2),
            f"{r['country_code']:10s} | Rate: {r['blended_hourly_rate_eur']:>8s} | "
            f"Price: {r['quote_price_eur']:>12s} EUR | Delta EU: {delta_eu}%",
            fontsize=8.2,
        )
        y2 += 14
    hyb = comp.get("onshore_nearshore_hybrid") or {}
    if hyb:
        p2.insert_text(
            (40, y2 + 4),
            f"Hybrid ({hyb.get('onshore_cve_country')}/{hyb.get('nearshore_execution_country')}): "
            f"{hyb.get('quote_price_eur')} EUR ({hyb.get('delta_vs_onshore_pct')}% vs onshore)",
            fontsize=8.5,
            color=(0.05, 0.35, 0.15),
        )
        y2 += 24

    p2.insert_text((36, y2 + 8), "Contractual Clause Audit & Poison-Clause Alerts", fontsize=11.5)
    y2 += 26
    for cl in (contract_audit.get("compliance_matrix") or [])[:14]:
        pflags = ",".join(cl.get("poison_flags") or [])
        tag = f"[{cl['status']}]" + (f" POISON={pflags}" if pflags else "")
        color = (0.72, 0.1, 0.1) if pflags else (0.12, 0.18, 0.28)
        p2.insert_text(
            (40, y2), f"{cl['clause_id']} {tag}: {cl['text'][:58]}", fontsize=8.0, color=color
        )
        y2 += 13

    y2 += 14
    p2.insert_text((36, y2), "Deep Physical IDP Summary & Citations", fontsize=11.5)
    y2 += 16
    bdf_sum = deep_idp.get("bdf_summary") or {}
    cad_sz = deep_idp.get("cad_brep_sizing") or {}
    bom_sz = deep_idp.get("bom_and_drawings") or {}
    p2.insert_text(
        (40, y2),
        f"IDP Maturity={idp.get('derived_idp_maturity')} | Nodes={idp.get('fem_nodes_count')} | "
        f"Active DOFs={(bdf_sum.get('dof_summary') or {}).get('active_dofs', 0)} | "
        f"Buy-to-Fly={cad_sz.get('buy_to_fly_ratio', '1.000')} | "
        f"BOM Parts={bom_sz.get('bom_parts_count', 0)}",
        fontsize=8.3,
    )
    y2 += 18

    bbox_cits = list(bom_sz.get("verified_bbox_citations") or [])[:3]
    for cl in contract_audit.get("compliance_matrix") or []:
        if cl.get("page_no") and cl.get("bbox") and len(bbox_cits) < 3:
            bbox_cits.append(
                {
                    "source_id": cl.get("clause_id", "clause"),
                    "source_hash": cl.get("source_file", "rfq"),
                    "page_no": cl["page_no"],
                    "bbox": cl["bbox"],
                    "text": cl.get("text", ""),
                }
            )
    for cit in bbox_cits:
        if y2 > 690:
            break
        thumb = _render_bbox_thumbnail(citation=cit, pdf_sources=pdf_sources)
        p2.insert_image(pymupdf.Rect(40, y2, 220, y2 + 95), stream=thumb)
        p2.insert_text(
            (230, y2 + 24),
            f"Cited Page {cit['page_no']} | BBox: {cit['bbox']}",
            fontsize=8.0,
            color=(0.72, 0.1, 0.1),
        )
        y2 += 104

    doc.embfile_add(
        _DSSE_ATTACHMENT_NAME,
        dsse_bytes,
        filename=_DSSE_ATTACHMENT_NAME,
        desc="DSSE v1 Ed25519 Quotation Attestation Envelope",
    )
    doc.embfile_add(
        _PUBKEY_ATTACHMENT_NAME,
        pub_pem,
        filename=_PUBKEY_ATTACHMENT_NAME,
        desc="Ed25519 Verification Public Key (PEM)",
    )
    doc.set_metadata(
        {
            "title": f"AeroRegu Signed Quotation Dossier ({dossier.get('rfq_id')})",
            "subject": f"merkle={merkle}",
            "keywords": qr_payload,
            "creator": "aeroregu-quotation-exporter",
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
        "bbox_thumbnails_count": len(bbox_cits),
        "output_path": out_str,
    }


def verify_quotation_signed_pdf(
    pdf_bytes: bytes,
    *,
    expected_public_key_pem: bytes | None = None,
) -> dict[str, Any]:
    """Verify embedded Ed25519 DSSE signature and ISO QR image in exported quotation PDF."""
    return verify_signed_pdf_report(pdf_bytes, expected_public_key_pem=expected_public_key_pem)


def export_change_order_xlsx(
    ccn_dossier: dict[str, Any],
    *,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export closed-loop Rev A -> Rev B Change-Order Addendum to a live-formula .xlsx book."""
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Resumen CCN"
    ws_wbs = wb.create_sheet("Delta WBS & CPM")
    ws_asm = wb.create_sheet("Supuestos Disparados")
    ws_ctr = wb.create_sheet("Delta Contractual")

    formula_count = 0
    fin = ccn_dossier.get("financial_delta") or {}
    cpm = ccn_dossier.get("cpm_delta") or {}
    wbs = ccn_dossier.get("wbs_delta") or {}
    cdelta = ccn_dossier.get("contract_delta") or {}
    triggered = list(ccn_dossier.get("triggered_assumptions") or [])

    # TAB 2: Delta WBS & CPM
    wbs_hdr = [
        "Archetype ID",
        "Status",
        "Base Hours",
        "Revised Hours",
        "Delta Hours",
        "Base Price (EUR)",
        "Revised Price (EUR)",
        "Delta Price (EUR)",
        "Base Float (w)",
        "Revised Float (w)",
        "Became Critical",
    ]
    ws_wbs.append(wbs_hdr)
    _style_header_row(ws_wbs, 1, len(wbs_hdr))
    ws_wbs.freeze_panes = "A2"

    nodes = list(wbs.get("node_deltas") or [])
    for idx, node in enumerate(nodes, start=2):
        ws_wbs.append(
            [
                _sanitize_excel_text(node.get("archetype_id", "")),
                _sanitize_excel_text(node.get("change_status", "")),
                _num_val(node.get("base_hours")),
                _num_val(node.get("revised_hours")),
                f"=D{idx}-C{idx}",
                _num_val(node.get("base_price_eur")),
                _num_val(node.get("revised_price_eur")),
                f"=G{idx}-F{idx}",
                _num_val(node.get("base_float_weeks")),
                _num_val(node.get("revised_float_weeks")),
                "YES" if node.get("became_critical") else "NO",
            ]
        )
        formula_count += 2
        for c_i in range(3, 11):
            ws_wbs.cell(row=idx, column=c_i).number_format = "#,##0.00"

    wbs_last = max(2, 1 + len(nodes))
    wbs_tot = wbs_last + 1
    ws_wbs.append(
        [
            "TOTAL CCN DELTA",
            f"=COUNTA(A2:A{wbs_last})",
            f"=SUM(C2:C{wbs_last})",
            f"=SUM(D2:D{wbs_last})",
            f"=D{wbs_tot}-C{wbs_tot}",
            f"=SUM(F2:F{wbs_last})",
            f"=SUM(G2:G{wbs_last})",
            f"=G{wbs_tot}-F{wbs_tot}",
            "",
            "",
            f'=COUNTIF(K2:K{wbs_last},"YES")',
        ]
    )
    formula_count += 8
    for c_i in range(1, len(wbs_hdr) + 1):
        ws_wbs.cell(row=wbs_tot, column=c_i).font = _BOLD_FONT
        ws_wbs.cell(row=wbs_tot, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_wbs)

    # TAB 3: Supuestos Disparados
    asm_hdr = ["Assumption ID", "Dimension", "Title", "Change-Order Trigger", "Trigger Reason"]
    ws_asm.append(asm_hdr)
    _style_header_row(ws_asm, 1, len(asm_hdr))
    for it in triggered:
        ws_asm.append(
            [
                _sanitize_excel_text(it.get("assumption_id", "")),
                _sanitize_excel_text(it.get("dimension", "")),
                _sanitize_excel_text(it.get("title", "")),
                _sanitize_excel_text(it.get("change_order_trigger", "")),
                _sanitize_excel_text(it.get("trigger_reason", "")),
            ]
        )
    asm_last = max(2, 1 + len(triggered))
    ws_asm.append(["TRIGGERED COUNT", f"=COUNTA(A2:A{asm_last})", "", "", ""])
    formula_count += 1
    _autofit_columns(ws_asm, max_width=56)

    # TAB 4: Delta Contractual
    ctr_hdr = ["Gate / Poison Item", "Baseline Rev A", "Revised Rev B", "Detail / Redline"]
    ws_ctr.append(ctr_hdr)
    _style_header_row(ws_ctr, 1, len(ctr_hdr))
    ws_ctr.append(
        [
            "Contractual Gate",
            _sanitize_excel_text(cdelta.get("base_gate", "")),
            _sanitize_excel_text(cdelta.get("revised_gate", "")),
            _sanitize_excel_text(cdelta.get("gate_transition", "")),
        ]
    )
    ws_ctr.append(
        [
            "Poison Clause Count",
            int(cdelta.get("base_poison_count") or 0),
            int(cdelta.get("revised_poison_count") or 0),
            "=C3-B3",
        ]
    )
    formula_count += 1
    for p_item in cdelta.get("new_poison_clauses") or []:
        ws_ctr.append(
            [
                _sanitize_excel_text(p_item.get("poison_id", "")),
                "ABSENT",
                _sanitize_excel_text(p_item.get("severity", "")),
                _sanitize_excel_text(p_item.get("redline", "")),
            ]
        )
    _autofit_columns(ws_ctr, max_width=64)

    # TAB 1: Resumen CCN
    ws_sum.append(["AeroRegu — Closed-Loop Change-Order (CCN) Addendum", "", "", ""])
    ws_sum["A1"].font = _TITLE_FONT
    ws_sum.append(["Metric", "Baseline (Rev A)", "Revised (Rev B)", "CCN Delta (Live Formula)"])
    _style_header_row(ws_sum, 2, 4)

    sum_rows = [
        (
            "Net Engineering Hours",
            _num_val(fin.get("base_net_hours")),
            _num_val(fin.get("revised_net_hours")),
            "=C3-B3",
        ),
        (
            "Unit/Lot PERT P80 Price (EUR)",
            _num_val(fin.get("base_p80_price_eur")),
            _num_val(fin.get("revised_p80_price_eur")),
            "=C4-B4",
        ),
        (
            "Multi-Year Quoted Price (EUR)",
            _num_val(fin.get("base_multiyear_quoted_price_eur")),
            _num_val(fin.get("revised_multiyear_quoted_price_eur")),
            "=C5-B5",
        ),
        (
            "Multi-Year Delta (%)",
            "",
            "",
            "=IF(B5>0,D5/B5,0)",
        ),
        (
            "Multi-Year NPV (EUR)",
            _num_val(fin.get("base_multiyear_npv_eur")),
            _num_val(fin.get("revised_multiyear_npv_eur")),
            "=C7-B7",
        ),
        (
            "Peak Negative Cash Flow (EUR)",
            _num_val(fin.get("base_peak_negative_cashflow_eur")),
            _num_val(fin.get("revised_peak_negative_cashflow_eur")),
            "=C8-B8",
        ),
        (
            "Critical Path Duration (Weeks)",
            _num_val(cpm.get("base_duration_weeks")),
            _num_val(cpm.get("revised_duration_weeks")),
            "=C9-B9",
        ),
        (
            "WBS Delta Check (Cross-Sheet)",
            f"='Delta WBS & CPM'!F{wbs_tot}",
            f"='Delta WBS & CPM'!G{wbs_tot}",
            f"='Delta WBS & CPM'!H{wbs_tot}",
        ),
        (
            "Triggered Assumptions Count",
            0,
            f"='Supuestos Disparados'!B{asm_last + 1}",
            "=C11",
        ),
        (
            "Amended Z3 SMT Margin / NPV",
            _sanitize_excel_text(
                (ccn_dossier.get("formal_amended_margin_proof") or {}).get("status", "SKIPPED")
            ),
            _sanitize_excel_text(
                (ccn_dossier.get("formal_amended_npv_proof") or {}).get("status", "SKIPPED")
            ),
            _sanitize_excel_text(ccn_dossier.get("decision_status", "")),
        ),
        (
            "CCN Change Reason",
            _sanitize_excel_text(ccn_dossier.get("cr_id", "CCN-001")),
            _sanitize_excel_text(ccn_dossier.get("baseline_rfq_id", "")),
            _sanitize_excel_text(ccn_dossier.get("change_reason", "")),
        ),
    ]
    for r_i, (m_lbl, b_val, rev_val, d_val) in enumerate(sum_rows, start=3):
        ws_sum.append([m_lbl, b_val, rev_val, d_val])
        for col_i, cell_v in ((2, b_val), (3, rev_val), (4, d_val)):
            if isinstance(cell_v, str) and cell_v.startswith("="):
                formula_count += 1
            if r_i == 6 and col_i == 4:
                ws_sum.cell(row=r_i, column=col_i).number_format = "+0.0%;-0.0%;0.0%"
            elif isinstance(cell_v, (int, float)) or (
                isinstance(cell_v, str) and cell_v.startswith("=") and r_i in (3, 4, 5, 7, 8, 9, 10)
            ):
                ws_sum.cell(row=r_i, column=col_i).number_format = "#,##0.00"
    _autofit_columns(ws_sum, max_width=56)

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


def export_change_order_signed_pdf(
    ccn_dossier: dict[str, Any],
    *,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate an Ed25519 DSSE + ISO QR signed Change-Order Addendum PDF dossier."""
    priv_pem, pub_pem = _resolve_signing_keypair(private_key_pem, public_key_pem)
    fin = ccn_dossier.get("financial_delta") or {}
    cpm = ccn_dossier.get("cpm_delta") or {}
    wbs = ccn_dossier.get("wbs_delta") or {}
    cdelta = ccn_dossier.get("contract_delta") or {}
    merkle = str(ccn_dossier.get("change_order_merkle_root") or ("0" * 64))

    attestation_payload = {
        "schema": "evidence-layer/quotation-ccn-pdf@1.0.0",
        "cr_id": str(ccn_dossier.get("cr_id") or "CCN-001"),
        "baseline_merkle_root": str(ccn_dossier.get("baseline_merkle_root") or ""),
        "revised_merkle_root": str(ccn_dossier.get("revised_merkle_root") or ""),
        "merkle_root": merkle,
        "decision_status": str(ccn_dossier.get("decision_status") or ""),
        "delta_multiyear_quoted_price_eur": str(
            fin.get("delta_multiyear_quoted_price_eur") or "0.000"
        ),
        "delta_duration_weeks": str(cpm.get("delta_duration_weeks") or "0.00"),
        "contract_transition": str(cdelta.get("gate_transition") or ""),
    }
    dsse_envelope = sign_attestation_dsse(attestation_payload, priv_pem)
    dsse_bytes = json.dumps(dsse_envelope, sort_keys=True, indent=2).encode("utf-8")
    sig_raw = base64.b64decode(dsse_envelope["signatures"][0]["sig"])
    sig_sha256 = hashlib.sha256(sig_raw).hexdigest()

    qr_payload = "aeroregu-ccn:" + json.dumps(
        {
            "v": 1,
            "c": str(ccn_dossier.get("cr_id") or "")[:16],
            "m": merkle[:16],
            "s": sig_sha256[:16],
            "d": str(fin.get("delta_multiyear_quoted_price_eur") or "")[:14],
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
        f"AeroRegu - Signed Change-Order Addendum ({ccn_dossier.get('cr_id', 'CCN-001')})",
        fontsize=13.5,
        color=(1, 1, 1),
    )
    page.insert_text(
        (44, 74),
        "ASSUMPTION / ESTIMATE closed-loop CCN delta. Requires human commercial & CVE approval.",
        fontsize=8.2,
        color=(0.82, 0.88, 0.96),
    )
    page.insert_image(pymupdf.Rect(452, 108, 556, 212), stream=qr_png)
    b_rfq = ccn_dossier.get("baseline_rfq_id")
    ch_reason = str(ccn_dossier.get("change_reason") or "")[:48]
    d_price = fin.get("delta_multiyear_quoted_price_eur")
    d_pct = fin.get("delta_price_pct")
    b_price = fin.get("base_multiyear_quoted_price_eur")
    r_price = fin.get("revised_multiyear_quoted_price_eur")
    d_npv = fin.get("delta_multiyear_npv_eur")
    d_pk = fin.get("delta_peak_negative_cashflow_eur")
    b_dur = cpm.get("base_duration_weeks")
    r_dur = cpm.get("revised_duration_weeks")
    d_dur = cpm.get("delta_duration_weeks")
    lines = [
        f"Baseline RFQ: {b_rfq}  |  Reason: {ch_reason}",
        f"Decision Status: {ccn_dossier.get('decision_status')}",
        f"Delta Multi-Year Price: {d_price} EUR ({d_pct}%)",
        f"Base -> Revised Price: {b_price} -> {r_price} EUR",
        f"Delta NPV: {d_npv} EUR  |  Delta Peak Neg CF: {d_pk} EUR",
        f"CPM Duration: {b_dur}w -> {r_dur}w (Delta {d_dur}w)",
        f"Contract Gate: {cdelta.get('gate_transition')}",
        f"Added Archetypes: {', '.join(wbs.get('added_archetypes') or []) or 'None'}",
        f"Removed Archetypes: {', '.join(wbs.get('removed_archetypes') or []) or 'None'}",
        f"CCN Merkle Root: {merkle[:48]}...",
    ]
    y = 124
    for ln in lines:
        page.insert_text((38, y), ln[:90], fontsize=9.0, color=(0.1, 0.14, 0.22))
        y += 16

    y += 10
    page.insert_text((38, y), "Triggered Assumptions & WBS Deltas", fontsize=11.0)
    y += 16
    for asm in (ccn_dossier.get("triggered_assumptions") or [])[:10]:
        page.insert_text(
            (42, y),
            f"- {asm['assumption_id']}: {asm['trigger_reason'][:78]}",
            fontsize=8.3,
            color=(0.18, 0.22, 0.30),
        )
        y += 14
    y += 8
    for nd in (wbs.get("node_deltas") or [])[:14]:
        if y > 790:
            break
        row_s = (
            f"{nd['archetype_id']} [{nd['change_status']}] "
            f"dHours={nd['delta_hours']} | dPrice={nd['delta_price_eur']} EUR"
        )
        page.insert_text(
            (42, y),
            row_s,
            fontsize=8.2,
            color=(0.12, 0.18, 0.28),
        )
        y += 13

    doc.embfile_add(
        _DSSE_ATTACHMENT_NAME,
        dsse_bytes,
        filename=_DSSE_ATTACHMENT_NAME,
        desc="DSSE v1 Ed25519 Change-Order Attestation Envelope",
    )
    doc.embfile_add(
        _PUBKEY_ATTACHMENT_NAME,
        pub_pem,
        filename=_PUBKEY_ATTACHMENT_NAME,
        desc="Ed25519 Verification Public Key (PEM)",
    )
    doc.set_metadata(
        {
            "title": f"AeroRegu Signed Change-Order ({ccn_dossier.get('cr_id', 'CCN-001')})",
            "subject": f"merkle={merkle}",
            "keywords": qr_payload,
            "creator": "aeroregu-ccn-exporter",
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


def export_portfolio_capacity_xlsx(
    portfolio_result: dict[str, Any],
    *,
    nearshore_plan: dict[str, Any] | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate native live-formula Excel (.xlsx) workbook for RCPSP Portfolio & Nearshore Plan."""
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "1_Portfolio_Summary"
    ws_roles = wb.create_sheet("2_Role_Bottlenecks")
    ws_rfqs = wb.create_sheet("3_RFQ_Schedule_Slip")
    ws_ns = wb.create_sheet("4_Nearshore_Optimization")

    formula_count = 0
    roles = list(portfolio_result.get("bottleneck_roles") or [])
    overflow_map = portfolio_result.get("overflow_hours_by_role") or {}
    rfqs = list(portfolio_result.get("rfq_schedules") or [])
    ns_roles = list((nearshore_plan or {}).get("per_role_allocation") or [])

    # TAB 2: Role Bottlenecks
    r_hdr = [
        "Role",
        "Headcount",
        "Weekly Target (h)",
        "Unconstrained Peak (h)",
        "Unconstrained Util (%)",
        "Leveled Util (%)",
        "Overflow (h)",
        "Bottleneck Status",
    ]
    ws_roles.append(r_hdr)
    _style_header_row(ws_roles, 1, len(r_hdr))
    ws_roles.freeze_panes = "A2"

    for idx, r_item in enumerate(roles, start=2):
        role_id = str(r_item.get("role") or "")
        ws_roles.append(
            [
                _sanitize_excel_text(role_id),
                int(r_item.get("headcount") or 0),
                _num_val(r_item.get("weekly_target_hours")),
                _num_val(r_item.get("unconstrained_peak_hours")),
                _num_val(r_item.get("unconstrained_peak_utilization_pct")),
                _num_val(r_item.get("leveled_peak_utilization_pct")),
                _num_val(overflow_map.get(role_id, "0")),
                f'=IF(E{idx}>100,"OVERLOADED",IF(F{idx}>85,"CONSTRAINED","OK"))',
            ]
        )
        formula_count += 1
        for c_i in (3, 4, 5, 6, 7):
            ws_roles.cell(row=idx, column=c_i).number_format = "#,##0.00"

    if not roles:
        ws_roles.append(["NONE", 0, 0, 0, 0, 0, 0, '=IF(E2>100,"OVERLOADED","OK")'])
        formula_count += 1
        last_role = 2
    else:
        last_role = 1 + len(roles)
    tot_role = last_role + 1
    ws_roles.append(
        [
            "OFFICE TOTAL / PEAK",
            f"=SUM(B2:B{last_role})",
            f"=SUM(C2:C{last_role})",
            f"=SUM(D2:D{last_role})",
            f"=MAX(E2:E{last_role})",
            f"=MAX(F2:F{last_role})",
            f"=SUM(G2:G{last_role})",
            f'=COUNTIF(H2:H{last_role},"OVERLOADED")',
        ]
    )
    formula_count += 7
    for c_i in range(1, len(r_hdr) + 1):
        ws_roles.cell(row=tot_role, column=c_i).font = _BOLD_FONT
        ws_roles.cell(row=tot_role, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_roles)

    # TAB 3: RFQ Schedule Slip
    rfq_hdr = [
        "RFQ ID",
        "Unconstrained Finish (wk)",
        "Leveled Finish (wk)",
        "Schedule Slip (wk)",
        "Leveled Start Month",
        "Schedule Status",
    ]
    ws_rfqs.append(rfq_hdr)
    _style_header_row(ws_rfqs, 1, len(rfq_hdr))
    ws_rfqs.freeze_panes = "A2"

    for idx, rfq in enumerate(rfqs, start=2):
        ws_rfqs.append(
            [
                _sanitize_excel_text(rfq.get("rfq_id", "")),
                int(rfq.get("unconstrained_finish_week") or 0),
                int(rfq.get("leveled_finish_week") or 0),
                f"=C{idx}-B{idx}",
                int(rfq.get("leveled_start_month") or 0),
                f'=IF(D{idx}>0,"SLIPPED","ON_TIME")',
            ]
        )
        formula_count += 2

    if not rfqs:
        ws_rfqs.append(["NONE", 0, 0, "=C2-B2", 0, "ON_TIME"])
        formula_count += 1
        last_rfq = 2
    else:
        last_rfq = 1 + len(rfqs)
    tot_rfq = last_rfq + 1
    ws_rfqs.append(
        [
            "PORTFOLIO TOTAL / MAX",
            f"=MAX(B2:B{last_rfq})",
            f"=MAX(C2:C{last_rfq})",
            f"=SUM(D2:D{last_rfq})",
            f"=MAX(E2:E{last_rfq})",
            f'=COUNTIF(F2:F{last_rfq},"SLIPPED")',
        ]
    )
    formula_count += 5
    for c_i in range(1, len(rfq_hdr) + 1):
        ws_rfqs.cell(row=tot_rfq, column=c_i).font = _BOLD_FONT
        ws_rfqs.cell(row=tot_rfq, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_rfqs)

    # TAB 4: Nearshore Allocation Optimization
    ns_hdr = [
        "Role",
        "Overflow (h)",
        "Retained Onshore (h)",
        "Offloaded Nearshore (h)",
        "Baseline Cost (EUR)",
        "Hybrid Cost (EUR)",
        "Net Savings (EUR)",
        "Allocation Policy",
    ]
    ws_ns.append(ns_hdr)
    _style_header_row(ws_ns, 1, len(ns_hdr))
    ws_ns.freeze_panes = "A2"

    for idx, n_item in enumerate(ns_roles, start=2):
        ws_ns.append(
            [
                _sanitize_excel_text(n_item.get("role", "")),
                _num_val(n_item.get("overflow_hours")),
                _num_val(n_item.get("retained_onshore_hours")),
                _num_val(n_item.get("offloaded_nearshore_hours")),
                _num_val(n_item.get("baseline_onshore_cost_eur")),
                _num_val(n_item.get("hybrid_cost_eur")),
                f"=E{idx}-F{idx}",
                _sanitize_excel_text(n_item.get("allocation_policy", "")),
            ]
        )
        formula_count += 1
        for c_i in (2, 3, 4, 5, 6, 7):
            ws_ns.cell(row=idx, column=c_i).number_format = "#,##0.00"

    if not ns_roles:
        ws_ns.append(["NONE", 0, 0, 0, 0, 0, "=E2-F2", "NOT_RUN"])
        formula_count += 1
        last_ns = 2
    else:
        last_ns = 1 + len(ns_roles)
    tot_ns = last_ns + 1
    ws_ns.append(
        [
            "OPTIMIZATION TOTAL",
            f"=SUM(B2:B{last_ns})",
            f"=SUM(C2:C{last_ns})",
            f"=SUM(D2:D{last_ns})",
            f"=SUM(E2:E{last_ns})",
            f"=SUM(F2:F{last_ns})",
            f"=E{tot_ns}-F{tot_ns}",
            f"=IF(E{tot_ns}>0,(G{tot_ns}/E{tot_ns})*100,0)",
        ]
    )
    formula_count += 7
    for c_i in range(1, len(ns_hdr) + 1):
        ws_ns.cell(row=tot_ns, column=c_i).font = _BOLD_FONT
        ws_ns.cell(row=tot_ns, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_ns)

    # TAB 1: Executive Summary (Cross-Sheet Live Formulas)
    ws_sum.append(["AeroRegu — Stress Office RCPSP Portfolio & Multi-Site Plan", "", ""])
    ws_sum["A1"].font = _TITLE_FONT
    ws_sum.append(
        [
            "ADVISORY NOTICE",
            "ESTIMATE / ASSUMPTION leveling aid. Requires engineering manager & CVE sign-off.",
            "",
        ]
    )
    ws_sum.append(["Portfolio KPI", "Live Formula / Value", "Source Tab"])
    _style_header_row(ws_sum, 3, 3)

    summary_rows = [
        ("Queued RFQs Count", int(portfolio_result.get("portfolio_rfq_count") or 0), "Input"),
        ("WBS Activities Count", int(portfolio_result.get("activity_count") or 0), "Input"),
        (
            "Overloaded Weeks Before Leveling",
            int(portfolio_result.get("overloaded_weeks_before_leveling") or 0),
            "RCPSP",
        ),
        ("Total Stress Office Headcount", f"='2_Role_Bottlenecks'!B{tot_role}", "Live Roles"),
        ("Peak Unconstrained Util (%)", f"='2_Role_Bottlenecks'!E{tot_role}", "Live Roles"),
        ("Peak Leveled Util (%)", f"='2_Role_Bottlenecks'!F{tot_role}", "Live Roles"),
        ("Total Overflow Hours (h)", f"='2_Role_Bottlenecks'!G{tot_role}", "Live Roles"),
        ("Max Leveled Finish Week", f"='3_RFQ_Schedule_Slip'!C{tot_rfq}", "Live Slip"),
        ("Cumulative RFQ Slip Weeks", f"='3_RFQ_Schedule_Slip'!D{tot_rfq}", "Live Slip"),
        (
            "Combined Peak Negative Cash Flow (EUR)",
            _num_val(portfolio_result.get("combined_peak_negative_cashflow_eur")),
            "Cash-Flow",
        ),
        (
            "Nearshore Hub",
            _sanitize_excel_text(
                f"{(nearshore_plan or {}).get('onshore_country', 'N/A')} -> "
                f"{(nearshore_plan or {}).get('nearshore_country', 'N/A')}"
            ),
            "Policy",
        ),
        ("Retained Onshore Overflow (h)", f"='4_Nearshore_Optimization'!C{tot_ns}", "Live Hub"),
        ("Offloaded Nearshore Hours (h)", f"='4_Nearshore_Optimization'!D{tot_ns}", "Live Hub"),
        ("Baseline Onshore Cost (EUR)", f"='4_Nearshore_Optimization'!E{tot_ns}", "Live Hub"),
        ("Hybrid Multi-Site Cost (EUR)", f"='4_Nearshore_Optimization'!F{tot_ns}", "Live Hub"),
        ("Net Multi-Site Savings (EUR)", "=B17-B18", "Live Hub"),
        (
            "CVE Governance Preserved",
            _sanitize_excel_text(
                str(bool((nearshore_plan or {}).get("cve_governance_preserved", True)))
            ),
            "Part 21J",
        ),
    ]
    for row_i, (lbl, val, src) in enumerate(summary_rows, start=4):
        ws_sum.append([lbl, val, src])
        if isinstance(val, str) and val.startswith("="):
            formula_count += 1
            ws_sum.cell(row=row_i, column=2).number_format = "#,##0.00"
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


def export_portfolio_capacity_signed_pdf(
    portfolio_result: dict[str, Any],
    *,
    nearshore_plan: dict[str, Any] | None = None,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate an Ed25519 DSSE + ISO QR signed PDF for RCPSP Portfolio & Nearshore Plan."""
    priv_pem, pub_pem = _resolve_signing_keypair(private_key_pem, public_key_pem)
    canonical_src = json.dumps(
        {
            "portfolio_rfq_count": portfolio_result.get("portfolio_rfq_count"),
            "bottleneck_roles": portfolio_result.get("bottleneck_roles"),
            "rfq_schedules": portfolio_result.get("rfq_schedules"),
            "recommended_nearshore_overflow_hours": portfolio_result.get(
                "recommended_nearshore_overflow_hours"
            ),
            "nearshore_plan": nearshore_plan,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    merkle = hashlib.sha256(canonical_src.encode("utf-8")).hexdigest()

    attestation_payload = {
        "schema": "evidence-layer/portfolio-capacity-pdf@1.0.0",
        "portfolio_rfq_count": int(portfolio_result.get("portfolio_rfq_count") or 0),
        "overloaded_weeks_before_leveling": int(
            portfolio_result.get("overloaded_weeks_before_leveling") or 0
        ),
        "recommended_nearshore_overflow_hours": str(
            portfolio_result.get("recommended_nearshore_overflow_hours") or "0.000"
        ),
        "combined_peak_negative_cashflow_eur": str(
            portfolio_result.get("combined_peak_negative_cashflow_eur") or "0.000"
        ),
        "nearshore_savings_eur": str((nearshore_plan or {}).get("net_savings_eur") or "0.00"),
        "cve_governance_preserved": bool(
            (nearshore_plan or {}).get("cve_governance_preserved", True)
        ),
        "merkle_root": merkle,
    }
    dsse_envelope = sign_attestation_dsse(attestation_payload, priv_pem)
    dsse_bytes = json.dumps(dsse_envelope, sort_keys=True, indent=2).encode("utf-8")
    sig_raw = base64.b64decode(dsse_envelope["signatures"][0]["sig"])
    sig_sha256 = hashlib.sha256(sig_raw).hexdigest()

    qr_payload = "aeroregu-port:" + json.dumps(
        {
            "v": 1,
            "n": int(portfolio_result.get("portfolio_rfq_count") or 0),
            "m": merkle[:16],
            "s": sig_sha256[:16],
            "ov": str(portfolio_result.get("recommended_nearshore_overflow_hours") or "0")[:10],
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
        "AeroRegu - Signed Portfolio RCPSP & Multi-Site Plan",
        fontsize=13.0,
        color=(1, 1, 1),
    )
    page.insert_text(
        (44, 74),
        "ESTIMATE / ASSUMPTION capacity leveling plan. Part 21.A.239 CVE remains onshore.",
        fontsize=8.2,
        color=(0.82, 0.88, 0.96),
    )
    page.insert_image(pymupdf.Rect(452, 108, 556, 212), stream=qr_png)

    top_role = (portfolio_result.get("bottleneck_roles") or [{}])[0]
    ov_wks = portfolio_result.get("overloaded_weeks_before_leveling")
    pk_cf = portfolio_result.get("combined_peak_negative_cashflow_eur")
    lines = [
        f"Queued RFQs: {portfolio_result.get('portfolio_rfq_count')}  |  "
        f"Activities: {portfolio_result.get('activity_count')}",
        f"Overloaded Weeks Before Leveling: {ov_wks}",
        f"Top Bottleneck: {top_role.get('role', 'N/A')} "
        f"({top_role.get('unconstrained_peak_utilization_pct', '0')}%)",
        f"Overflow Hours: {portfolio_result.get('recommended_nearshore_overflow_hours')} h",
        f"Combined Peak Neg Cash Flow: -{pk_cf} EUR",
        f"Nearshore Route: {(nearshore_plan or {}).get('onshore_country', 'N/A')} -> "
        f"{(nearshore_plan or {}).get('nearshore_country', 'N/A')} | "
        f"Savings={(nearshore_plan or {}).get('net_savings_eur', '0.00')} EUR",
        f"CVE Onshore Preserved: {(nearshore_plan or {}).get('cve_governance_preserved', True)}",
        f"Portfolio Digest: {merkle[:48]}...",
    ]
    y = 124
    for ln in lines:
        page.insert_text((38, y), ln[:90], fontsize=9.0, color=(0.1, 0.14, 0.22))
        y += 16

    y += 10
    page.insert_text((38, y), "7-Role Bottleneck & Leveled Utilization", fontsize=11.0)
    y += 16
    for br in (portfolio_result.get("bottleneck_roles") or [])[:7]:
        un_u = br["unconstrained_peak_utilization_pct"]
        lv_u = br["leveled_peak_utilization_pct"]
        page.insert_text(
            (42, y),
            f"{br['role']}: hc={br['headcount']} unconstr={un_u}% leveled={lv_u}%",
            fontsize=8.3,
            color=(0.18, 0.22, 0.30),
        )
        y += 14

    y += 8
    page.insert_text((38, y), "RFQ Leveled Schedule Slip", fontsize=11.0)
    y += 16
    for rs in (portfolio_result.get("rfq_schedules") or [])[:10]:
        if y > 790:
            break
        page.insert_text(
            (42, y),
            f"{rs['rfq_id']}: {rs['unconstrained_finish_week']}w -> {rs['leveled_finish_week']}w "
            f"(slip={rs['schedule_slip_weeks']}w)",
            fontsize=8.2,
            color=(0.12, 0.18, 0.28),
        )
        y += 13

    doc.embfile_add(
        _DSSE_ATTACHMENT_NAME,
        dsse_bytes,
        filename=_DSSE_ATTACHMENT_NAME,
        desc="DSSE v1 Ed25519 Portfolio Capacity Attestation Envelope",
    )
    doc.embfile_add(
        _PUBKEY_ATTACHMENT_NAME,
        pub_pem,
        filename=_PUBKEY_ATTACHMENT_NAME,
        desc="Ed25519 Verification Public Key (PEM)",
    )
    doc.set_metadata(
        {
            "title": "AeroRegu Signed Portfolio RCPSP Plan",
            "subject": f"merkle={merkle}",
            "keywords": qr_payload,
            "creator": "aeroregu-portfolio-exporter",
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


def export_evm_postmortem_xlsx(
    postmortem_report: dict[str, Any],
    *,
    fx_report: dict[str, Any] | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate native live-formula Excel (.xlsx) workbook for Bid-to-Actual EVM & FX hedging."""
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "1_EVM_Summary"
    ws_wbs = wb.create_sheet("2_WBS_Earned_Value")
    ws_asm = wb.create_sheet("3_Broken_Assumptions")
    ws_fx = wb.create_sheet("4_FX_Hedging_Z3")

    formula_count = 0
    evm = postmortem_report.get("evm_summary") or {}
    nodes = list(postmortem_report.get("per_node_evm") or [])
    attributions = list(postmortem_report.get("broken_assumptions_attributed") or [])

    # TAB 2: Per-Node Earned Value
    wbs_hdr = [
        "Archetype ID",
        "Quoted Hours",
        "Actual Hours",
        "Hours Variance",
        "BAC Cost (EUR)",
        "PV (EUR)",
        "EV (EUR)",
        "AC (EUR)",
        "CV (EUR)",
        "SV (EUR)",
        "CPI",
        "SPI",
        "EAC (EUR)",
        "Outcome",
    ]
    ws_wbs.append(wbs_hdr)
    _style_header_row(ws_wbs, 1, len(wbs_hdr))
    ws_wbs.freeze_panes = "A2"

    for idx, nd in enumerate(nodes, start=2):
        ws_wbs.append(
            [
                _sanitize_excel_text(nd.get("archetype_id", "")),
                _num_val(nd.get("quoted_hours")),
                _num_val(nd.get("actual_hours")),
                f"=C{idx}-B{idx}",
                _num_val(nd.get("bac_cost_eur")),
                _num_val(nd.get("pv_eur")),
                _num_val(nd.get("ev_eur")),
                _num_val(nd.get("ac_eur")),
                f"=G{idx}-H{idx}",
                f"=G{idx}-F{idx}",
                f"=IF(H{idx}>0,G{idx}/H{idx},1)",
                f"=IF(F{idx}>0,G{idx}/F{idx},1)",
                f"=IF(K{idx}>0,E{idx}/K{idx},E{idx})",
                _sanitize_excel_text(nd.get("outcome", "")),
            ]
        )
        formula_count += 6
        for c_i in (2, 3, 4, 5, 6, 7, 8, 9, 10, 13):
            ws_wbs.cell(row=idx, column=c_i).number_format = "#,##0.00"
        for c_i in (11, 12):
            ws_wbs.cell(row=idx, column=c_i).number_format = "0.000"

    if not nodes:
        ws_wbs.append(["NONE", 0, 0, "=C2-B2", 0, 0, 0, 0, "=G2-H2", "=G2-F2", 1, 1, 0, "N/A"])
        formula_count += 3
        last_wbs = 2
    else:
        last_wbs = 1 + len(nodes)
    tot_wbs = last_wbs + 1
    ws_wbs.append(
        [
            "PROGRAM TOTAL",
            f"=SUM(B2:B{last_wbs})",
            f"=SUM(C2:C{last_wbs})",
            f"=C{tot_wbs}-B{tot_wbs}",
            f"=SUM(E2:E{last_wbs})",
            f"=SUM(F2:F{last_wbs})",
            f"=SUM(G2:G{last_wbs})",
            f"=SUM(H2:H{last_wbs})",
            f"=G{tot_wbs}-H{tot_wbs}",
            f"=G{tot_wbs}-F{tot_wbs}",
            f"=IF(H{tot_wbs}>0,G{tot_wbs}/H{tot_wbs},1)",
            f"=IF(F{tot_wbs}>0,G{tot_wbs}/F{tot_wbs},1)",
            f"=IF(K{tot_wbs}>0,E{tot_wbs}/K{tot_wbs},E{tot_wbs})",
            f'=COUNTIF(N2:N{last_wbs},"WON_OVERRUN")',
        ]
    )
    formula_count += 13
    for c_i in range(1, len(wbs_hdr) + 1):
        ws_wbs.cell(row=tot_wbs, column=c_i).font = _BOLD_FONT
        ws_wbs.cell(row=tot_wbs, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_wbs)

    # TAB 3: Broken Assumptions Attribution
    asm_hdr = [
        "Assumption ID",
        "Dimension",
        "Title",
        "Attributed Overrun (h)",
        "Root-Cause Diagnosis",
    ]
    ws_asm.append(asm_hdr)
    _style_header_row(ws_asm, 1, len(asm_hdr))
    for at in attributions:
        ws_asm.append(
            [
                _sanitize_excel_text(at.get("assumption_id", "")),
                _sanitize_excel_text(at.get("dimension", "")),
                _sanitize_excel_text(at.get("title", "")),
                _num_val(at.get("attributed_overrun_hours")),
                _sanitize_excel_text(at.get("cause", "")),
            ]
        )
    asm_last = max(2, 1 + len(attributions))
    if attributions:
        ws_asm.append(
            ["TOTAL ATTRIBUTED", "", f"=COUNTA(A2:A{asm_last})", f"=SUM(D2:D{asm_last})", ""]
        )
        formula_count += 2
    _autofit_columns(ws_asm)

    # TAB 4: FX Hedging & Z3 Shock Sensitivity
    fx_hdr = [
        "FX Shock (%)",
        "Unhedged Revenue (EUR)",
        "Hedged Revenue (EUR)",
        "Hedge Gain / Delta (EUR)",
        "Unhedged Margin (%)",
        "Hedged Margin (%)",
    ]
    ws_fx.append(["AeroRegu Multi-Currency FX Hedging & Z3 SMT Margin Gate", "", "", "", "", ""])
    ws_fx["A1"].font = _TITLE_FONT
    fx_z3 = (fx_report or {}).get("formal_fx_margin_proof") or {}
    ws_fx.append(
        [
            "Billing / Cost Currency",
            _sanitize_excel_text(
                f"{(fx_report or {}).get('billing_currency', 'EUR')} / "
                f"{(fx_report or {}).get('cost_currency', 'EUR')}"
            ),
            "Hedge Ratio (%)",
            _num_val((fx_report or {}).get("hedge_ratio_pct")),
            "Z3 SMT Status",
            _sanitize_excel_text(fx_z3.get("status") or "NOT_RUN"),
        ]
    )
    ws_fx.append(fx_hdr)
    _style_header_row(ws_fx, 3, len(fx_hdr))
    scenarios = list((fx_report or {}).get("sensitivity_scenarios") or [])
    for row_i, sc in enumerate(scenarios, start=4):
        ws_fx.append(
            [
                _num_val(sc.get("fx_shock_pct")),
                _num_val(sc.get("unhedged_revenue_eur")),
                _num_val(sc.get("hedged_revenue_eur")),
                f"=C{row_i}-B{row_i}",
                _num_val(sc.get("unhedged_margin_pct")),
                _num_val(sc.get("hedged_margin_pct")),
            ]
        )
        formula_count += 1
        for c_i in (2, 3, 4):
            ws_fx.cell(row=row_i, column=c_i).number_format = "#,##0.00"
    _autofit_columns(ws_fx)

    # TAB 1: EVM Executive Summary (Cross-Sheet Live Formulas)
    ws_sum.append(["AeroRegu — Bid-to-Actual EVM Post-Mortem Dashboard", "", ""])
    ws_sum["A1"].font = _TITLE_FONT
    ws_sum.append(
        [
            "ADVISORY NOTICE",
            "ASSUMPTION / ESTIMATE closed-loop EVM feedback; requires human controller sign-off.",
            "",
        ]
    )
    ws_sum.append(["KPI / Gate", "Live Value / Formula", "Reference"])
    _style_header_row(ws_sum, 3, 3)

    sell_price = _num_val(evm.get("quoted_selling_price_eur"))
    summary_rows = [
        ("Project ID", _sanitize_excel_text(postmortem_report.get("project_id", "")), "Metadata"),
        (
            "Baseline RFQ ID",
            _sanitize_excel_text(postmortem_report.get("baseline_rfq_id", "")),
            "Baseline",
        ),
        (
            "Health Status",
            _sanitize_excel_text(postmortem_report.get("health_status", "")),
            "EVM Gate",
        ),
        ("Quoted Hours (h)", f"='2_WBS_Earned_Value'!B{tot_wbs}", "Live WBS"),
        ("Actual Burned Hours (h)", f"='2_WBS_Earned_Value'!C{tot_wbs}", "Live WBS"),
        ("Hours Variance (h)", "=B8-B7", "Live Delta"),
        ("Budget at Completion BAC (EUR)", f"='2_WBS_Earned_Value'!E{tot_wbs}", "Live WBS"),
        ("Earned Value EV (EUR)", f"='2_WBS_Earned_Value'!G{tot_wbs}", "Live WBS"),
        ("Actual Cost AC (EUR)", f"='2_WBS_Earned_Value'!H{tot_wbs}", "Live WBS"),
        ("Cost Performance Index CPI", f"='2_WBS_Earned_Value'!K{tot_wbs}", "Live EVM"),
        ("Schedule Performance Index SPI", f"='2_WBS_Earned_Value'!L{tot_wbs}", "Live EVM"),
        ("Estimate at Completion EAC (EUR)", f"='2_WBS_Earned_Value'!M{tot_wbs}", "Live EVM"),
        ("Variance at Completion VAC (EUR)", "=B10-B15", "Live EVM"),
        ("Quoted Selling Price (EUR)", sell_price, "Contract"),
        ("Realized Gross Margin (EUR)", "=B17-B12", "Live Margin"),
        ("Realized Gross Margin (%)", "=IF(B17>0,(B18/B17)*100,0)", "Live Margin"),
        (
            "Ledger Merkle Root",
            _sanitize_excel_text(postmortem_report.get("merkle_root", "")),
            "Audit Trail",
        ),
    ]
    for idx, (lbl, val, src) in enumerate(summary_rows, start=4):
        ws_sum.append([lbl, val, src])
        if isinstance(val, str) and val.startswith("="):
            formula_count += 1
            ws_sum.cell(row=idx, column=2).number_format = (
                "0.000" if ("CPI" in lbl or "SPI" in lbl) else "#,##0.00"
            )
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


def export_evm_postmortem_signed_pdf(
    postmortem_report: dict[str, Any],
    *,
    fx_report: dict[str, Any] | None = None,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate an Ed25519 DSSE + ISO QR signed PDF for Bid-to-Actual EVM & FX post-mortem."""
    priv_pem, pub_pem = _resolve_signing_keypair(private_key_pem, public_key_pem)
    evm = postmortem_report.get("evm_summary") or {}
    merkle = str(postmortem_report.get("merkle_root") or ("0" * 64))
    proj_id = str(postmortem_report.get("project_id") or "POST-001")
    fx_z3 = (fx_report or {}).get("formal_fx_margin_proof") or {}

    attestation_payload = {
        "schema": "evidence-layer/quotation-evm-pdf@1.0.0",
        "project_id": proj_id,
        "baseline_rfq_id": str(postmortem_report.get("baseline_rfq_id") or ""),
        "health_status": str(postmortem_report.get("health_status") or ""),
        "cpi": str(evm.get("cpi") or "1.000"),
        "spi": str(evm.get("spi") or "1.000"),
        "eac_eur": str(evm.get("eac_eur") or "0.000"),
        "vac_eur": str(evm.get("vac_eur") or "0.000"),
        "fx_proof_status": str(fx_z3.get("status") or "NONE"),
        "merkle_root": merkle,
    }
    dsse_envelope = sign_attestation_dsse(attestation_payload, priv_pem)
    dsse_bytes = json.dumps(dsse_envelope, sort_keys=True, indent=2).encode("utf-8")
    sig_raw = base64.b64decode(dsse_envelope["signatures"][0]["sig"])
    sig_sha256 = hashlib.sha256(sig_raw).hexdigest()

    qr_payload = "aeroregu-evm:" + json.dumps(
        {
            "v": 1,
            "p": proj_id[:16],
            "m": merkle[:16],
            "s": sig_sha256[:16],
            "c": str(evm.get("cpi") or "")[:8],
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
        f"AeroRegu - Signed Bid-to-Actual EVM Post-Mortem ({proj_id})",
        fontsize=13.0,
        color=(1, 1, 1),
    )
    page.insert_text(
        (44, 74),
        "ASSUMPTION / ESTIMATE closed-loop ERP EVM & FX dossier. Requires human approval.",
        fontsize=8.2,
        color=(0.82, 0.88, 0.96),
    )
    page.insert_image(pymupdf.Rect(452, 108, 556, 212), stream=qr_png)

    lines = [
        f"Project ID: {proj_id}  |  Baseline RFQ: {postmortem_report.get('baseline_rfq_id')}",
        f"Health Status: {postmortem_report.get('health_status')}",
        f"Quoted vs Actual Hours: {evm.get('quoted_hours')} h -> {evm.get('actual_hours')} h "
        f"(Var {evm.get('hours_variance')} h / {evm.get('hours_variance_pct')}%)",
        f"EVM Indexes: CPI={evm.get('cpi')} | SPI={evm.get('spi')} | TCPI={evm.get('tcpi_bac')}",
        f"BAC={evm.get('bac_cost_eur')} EUR | AC={evm.get('ac_eur')} EUR "
        f"| EAC={evm.get('eac_eur')} EUR",
        f"VAC={evm.get('vac_eur')} EUR | Realized Margin={evm.get('realized_margin_pct')}%",
        f"FX Hedging Z3 Gate: {fx_z3.get('status') or 'NOT_INCLUDED'} "
        f"({(fx_report or {}).get('billing_currency', 'EUR')})",
        f"Ledger Merkle Root: {merkle[:48]}...",
    ]
    y = 124
    for ln in lines:
        page.insert_text((38, y), ln[:90], fontsize=9.0, color=(0.1, 0.14, 0.22))
        y += 16

    y += 10
    page.insert_text((38, y), "Per-Node Earned Value & Broken Assumptions", fontsize=11.0)
    y += 16
    for at in (postmortem_report.get("broken_assumptions_attributed") or [])[:8]:
        page.insert_text(
            (42, y),
            f"- {at['assumption_id']} ({at['attributed_overrun_hours']}h): {at['cause'][:72]}",
            fontsize=8.3,
            color=(0.18, 0.22, 0.30),
        )
        y += 14
    y += 8
    for nd in (postmortem_report.get("per_node_evm") or [])[:14]:
        if y > 790:
            break
        page.insert_text(
            (42, y),
            f"{nd['archetype_id']} [{nd['outcome']}] Q={nd['quoted_hours']}h "
            f"A={nd['actual_hours']}h CPI={nd['cpi']} EAC={nd['eac_eur']} EUR",
            fontsize=8.2,
            color=(0.12, 0.18, 0.28),
        )
        y += 13

    doc.embfile_add(
        _DSSE_ATTACHMENT_NAME,
        dsse_bytes,
        filename=_DSSE_ATTACHMENT_NAME,
        desc="DSSE v1 Ed25519 EVM Post-Mortem Attestation Envelope",
    )
    doc.embfile_add(
        _PUBKEY_ATTACHMENT_NAME,
        pub_pem,
        filename=_PUBKEY_ATTACHMENT_NAME,
        desc="Ed25519 Verification Public Key (PEM)",
    )
    doc.set_metadata(
        {
            "title": f"AeroRegu Signed EVM Post-Mortem ({proj_id})",
            "subject": f"merkle={merkle}",
            "keywords": qr_payload,
            "creator": "aeroregu-evm-exporter",
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
