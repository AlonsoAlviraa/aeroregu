"""EASA Part 21J Means-of-Compliance (MoC 0..9) Readiness Matrix & CVE Packager.

Deterministically cross-links CS-27/CS-29 structural and systems requirements to
computed Stress-Note Dossier checks, Load-Case Envelope studies, FEM/NAFEMS audits,
ECN revision tags, SHA-256 Ledger hashes, and distinct Part 21J CVE sign-offs.
Every artifact carries the mandatory human-reviewer advisory disclaimer.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymupdf
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

MOC_CODE_DESCRIPTIONS: dict[str, str] = {
    "MOC-0": "Compliance Statement",
    "MOC-1": "Design Review / Description",
    "MOC-2": "Calculation / Analysis",
    "MOC-3": "Safety Assessment / FHA-FMEA",
    "MOC-4": "Laboratory / Rig Tests",
    "MOC-5": "Ground Tests on Aircraft",
    "MOC-6": "Flight Tests",
    "MOC-7": "Design Inspection / Conformity",
    "MOC-8": "Simulation / Validated FEM",
    "MOC-9": "Equipment Qualification",
}

DEFAULT_CS29_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "cs_paragraph": "CS 29.301",
        "title": "Loads General Distribution",
        "required_mocs": ["MOC-0", "MOC-2"],
        "method_ids": ["rigid_body_point_mass", "load_envelope_combiner"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.303",
        "title": "Factor of Safety",
        "required_mocs": ["MOC-2"],
        "method_ids": ["margin_of_safety", "load_envelope_combiner"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.305",
        "title": "Strength and Deformation",
        "required_mocs": ["MOC-2", "MOC-8"],
        "method_ids": ["column_plate_buckling", "tailboom_boxbeam_combined_stress"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.307",
        "title": "Proof of Structure",
        "required_mocs": ["MOC-2", "MOC-4", "MOC-8"],
        "method_ids": ["nafems_sol105_gpforce", "orthotropic_composite_plate_buckling"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.561",
        "title": "Emergency Landing General",
        "required_mocs": ["MOC-2", "MOC-4"],
        "method_ids": ["cs29_crashworthiness_561_562_load"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.571",
        "title": "Fatigue Evaluation of Structure",
        "required_mocs": ["MOC-2", "MOC-4"],
        "method_ids": ["walker_mean_stress_crack_growth", "palmgren_miner_fatigue"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.603",
        "title": "Materials",
        "required_mocs": ["MOC-1", "MOC-2"],
        "method_ids": ["allowables_mmpds16"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.613",
        "title": "Material Strength Properties & Basis",
        "required_mocs": ["MOC-2"],
        "method_ids": [
            "statistical_ab_basis_tolerance_bound",
            "composite_bolted_joint_bearing_tension_shear",
        ],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.631",
        "title": "Bird Strike Damage Tolerance",
        "required_mocs": ["MOC-2", "MOC-8"],
        "method_ids": ["cs29_bird_strike_penetration_screen"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.725",
        "title": "Limit Drop Tests / Skid Gear",
        "required_mocs": ["MOC-2", "MOC-4"],
        "method_ids": ["cs29_skid_landing_gear_drop_energy"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.801",
        "title": "Ditching Bottom-Hull Impact",
        "required_mocs": ["MOC-2", "MOC-8"],
        "method_ids": ["cs29_ditching_water_impact_panel"],
        "revision": "REV-A",
    },
    {
        "cs_paragraph": "CS 29.1191",
        "title": "Firewalls Thermal & Containment",
        "required_mocs": ["MOC-2", "MOC-9"],
        "method_ids": ["firewall_thermal_buckling_screen"],
        "revision": "REV-A",
    },
]

_STATUS_SEVERITY: dict[str, int] = {
    "GAP_NEGATIVE_MARGIN": 1,
    "GAP_STALE_REVISION": 2,
    "GAP_MISSING_EVIDENCE": 3,
    "READY_FOR_CVE_REVIEW": 4,
    "CVE_SIGNED_ADVISORY": 5,
}


def build_part21j_moc_matrix(
    program_id: str,
    *,
    requirements: list[dict[str, Any]] | None = None,
    stress_dossier: dict[str, Any] | None = None,
    load_envelope: dict[str, Any] | None = None,
    fem_audit: dict[str, Any] | None = None,
    ledger_event_hashes: dict[str, str] | None = None,
    cve_signoffs: dict[str, dict[str, Any]] | None = None,
    active_ecn_revision: str = "REV-A",
    ledger: Ledger | None = None,
    tenant_id: str = "demo",
    actor_id: str = "cve-office",
) -> dict[str, Any]:
    """Build deterministic Part 21J Means-of-Compliance matrix and gap register."""
    reqs = (
        list(requirements)
        if requirements is not None
        else [dict(r) for r in DEFAULT_CS29_REQUIREMENTS]
    )
    if not reqs:
        raise ValueError("empty_moc_requirements")

    hash_map = dict(ledger_event_hashes or {})
    signoff_map = dict(cve_signoffs or {})

    # Index checks from stress_dossier by method_id and check_id
    checks_by_method: dict[str, list[dict[str, Any]]] = {}
    dossier_hash = ""
    if isinstance(stress_dossier, dict):
        dossier_hash = str(
            stress_dossier.get("ledger_event_hash") or stress_dossier.get("merkle_root") or ""
        )
        for ch in stress_dossier.get("checks_results") or []:
            mid = str(ch.get("method_id") or "")
            checks_by_method.setdefault(mid, []).append(ch)
            cid = str(ch.get("check_id") or "")
            if cid:
                checks_by_method.setdefault(cid, []).append(ch)

    env_hash = ""
    if isinstance(load_envelope, dict):
        env_hash = str(
            load_envelope.get("ledger_event_hash") or load_envelope.get("merkle_root") or ""
        )
    fem_hash = ""
    if isinstance(fem_audit, dict):
        fem_hash = str(fem_audit.get("audit_sha256") or fem_audit.get("merkle_root") or "")

    rows: list[dict[str, Any]] = []
    open_gaps: list[dict[str, Any]] = []

    for req in reqs:
        cs_para = str(req["cs_paragraph"])
        title = str(req.get("title") or cs_para)
        req_mocs = [str(m) for m in (req.get("required_mocs") or ["MOC-2"])]
        linked_methods = [str(m) for m in (req.get("method_ids") or [])]
        ev_rev = str(req.get("revision") or active_ecn_revision)

        linked_checks: list[dict[str, Any]] = []
        min_ms_dec: Decimal | None = None
        for mid in linked_methods:
            for ch in checks_by_method.get(mid, []):
                linked_checks.append(ch)
                ms_val = Decimal(str(ch["governing_ms"]))
                if min_ms_dec is None or ms_val < min_ms_dec:
                    min_ms_dec = ms_val

        # Also pull load_envelope governing MS when load_envelope_combiner is linked
        if "load_envelope_combiner" in linked_methods and isinstance(load_envelope, dict):
            ms_env = Decimal(str(load_envelope.get("global_ms_min") or "0"))
            if min_ms_dec is None or ms_env < min_ms_dec:
                min_ms_dec = ms_env

        ev_hashes: list[str] = []
        if cs_para in hash_map and hash_map[cs_para]:
            ev_hashes.append(str(hash_map[cs_para]))
        if linked_checks and dossier_hash:
            ev_hashes.append(dossier_hash)
        if "load_envelope_combiner" in linked_methods and env_hash:
            ev_hashes.append(env_hash)
        if "nafems_sol105_gpforce" in linked_methods and fem_hash:
            ev_hashes.append(fem_hash)
        for m_code in req_mocs:
            key_m = f"{cs_para}:{m_code}"
            if key_m in hash_map and hash_map[key_m]:
                ev_hashes.append(str(hash_map[key_m]))
        if isinstance(req.get("evidence_hash"), str) and req["evidence_hash"]:
            ev_hashes.append(str(req["evidence_hash"]))
        ev_hashes = list(dict.fromkeys(ev_hashes))

        # Check explicit test/artifact presence for MOC-4..MOC-9
        provided_mocs = {str(m) for m in (req.get("provided_mocs") or [])}
        if linked_checks or (
            "load_envelope_combiner" in linked_methods and isinstance(load_envelope, dict)
        ):
            provided_mocs.update({"MOC-0", "MOC-1", "MOC-2"})
        if isinstance(fem_audit, dict) and "nafems_sol105_gpforce" in linked_methods:
            provided_mocs.add("MOC-8")
        for m_code in req_mocs:
            if f"{cs_para}:{m_code}" in hash_map:
                provided_mocs.add(m_code)
        if cs_para in hash_map:
            provided_mocs.update(req_mocs)

        missing_mocs = [m for m in req_mocs if m not in provided_mocs]
        has_negative_ms = min_ms_dec is not None and min_ms_dec < Decimal("0")
        is_stale_rev = ev_rev != active_ecn_revision
        sign_rec = signoff_map.get(cs_para)
        cve_signed = bool(
            isinstance(sign_rec, dict)
            and sign_rec.get("cve_id")
            and sign_rec.get("distinct_reviewer", True)
        )

        if has_negative_ms:
            status = "GAP_NEGATIVE_MARGIN"
            gap_reason = (
                f"Negative margin of safety ({format_quantum(min_ms_dec, Decimal('0.0001'))})"
            )
        elif is_stale_rev:
            status = "GAP_STALE_REVISION"
            gap_reason = f"Evidence revision {ev_rev} lags active ECN {active_ecn_revision}"
        elif missing_mocs or not ev_hashes:
            status = "GAP_MISSING_EVIDENCE"
            gap_reason = (
                f"Missing MoC artifacts: {', '.join(missing_mocs)}"
                if missing_mocs
                else "Missing SHA-256 ledger evidence hash"
            )
        elif cve_signed:
            status = "CVE_SIGNED_ADVISORY"
            gap_reason = ""
        else:
            status = "READY_FOR_CVE_REVIEW"
            gap_reason = ""

        ms_str = format_quantum(min_ms_dec, Decimal("0.0001")) if min_ms_dec is not None else "N/A"
        row = {
            "cs_paragraph": cs_para,
            "title": title,
            "required_mocs": req_mocs,
            "provided_mocs": sorted(provided_mocs),
            "missing_mocs": missing_mocs,
            "linked_methods": linked_methods,
            "min_governing_ms": ms_str,
            "revision": ev_rev,
            "evidence_hashes": ev_hashes,
            "cve_signed": cve_signed,
            "cve_id": str(sign_rec.get("cve_id"))
            if isinstance(sign_rec, dict) and sign_rec.get("cve_id")
            else "",
            "status": status,
            "gap_reason": gap_reason,
        }
        rows.append(row)
        if status.startswith("GAP_"):
            open_gaps.append(
                {
                    "cs_paragraph": cs_para,
                    "title": title,
                    "status": status,
                    "severity": _STATUS_SEVERITY.get(status, 3),
                    "reason": gap_reason,
                }
            )

    open_gaps.sort(key=lambda g: (g["severity"], g["cs_paragraph"]))
    ready_count = sum(
        1 for r in rows if r["status"] in {"READY_FOR_CVE_REVIEW", "CVE_SIGNED_ADVISORY"}
    )
    signed_count = sum(1 for r in rows if r["status"] == "CVE_SIGNED_ADVISORY")
    gap_count = len(open_gaps)
    readiness_pct = format_quantum(
        (Decimal(ready_count) / Decimal(len(rows))) * Decimal("100"),
        Decimal("0.01"),
    )

    matrix_sha = hashlib.sha256(
        json.dumps(
            {
                "program_id": program_id,
                "active_ecn_revision": active_ecn_revision,
                "readiness_pct": readiness_pct,
                "rows": rows,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    result: dict[str, Any] = {
        "label": "ASSUMPTION",
        "not_a_certification_determination": True,
        "assistance_disclaimer": ASSISTANCE_DISCLAIMER,
        "program_id": program_id,
        "active_ecn_revision": active_ecn_revision,
        "requirement_count": len(rows),
        "ready_count": ready_count,
        "cve_signed_count": signed_count,
        "open_gap_count": gap_count,
        "readiness_pct": readiness_pct,
        "overall_status": (
            "READY_FOR_CVE_PACKAGE_SIGNOFF" if gap_count == 0 else "OPEN_EVIDENCE_OR_MARGIN_GAPS"
        ),
        "moc_definitions": MOC_CODE_DESCRIPTIONS,
        "matrix_rows": rows,
        "open_gaps": open_gaps,
        "matrix_sha256": matrix_sha,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    if ledger is not None:
        src_proj = project_source(
            f"moc-matrix-{program_id}",
            f"https://aeroregu.local/moc/{program_id}",
            "ASSUMPTION",
        )
        env = make_envelope(
            sources=[src_proj],
            method_version="part21j_moc_matrix@1.0.0",
            inputs={
                "program_id": program_id,
                "active_ecn_revision": active_ecn_revision,
                "matrix_sha256": matrix_sha,
            },
            confidence="deterministic",
            result={
                "readiness_pct": readiness_pct,
                "ready_count": str(ready_count),
                "open_gap_count": str(gap_count),
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
                    "record_kind": "part21j_moc_matrix",
                    "program_id": program_id,
                    "active_ecn_revision": active_ecn_revision,
                    "readiness_pct": readiness_pct,
                    "ready_count": str(ready_count),
                    "open_gap_count": str(gap_count),
                    "matrix_sha256": matrix_sha,
                },
                "envelope": env,
            },
        )
        result["ledger_event_hash"] = ev_hash
        result["merkle_root"] = ledger.merkle_root()
    else:
        result["merkle_root"] = matrix_sha

    return result


def export_moc_matrix_xlsx(
    matrix: dict[str, Any],
    *,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export Part 21J MoC Matrix multi-tab live-formula Excel workbook (CWE-1236 safe)."""
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "1_Program_Readiness"
    ws_mat = wb.create_sheet("2_CS29_MoC_Matrix")
    ws_gap = wb.create_sheet("3_Open_Gaps")

    formula_count = 0

    mat_hdr = [
        "CS Paragraph",
        "Title",
        "Required MoCs",
        "Provided MoCs",
        "Min MS",
        "Revision",
        "Evidence Hashes",
        "CVE ID",
        "Readiness Status",
    ]
    ws_mat.append(mat_hdr)
    _style_header_row(ws_mat, 1, len(mat_hdr))
    ws_mat.freeze_panes = "A2"

    rows = list(matrix.get("matrix_rows") or [])
    for idx, r in enumerate(rows, start=2):
        ms_val = r.get("min_governing_ms")
        ms_cell: Any = _num_val(ms_val) if ms_val not in (None, "N/A", "") else "N/A"
        ws_mat.append(
            [
                _sanitize_excel_text(r.get("cs_paragraph", "")),
                _sanitize_excel_text(r.get("title", "")),
                _sanitize_excel_text(", ".join(r.get("required_mocs") or [])),
                _sanitize_excel_text(", ".join(r.get("provided_mocs") or [])),
                ms_cell,
                _sanitize_excel_text(r.get("revision", "")),
                len(r.get("evidence_hashes") or []),
                _sanitize_excel_text(r.get("cve_id", "")),
                _sanitize_excel_text(r.get("status", "")),
            ]
        )
        if isinstance(ms_cell, (int, float)):
            ws_mat.cell(row=idx, column=5).number_format = "0.0000"

    mat_last = max(2, 1 + len(rows))
    mat_tot = mat_last + 1
    ws_mat.append(
        [
            "PROGRAM TOTALS",
            f"=COUNTA(A2:A{mat_last})",
            "",
            "",
            f'=COUNTIF(I2:I{mat_last},"READY_FOR_CVE_REVIEW")+COUNTIF(I2:I{mat_last},"CVE_SIGNED_ADVISORY")',
            f'=COUNTIF(I2:I{mat_last},"CVE_SIGNED_ADVISORY")',
            f"=SUM(G2:G{mat_last})",
            "",
            f'=IF(E{mat_tot}=B{mat_tot},"ALL_ROWS_READY","GAPS_PRESENT")',
        ]
    )
    formula_count += 5
    for c_i in range(1, len(mat_hdr) + 1):
        ws_mat.cell(row=mat_tot, column=c_i).font = _BOLD_FONT
        ws_mat.cell(row=mat_tot, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_mat)

    gap_hdr = ["CS Paragraph", "Title", "Gap Status", "Severity", "Reason"]
    ws_gap.append(gap_hdr)
    _style_header_row(ws_gap, 1, len(gap_hdr))
    ws_gap.freeze_panes = "A2"
    gaps = list(matrix.get("open_gaps") or [])
    if gaps:
        for g in gaps:
            ws_gap.append(
                [
                    _sanitize_excel_text(g.get("cs_paragraph", "")),
                    _sanitize_excel_text(g.get("title", "")),
                    _sanitize_excel_text(g.get("status", "")),
                    int(g.get("severity") or 3),
                    _sanitize_excel_text(g.get("reason", "")),
                ]
            )
        gap_last = 1 + len(gaps)
    else:
        ws_gap.append(["NONE", "No Open Gaps", "NONE", 0, "All rows ready"])
        gap_last = 2
    ws_gap.append(
        [
            "GAP COUNT",
            f'=COUNTIF(C2:C{gap_last},"GAP_*")',
            "",
            "",
            "",
        ]
    )
    formula_count += 1
    _autofit_columns(ws_gap)

    ws_sum.append(["AeroRegu — Part 21J Means-of-Compliance Readiness Aid", "", ""])
    ws_sum["A1"].font = _TITLE_FONT
    ws_sum.append(["ADVISORY NOTICE", ASSISTANCE_DISCLAIMER, ""])
    ws_sum.append(["Metric", "Live Formula / Value", "Source"])
    _style_header_row(ws_sum, 3, 3)

    summary_rows = [
        ("Program ID", _sanitize_excel_text(matrix.get("program_id", "")), "Metadata"),
        ("Active ECN Revision", _sanitize_excel_text(matrix.get("active_ecn_revision", "")), "CM"),
        ("Requirements Tracked", f"='2_CS29_MoC_Matrix'!B{mat_tot}", "Live Matrix"),
        ("Rows Ready for CVE Review", f"='2_CS29_MoC_Matrix'!E{mat_tot}", "Live Matrix"),
        ("CVE Signed Rows (Advisory)", f"='2_CS29_MoC_Matrix'!F{mat_tot}", "Live Signoffs"),
        ("Readiness (%)", "=(B7/B6)*100", "Live Ratio"),
        ("Open Gaps Count", f"='3_Open_Gaps'!B{gap_last + 1}", "Live Gaps"),
        ("Package Gate", f"='2_CS29_MoC_Matrix'!I{mat_tot}", "Live Gate"),
        ("Ledger Merkle Root", _sanitize_excel_text(matrix.get("merkle_root", "")), "Audit Trail"),
    ]
    for r_i, (lbl, val, src) in enumerate(summary_rows, start=4):
        ws_sum.append([lbl, val, src])
        if isinstance(val, str) and val.startswith("="):
            formula_count += 1
            if "%" in lbl:
                ws_sum.cell(row=r_i, column=2).number_format = "0.00"
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


def export_moc_matrix_pdf(
    matrix: dict[str, Any],
    *,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export Ed25519 DSSE + ISO QR signed PDF Part 21J MoC Readiness Matrix."""
    priv_pem, pub_pem = _resolve_signing_keypair(private_key_pem, public_key_pem)
    merkle = str(matrix.get("merkle_root") or matrix.get("matrix_sha256") or ("0" * 64))
    pid = str(matrix.get("program_id") or "PROG-H145-MOD")

    attestation_payload = {
        "schema": "evidence-layer/part21j-moc-matrix@1.0.0",
        "program_id": pid,
        "active_ecn_revision": str(matrix.get("active_ecn_revision") or "REV-A"),
        "requirement_count": int(matrix.get("requirement_count") or 0),
        "ready_count": int(matrix.get("ready_count") or 0),
        "open_gap_count": int(matrix.get("open_gap_count") or 0),
        "readiness_pct": str(matrix.get("readiness_pct") or "0.00"),
        "merkle_root": merkle,
    }
    dsse_envelope = sign_attestation_dsse(attestation_payload, priv_pem)
    dsse_bytes = json.dumps(dsse_envelope, sort_keys=True, indent=2).encode("utf-8")
    sig_raw = base64.b64decode(dsse_envelope["signatures"][0]["sig"])
    sig_sha256 = hashlib.sha256(sig_raw).hexdigest()

    qr_payload = "aeroregu-moc:" + json.dumps(
        {
            "v": 1,
            "p": pid[:16],
            "m": merkle[:16],
            "s": sig_sha256[:16],
            "r": str(matrix.get("readiness_pct") or ""),
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
        f"AeroRegu - Part 21J MoC Readiness Package ({pid})",
        fontsize=12.5,
        color=(1, 1, 1),
    )
    page.insert_text((44, 74), ASSISTANCE_DISCLAIMER, fontsize=8.2, color=(0.82, 0.88, 0.96))
    page.insert_image(pymupdf.Rect(452, 108, 556, 212), stream=qr_png)

    lines = [
        f"Program ID: {pid}  |  ECN Revision: {matrix.get('active_ecn_revision')}",
        (
            f"Readiness: {matrix.get('readiness_pct')}% "
            f"({matrix.get('ready_count')}/{matrix.get('requirement_count')}) | "
            f"CVE Signed: {matrix.get('cve_signed_count')}"
        ),
        f"Open Gaps: {matrix.get('open_gap_count')} | Overall: {matrix.get('overall_status')}",
        f"Ledger Merkle Root: {merkle[:48]}...",
    ]
    y = 124
    for ln in lines:
        page.insert_text((38, y), ln[:92], fontsize=9.0, color=(0.1, 0.14, 0.22))
        y += 16

    y += 14
    page.insert_text((38, y), "CS-29 Means-of-Compliance Matrix", fontsize=11.0)
    y += 16
    for row in (matrix.get("matrix_rows") or [])[:26]:
        if y > 790:
            break
        row_s = (
            f"{row['cs_paragraph']:10s} | MoCs={','.join(row['required_mocs'])[:16]} | "
            f"MS={row['min_governing_ms']} | Rev={row['revision']} | {row['status']}"
        )
        page.insert_text((40, y), row_s[:95], fontsize=7.8, color=(0.14, 0.18, 0.26))
        y += 13

    doc.embfile_add(
        _DSSE_ATTACHMENT_NAME,
        dsse_bytes,
        filename=_DSSE_ATTACHMENT_NAME,
        desc="DSSE v1 Ed25519 Part 21J MoC Matrix Attestation",
    )
    doc.embfile_add(
        _PUBKEY_ATTACHMENT_NAME,
        pub_pem,
        filename=_PUBKEY_ATTACHMENT_NAME,
        desc="Ed25519 Verification Public Key (PEM)",
    )
    doc.set_metadata(
        {
            "title": f"AeroRegu Part 21J MoC Readiness ({pid})",
            "subject": f"merkle={merkle}",
            "keywords": qr_payload,
            "creator": "aeroregu-moc-matrix-exporter",
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
