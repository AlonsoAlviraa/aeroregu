"""Second NASA memorandum. Dev gold written beside the checker, not a held-out set."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from evidence_ingest.pdf import read_pdf_pages
from evidence_kernel.paths import repo_root

PDF_RELATIVE = Path("data/ntrs/NASA-19890004039.pdf")
EXPECTED_SHA256 = "9f924ea50e0068013825354ec43d6b41ff28c2e24dac67bb6de577ef83d8e779"

GOLD_FIELDS = (
    {
        "name": "blade_count_word",
        "value_text": "three",
        "unit_text": "1",
        "pattern": r"(three)-bladed\s+helicopter",
    },
    {
        "name": "rotor_radius_m",
        "value_text": "5.25",
        "unit_text": "m",
        "pattern": r"rotor radius = ([0-9.]+) m",
    },
    {
        "name": "lift_curve_slope",
        "value_text": "5.7",
        "unit_text": "1",
        "pattern": r"lift curve slope = ([0-9.]+)",
    },
    {
        "name": "level_flight_ratio_low",
        "value_text": "0.14",
        "unit_text": "1",
        "pattern": r"advance ratio from ([0-9.]+) to",
    },
    {
        "name": "level_flight_ratio_high",
        "value_text": "0.37",
        "unit_text": "1",
        "pattern": r"advance ratio from 0\.14 to\s+([0-9]+\.[0-9]+)",
    },
)


def gold_sha256() -> str:
    import json

    payload = json.dumps(list(GOLD_FIELDS), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def score_second() -> dict[str, Any]:
    from evidence_eval.b3 import _quote, judged_field
    from evidence_eval.quote_pipeline import stacked_bare_numbers
    from evidence_eval.score import wilson

    path = repo_root() / PDF_RELATIVE
    if not path.is_file():
        return {
            "document": "NASA-19890004039",
            "pdf_present": False,
            "scored": False,
            "label": "NOT_VERIFIED",
            "note": "The second NASA PDF is not on disk.",
        }
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        return {
            "document": "NASA-19890004039",
            "pdf_present": True,
            "scored": False,
            "label": "NOT_VERIFIED",
            "note": "The local PDF hash does not match the data register.",
        }
    pages = read_pdf_pages(path, (1, 40))
    full = "\n".join(pages)
    shallow = "\n".join(pages[:2])
    hits = _hits(full, judged_field, _quote)
    shallow_hits = _hits(shallow, judged_field, _quote)
    alarms, emitted = _false_alarms(full, judged_field, _quote)
    shallow_alarms, shallow_emitted = _false_alarms(shallow, judged_field, _quote)
    hashes, unit_abstains, numeric_violations, recorded = _record_fields(full)
    total = len(GOLD_FIELDS)
    decimal_hits, words = _split_hits(full, judged_field, _quote)
    decimal_total = sum(1 for field in GOLD_FIELDS if _is_decimal(field["value_text"]))
    shared = _shared_ids(full)
    column = stacked_bare_numbers(full, "V3101")
    column_hash = _record_column_abstain(column)
    return {
        "document": "NASA-19890004039",
        "pdf_present": True,
        "scored": True,
        "expert_holdout": False,
        "fields_correct": f"{hits}/{total}",
        "decimal_fields_correct": f"{decimal_hits}/{decimal_total}",
        "word_labels_not_recomputed": words,
        "field_accuracy_ci95": wilson(hits, total),
        "page_limited_fields_correct": f"{shallow_hits}/{total}",
        "page_limited_ci95": wilson(shallow_hits, total),
        "no_agent_fields_correct": f"0/{total}",
        "no_agent_ci95": wilson(0, total),
        "beats_no_agent": hits > 0,
        "beats_single_llm": "NOT_VERIFIED",
        "false_alarms": f"{alarms}/{emitted}",
        "false_alarm_ci95": wilson(alarms, emitted),
        "page_limited_false_alarms": f"{shallow_alarms}/{shallow_emitted}",
        "page_limited_false_alarm_ci95": wilson(shallow_alarms, shallow_emitted),
        "abstentions_correct": (f"{_abstention_hits(words, recorded, column)}/2"),
        "abstention_ci95": wilson(_abstention_hits(words, recorded, column), 2),
        "field_pages": _pages(pages, judged_field, _quote),
        "event_hashes": hashes,
        "llm_numeric_violation": numeric_violations,
        "recorded_fields": recorded,
        "unit_abstain_hashes": unit_abstains,
        "shared_with_first_memo": shared["shared"],
        "absent_from_second_memo": shared["absent"],
        "table_magnitudes_stored": False,
        "flight_table_column_abstained": column,
        "column_abstain_hash": column_hash,
        "label": "ESTIMATE",
        "note": (
            "Gold and checker were written in the same session. "
            "This is not a held-out set. Beating the no-read baseline is trivial. "
            "A word label is counted in the field score and is not written as a number. "
            "A false alarm is an emitted field whose value is not the gold value. "
            "The abstention count is that word label and the flight-table column."
        ),
    }


def _record_column_abstain(column: bool) -> str | None:
    import tempfile

    from evidence_kernel.disagreement import enqueue
    from evidence_kernel.ledger import Ledger

    if not column:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "b3-column.sqlite3", "bench")
        return enqueue(
            ledger,
            tenant_id="bench",
            actor_id="orchestrator",
            created_at="2026-11-04T19:00:00Z",
            reason="unreadable_table",
        )


def _shared_ids(text: str) -> dict[str, list[str]]:
    import re

    from evidence_eval.b3 import _LOAD_CASE_IDS

    found = set(re.findall(r"\bV\d{4}\b", text))
    return {
        "shared": [item for item in _LOAD_CASE_IDS if item in found],
        "absent": [item for item in _LOAD_CASE_IDS if item not in found],
    }


def _record_fields(
    text: str, fields: tuple[dict[str, str], ...] | None = None
) -> tuple[list[str], list[str], int, list[dict[str, str]]]:
    import tempfile

    from evidence_kernel.contracts import ExtractorOutput, ScribeOutput, ScribeSentence, SpanQuote
    from evidence_kernel.disagreement import decide, enqueue
    from evidence_kernel.envelope import make_envelope, project_source
    from evidence_kernel.ledger import Ledger
    from evidence_kernel.orchestrator import record

    from evidence_eval.b3 import _quote
    from evidence_eval.quote_pipeline import challenge

    chosen = GOLD_FIELDS if fields is None else fields
    hashes: list[str] = []
    abstains: list[str] = []
    recorded: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "b3-second.sqlite3", "bench")
        for index, field in enumerate(chosen):
            quoted = _quote(text, field)
            if quoted is None:
                continue
            if not _is_decimal(quoted["value_text"]):
                continue
            if not _measured_ok(quoted["value_text"], field["unit_text"]):
                abstains.append(
                    enqueue(
                        ledger,
                        tenant_id="bench",
                        actor_id="orchestrator",
                        created_at=f"2026-11-04T18:21:{index:02d}Z",
                        reason="unit_mismatch",
                    )
                )
                continue
            span = SpanQuote.model_validate(quoted)
            extractor = ExtractorOutput(fields=[span], clause_ids=[], assumptions=[])
            if decide(extractor, challenge(text, span)) == "human_queue":
                abstains.append(
                    enqueue(
                        ledger,
                        tenant_id="bench",
                        actor_id="orchestrator",
                        created_at=f"2026-11-04T18:22:{index:02d}Z",
                        reason="agent_disagreement",
                    )
                )
                continue
            from decimal import Decimal

            value = str(Decimal(quoted["value_text"]))
            envelope = make_envelope(
                sources=[project_source("quote", "https://aeroregu.local/quote", "ASSUMPTION")],
                method_version="span_quote@1.0.0",
                inputs={"name": span.name},
                confidence="deterministic",
                result={"name": span.name, "value": value, "unit": field["unit_text"]},
            )
            digest = record(
                ledger,
                {
                    "event_type": "agent_turn",
                    "tenant_id": "bench",
                    "actor_id": "orchestrator",
                    "created_at": f"2026-11-04T18:20:{index:02d}Z",
                    "payload": {"name": span.name},
                    "envelope": envelope,
                },
            )
            ScribeOutput(
                sentences=[ScribeSentence(text="The span is recorded.", ledger_event_hash=digest)]
            )
            hashes.append(digest)
            recorded.append({"name": span.name, "value": value, "unit": field["unit_text"]})
        from evidence_kernel.numbers import stray_physical_numbers

        violations = 0
        for event in ledger.events():
            result = (event["body"].get("envelope") or {}).get("result") or {}
            value = result.get("value") if isinstance(result, dict) else None
            allowed = {value} if isinstance(value, str) else set()
            violations += len(stray_physical_numbers(result, allowed))
    return hashes, abstains, violations, recorded


def _false_alarms(text: str, judged_field, quote) -> tuple[int, int]:
    alarms = 0
    emitted = 0
    for field in GOLD_FIELDS:
        quoted = quote(text, field)
        if quoted is None:
            continue
        emitted += 1
        accepted = (
            judged_field(field["name"], quoted, field["value_text"])
            and _measured_ok(quoted["value_text"], field["unit_text"])
            and _challenger_accepts(text, quoted)
        )
        if not accepted:
            alarms += 1
    return alarms, emitted


def _abstention_hits(words: list[str], recorded: list[dict[str, str]], column: bool) -> int:
    recorded_names = {item.get("name") for item in recorded}
    word_not_stored = "blade_count_word" in words and "blade_count_word" not in recorded_names
    table_not_stored = bool(column)
    return int(word_not_stored) + int(table_not_stored)


def _hits(text: str, judged_field, quote) -> int:
    count = 0
    for field in GOLD_FIELDS:
        quoted = quote(text, field)
        if not judged_field(field["name"], quoted, field["value_text"]):
            continue
        if quoted is None or not _measured_ok(quoted["value_text"], field["unit_text"]):
            continue
        if not _challenger_accepts(text, quoted):
            continue
        count += 1
    return count


def _split_hits(text: str, judged_field, quote) -> tuple[int, list[str]]:
    decimal_hits = 0
    words: list[str] = []
    for field in GOLD_FIELDS:
        quoted = quote(text, field)
        if not judged_field(field["name"], quoted, field["value_text"]):
            continue
        if quoted is None or not _measured_ok(quoted["value_text"], field["unit_text"]):
            continue
        if not _challenger_accepts(text, quoted):
            continue
        if _is_decimal(field["value_text"]):
            decimal_hits += 1
        else:
            words.append(field["name"])
    return decimal_hits, words


def _is_decimal(value: str) -> bool:
    from decimal import Decimal

    try:
        Decimal(value)
    except Exception:
        return False
    return True


def _challenger_accepts(text: str, quoted: dict[str, Any]) -> bool:
    from evidence_kernel.contracts import ExtractorOutput, SpanQuote
    from evidence_kernel.disagreement import decide

    from evidence_eval.quote_pipeline import challenge

    span = SpanQuote.model_validate(quoted)
    extractor = ExtractorOutput(fields=[span], clause_ids=[], assumptions=[])
    return decide(extractor, challenge(text, span)) == "continue"


def _measured_ok(value: str, unit_text: str) -> bool:
    from evidence_eval.quote_pipeline import measured_value_ok

    return measured_value_ok(value, unit_text)


def _pages(pages: list[str], judged_field, quote) -> dict[str, int | None]:
    found: dict[str, int | None] = {}
    for field in GOLD_FIELDS:
        page_no = None
        for index, page in enumerate(pages, start=1):
            quoted = quote(page, field)
            if not judged_field(field["name"], quoted, field["value_text"]):
                continue
            if quoted is None or not _measured_ok(quoted["value_text"], field["unit_text"]):
                continue
            page_no = index
            break
        found[field["name"]] = page_no
    return found
