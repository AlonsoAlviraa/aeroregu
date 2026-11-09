from __future__ import annotations

from typing import Any

from evidence_kernel.canonical import inputs_hash
from evidence_kernel.schema import validate_instance

LABELS = ("VERIFIED", "PARTIAL", "NOT_VERIFIED", "ASSUMPTION", "ESTIMATE")
CONFIDENCE = ("deterministic", "quoted", "draft", "abstain")


def project_source(
    source_id: str, uri: str, label: str, content_hash: str = "assumption"
) -> dict[str, str]:
    if label not in LABELS:
        raise ValueError(label)
    source = {
        "source_id": source_id,
        "uri": uri,
        "content_hash": content_hash,
        "label": label,
    }
    if label == "PARTIAL":
        source["partial_note"] = "partial source"
    return source


def make_envelope(
    *,
    sources: list[dict[str, Any]],
    method_version: str,
    inputs: Any,
    confidence: str,
    result: Any = None,
    abstain_reason: str | None = None,
) -> dict[str, Any]:
    if confidence not in CONFIDENCE:
        raise ValueError(confidence)
    if method_version.startswith("llm_extract@") and confidence == "deterministic":
        raise ValueError("llm drafts cannot use confidence deterministic")
    envelope: dict[str, Any] = {
        "sources": sources,
        "method_version": method_version,
        "inputs_hash": inputs_hash(inputs),
        "confidence": confidence,
        "abstain": None,
    }
    if confidence == "abstain":
        envelope["abstain"] = {
            "reason": abstain_reason or "unspecified",
            "escalate_to": "human_engineer",
        }
    else:
        if result is None:
            raise ValueError("result is required unless confidence is abstain")
        envelope["result"] = result
    validate_instance("envelope.schema.json", envelope)
    return envelope
