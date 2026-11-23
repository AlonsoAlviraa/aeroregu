"""Closed-Loop Bid-to-Actual ERP Earned Value Management (EVM) Post-Mortem Engine.

Compares ERP/SAP actual hours & costs against a sealed Composite Rotorcraft Baseline Dossier,
computes standard PMI/Aerospace EVM metrics (BAC, PV, EV, AC, CV, SV, CPI, SPI, EAC, VAC, TCPI)
per WBS archetype and program total, attributes variance root causes to broken master assumptions,
exports calibration-ready records for historical/advanced quotation calibration,
and seals an immutable `bid_actual_postmortem` event into the cryptographic Ledger.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from evidence_calc.quantize import format_quantum
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record
from openpyxl import load_workbook

from evidence_coverage.historical_quotation_calibrator import HistoricalQuotationRecord
from evidence_coverage.rotorcraft_quotation_catalog import ROTORCRAFT_MASTER_ASSUMPTIONS

_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")

_ASM_BY_ID: dict[str, dict[str, Any]] = {
    a["assumption_id"]: a for a in ROTORCRAFT_MASTER_ASSUMPTIONS
}


def _d(val: Any, default: str = "0") -> Decimal:
    if val is None or str(val).strip() == "":
        return Decimal(default)
    try:
        return Decimal(str(val).strip())
    except Exception:
        return Decimal(default)


def parse_erp_actuals_input(
    actuals: list[dict[str, Any]] | str | Path | None = None,
    *,
    actuals_csv: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize ERP/SAP actuals from list[dict], CSV text, .csv file, or .xlsx workbook."""
    if isinstance(actuals, list):
        return [dict(row) for row in actuals if isinstance(row, dict)]

    if actuals_csv and actuals_csv.strip():
        reader = csv.DictReader(io.StringIO(actuals_csv.strip()))
        return [dict(r) for r in reader]

    if isinstance(actuals, (str, Path)):
        raw_str = str(actuals).strip()
        p = Path(raw_str)
        if p.is_file():
            suf = p.suffix.lower()
            if suf == ".xlsx":
                wb = load_workbook(filename=p, read_only=True, data_only=True)
                try:
                    ws = wb.active
                    rows = list(ws.iter_rows(values_only=True))
                finally:
                    wb.close()
                if len(rows) < 2:
                    return []
                headers = [str(c or "").strip() for c in rows[0]]
                out: list[dict[str, Any]] = []
                for row in rows[1:]:
                    if not any(cell is not None and str(cell).strip() != "" for cell in row):
                        continue
                    out.append(
                        {
                            headers[idx]: (row[idx] if idx < len(row) else "")
                            for idx in range(len(headers))
                            if headers[idx]
                        }
                    )
                return out
            content = p.read_text(encoding="utf-8", errors="ignore")
            return [dict(r) for r in csv.DictReader(io.StringIO(content))]
        if "\n" in raw_str or "," in raw_str:
            return [dict(r) for r in csv.DictReader(io.StringIO(raw_str))]

    return []


def _parse_broken_ids(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        items = [x.strip() for x in raw.replace(",", ";").split(";") if x.strip()]
    else:
        items = []
    return list(dict.fromkeys(items))


def _attribute_assumption(asm_id: str, cause: str, overrun_hours: Decimal) -> dict[str, str]:
    rec = _ASM_BY_ID.get(asm_id, {})
    return {
        "assumption_id": asm_id,
        "dimension": str(rec.get("dimension") or "COMMERCIAL_AND_RATES"),
        "title": str(rec.get("title") or asm_id),
        "attributed_overrun_hours": format_quantum(overrun_hours, _Q2),
        "cause": cause,
    }


def run_bid_actual_evm_postmortem(
    ledger: Ledger,
    baseline_dossier: dict[str, Any],
    actuals: list[dict[str, Any]] | str | Path | None = None,
    *,
    actuals_csv: str | None = None,
    project_id: str | None = None,
    actual_ecn_iterations: int = 0,
    idp_rework_hours: str = "0",
    unbilled_scope_hours: str = "0",
    cve_rework_hours: str = "0",
    actor_id: str = "stress-office-controller",
    created_at: str | None = None,
) -> dict[str, Any]:
    """Run closed-loop Bid vs Actual EVM analysis, variance attribution & Ledger sealing."""
    rows = parse_erp_actuals_input(actuals, actuals_csv=actuals_csv)
    by_arch: dict[str, dict[str, Any]] = {}
    for row in rows:
        aid = str(row.get("archetype_id") or "").strip()
        if aid:
            by_arch[aid] = row

    dag = baseline_dossier.get("composite_wbs_dag") or {}
    nodes = list(dag.get("nodes") or [])
    if not nodes:
        raise ValueError("baseline_dossier_missing_composite_wbs_dag_nodes")

    cls_res = baseline_dossier.get("classification") or {}
    country_prof = baseline_dossier.get("country_profile") or {}
    idp_res = baseline_dossier.get("idp_physical_extraction") or {}
    spec = baseline_dossier.get("spec") or {}

    country_code = str(country_prof.get("country_code") or spec.get("country_code") or "EU_DEFAULT")
    cert_basis = str(cls_res.get("cert_basis") or "CS-29")
    mat_family = str(cls_res.get("material_family") or "HYBRID_AL_CFRP")
    cosysmo_cx = str(idp_res.get("derived_cosysmo_complexity") or "NOMINAL")
    idp_mat = str(idp_res.get("derived_idp_maturity") or "PARTIAL")

    rfq_id = str(baseline_dossier.get("rfq_id") or "RFQ-UNKNOWN")
    proj_id = str(project_id or f"POST-{rfq_id}")
    ts = created_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    per_node_evm: list[dict[str, Any]] = []
    calibrated_records: list[dict[str, Any]] = []

    tot_quoted_hours = _ZERO
    tot_actual_hours = _ZERO
    tot_bac = _ZERO
    tot_pv = _ZERO
    tot_ev = _ZERO
    tot_ac = _ZERO
    tot_selling_price = _ZERO
    broken_ids_all: list[str] = []

    with localcontext() as ctx:
        ctx.prec = 30
        for node in nodes:
            aid = str(node["archetype_id"])
            q_hrs = _d(node.get("net_hours"), "0")
            bac_cost = _d(node.get("net_cost_eur"), "0")
            sell_price = _d(node.get("net_price_eur"), "0")
            hourly_implied = (bac_cost / q_hrs) if q_hrs > _ZERO else Decimal("110.000")

            act_row = by_arch.get(aid) or {}
            a_hrs = (
                _d(act_row.get("actual_hours") or act_row.get("actual_burned_hours"))
                if act_row and (act_row.get("actual_hours") or act_row.get("actual_burned_hours"))
                else q_hrs
            )
            a_cost = (
                _d(act_row.get("actual_cost_eur"))
                if act_row and act_row.get("actual_cost_eur") not in (None, "")
                else a_hrs * hourly_implied
            )
            earned_pct = max(
                _ZERO,
                min(_HUNDRED, _d(act_row.get("earned_pct"), "100")),
            )
            planned_pct = max(
                _ZERO,
                min(_HUNDRED, _d(act_row.get("planned_pct"), "100")),
            )

            pv = bac_cost * (planned_pct / _HUNDRED)
            ev = bac_cost * (earned_pct / _HUNDRED)
            ac = a_cost
            cv = ev - ac
            sv = ev - pv
            cpi = (ev / ac) if ac > _ZERO else _ONE
            spi = (ev / pv) if pv > _ZERO else _ONE
            eac = (bac_cost / cpi) if cpi > _ZERO else bac_cost
            hrs_var = a_hrs - q_hrs
            hrs_var_pct = (hrs_var / q_hrs) * _HUNDRED if q_hrs > _ZERO else _ZERO

            row_broken = _parse_broken_ids(act_row.get("broken_assumptions"))
            if hrs_var_pct > Decimal("10") and not row_broken:
                row_broken = ["ASM-TS-01"]
            for bid in row_broken:
                if bid not in broken_ids_all:
                    broken_ids_all.append(bid)

            node_outcome = "WON_OVERRUN" if hrs_var_pct > Decimal("5") else "WON_ON_BUDGET"

            tot_quoted_hours += q_hrs
            tot_actual_hours += a_hrs
            tot_bac += bac_cost
            tot_pv += pv
            tot_ev += ev
            tot_ac += ac
            tot_selling_price += sell_price

            per_node_evm.append(
                {
                    "archetype_id": aid,
                    "quoted_hours": format_quantum(q_hrs, _Q2),
                    "actual_hours": format_quantum(a_hrs, _Q2),
                    "hours_variance": format_quantum(hrs_var, _Q2),
                    "hours_variance_pct": format_quantum(hrs_var_pct, _Q2),
                    "bac_cost_eur": format_quantum(bac_cost, _Q3),
                    "pv_eur": format_quantum(pv, _Q3),
                    "ev_eur": format_quantum(ev, _Q3),
                    "ac_eur": format_quantum(ac, _Q3),
                    "cv_eur": format_quantum(cv, _Q3),
                    "sv_eur": format_quantum(sv, _Q3),
                    "cpi": format_quantum(cpi, _Q3),
                    "spi": format_quantum(spi, _Q3),
                    "eac_eur": format_quantum(eac, _Q3),
                    "outcome": node_outcome,
                }
            )

            hist_rec = HistoricalQuotationRecord(
                quote_id=f"{proj_id}-{aid}",
                archetype_id=aid,
                country_code=country_code,
                cert_basis=cert_basis,
                material_family=mat_family,
                cosysmo_complexity=cosysmo_cx,
                idp_maturity=idp_mat,
                fem_nodes_count=int(idp_res.get("fem_nodes_count") or 0),
                load_cases_count=int(idp_res.get("load_cases_count") or 0),
                cbush_joints_count=int(idp_res.get("cbush_joints_count") or 0),
                cad_drawings_count=int(idp_res.get("dxf_entities_count") or 0),
                ply_count=int(idp_res.get("pcomp_laminates_count") or 0),
                quoted_hours=format_quantum(q_hrs, _Q3),
                actual_burned_hours=format_quantum(a_hrs, _Q3),
                quoted_price_eur=format_quantum(sell_price, _Q3),
                actual_cost_eur=format_quantum(ac, _Q3),
                ecn_iterations_actual=max(0, int(actual_ecn_iterations)),
                broken_assumption_ids=tuple(row_broken),
                outcome=node_outcome,
                record_sha256=str(baseline_dossier.get("merkle_root") or "0" * 64),
            )
            calibrated_records.append(
                {
                    "quote_id": hist_rec.quote_id,
                    "archetype_id": hist_rec.archetype_id,
                    "country_code": hist_rec.country_code,
                    "cert_basis": hist_rec.cert_basis,
                    "material_family": hist_rec.material_family,
                    "cosysmo_complexity": hist_rec.cosysmo_complexity,
                    "idp_maturity": hist_rec.idp_maturity,
                    "fem_nodes_count": hist_rec.fem_nodes_count,
                    "load_cases_count": hist_rec.load_cases_count,
                    "cbush_joints_count": hist_rec.cbush_joints_count,
                    "cad_drawings_count": hist_rec.cad_drawings_count,
                    "ply_count": hist_rec.ply_count,
                    "quoted_hours": hist_rec.quoted_hours,
                    "actual_burned_hours": hist_rec.actual_burned_hours,
                    "quoted_price_eur": hist_rec.quoted_price_eur,
                    "actual_cost_eur": hist_rec.actual_cost_eur,
                    "ecn_iterations_actual": hist_rec.ecn_iterations_actual,
                    "broken_assumption_ids": list(hist_rec.broken_assumption_ids),
                    "outcome": hist_rec.outcome,
                    "record_sha256": hist_rec.record_sha256,
                }
            )

        cv_tot = tot_ev - tot_ac
        sv_tot = tot_ev - tot_pv
        cpi_tot = (tot_ev / tot_ac) if tot_ac > _ZERO else _ONE
        spi_tot = (tot_ev / tot_pv) if tot_pv > _ZERO else _ONE
        eac_tot = (tot_bac / cpi_tot) if cpi_tot > _ZERO else tot_bac
        vac_tot = tot_bac - eac_tot
        rem_work = max(_ZERO, tot_bac - tot_ev)
        rem_budget = tot_bac - tot_ac
        tcpi_bac = (rem_work / rem_budget) if rem_budget > _ZERO else Decimal("9.999")
        tot_hrs_var = tot_actual_hours - tot_quoted_hours
        tot_hrs_var_pct = (
            (tot_hrs_var / tot_quoted_hours) * _HUNDRED if tot_quoted_hours > _ZERO else _ZERO
        )
        realized_margin_eur = tot_selling_price - tot_ac
        realized_margin_pct = (
            (realized_margin_eur / tot_selling_price) * _HUNDRED
            if tot_selling_price > _ZERO
            else _ZERO
        )

    # Root-cause attribution to ROTORCRAFT_MASTER_ASSUMPTIONS
    idp_rew = _d(idp_rework_hours)
    unbilled_hrs = _d(unbilled_scope_hours)
    cve_rew = _d(cve_rework_hours)
    attributions: list[dict[str, str]] = []
    if idp_rew > _ZERO or "ASM-IDP-01" in broken_ids_all:
        attributions.append(
            _attribute_assumption(
                "ASM-IDP-01",
                "OEM IDP CAD/GFEM freeze incomplete or delayed relative to baseline gate.",
                idp_rew,
            )
        )
    if (
        int(actual_ecn_iterations) > int(spec.get("ecn_iterations") or 2)
        or "ASM-SCH-01" in broken_ids_all
    ):
        attributions.append(
            _attribute_assumption(
                "ASM-SCH-01",
                f"Realized ECN design loops ({actual_ecn_iterations}) exceeded baseline allowance.",
                max(_ZERO, tot_hrs_var - idp_rew - unbilled_hrs - cve_rew),
            )
        )
    if unbilled_hrs > _ZERO or "ASM-TS-01" in broken_ids_all:
        attributions.append(
            _attribute_assumption(
                "ASM-TS-01",
                "Unbilled OEM scope creep detected; Change-Order (CCN) recovery recommended.",
                unbilled_hrs,
            )
        )
    if cve_rew > _ZERO or "ASM-DOA-01" in broken_ids_all:
        attributions.append(
            _attribute_assumption(
                "ASM-DOA-01",
                "Part 21J CVE compliance check-signoff iteration exceeded baseline allocation.",
                cve_rew,
            )
        )
    if cpi_tot < Decimal("0.90") and not attributions:
        attributions.append(
            _attribute_assumption(
                "ASM-CM-01",
                "Program cost performance index (CPI < 0.90) indicates rate/efficiency erosion.",
                max(_ZERO, tot_hrs_var),
            )
        )

    if cpi_tot >= Decimal("0.98") and spi_tot >= Decimal("0.98"):
        health = "ON_BUDGET_ON_SCHEDULE"
    elif cpi_tot >= Decimal("0.90"):
        health = "WATCH_VARIANCE"
    else:
        health = "OVERRUN_CALIBRATION_ALERT"

    evm_summary = {
        "bac_cost_eur": format_quantum(tot_bac, _Q3),
        "pv_eur": format_quantum(tot_pv, _Q3),
        "ev_eur": format_quantum(tot_ev, _Q3),
        "ac_eur": format_quantum(tot_ac, _Q3),
        "cv_eur": format_quantum(cv_tot, _Q3),
        "sv_eur": format_quantum(sv_tot, _Q3),
        "cpi": format_quantum(cpi_tot, _Q3),
        "spi": format_quantum(spi_tot, _Q3),
        "eac_eur": format_quantum(eac_tot, _Q3),
        "vac_eur": format_quantum(vac_tot, _Q3),
        "tcpi_bac": format_quantum(tcpi_bac, _Q3),
        "quoted_hours": format_quantum(tot_quoted_hours, _Q2),
        "actual_hours": format_quantum(tot_actual_hours, _Q2),
        "hours_variance": format_quantum(tot_hrs_var, _Q2),
        "hours_variance_pct": format_quantum(tot_hrs_var_pct, _Q2),
        "quoted_selling_price_eur": format_quantum(tot_selling_price, _Q3),
        "realized_margin_eur": format_quantum(realized_margin_eur, _Q3),
        "realized_margin_pct": format_quantum(realized_margin_pct, _Q2),
    }

    payload = {
        "record_kind": "bid_actual_postmortem",
        "project_id": proj_id,
        "baseline_rfq_id": rfq_id,
        "baseline_merkle_root": baseline_dossier.get("merkle_root"),
        "health_status": health,
        "evm_summary": evm_summary,
        "broken_assumptions_attributed": attributions,
        "calibrated_records_count": len(calibrated_records),
    }
    env = make_envelope(
        sources=[
            project_source(
                "bid-actual-evm-postmortem",
                f"https://aeroregu.local/rotorcraft/postmortem/{proj_id}",
                "ESTIMATE",
            )
        ],
        method_version="bid_actual_postmortem@1.0.0",
        inputs={
            "project_id": proj_id,
            "baseline_rfq_id": rfq_id,
            "nodes_count": len(per_node_evm),
            "actual_ecn_iterations": int(actual_ecn_iterations),
        },
        confidence="deterministic",
        result=payload,
    )
    ev_hash = record(
        ledger,
        {
            "event_type": "calc",
            "tenant_id": ledger.tenant_id,
            "actor_id": actor_id,
            "created_at": ts,
            "payload": payload,
            "envelope": env,
        },
    )

    return {
        "project_id": proj_id,
        "baseline_rfq_id": rfq_id,
        "baseline_merkle_root": baseline_dossier.get("merkle_root"),
        "tenant_id": ledger.tenant_id,
        "health_status": health,
        "evm_summary": evm_summary,
        "per_node_evm": per_node_evm,
        "broken_assumptions_attributed": attributions,
        "calibrated_historical_records": calibrated_records,
        "postmortem_event_hash": ev_hash,
        "merkle_root": ledger.merkle_root(),
        "advisory_boundary": (
            "EVM post-mortem provides deterministic ASSUMPTION/ESTIMATE project feedback; "
            "human sign-off required prior to repricing or ERP close-out."
        ),
    }
