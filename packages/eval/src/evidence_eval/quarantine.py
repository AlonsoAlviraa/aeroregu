"""Faults that are not in the frozen detectors.

A case here is a negative result until a later, separate change adds a detector.
Do not teach the checker this fault in the same commit that adds the case.
"""

from __future__ import annotations

from typing import Any

from evidence_eval.challenger_faults import propose_duplicate_citation


def duplicate_citation_artifact() -> dict[str, Any]:
    return propose_duplicate_citation()["artifact"]


def quarantine_status() -> dict[str, Any]:
    import tempfile
    from pathlib import Path

    from evidence_kernel.contracts import ExtractorOutput, JudgeInput, SpanQuote
    from evidence_kernel.disagreement import decide, enqueue
    from evidence_kernel.ledger import Ledger

    from evidence_eval.detect import assess
    from evidence_eval.score import wilson

    proposed = propose_duplicate_citation()
    verdict = assess(proposed["artifact"])["verdict"]
    judged = JudgeInput(
        case_id="quarantine-duplicate-citation",
        verdict=verdict,
        gold_label="detect:duplicate_citation",
    )
    extractor = ExtractorOutput(
        fields=[SpanQuote(name="citation", value_text="VTOL.2210", span_start=0, span_end=10)],
        clause_ids=["VTOL.2210", "VTOL.2215"],
        assumptions=[],
    )
    system = "abstain" if decide(extractor, proposed["proposal"]) == "human_queue" else verdict
    detected = judged.verdict == judged.gold_label
    hits = 1 if detected else 0
    event_hash = None
    if system == "abstain":
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "quarantine.sqlite3", "bench")
            event_hash = enqueue(
                ledger,
                tenant_id="bench",
                actor_id="orchestrator",
                created_at="2026-11-03T21:30:00Z",
                reason="agent_disagreement",
            )
            queued = ledger.events()[-1]["body"]
    else:
        queued = None
    return {
        "fault": "duplicate_citation",
        "verdict": judged.verdict,
        "system_verdict": system,
        "detected": detected,
        "recall": f"{hits}/1",
        "recall_ci95": wilson(hits, 1),
        "challenger_reason_ignored": proposed["proposal"].reason != system,
        "queue": "human_engineer" if system == "abstain" else None,
        "event_hash": event_hash,
        "event_type": None if queued is None else queued["event_type"],
        "protocol_abstain": system == "abstain",
        "abstention_matches_gold": system == judged.gold_label,
        "label": "ESTIMATE",
        "note": (
            "Checker says clean. The system abstains and queues the case. That is not a detection."
        ),
    }
