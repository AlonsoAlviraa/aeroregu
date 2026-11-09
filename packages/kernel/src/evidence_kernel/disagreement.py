"""Extractor versus challenger. The ledger write stays in the orchestrator."""

from __future__ import annotations

from typing import Any, Literal

from evidence_kernel.contracts import ChallengerOutput, ExtractorOutput
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record

Decision = Literal["continue", "human_queue"]


def decide(extractor: ExtractorOutput, challenger: ChallengerOutput) -> Decision:
    if extractor.confidence == "low" or challenger.confidence == "low":
        return "human_queue"
    if challenger.attack == "hit":
        return "human_queue"
    if not extractor.fields and not extractor.clause_ids:
        return "human_queue"
    return "continue"


def enqueue(
    ledger: Ledger,
    *,
    tenant_id: str,
    actor_id: str,
    created_at: str,
    reason: str,
) -> str:
    envelope = make_envelope(
        sources=[
            project_source(
                "orchestrator",
                "https://aeroregu.local/orchestrator",
                "ASSUMPTION",
            )
        ],
        method_version="orchestrator@1.0.0",
        inputs={"reason": reason},
        confidence="abstain",
        abstain_reason=reason,
    )
    body: dict[str, Any] = {
        "event_type": "abstain",
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "created_at": created_at,
        "payload": {"queue": "human_engineer", "reason": reason},
        "envelope": envelope,
    }
    return record(ledger, body)
