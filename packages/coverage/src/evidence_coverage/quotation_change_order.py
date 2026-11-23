"""Closed-Loop Change-Order (CCN / CR) Delta Pricer & Assumption Trigger Mapper.

Compares an approved Rev A Baseline Composite Dossier against a Rev B Change Request,
re-pricing WBS DAG nodes, CPM critical path, engineering synergy, multi-year Wright/Crawford
cash flow & NPV, deep physical IDP deltas, contractual poison clauses, and Z3 SMT proofs,
while sealing an immutable `quotation_change_order` event into the cryptographic ledger.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from evidence_calc.quantize import format_quantum
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record

from evidence_coverage.composite_dag_quotation import (
    CompositeRotorcraftQuotationSpec,
    run_composite_rotorcraft_quotation,
)
from evidence_coverage.rotorcraft_quotation_catalog import ROTORCRAFT_MASTER_ASSUMPTIONS

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")

_ASSUMPTION_BY_ID: dict[str, dict[str, Any]] = {
    a["assumption_id"]: a for a in ROTORCRAFT_MASTER_ASSUMPTIONS
}


def _d(val: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def _coerce_spec(
    revised_spec: CompositeRotorcraftQuotationSpec | dict[str, Any],
    *,
    enforce_contract_gate: bool,
) -> CompositeRotorcraftQuotationSpec:
    if isinstance(revised_spec, CompositeRotorcraftQuotationSpec):
        raw = asdict(revised_spec)
    elif isinstance(revised_spec, dict):
        allowed = {f.name for f in fields(CompositeRotorcraftQuotationSpec)}
        raw = {k: v for k, v in revised_spec.items() if k in allowed}
        if isinstance(raw.get("archetype_ids"), list):
            raw["archetype_ids"] = tuple(raw["archetype_ids"])
        if isinstance(raw.get("custom_edges"), list):
            raw["custom_edges"] = tuple(tuple(e) for e in raw["custom_edges"])
    else:
        raise TypeError("revised_spec must be CompositeRotorcraftQuotationSpec or dict")
    raw["enforce_contract_gate"] = bool(enforce_contract_gate)
    return CompositeRotorcraftQuotationSpec(**raw)


def _assumption_hit(asm_id: str, reason: str) -> dict[str, str]:
    rec = _ASSUMPTION_BY_ID.get(asm_id, {})
    return {
        "assumption_id": asm_id,
        "dimension": str(rec.get("dimension") or "COMMERCIAL_AND_RATES"),
        "title": str(rec.get("title") or asm_id),
        "change_order_trigger": str(rec.get("change_order_trigger") or ""),
        "trigger_reason": reason,
    }


def compute_quotation_change_order(
    ledger: Ledger,
    baseline_dossier: dict[str, Any],
    revised_spec: CompositeRotorcraftQuotationSpec | dict[str, Any],
    *,
    cr_id: str = "CCN-001",
    change_reason: str = "",
    enforce_contract_gate: bool = True,
) -> dict[str, Any]:
    """Compute closed-loop Rev A -> Rev B Change-Order delta dossier & seal into Ledger."""
    eff_spec = _coerce_spec(revised_spec, enforce_contract_gate=enforce_contract_gate)
    revised_dossier = run_composite_rotorcraft_quotation(ledger, eff_spec)

    created_at = eff_spec.created_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    base_merkle = str(baseline_dossier.get("merkle_root") or "")
    rev_merkle = str(revised_dossier.get("merkle_root") or "")

    # Fail-closed immediately when Rev B triggers ABSTAIN (cycle or blocking poison clause)
    if revised_dossier.get("confidence") == "abstain":
        ca_rev = revised_dossier.get("contract_audit") or {}
        env = make_envelope(
            sources=[
                project_source(
                    "quotation-change-order",
                    f"https://aeroregu.local/rotorcraft/change-order/{cr_id}",
                    "ASSUMPTION",
                )
            ],
            method_version="quotation_change_order@1.0.0",
            inputs={
                "cr_id": cr_id,
                "baseline_merkle_root": base_merkle,
                "revised_merkle_root": rev_merkle,
            },
            confidence="abstain",
            abstain_reason=str(revised_dossier.get("abstain_reason") or "revised_spec_abstain"),
        )
        ev_hash = record(
            ledger,
            {
                "event_type": "abstain",
                "tenant_id": ledger.tenant_id,
                "actor_id": eff_spec.actor_id,
                "created_at": created_at,
                "payload": {
                    "cr_id": cr_id,
                    "baseline_merkle_root": base_merkle,
                    "revised_merkle_root": rev_merkle,
                    "reason": revised_dossier.get("abstain_reason"),
                },
                "envelope": env,
            },
        )
        return {
            "cr_id": cr_id,
            "change_reason": change_reason,
            "baseline_rfq_id": baseline_dossier.get("rfq_id"),
            "revised_rfq_id": revised_dossier.get("rfq_id"),
            "confidence": "abstain",
            "decision_status": "ABSTAIN_ESCALATED",
            "abstain_reason": revised_dossier.get("abstain_reason"),
            "baseline_merkle_root": base_merkle,
            "revised_merkle_root": rev_merkle,
            "change_order_event_hash": ev_hash,
            "change_order_merkle_root": ledger.merkle_root(),
            "contract_delta": {
                "base_gate": (baseline_dossier.get("contract_audit") or {}).get(
                    "overall_contract_gate"
                ),
                "revised_gate": ca_rev.get("overall_contract_gate"),
                "new_poison_clauses": ca_rev.get("poison_clauses_detected") or [],
            },
            "revised_dossier": revised_dossier,
        }

    # Extract baseline and revised structured sub-documents
    base_dag = baseline_dossier.get("composite_wbs_dag") or {}
    rev_dag = revised_dossier.get("composite_wbs_dag") or {}
    base_nodes = {n["archetype_id"]: n for n in (base_dag.get("nodes") or [])}
    rev_nodes = {n["archetype_id"]: n for n in (rev_dag.get("nodes") or [])}

    added_archs = sorted(set(rev_nodes) - set(base_nodes))
    removed_archs = sorted(set(base_nodes) - set(rev_nodes))
    retained_archs = sorted(set(base_nodes) & set(rev_nodes))

    node_deltas: list[dict[str, Any]] = []
    for aid in sorted(set(base_nodes) | set(rev_nodes)):
        bn = base_nodes.get(aid)
        rn = rev_nodes.get(aid)
        status = "RETAINED" if (bn and rn) else ("ADDED" if rn else "REMOVED")
        bh = _d(bn["net_hours"]) if bn else _ZERO
        rh = _d(rn["net_hours"]) if rn else _ZERO
        bp = _d(bn["net_price_eur"]) if bn else _ZERO
        rp = _d(rn["net_price_eur"]) if rn else _ZERO
        bf = _d(bn["total_float_weeks"]) if bn else _ZERO
        rf = _d(rn["total_float_weeks"]) if rn else _ZERO
        node_deltas.append(
            {
                "archetype_id": aid,
                "change_status": status,
                "base_hours": format_quantum(bh, _Q3),
                "revised_hours": format_quantum(rh, _Q3),
                "delta_hours": format_quantum(rh - bh, _Q3),
                "base_price_eur": format_quantum(bp, _Q3),
                "revised_price_eur": format_quantum(rp, _Q3),
                "delta_price_eur": format_quantum(rp - bp, _Q3),
                "base_float_weeks": format_quantum(bf, _Q2),
                "revised_float_weeks": format_quantum(rf, _Q2),
                "became_critical": bool(
                    (not bn or not bn.get("is_critical")) and (rn and rn.get("is_critical"))
                ),
            }
        )

    # CPM Schedule delta
    base_cp = list(base_dag.get("critical_path_archetypes") or [])
    rev_cp = list(rev_dag.get("critical_path_archetypes") or [])
    base_dur = _d(base_dag.get("project_duration_weeks"))
    rev_dur = _d(rev_dag.get("project_duration_weeks"))
    delta_dur = rev_dur - base_dur
    newly_critical = sorted(set(rev_cp) - set(base_cp))

    # Financial delta (WBS + PERT P80 + Multi-Year Cashflow & NPV)
    base_h = _d(base_dag.get("synergy_net_total_hours"))
    rev_h = _d(rev_dag.get("synergy_net_total_hours"))
    base_c = _d(base_dag.get("synergy_net_total_cost_eur"))
    rev_c = _d(rev_dag.get("synergy_net_total_cost_eur"))

    base_p80 = _d((baseline_dossier.get("pert_envelope") or {}).get("price_p80_eur"))
    rev_p80 = _d((revised_dossier.get("pert_envelope") or {}).get("price_p80_eur"))

    base_my = (baseline_dossier.get("multiyear_cashflow_learning") or {}).get("outputs") or {}
    rev_my = (revised_dossier.get("multiyear_cashflow_learning") or {}).get("outputs") or {}
    base_mq = _d(base_my.get("quoted_price_eur"))
    rev_mq = _d(rev_my.get("quoted_price_eur"))
    base_npv = _d(base_my.get("net_present_value_eur"))
    rev_npv = _d(rev_my.get("net_present_value_eur"))
    base_pk = _d(base_my.get("peak_negative_cashflow_eur"))
    rev_pk = _d(rev_my.get("peak_negative_cashflow_eur"))

    delta_mq = rev_mq - base_mq
    delta_pct = (delta_mq / base_mq) * _HUNDRED if base_mq > _ZERO else _ZERO

    financial_delta = {
        "base_net_hours": format_quantum(base_h, _Q3),
        "revised_net_hours": format_quantum(rev_h, _Q3),
        "delta_net_hours": format_quantum(rev_h - base_h, _Q3),
        "base_net_cost_eur": format_quantum(base_c, _Q3),
        "revised_net_cost_eur": format_quantum(rev_c, _Q3),
        "delta_net_cost_eur": format_quantum(rev_c - base_c, _Q3),
        "base_p80_price_eur": format_quantum(base_p80, _Q3),
        "revised_p80_price_eur": format_quantum(rev_p80, _Q3),
        "delta_p80_price_eur": format_quantum(rev_p80 - base_p80, _Q3),
        "base_multiyear_quoted_price_eur": format_quantum(base_mq, _Q3),
        "revised_multiyear_quoted_price_eur": format_quantum(rev_mq, _Q3),
        "delta_multiyear_quoted_price_eur": format_quantum(delta_mq, _Q3),
        "delta_price_pct": format_quantum(delta_pct, _Q2),
        "base_multiyear_npv_eur": format_quantum(base_npv, _Q3),
        "revised_multiyear_npv_eur": format_quantum(rev_npv, _Q3),
        "delta_multiyear_npv_eur": format_quantum(rev_npv - base_npv, _Q3),
        "base_peak_negative_cashflow_eur": format_quantum(base_pk, _Q3),
        "revised_peak_negative_cashflow_eur": format_quantum(rev_pk, _Q3),
        "delta_peak_negative_cashflow_eur": format_quantum(rev_pk - base_pk, _Q3),
    }

    # Physical IDP delta
    base_idp = baseline_dossier.get("idp_physical_extraction") or {}
    rev_idp = revised_dossier.get("idp_physical_extraction") or {}
    d_fem_nodes = int(rev_idp.get("fem_nodes_count") or 0) - int(
        base_idp.get("fem_nodes_count") or 0
    )
    d_fem_elems = int(rev_idp.get("fem_elements_count") or 0) - int(
        base_idp.get("fem_elements_count") or 0
    )
    d_load_cases = int(rev_idp.get("load_cases_count") or 0) - int(
        base_idp.get("load_cases_count") or 0
    )
    d_btf = _d(rev_idp.get("step_buy_to_fly_ratio"), "1") - _d(
        base_idp.get("step_buy_to_fly_ratio"), "1"
    )
    d_bom = int(rev_idp.get("bom_parts_count") or 0) - int(base_idp.get("bom_parts_count") or 0)
    idp_delta = {
        "delta_fem_nodes": d_fem_nodes,
        "delta_fem_elements": d_fem_elems,
        "delta_load_cases": d_load_cases,
        "delta_step_buy_to_fly_ratio": format_quantum(d_btf, _Q3),
        "delta_bom_parts_count": d_bom,
    }

    # Contractual matrix delta
    base_ca = baseline_dossier.get("contract_audit") or {}
    rev_ca = revised_dossier.get("contract_audit") or {}
    base_gate = str(base_ca.get("overall_contract_gate") or "SUPPORTED")
    rev_gate = str(rev_ca.get("overall_contract_gate") or "SUPPORTED")
    base_poison_keys = {
        (p.get("poison_id"), p.get("excerpt"))
        for p in (base_ca.get("poison_clauses_detected") or [])
    }
    new_poisons = [
        p
        for p in (rev_ca.get("poison_clauses_detected") or [])
        if (p.get("poison_id"), p.get("excerpt")) not in base_poison_keys
    ]
    contract_delta = {
        "base_gate": base_gate,
        "revised_gate": rev_gate,
        "gate_transition": f"{base_gate} -> {rev_gate}",
        "base_poison_count": int(base_ca.get("poison_clauses_count") or 0),
        "revised_poison_count": int(rev_ca.get("poison_clauses_count") or 0),
        "new_poison_clauses": new_poisons,
    }

    # Deterministic mapping to Rotorcraft Master Assumptions triggered by this CR
    triggered_assumptions: list[dict[str, str]] = []
    if added_archs or removed_archs:
        triggered_assumptions.append(
            _assumption_hit(
                "ASM-TS-01",
                f"WBS scope modified: +{added_archs} / -{removed_archs}.",
            )
        )
    if (rev_h - base_h) > _ZERO:
        triggered_assumptions.append(
            _assumption_hit(
                "ASM-TS-02",
                f"Engineering workload increased by +{financial_delta['delta_net_hours']} h.",
            )
        )
    if any(aid.startswith("Q-DYN-") for aid in added_archs):
        dyn_added = [a for a in added_archs if a.startswith("Q-DYN-")]
        triggered_assumptions.append(
            _assumption_hit(
                "ASM-DY-01",
                f"Rotorcraft dynamics/crashworthiness scope added: {dyn_added}",
            )
        )
    if d_fem_elems != 0 or d_load_cases != 0 or d_bom != 0:
        triggered_assumptions.append(
            _assumption_hit(
                "ASM-IDP-03",
                (
                    f"IDP physical package delta: FEM elems {d_fem_elems:+d}, "
                    f"LCs {d_load_cases:+d}, BOM {d_bom:+d}."
                ),
            )
        )
    if delta_dur != _ZERO or newly_critical:
        triggered_assumptions.append(
            _assumption_hit(
                "ASM-SCH-01",
                (
                    f"CPM schedule duration delta {delta_dur:+.1f} w; "
                    f"newly critical: {newly_critical}."
                ),
            )
        )
    if delta_mq != _ZERO:
        d_mq_eur = financial_delta["delta_multiyear_quoted_price_eur"]
        d_pct_s = financial_delta["delta_price_pct"]
        triggered_assumptions.append(
            _assumption_hit(
                "ASM-COM-02",
                f"Commercial lot/scope delta of {d_mq_eur} EUR ({d_pct_s}%).",
            )
        )
    if (rev_pk - base_pk) != _ZERO:
        d_pk_eur = financial_delta["delta_peak_negative_cashflow_eur"]
        triggered_assumptions.append(
            _assumption_hit(
                "ASM-COM-04",
                f"Working-capital Peak Negative Cash Flow shifted by {d_pk_eur} EUR.",
            )
        )
    if new_poisons or rev_gate != base_gate:
        trans = contract_delta["gate_transition"]
        triggered_assumptions.append(
            _assumption_hit(
                "ASM-LEG-04",
                f"Contractual gate transition {trans} ({len(new_poisons)} new flags).",
            )
        )

    amended_margin_proof = revised_dossier.get("formal_margin_proof") or {}
    amended_npv_proof = revised_dossier.get("formal_multiyear_npv_proof") or {}
    both_proved = (not eff_spec.enable_formal_smt) or (
        bool(amended_margin_proof.get("proved")) and bool(amended_npv_proof.get("proved"))
    )
    decision_status = (
        "APPROVED_FOR_HUMAN_REVIEW" if both_proved else "MARGIN_FLOOR_COUNTEREXAMPLE_HOLD"
    )

    ccn_hash_payload = {
        "cr_id": cr_id,
        "baseline_merkle_root": base_merkle,
        "revised_merkle_root": rev_merkle,
        "financial_delta": financial_delta,
        "wbs_delta": {"added": added_archs, "removed": removed_archs, "nodes": node_deltas},
    }
    ccn_digest = hashlib.sha256(str(ccn_hash_payload).encode("utf-8")).hexdigest()

    env = make_envelope(
        sources=[
            project_source(
                "quotation-change-order",
                f"https://aeroregu.local/rotorcraft/change-order/{cr_id}",
                "ASSUMPTION",
            )
        ],
        method_version="quotation_change_order@1.0.0",
        inputs={
            "cr_id": cr_id,
            "baseline_merkle_root": base_merkle,
            "revised_merkle_root": rev_merkle,
        },
        confidence="deterministic",
        result={
            "delta_multiyear_quoted_price_eur": financial_delta["delta_multiyear_quoted_price_eur"],
            "delta_duration_weeks": format_quantum(delta_dur, _Q2),
            "decision_status": decision_status,
        },
    )
    ev_hash = record(
        ledger,
        {
            "event_type": "calc",
            "tenant_id": ledger.tenant_id,
            "actor_id": eff_spec.actor_id,
            "created_at": created_at,
            "payload": {
                "record_kind": "quotation_change_order",
                "cr_id": cr_id,
                "change_reason": change_reason,
                "baseline_rfq_id": baseline_dossier.get("rfq_id"),
                "revised_rfq_id": revised_dossier.get("rfq_id"),
                "baseline_merkle_root": base_merkle,
                "revised_merkle_root": rev_merkle,
                "ccn_digest": ccn_digest,
                "financial_delta": financial_delta,
                "decision_status": decision_status,
            },
            "envelope": env,
        },
    )

    return {
        "cr_id": cr_id,
        "change_reason": change_reason,
        "baseline_rfq_id": baseline_dossier.get("rfq_id"),
        "revised_rfq_id": revised_dossier.get("rfq_id"),
        "confidence": "deterministic",
        "decision_status": decision_status,
        "wbs_delta": {
            "added_archetypes": added_archs,
            "removed_archetypes": removed_archs,
            "retained_archetypes": retained_archs,
            "node_deltas": node_deltas,
        },
        "cpm_delta": {
            "base_duration_weeks": format_quantum(base_dur, _Q2),
            "revised_duration_weeks": format_quantum(rev_dur, _Q2),
            "delta_duration_weeks": format_quantum(delta_dur, _Q2),
            "base_critical_path": base_cp,
            "revised_critical_path": rev_cp,
            "newly_critical_archetypes": newly_critical,
        },
        "financial_delta": financial_delta,
        "idp_delta": idp_delta,
        "contract_delta": contract_delta,
        "triggered_assumptions": triggered_assumptions,
        "formal_amended_margin_proof": amended_margin_proof,
        "formal_amended_npv_proof": amended_npv_proof,
        "baseline_merkle_root": base_merkle,
        "revised_merkle_root": rev_merkle,
        "change_order_event_hash": ev_hash,
        "change_order_merkle_root": ledger.merkle_root(),
        "revised_dossier": revised_dossier,
        "advisory_only": (
            "Closed-loop ASSUMPTION / ESTIMATE Change-Order addendum; human commercial & CVE "
            "approval required before customer issue."
        ),
    }
