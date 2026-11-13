from __future__ import annotations

from pathlib import Path

from evidence_coverage.gate import evaluate_traceability_gate, format_openfasttrace_report
from evidence_coverage.grid import Cell, generate_cells
from evidence_coverage.status import invalidate_mass_shift, set_cell_status
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record


def test_traceability_gate_blocks_gaps_and_closes_when_covered(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db", "t1")
    subset = generate_cells()[:3]
    set_cell_status(
        ledger,
        cell=subset[0],
        status="calc",
        actor_id="author-1",
        actor_role="author",
        created_at="2026-11-12T10:00:00Z",
        evidence_event_hash="a" * 64,
    )

    blocked = evaluate_traceability_gate(
        ledger.events(), chain_verified=ledger.verify(), cells=subset
    )
    assert blocked["gate_status"] == "blocked"
    assert "coverage_gaps_remaining" in blocked["blockers"]
    assert blocked["counts"]["gap_cells"] == 2

    set_cell_status(
        ledger,
        cell=subset[1],
        status="not_in_envelope",
        actor_id="rev-1",
        actor_role="human",
        created_at="2026-11-12T10:01:00Z",
    )
    set_cell_status(
        ledger,
        cell=subset[2],
        status="justified_not_critical",
        actor_id="rev-1",
        actor_role="human",
        created_at="2026-11-12T10:02:00Z",
    )

    ready = evaluate_traceability_gate(
        ledger.events(), chain_verified=ledger.verify(), cells=subset
    )
    assert ready["gate_status"] == "ready_for_human_review"
    assert ready["coverage_ratio"] == "1.000"
    assert ready["blockers"] == []

    strict = evaluate_traceability_gate(
        ledger.events(),
        chain_verified=ledger.verify(),
        cells=subset,
        require_head_signoff=True,
    )
    assert strict["gate_status"] == "blocked"
    assert "head_event_missing_human_signoff" in strict["blockers"]

    # Human sign-off on head closes strict gate too
    record(
        ledger,
        {
            "event_type": "human_signoff",
            "tenant_id": "t1",
            "actor_id": "rev-1",
            "created_at": "2026-11-12T10:03:00Z",
            "payload": {
                "actor_id": "rev-1",
                "target_event_hash": ledger.head_hash(),
                "statement": "reviewed this event",
            },
            "envelope": make_envelope(
                sources=[
                    project_source("human-review", "https://aeroregu.local/review", "ASSUMPTION")
                ],
                method_version="human_signoff@1.0.0",
                inputs={"target_event_hash": ledger.head_hash()},
                confidence="deterministic",
                result={"signed": "true"},
            ),
        },
    )
    strict_signed = evaluate_traceability_gate(
        ledger.events(),
        chain_verified=ledger.verify(),
        cells=subset,
        require_head_signoff=True,
    )
    assert strict_signed["gate_status"] == "ready_for_human_review"
    report_txt = format_openfasttrace_report(strict_signed)
    assert "SPEC-SMT-ENVELOPE" in report_txt
    assert "does not determine compliance" in report_txt


def test_traceability_gate_detects_stale_invalidations(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db", "t1")
    cell = Cell(
        cell_id="m800.000-cg0.000-lf1.000-unone",
        axes={
            "mass_kg": "800.000",
            "cg_x_m": "0.000",
            "load_factor": "1.000",
            "failed_unit": "none",
        },
    )
    set_cell_status(
        ledger,
        cell=cell,
        status="calc",
        actor_id="author-1",
        actor_role="author",
        created_at="2026-11-12T10:00:00Z",
        evidence_event_hash="b" * 64,
    )
    invalidate_mass_shift(
        ledger,
        [{"cell_id": cell.cell_id, "inputs": {"mass_kg": "800.000"}, "inputs_hash": "1" * 64}],
        actor_id="author-1",
        created_at="2026-11-12T10:01:00Z",
    )
    gate = evaluate_traceability_gate(ledger.events(), chain_verified=True, cells=[cell])
    assert gate["gate_status"] == "blocked"
    assert "stale_cells_require_reverification" in gate["blockers"]
