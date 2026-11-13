"""Deterministic in-toto-style pipeline attestation bundle over ledger events."""

from __future__ import annotations

from typing import Any

from evidence_kernel.canonical import inputs_hash
from evidence_kernel.ledger import GENESIS
from evidence_kernel.merkle import merkle_root


def build_pipeline_attestation(
    events: list[dict[str, Any]],
    *,
    predicate_type: str = "https://aeroregu.local/attestation/v1",
) -> dict[str, Any]:
    """Build a deterministic provenance bundle across calc, agent_turn, and signoff steps."""
    steps: list[dict[str, Any]] = []
    for seq, event in enumerate(events, start=1):
        body = event["body"]
        envelope = body["envelope"]
        payload = body["payload"]
        step = {
            "step_index": str(seq),
            "step_type": str(body["event_type"]),
            "actor_id": str(body["actor_id"]),
            "created_at": str(body["created_at"]),
            "event_hash": str(event["event_hash"]),
            "prev_hash": str(event["prev_hash"]),
            "method_version": str(envelope["method_version"]),
            "inputs_hash": str(envelope["inputs_hash"]),
            "confidence": str(envelope["confidence"]),
            "payload_digest": inputs_hash(payload),
        }
        if body["event_type"] == "agent_turn":
            step["agent_id"] = str(payload.get("agent_id", ""))
            step["prompt_hash"] = str(payload.get("prompt_hash", ""))
            step["materials"] = list(payload.get("input_event_hashes") or [])
        steps.append(step)

    head_hash = str(events[-1]["event_hash"]) if events else GENESIS
    m_root = merkle_root([str(event["event_hash"]) for event in events])
    core = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": predicate_type,
        "subject": [
            {
                "name": "evidence_ledger_head",
                "digest": {"sha256": head_hash, "merkle_root": m_root},
            }
        ],
        "predicate": {
            "event_count": str(len(events)),
            "steps": steps,
        },
    }
    return {"attestation_digest": inputs_hash(core), **core}
