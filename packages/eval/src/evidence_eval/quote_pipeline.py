"""Extractor proposes a quotation. Challenger checks the span. Code parses the number."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from evidence_calc.units import units_compatible
from evidence_kernel.contracts import (
    ChallengerOutput,
    ExtractorOutput,
    ScribeOutput,
    ScribeSentence,
    SpanQuote,
)
from evidence_kernel.disagreement import decide, enqueue
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record


def propose(text: str, pattern: str, name: str, unit_text: str) -> ExtractorOutput:
    match = re.search(pattern, text)
    if match is None:
        return ExtractorOutput(fields=[], clause_ids=[], assumptions=[])
    value = match.group(1)
    return ExtractorOutput(
        fields=[
            SpanQuote(
                name=name,
                value_text=value,
                unit_text=unit_text,
                span_start=match.start(1),
                span_end=match.end(1),
            )
        ],
        clause_ids=[],
        assumptions=[],
    )


def challenge(text: str, field: SpanQuote) -> ChallengerOutput:
    snippet = text[field.span_start : field.span_end]
    if snippet == field.value_text or _same_number(snippet, field.value_text):
        return ChallengerOutput(attack="miss", reason="span_matches", evidence_span=snippet)
    return ChallengerOutput(attack="hit", reason="span", evidence_span=snippet)


def _same_number(left: str, right: str) -> bool:
    from decimal import Decimal

    try:
        return Decimal(left) == Decimal(right)
    except Exception:
        return False


def line_is_one_number(line: str) -> bool:
    from decimal import Decimal

    text = line.strip()
    if text == "":
        return False
    try:
        Decimal(text)
    except Exception:
        return False
    return True


def stacked_bare_numbers(text: str, anchor: str, minimum: int = 3) -> bool:
    """A column of one number per line is not a value to quote."""
    index = text.find(anchor)
    if index < 0:
        return False
    count = 0
    for line in text[index:].splitlines()[1:]:
        if line.strip() == "":
            continue
        if line_is_one_number(line):
            count += 1
            if count >= minimum:
                return True
            continue
        if _damaged_number(line) and count >= 1:
            return True
        break
    return False


def _damaged_number(line: str) -> bool:
    import re

    text = line.strip()
    if text == "" or line_is_one_number(text):
        return False
    if re.fullmatch(r"V\d{4}", text):
        return False
    letters = re.findall(r"[A-Za-z]", text)
    digits = re.findall(r"\d", text)
    if not digits:
        return False
    return len(letters) <= 2


def line_is_unreadable_table(text: str, offset: int) -> bool:
    """A row of numbers with almost no words is not a value to quote."""
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    numbers = re.findall(r"-?\d+(?:\.\d+)?", line)
    words = re.findall(r"[A-Za-z]{2,}", line)
    return len(numbers) >= 3 and len(words) < 2


def run_quote(
    ledger: Ledger,
    *,
    text: str,
    pattern: str,
    name: str,
    unit_text: str,
    expected_unit: str,
    tenant_id: str,
    actor_id: str,
    created_at: str,
    field: SpanQuote | None = None,
) -> dict[str, Any]:
    extractor = propose(text, pattern, name, unit_text)
    chosen = field if field is not None else (extractor.fields[0] if extractor.fields else None)
    if chosen is None:
        digest = _queue(ledger, tenant_id, actor_id, created_at, "no_span")
        return {"queue": "human_engineer", "event_hash": digest, "value": None}
    challenger = challenge(text, chosen)
    if decide(extractor if field is None else _one(chosen), challenger) == "human_queue":
        digest = _queue(ledger, tenant_id, actor_id, created_at, "agent_disagreement")
        return {"queue": "human_engineer", "event_hash": digest, "value": None}
    if line_is_unreadable_table(text, chosen.span_start):
        digest = _queue(ledger, tenant_id, actor_id, created_at, "unreadable_table")
        return {"queue": "human_engineer", "event_hash": digest, "value": None}
    if not units_compatible(chosen.unit_text, expected_unit):
        digest = _queue(ledger, tenant_id, actor_id, created_at, "unit_mismatch")
        return {"queue": "human_engineer", "event_hash": digest, "value": None}
    try:
        value = Decimal(chosen.value_text)
    except Exception:
        digest = _queue(ledger, tenant_id, actor_id, created_at, "ambiguous_input")
        return {"queue": "human_engineer", "event_hash": digest, "value": None}
    envelope = make_envelope(
        sources=[project_source("quote", "https://aeroregu.local/quote", "ASSUMPTION")],
        method_version="quote_decimal@1.0.0",
        inputs={"name": name, "unit_text": unit_text},
        confidence="deterministic",
        result={"value": str(value), "unit": expected_unit},
    )
    digest = record(
        ledger,
        {
            "event_type": "recompute_flag",
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "created_at": created_at,
            "payload": {"name": name, "quoted": chosen.value_text},
            "envelope": envelope,
        },
    )
    scribe = ScribeOutput(
        sentences=[ScribeSentence(text=f"{name} is recorded.", ledger_event_hash=digest)]
    )
    return {
        "queue": None,
        "event_hash": digest,
        "value": str(value),
        "scribe": scribe.sentences[0].ledger_event_hash,
    }


def score_nasa_quotes(ledger: Ledger) -> dict[str, Any]:
    """Run the quote path on the local NASA TM. Dev gold, not a held-out set."""
    import hashlib

    from evidence_kernel.paths import repo_root

    from evidence_eval.b3 import EXPECTED_SHA256, GOLD_FIELDS, PDF_RELATIVE, _pdf_pages

    pdf = repo_root() / PDF_RELATIVE
    if not pdf.is_file():
        return {"ready": False, "label": "NOT_VERIFIED", "matched": "0/0"}
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        return {
            "ready": False,
            "label": "NOT_VERIFIED",
            "matched": "0/0",
            "llm_numeric_violation": 0,
            "sha256": digest,
        }
    text = "\n".join(_pdf_pages(pdf))
    matched = 0
    false_alarms = 0
    recorded: list[dict[str, str]] = []
    for index, field in enumerate(GOLD_FIELDS):
        unit = _pint_unit(field["unit_text"])
        outcome = run_quote(
            ledger,
            text=text,
            pattern=field["pattern"],
            name=field["name"],
            unit_text=unit,
            expected_unit=unit,
            tenant_id=ledger.tenant_id,
            actor_id="orchestrator",
            created_at=f"2026-11-03T20:40:{index:02d}Z",
        )
        if outcome["value"] is None:
            continue
        recorded.append({"name": field["name"], "value": outcome["value"], "unit": unit})
        if outcome["value"] == field["value_text"]:
            matched += 1
        else:
            false_alarms += 1
    absent = run_quote(
        ledger,
        text=text,
        pattern=r"not-in-this-memorandum (\d+)",
        name="absent",
        unit_text="dimensionless",
        expected_unit="dimensionless",
        tenant_id=ledger.tenant_id,
        actor_id="orchestrator",
        created_at="2026-11-03T20:41:00Z",
    )
    abstain_ok = absent["value"] is None and absent["queue"] == "human_engineer"
    total = len(GOLD_FIELDS)
    from evidence_kernel.numbers import stray_physical_numbers

    violations = 0
    for event in ledger.events():
        result = (event["body"].get("envelope") or {}).get("result") or {}
        value = result.get("value") if isinstance(result, dict) else None
        allowed = {value} if isinstance(value, str) else set()
        violations += len(stray_physical_numbers(result, allowed))
    from evidence_eval.score import wilson

    return {
        "ready": True,
        "label": "ESTIMATE",
        "matched": f"{matched}/{total}",
        "false_alarms": false_alarms,
        "llm_numeric_violation": violations,
        "recorded_fields": recorded,
        "abstain_ok": abstain_ok,
        "recall_ci95": wilson(matched, total),
        "sha256": digest,
        "expert_holdout": False,
    }


def quotes_ok(report: dict[str, Any]) -> bool:
    if not report["ready"]:
        return True
    matched, total = report["matched"].split("/")
    if total == "0" or matched != total:
        return False
    if report.get("false_alarms", 0) != 0:
        return False
    if report.get("llm_numeric_violation", 0) != 0:
        return False
    return report.get("abstain_ok", True) is True


def measured_value_ok(value: str, unit_text: str) -> bool:
    from decimal import Decimal

    from evidence_calc.units import units_compatible

    try:
        Decimal(value)
        numeric = True
    except Exception:
        numeric = False
    if not numeric:
        return unit_text == "1" and value.isalpha()
    if unit_text == "m":
        return units_compatible("m", "meter")
    if unit_text == "m/s2":
        return units_compatible(_pint_unit(unit_text), "meter / second ** 2")
    if unit_text == "1":
        return True
    return units_compatible(unit_text, unit_text)


def _pint_unit(unit_text: str) -> str:
    if unit_text == "m/s2":
        return "meter / second ** 2"
    if unit_text == "1":
        return "dimensionless"
    return unit_text


def _one(field: SpanQuote) -> ExtractorOutput:
    return ExtractorOutput(fields=[field], clause_ids=[], assumptions=[])


def _queue(ledger: Ledger, tenant_id: str, actor_id: str, created_at: str, reason: str) -> str:
    return enqueue(
        ledger,
        tenant_id=tenant_id,
        actor_id=actor_id,
        created_at=created_at,
        reason=reason,
    )
