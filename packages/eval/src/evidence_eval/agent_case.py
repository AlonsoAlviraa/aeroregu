"""One orchestrated case: extract, challenge, map, then the orchestrator records it.

The sentence is synthetic. It is not a quotation from a certification specification.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from evidence_kernel.contracts import (
    ExtractorOutput,
    MapperLink,
    MapperOutput,
    ScribeOutput,
    ScribeSentence,
    SpanQuote,
)
from evidence_kernel.disagreement import decide, enqueue
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record

from evidence_eval.b2 import ID_RE, PUBLIC_HEADINGS, _nearest_evidence_id, predict
from evidence_eval.quote_pipeline import challenge

_EVIDENCE = re.compile(r"\bev-\d+\b")


def run_identifier_case(
    ledger: Ledger,
    *,
    text: str,
    evidence_id: str,
    tenant_id: str,
    actor_id: str,
    created_at: str,
    confidence: Literal["low", "high"] = "high",
    evidence_hash: str | None = None,
) -> dict[str, Any]:
    matches = list(ID_RE.finditer(text))
    if len(matches) != 1:
        reason = "ambiguous_input" if len(matches) > 1 else "no_span"
        digest = _queue(ledger, tenant_id, actor_id, created_at, reason)
        return _queued(digest)
    match = matches[0]
    if match.group() not in PUBLIC_HEADINGS:
        digest = _queue(ledger, tenant_id, actor_id, created_at, "unknown_heading")
        return _queued(digest)
    field = SpanQuote(
        name="requirement_id",
        value_text=match.group(),
        span_start=match.start(),
        span_end=match.end(),
    )
    extractor = ExtractorOutput(
        confidence=confidence,
        fields=[field],
        clause_ids=[match.group()],
        assumptions=[],
    )
    challenger = challenge(text, field)
    if decide(extractor, challenger) == "human_queue":
        digest = _queue(ledger, tenant_id, actor_id, created_at, "agent_disagreement")
        return _queued(digest)
    named = _nearest_evidence_id(text, match.start())
    if named is None or named != evidence_id:
        digest = _queue(ledger, tenant_id, actor_id, created_at, "evidence_not_in_text")
        return _queued(digest)
    link = MapperLink(
        requirement_id=match.group(),
        evidence_id=evidence_id,
        span_start=match.start(),
        span_end=match.end(),
    )
    mapper = MapperOutput(links=[link])
    recorded = mapper.links[0]
    if text[recorded.span_start : recorded.span_end] != recorded.requirement_id:
        digest = _queue(ledger, tenant_id, actor_id, created_at, "bad_span")
        return _queued(digest)
    if _EVIDENCE.fullmatch(recorded.evidence_id) is None:
        digest = _queue(ledger, tenant_id, actor_id, created_at, "bad_evidence_id")
        return _queued(digest)
    if evidence_hash == "0" * 64:
        digest = _flag_zero_hash(
            ledger,
            tenant_id,
            actor_id,
            created_at,
            recorded.requirement_id,
            recorded.evidence_id,
        )
        return {
            "queue": None,
            "event_hash": digest,
            "requirement_id": None,
            "false_coverage": True,
            "scribe": digest,
        }
    envelope = make_envelope(
        sources=[project_source("mapper", "https://aeroregu.local/mapper", "ASSUMPTION")],
        method_version="identifier_map@1.0.0",
        inputs={"evidence_id": recorded.evidence_id},
        confidence="deterministic",
        result={"requirement_id": recorded.requirement_id, "evidence_id": recorded.evidence_id},
    )
    digest = record(
        ledger,
        {
            "event_type": "requirement_recorded",
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "created_at": created_at,
            "payload": {
                "requirement_id": recorded.requirement_id,
                "evidence_id": recorded.evidence_id,
            },
            "envelope": envelope,
        },
    )
    scribe = ScribeOutput(
        sentences=[
            ScribeSentence(
                text=f"{recorded.requirement_id} is linked.",
                ledger_event_hash=digest,
            )
        ]
    )
    return {
        "queue": None,
        "event_hash": digest,
        "requirement_id": recorded.requirement_id,
        "scribe": scribe.sentences[0].ledger_event_hash,
        "false_coverage": False,
    }


def map_report(
    ledger: Ledger,
    *,
    text: str,
    evidence: list[dict[str, str]],
    tenant_id: str,
    actor_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Record every nearest public heading. A tie with the verifier is not a win."""
    links, flags = predict(text, evidence, check_hash=True)
    if not links and not flags:
        matches = list(ID_RE.finditer(text))
        public = [match for match in matches if match.group() in PUBLIC_HEADINGS]
        reason = "unknown_heading" if matches and not public else "ambiguous_input"
        digest = _queue(ledger, tenant_id, actor_id, created_at, reason)
        return _mapped(digest, reason, [], [])
    for link in links:
        field = SpanQuote(
            name="requirement_id",
            value_text=link["requirement_id"],
            span_start=link["span_start"],
            span_end=link["span_end"],
        )
        extractor = ExtractorOutput(
            fields=[field],
            clause_ids=[link["requirement_id"]],
            assumptions=[],
        )
        if decide(extractor, challenge(text, field)) == "human_queue":
            digest = _queue(ledger, tenant_id, actor_id, created_at, "agent_disagreement")
            return _mapped(digest, "agent_disagreement", [], [])
    recorded: list[dict[str, str]] = []
    for link in links:
        digest = _record_requirement(
            ledger,
            tenant_id,
            actor_id,
            created_at,
            link["requirement_id"],
            link["evidence_id"],
        )
        recorded.append(
            {
                "requirement_id": link["requirement_id"],
                "evidence_id": link["evidence_id"],
                "event_hash": digest,
            }
        )
    flagged: list[dict[str, str]] = []
    for requirement_id, evidence_id in sorted(flags):
        digest = _flag_zero_hash(
            ledger,
            tenant_id,
            actor_id,
            created_at,
            requirement_id,
            evidence_id,
        )
        flagged.append(
            {
                "requirement_id": requirement_id,
                "evidence_id": evidence_id,
                "event_hash": digest,
            }
        )
    return _mapped(None, None, recorded, flagged, _violations(ledger))


def _record_requirement(
    ledger: Ledger,
    tenant_id: str,
    actor_id: str,
    created_at: str,
    requirement_id: str,
    evidence_id: str,
) -> str:
    envelope = make_envelope(
        sources=[project_source("mapper", "https://aeroregu.local/mapper", "ASSUMPTION")],
        method_version="identifier_map@1.0.0",
        inputs={"evidence_id": evidence_id},
        confidence="deterministic",
        result={"requirement_id": requirement_id, "evidence_id": evidence_id},
    )
    return record(
        ledger,
        {
            "event_type": "requirement_recorded",
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "created_at": created_at,
            "payload": {"requirement_id": requirement_id, "evidence_id": evidence_id},
            "envelope": envelope,
        },
    )


def _mapped(
    digest: str | None,
    reason: str | None,
    links: list[dict[str, str]],
    false_coverage: list[dict[str, str]],
    violations: int = 0,
) -> dict[str, Any]:
    return {
        "queue": "human_engineer" if reason else None,
        "reason": reason,
        "event_hash": digest,
        "links": links,
        "false_coverage": false_coverage,
        "llm_numeric_violation": violations,
    }


def _violations(ledger: Ledger) -> int:
    from evidence_kernel.numbers import stray_physical_numbers

    count = 0
    for event in ledger.events():
        envelope = event["body"].get("envelope") or {}
        count += len(stray_physical_numbers(envelope.get("result"), set()))
    return count


def _queued(digest: str) -> dict[str, Any]:
    return {
        "queue": "human_engineer",
        "event_hash": digest,
        "requirement_id": None,
        "false_coverage": False,
    }


def _flag_zero_hash(
    ledger: Ledger,
    tenant_id: str,
    actor_id: str,
    created_at: str,
    requirement_id: str,
    evidence_id: str,
) -> str:
    envelope = make_envelope(
        sources=[project_source("verifier", "https://aeroregu.local/verifier", "ASSUMPTION")],
        method_version="hash_check@1.0.0",
        inputs={"evidence_id": evidence_id},
        confidence="deterministic",
        result={"flag": "zero_hash"},
    )
    digest = record(
        ledger,
        {
            "event_type": "recompute_flag",
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "created_at": created_at,
            "payload": {
                "flag": "zero_hash",
                "requirement_id": requirement_id,
                "evidence_id": evidence_id,
            },
            "envelope": envelope,
        },
    )
    ScribeOutput(
        sentences=[ScribeSentence(text="The zero hash was refused.", ledger_event_hash=digest)]
    )
    return digest


def _queue(ledger: Ledger, tenant_id: str, actor_id: str, created_at: str, reason: str) -> str:
    return enqueue(
        ledger,
        tenant_id=tenant_id,
        actor_id=actor_id,
        created_at=created_at,
        reason=reason,
    )
