"""Automated Batch Stress-Note Dossier Packager & Compliance-Aid Exporter.

Aggregates multiple component structural/systems checks across the 56-card AeroRegu catalog,
resolves MMPDS-16 / CMH-17 allowables with 50-digit FLINT/Arb uncertainty intervals, runs
continuous Z3 SMT formal proofs, identifies the governing minimum Margin of Safety, seals a
single batch event into the SHA-256 Merkle Ledger, and exports native live-formula Excel (.xlsx)
+ Ed25519 DSSE & ISO QR signed PDF summary dossiers.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from evidence_calc.quantize import format_quantum
from evidence_calc.registry import run_method
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record
from openpyxl import Workbook

from evidence_coverage.pdf_layout import CorporatePDFBuilder, compute_dsse_sig_prefix
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
_MARGIN_KEY_PRIORITY: tuple[str, ...] = (
    "governing_ms",
    "margin_of_safety",
    "life_margin_of_safety",
    "margin_vs_a_basis",
    "von_mises_ms",
    "clearance_margin_pct",
)
_Q4 = Decimal("0.0001")


def _extract_governing_margin(
    outputs: dict[str, Any],
    exact_intervals: dict[str, Any],
) -> tuple[str, Decimal, dict[str, Any]]:
    for key in _MARGIN_KEY_PRIORITY:
        if key in outputs:
            val = Decimal(str(outputs[key]))
            if key == "clearance_margin_pct":
                val = val / Decimal("100")
            iv = exact_intervals.get(key) or {}
            return key, val, iv
    raise ValueError("missing_margin_output_in_check")


def build_stress_summary_dossier(
    dossier_id: str,
    checks: list[dict[str, Any]],
    *,
    ledger: Ledger | None = None,
    tenant_id: str = "demo",
    actor_id: str = "stress-office",
    include_formal_proofs: bool = True,
) -> dict[str, Any]:
    """Run deterministic Arb + Z3 batch stress checks, seal Ledger, and identify governing MS."""
    if not checks:
        raise ValueError("empty_stress_checks")

    results: list[dict[str, Any]] = []
    gov_min_ms: Decimal | None = None
    gov_check_id = ""
    gov_component = ""
    gov_method_id = ""
    passed_count = 0
    failed_count = 0
    proved_count = 0
    all_sources: list[dict[str, Any]] = []

    formal_fn = None
    if include_formal_proofs:
        try:
            from evidence_api.formal_methods import run_formal_proof_for_method

            formal_fn = run_formal_proof_for_method
        except Exception:
            formal_fn = None

    for idx, spec in enumerate(checks, start=1):
        check_id = str(spec.get("check_id") or f"CHK-{idx:03d}")
        comp_name = str(spec.get("component_name") or f"Component-{idx}")
        method_id = str(spec["method_id"])
        raw_inputs = dict(spec.get("inputs") or {})
        mat_lookup = spec.get("material_lookup")
        if isinstance(mat_lookup, dict):
            mat_copy = dict(mat_lookup)
            if "material_id" in mat_copy:
                mat_copy.setdefault("include_intervals", True)
            raw_inputs["material_lookup"] = mat_copy

        ran = run_method(
            method_id,
            raw_inputs,
            normalize_units=bool(spec.get("normalize_units", False)),
            include_intervals=True,
        )
        outputs = dict(ran["outputs"])
        intervals = dict(ran.get("exact_intervals") or {})
        margin_key, margin_val, margin_iv = _extract_governing_margin(outputs, intervals)

        if margin_val >= Decimal("0"):
            passed_count += 1
            margin_status = "POSITIVE_MARGIN"
        else:
            failed_count += 1
            margin_status = "NEGATIVE_MARGIN"

        if gov_min_ms is None or margin_val < gov_min_ms:
            gov_min_ms = margin_val
            gov_check_id = check_id
            gov_component = comp_name
            gov_method_id = method_id

        formal_res: dict[str, Any] | None = None
        if formal_fn is not None:
            numeric_in = dict(raw_inputs)
            numeric_in.pop("material_lookup", None)
            numeric_in.pop("_input_units", None)
            # Inject resolved allowables so Z3 proves over the material-knockdown allowable
            for fld, prov in (ran.get("allowable_provenance") or {}).items():
                numeric_in[fld] = str(prov["allowable_value_mpa"])
            formal_res = formal_fn(
                method_id,
                numeric_in,
                formal_bounds=spec.get("formal_bounds"),
            )
            if formal_res.get("proved") is True:
                proved_count += 1

        for src in ran.get("sources") or []:
            if isinstance(src, dict):
                all_sources.append(src)

        results.append(
            {
                "check_id": check_id,
                "component_name": comp_name,
                "method_id": method_id,
                "method_version": ran["method_version"],
                "margin_key": margin_key,
                "governing_ms": format_quantum(margin_val, _Q4),
                "margin_status": margin_status,
                "arb_interval": margin_iv,
                "allowable_provenance": ran.get("allowable_provenance") or {},
                "formal_proof": formal_res,
                "outputs": outputs,
            }
        )

    assert gov_min_ms is not None
    overall_status = "ALL_MARGINS_POSITIVE" if failed_count == 0 else "NEGATIVE_MARGIN_FLAGGED"

    canonical_payload = json.dumps(
        {
            "dossier_id": dossier_id,
            "check_count": len(results),
            "global_ms_min": format_quantum(gov_min_ms, _Q4),
            "governing_check_id": gov_check_id,
            "checks": [
                {
                    "check_id": r["check_id"],
                    "method_id": r["method_id"],
                    "governing_ms": r["governing_ms"],
                    "formal_status": (r.get("formal_proof") or {}).get("status"),
                }
                for r in results
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    dossier_sha = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    out: dict[str, Any] = {
        "dossier_id": dossier_id,
        "tenant_id": tenant_id,
        "check_count": len(results),
        "passed_margin_count": passed_count,
        "failed_margin_count": failed_count,
        "formal_proved_count": proved_count,
        "global_ms_min": format_quantum(gov_min_ms, _Q4),
        "governing_check_id": gov_check_id,
        "governing_component": gov_component,
        "governing_method_id": gov_method_id,
        "overall_status": overall_status,
        "checks_results": results,
        "dossier_sha256": dossier_sha,
        "advisory_only": ASSISTANCE_DISCLAIMER,
    }

    if ledger is not None:
        sources = all_sources or [project_source("stress_dossier_batch")]
        env = make_envelope(
            sources=sources[:16],
            method_version="stress_dossier_packager@1.0.0",
            inputs={
                "dossier_id": dossier_id,
                "check_count": len(results),
                "dossier_sha256": dossier_sha,
            },
            confidence="deterministic",
            result={
                "global_ms_min": out["global_ms_min"],
                "governing_check_id": gov_check_id,
                "overall_status": overall_status,
                "formal_proved_count": proved_count,
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
                    "record_kind": "stress_dossier_batch",
                    "dossier_id": dossier_id,
                    "global_ms_min": out["global_ms_min"],
                    "governing_check_id": gov_check_id,
                    "overall_status": overall_status,
                    "dossier_sha256": dossier_sha,
                },
                "envelope": env,
            },
        )
        out["ledger_event_hash"] = ev_hash
        out["merkle_root"] = ledger.merkle_root()
    else:
        out["merkle_root"] = dossier_sha

    return out


def export_stress_dossier_xlsx(
    dossier: dict[str, Any],
    *,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export multi-tab live-formula Excel (.xlsx) Stress Summary Matrix with CWE-1236 defense."""
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "1_Stress_Summary"
    ws_chk = wb.create_sheet("2_Component_Checks")
    ws_mat = wb.create_sheet("3_Allowables_Arb_Bounds")

    formula_count = 0
    rows = list(dossier.get("checks_results") or [])

    # TAB 2: Component Checks
    chk_hdr = [
        "Check ID",
        "Component",
        "Method ID",
        "Governing MS",
        "Arb Lower",
        "Arb Upper",
        "Z3 SMT Status",
        "Margin Status",
    ]
    ws_chk.append(chk_hdr)
    _style_header_row(ws_chk, 1, len(chk_hdr))
    ws_chk.freeze_panes = "A2"

    for idx, ch in enumerate(rows, start=2):
        arb_iv = ch.get("arb_interval") or {}
        z3_st = str((ch.get("formal_proof") or {}).get("status") or "NOT_RUN")
        ws_chk.append(
            [
                _sanitize_excel_text(ch.get("check_id", "")),
                _sanitize_excel_text(ch.get("component_name", "")),
                _sanitize_excel_text(ch.get("method_id", "")),
                _num_val(ch.get("governing_ms")),
                _num_val(arb_iv.get("lower", ch.get("governing_ms"))),
                _num_val(arb_iv.get("upper", ch.get("governing_ms"))),
                _sanitize_excel_text(z3_st),
                f'=IF(D{idx}>=0,"POSITIVE_MARGIN","NEGATIVE_MARGIN")',
            ]
        )
        formula_count += 1
        for c_i in (4, 5, 6):
            ws_chk.cell(row=idx, column=c_i).number_format = "0.0000"

    last_chk = max(2, 1 + len(rows))
    tot_chk = last_chk + 1
    ws_chk.append(
        [
            "DOSSIER MIN / SUMMARY",
            f"=COUNTA(A2:A{last_chk})",
            "",
            f"=MIN(D2:D{last_chk})",
            f"=MIN(E2:E{last_chk})",
            f"=MAX(F2:F{last_chk})",
            f'=COUNTIF(G2:G{last_chk},"PROVED_UNSAT")',
            f'=IF(COUNTIF(H2:H{last_chk},"NEGATIVE_MARGIN")>0,"NEGATIVE_MARGIN_FLAGGED","ALL_MARGINS_POSITIVE")',
        ]
    )
    formula_count += 6
    for c_i in range(1, len(chk_hdr) + 1):
        ws_chk.cell(row=tot_chk, column=c_i).font = _BOLD_FONT
        ws_chk.cell(row=tot_chk, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_chk)

    # TAB 3: MMPDS-16 / CMH-17 Allowables & Arb Uncertainty Bounds
    mat_hdr = [
        "Check ID",
        "Target Field",
        "Material",
        "Basis",
        "Environment",
        "Nominal (MPa)",
        "Certified Lower (MPa)",
        "Catalog SHA-256",
    ]
    ws_mat.append(mat_hdr)
    _style_header_row(ws_mat, 1, len(mat_hdr))
    ws_mat.freeze_panes = "A2"
    mat_count = 0
    for ch in rows:
        prov_map = ch.get("allowable_provenance") or {}
        for fld, prov in prov_map.items():
            mat_count += 1
            ws_mat.append(
                [
                    _sanitize_excel_text(ch.get("check_id", "")),
                    _sanitize_excel_text(fld),
                    _sanitize_excel_text(prov.get("material_id", "")),
                    _sanitize_excel_text(prov.get("basis", "")),
                    _sanitize_excel_text(prov.get("environment", "")),
                    _num_val(prov.get("allowable_value_mpa")),
                    _num_val(
                        prov.get("certified_lower_bound_mpa", prov.get("allowable_value_mpa"))
                    ),
                    _sanitize_excel_text(prov.get("catalog_sha256", "")),
                ]
            )
    if mat_count == 0:
        ws_mat.append(["NONE", "-", "-", "-", "-", 0, 0, "-"])
        mat_last = 2
    else:
        mat_last = 1 + mat_count
    ws_mat.append(["ALLOWABLE COUNT", f"=COUNTA(A2:A{mat_last})", "", "", "", "", "", ""])
    formula_count += 1
    _autofit_columns(ws_mat)

    # TAB 1: Stress Summary Dashboard
    ws_sum.append(["AeroRegu — Batch Stress Summary Compliance-Aid Dossier", "", ""])
    ws_sum["A1"].font = _TITLE_FONT
    ws_sum.append(["ADVISORY NOTICE", ASSISTANCE_DISCLAIMER, ""])
    ws_sum.append(["Summary Gate", "Live Formula / Value", "Source"])
    _style_header_row(ws_sum, 3, 3)

    summary_rows = [
        ("Dossier ID", _sanitize_excel_text(dossier.get("dossier_id", "")), "Metadata"),
        ("Total Component Checks", f"='2_Component_Checks'!B{tot_chk}", "Live Matrix"),
        (
            "Governing Check ID",
            _sanitize_excel_text(dossier.get("governing_check_id", "")),
            "Critical",
        ),
        (
            "Governing Component",
            _sanitize_excel_text(dossier.get("governing_component", "")),
            "Critical",
        ),
        ("Minimum Margin of Safety (MS)", f"='2_Component_Checks'!D{tot_chk}", "Live Matrix"),
        ("Minimum Arb Lower Bound", f"='2_Component_Checks'!E{tot_chk}", "Live Arb"),
        ("Z3 SMT Proved Count", f"='2_Component_Checks'!G{tot_chk}", "Live Z3"),
        ("Overall Dossier Gate", f"='2_Component_Checks'!H{tot_chk}", "Live Gate"),
        ("Material Lookup Rows", f"='3_Allowables_Arb_Bounds'!B{mat_last + 1}", "Live Allowables"),
        ("Ledger Merkle Root", _sanitize_excel_text(dossier.get("merkle_root", "")), "Audit Trail"),
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


def export_stress_dossier_signed_pdf(
    dossier: dict[str, Any],
    *,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export Ed25519 DSSE + offline ISO QR signed PDF Stress Summary Compliance-Aid Note."""
    priv_pem, pub_pem = _resolve_signing_keypair(private_key_pem, public_key_pem)
    merkle = str(dossier.get("merkle_root") or dossier.get("dossier_sha256") or ("0" * 64))
    did = str(dossier.get("dossier_id") or "STRESS-DOSSIER-001")

    attestation_payload = {
        "schema": "evidence-layer/stress-summary-dossier@1.0.0",
        "dossier_id": did,
        "check_count": int(dossier.get("check_count") or 0),
        "global_ms_min": str(dossier.get("global_ms_min") or "0.0000"),
        "governing_check_id": str(dossier.get("governing_check_id") or ""),
        "overall_status": str(dossier.get("overall_status") or ""),
        "formal_proved_count": int(dossier.get("formal_proved_count") or 0),
        "merkle_root": merkle,
    }
    sig_sha256 = compute_dsse_sig_prefix(attestation_payload, priv_pem)
    qr_payload = "aeroregu-stress:" + json.dumps(
        {
            "v": 1,
            "d": did[:16],
            "m": merkle[:16],
            "s": sig_sha256[:16],
            "ms": str(dossier.get("global_ms_min") or "")[:10],
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    p_cnt = dossier.get("passed_margin_count")
    t_cnt = dossier.get("check_count")
    meta_kpis = [
        ("Dossier ID", did),
        ("Overall Status", str(dossier.get("overall_status") or "")),
        ("Checks Passed / Total", f"{p_cnt} / {t_cnt}"),
        ("Z3 SMT Proved", f"{dossier.get('formal_proved_count')} / {t_cnt}"),
        (
            "Governing Min MS",
            f"{dossier.get('global_ms_min')} ({dossier.get('governing_check_id')} - "
            f"{dossier.get('governing_component')})",
        ),
        ("Governing Method", str(dossier.get("governing_method_id") or "")),
        ("Ledger Merkle Root", f"{merkle[:36]}..."),
    ]
    builder = CorporatePDFBuilder(
        title=f"AeroRegu - Signed Stress Summary Note ({did})",
        subtitle=ASSISTANCE_DISCLAIMER,
        merkle_root=merkle,
        qr_payload=qr_payload,
        meta_kpis=meta_kpis,
        creator="aeroregu-stress-dossier-exporter",
    )
    table_rows = [
        [
            ch.get("check_id", ""),
            ch.get("component_name", ""),
            ch.get("method_id", ""),
            ch.get("governing_ms", ""),
            f"[{(ch.get('arb_interval') or {}).get('lower', '-')}, "
            f"{(ch.get('arb_interval') or {}).get('upper', '-')}]",
            (ch.get("formal_proof") or {}).get("status") or "NOT_RUN",
        ]
        for ch in (dossier.get("checks_results") or [])
    ]
    builder.add_table(
        "Component Check Summary Matrix (Arb 50-Digit Intervals + Z3 SMT)",
        ["Check ID", "Component", "Method ID", "Min MS", "Arb [Lower, Upper]", "Z3 SMT"],
        table_rows,
        col_widths=[56, 98, 126, 52, 114, 77],
    )
    return builder.finalize_signed(
        attestation_payload=attestation_payload,
        private_key_pem=priv_pem,
        public_key_pem=pub_pem,
        metadata_title=f"AeroRegu Signed Stress Summary ({did})",
        output_path=output_path,
    )
