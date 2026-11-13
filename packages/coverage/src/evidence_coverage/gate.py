"""Deterministic OpenFastTrace-style traceability and re-verification gate."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from evidence_kernel.canonical import inputs_hash

from evidence_coverage.dossier import build_enterprise_dossier
from evidence_coverage.grid import Cell
from evidence_coverage.status import gap_report


def evaluate_traceability_gate(
    events: list[dict[str, Any]],
    *,
    chain_verified: bool = True,
    dossier: dict[str, Any] | None = None,
    cells: list[Cell] | None = None,
    require_head_signoff: bool = False,
) -> dict[str, Any]:
    """Evaluate ledger integrity, coverage closure, SMT proof, and sign-off status.

    Produces a deterministic traceability summary for human review. Never determines compliance.
    """
    resolved_dossier = (
        dossier
        if dossier is not None
        else build_enterprise_dossier(events, chain_verified=chain_verified)
    )
    coverage = gap_report(events, cells=cells)

    total_cells = int(coverage["cell_count"])
    calc_count = int(coverage["calc_count"])
    excluded_count = len(coverage["not_in_envelope"])
    justified_count = len(coverage["justified_not_critical"])
    covered_count = calc_count + excluded_count + justified_count
    gap_count = int(coverage["gap_count"])

    coverage_ratio = (
        format((Decimal(covered_count) / Decimal(total_cells)).quantize(Decimal("0.001")), "f")
        if total_cells > 0
        else "0.000"
    )

    reverify = resolved_dossier["delta_reverification_manifest"]
    stale_cells = list(reverify["stale_cells_requiring_rerun"])
    stale_signoffs = list(reverify["stale_signoffs"])
    recompute_flags = list(resolved_dossier["agent_audit_trail"]["recompute_flags"])
    abstentions = list(resolved_dossier["agent_audit_trail"]["abstentions"])
    formal = resolved_dossier["formal_envelope_proof"]
    signoffs = list(resolved_dossier["human_signoffs"])
    active_signoffs = [s for s in signoffs if s.get("status") == "active"]
    head_hash = str(resolved_dossier["head_hash"])
    non_signoff_hashes = [
        str(event["event_hash"])
        for event in events
        if event.get("body", {}).get("event_type") != "human_signoff"
    ]
    latest_reviewable_hash = non_signoff_hashes[-1] if non_signoff_hashes else ""
    head_signed_off = bool(latest_reviewable_hash) and any(
        s.get("target_event_hash") == latest_reviewable_hash for s in active_signoffs
    )

    blockers: list[str] = []
    if not chain_verified:
        blockers.append("ledger_chain_unverified")
    if gap_count > 0:
        blockers.append("coverage_gaps_remaining")
    if stale_cells:
        blockers.append("stale_cells_require_reverification")
    if stale_signoffs:
        blockers.append("superseded_human_signoffs")
    if recompute_flags:
        blockers.append("recompute_flags_present")
    if not formal.get("envelope_proved"):
        blockers.append("formal_envelope_not_proved")
    if require_head_signoff and not head_signed_off:
        blockers.append("head_event_missing_human_signoff")

    warnings: list[str] = []
    if abstentions:
        warnings.append("abstentions_recorded")
    if not head_signed_off and not require_head_signoff:
        warnings.append("head_event_pending_human_signoff")

    traceability_items = [
        {
            "spec_id": "SPEC-LEDGER-CHAIN",
            "status": "covered" if chain_verified else "uncovered",
            "evidence_ref": head_hash,
        },
        {
            "spec_id": "SPEC-MERKLE-ROOT",
            "status": "covered" if resolved_dossier.get("merkle_root") else "uncovered",
            "evidence_ref": str(resolved_dossier.get("merkle_root", "")),
        },
        {
            "spec_id": "SPEC-COVERAGE-GRID",
            "status": "covered"
            if gap_count == 0
            else "partial"
            if covered_count > 0
            else "uncovered",
            "evidence_ref": f"{covered_count}/{total_cells}",
        },
        {
            "spec_id": "SPEC-SMT-ENVELOPE",
            "status": "covered" if formal.get("envelope_proved") else "uncovered",
            "evidence_ref": str(formal.get("proof_hash", "")),
        },
        {
            "spec_id": "SPEC-DELTA-REVERIFY",
            "status": "covered" if not (stale_cells or stale_signoffs) else "uncovered",
            "evidence_ref": f"stale_cells={len(stale_cells)},stale_signoffs={len(stale_signoffs)}",
        },
        {
            "spec_id": "SPEC-HUMAN-SIGNOFF",
            "status": "covered" if active_signoffs else "uncovered",
            "evidence_ref": str(len(active_signoffs)),
        },
        {
            "spec_id": "SPEC-INGESTED-REQS",
            "status": "covered" if resolved_dossier.get("recorded_requirements") else "optional",
            "evidence_ref": str(len(resolved_dossier.get("recorded_requirements") or [])),
        },
    ]

    core = {
        "gate_status": "ready_for_human_review" if not blockers else "blocked",
        "chain_verified": chain_verified,
        "head_hash": head_hash,
        "merkle_root": str(resolved_dossier.get("merkle_root", "")),
        "dossier_hash": str(resolved_dossier.get("dossier_hash", "")),
        "coverage_ratio": coverage_ratio,
        "counts": {
            "total_cells": total_cells,
            "covered_cells": covered_count,
            "calc_cells": calc_count,
            "not_in_envelope_cells": excluded_count,
            "justified_not_critical_cells": justified_count,
            "gap_cells": gap_count,
            "stale_cells": len(stale_cells),
            "stale_signoffs": len(stale_signoffs),
            "recompute_flags": len(recompute_flags),
            "abstentions": len(abstentions),
            "active_signoffs": len(active_signoffs),
        },
        "head_signed_off": head_signed_off,
        "blockers": blockers,
        "warnings": warnings,
        "traceability_items": traceability_items,
        "note": (
            "This traceability gate assists a human reviewer. It does not determine compliance."
        ),
    }
    return {"gate_digest": inputs_hash(core), **core}


def format_openfasttrace_report(gate_result: dict[str, Any]) -> str:
    """Render a deterministic plain-text OpenFastTrace-style traceability summary."""
    lines = [
        f"# Traceability Gate Report ({gate_result['gate_status']})",
        f"Note: {gate_result['note']}",
        f"Gate Digest: {gate_result['gate_digest']}",
        f"Merkle Root: {gate_result['merkle_root']}",
        f"Coverage Ratio: {gate_result['coverage_ratio']}",
        "",
        "## Specification Items",
    ]
    for item in gate_result["traceability_items"]:
        lines.append(f"- [{item['status']}] {item['spec_id']} -> {item['evidence_ref']}")
    if gate_result["blockers"]:
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {blocker}" for blocker in gate_result["blockers"])
    return "\n".join(lines) + "\n"
