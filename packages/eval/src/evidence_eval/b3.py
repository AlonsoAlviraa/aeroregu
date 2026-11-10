"""B3 dev extraction against a local NASA TM when the file is present.

The PDF stays under data/ and is not committed. Gold strings are short
fields read from that file. This is a dev set written beside the checker,
not an expert held-out set.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from evidence_ingest.pdf import read_pdf_pages
from evidence_kernel.paths import repo_root

PDF_RELATIVE = Path("data/ntrs/NASA-TM-101040.pdf")
EXPECTED_SHA256 = "5ee682caf7d0ce2f95f327fcb3f9ea2ba5ff7ab25d79f8f4aba08a9a6f79fbed"
NTRS_URL = "https://ntrs.nasa.gov/citations/19890010753"

GOLD_FIELDS = (
    {
        "name": "blade_count",
        "value_text": "3",
        "unit_text": "1",
        "pattern": r"number of blades = (\d+)",
    },
    {
        "name": "gravity",
        "value_text": "9.8",
        "unit_text": "m/s2",
        "pattern": r"gravitational acceleration \(m/s2\) = ([0-9.]+)",
    },
    {
        "name": "strain_gage_count",
        "value_text": "31",
        "unit_text": "1",
        "pattern": r"(\d+) strain gages",
    },
    {
        "name": "flight_condition_count",
        "value_text": "23",
        "unit_text": "1",
        "pattern": r"Data from (\d+) flight conditions",
    },
    {
        "name": "level_flight_ratio_low",
        "value_text": "0.14",
        "unit_text": "1",
        "pattern": r"level flights ranging from p\. = ([0-9.]+) to",
    },
    {
        "name": "level_flight_ratio_high",
        "value_text": "0.37",
        "unit_text": "1",
        "pattern": r"p\. = 0\.14 to ([0-9.]+)",
    },
    {
        "name": "turning_flight_ratio_low",
        "value_text": "0.26",
        "unit_text": "1",
        "pattern": r"turning flights from p = ([0-9.]+)",
    },
    {
        "name": "turning_flight_ratio_high",
        "value_text": "0.35",
        "unit_text": "1",
        "pattern": r"p = 0\.26 to ([0-9.]+)",
    },
)


def gold_sha256() -> str:
    import json

    payload = json.dumps(list(GOLD_FIELDS), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def score_b3() -> dict[str, Any]:
    path = repo_root() / PDF_RELATIVE
    holdout = {"scored": False, "llm_numeric_violation": 0}
    if not path.is_file():
        return {
            "benchmark": "B3",
            "ready": False,
            "pdf_present": False,
            "label": "NOT_VERIFIED",
            "note": "Local PDF is absent. The NTRS record was read; the file was not scored.",
            "source_url": NTRS_URL,
            "expert_holdout": holdout["scored"],
            "expert_holdout_llm_numeric_violation": holdout.get("llm_numeric_violation", 0),
        }
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        return {
            "benchmark": "B3",
            "ready": False,
            "pdf_present": True,
            "label": "NOT_VERIFIED",
            "note": "Local PDF hash does not match the file read on 2026-11-03.",
            "source_url": NTRS_URL,
            "sha256": digest,
            "expert_holdout": holdout["scored"],
            "expert_holdout_llm_numeric_violation": holdout.get("llm_numeric_violation", 0),
        }
    pages = _pdf_pages(path)
    full = "\n".join(pages)
    shallow = "\n".join(pages[:2])
    full_hits = _hit_count(full)
    shallow_hits = _hit_count(shallow)
    false_alarms, emitted = _false_alarms(full)
    shallow_alarms, shallow_emitted = _false_alarms(shallow)
    page_limited_misses = _missed_fields(shallow)
    field_pages = _field_pages(pages)
    total = len(GOLD_FIELDS)
    unit_error = _unit_error_detected()
    abstained = _empty_text_abstains()
    assumption = _assumption_span(full)
    load_cases = _load_case_ids(full)
    load_factor = _load_factor_column_abstains(full)
    load_factor_hash = _record_load_factor_abstain(load_factor)
    quoted, quoted_abstains = _record_quoted_spans(full)
    from evidence_eval.score import wilson

    return {
        "benchmark": "B3",
        "ready": False,
        "dev_pdf_scored": True,
        "pdf_present": True,
        "label": "ESTIMATE",
        "date": "2026-11-03",
        "source_url": NTRS_URL,
        "sha256": digest,
        "document": "NASA-TM-101040",
        "fields_correct": f"{full_hits}/{total}",
        "field_accuracy": _ratio(full_hits, total),
        "field_accuracy_ci95": wilson(full_hits, total),
        "no_agent_fields_correct": f"0/{total}",
        "no_agent_field_accuracy": "0.000",
        "no_agent_ci95": wilson(0, total),
        "page_limited_fields_correct": f"{shallow_hits}/{total}",
        "page_limited_field_accuracy": _ratio(shallow_hits, total),
        "page_limited_ci95": wilson(shallow_hits, total),
        "page_limited_misses": page_limited_misses,
        "field_pages": field_pages,
        "unit_error_detected": unit_error,
        "empty_text_abstained": abstained,
        "assumption_span_found": assumption,
        "assumption_value": None,
        "load_case_ids_found": load_cases["found"],
        "load_case_ids": load_cases["ids"],
        "load_case_value": None,
        "load_factor_column_abstained": load_factor,
        "load_factor_value": None,
        "load_factor_abstain_hash": load_factor_hash,
        "quoted_span_hashes": quoted,
        "quoted_span_abstains": quoted_abstains,
        "expert_holdout": holdout["scored"],
        "expert_holdout_llm_numeric_violation": holdout.get("llm_numeric_violation", 0),
        "false_alarms": f"{false_alarms}/{emitted}",
        "false_alarm_ci95": wilson(false_alarms, emitted),
        "page_limited_false_alarms": f"{shallow_alarms}/{shallow_emitted}",
        "page_limited_false_alarm_ci95": wilson(shallow_alarms, shallow_emitted),
        "abstentions_correct": f"{_abstention_hits(abstained, load_factor, assumption)}/3",
        "abstention_ci95": wilson(_abstention_hits(abstained, load_factor, assumption), 3),
        "beats_page_limited_reader": full_hits > shallow_hits,
        "beats_no_agent": full_hits > 0,
        "beats_single_llm": "NOT_VERIFIED",
        "notes": [
            "Gold and checker were written in the same session. This is not a held-out set.",
            "ready is false. dev_pdf_scored only means the local PDF matched the dev patterns.",
            "The spec no-agent baseline reads no pages and returns no fields.",
            "Beating that baseline is a trivial comparison.",
            "A false alarm is an emitted field whose value is not the gold value.",
            "The abstention count is empty text, the load-factor column, and the assumption span.",
            "The two-page count is a separate page-limited reader.",
            "The full-document reader uses the same patterns on every page.",
            "Page text comes from evidence_ingest.pdf.read_pdf_pages.",
            "A live single-LLM baseline was not run.",
            "Field hits pass through JudgeInput. A reasoning field is not a hit.",
            "The assumption span is quoted and is not turned into a number.",
            "Assumption and load-case spans are ledger events written by the orchestrator.",
            "NTRS lists an Aerospatiale co-author.",
            "The citation page says public use is permitted.",
        ],
    }


def _record_quoted_spans(text: str) -> tuple[list[str], list[str]]:
    import tempfile
    from pathlib import Path

    from evidence_kernel.contracts import ExtractorOutput, ScribeOutput, ScribeSentence, SpanQuote
    from evidence_kernel.disagreement import decide, enqueue
    from evidence_kernel.envelope import make_envelope, project_source
    from evidence_kernel.ledger import Ledger
    from evidence_kernel.orchestrator import record

    from evidence_eval.quote_pipeline import challenge

    fragments = (
        "assumed to be a beam",
        "V3101, V3103, V3105, V3106",
        "V3109, and V3111",
    )
    hashes: list[str] = []
    abstains: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "b3.sqlite3", "bench")
        for index, fragment in enumerate(fragments):
            start = text.find(fragment)
            if start < 0:
                continue
            field = SpanQuote(
                name=f"span-{index}",
                value_text=fragment,
                span_start=start,
                span_end=start + len(fragment),
            )
            extractor = ExtractorOutput(fields=[field], clause_ids=[], assumptions=[])
            if decide(extractor, challenge(text, field)) == "human_queue":
                abstains.append(
                    enqueue(
                        ledger,
                        tenant_id="bench",
                        actor_id="orchestrator",
                        created_at=f"2026-11-03T21:21:{index:02d}Z",
                        reason="agent_disagreement",
                    )
                )
                continue
            envelope = make_envelope(
                sources=[project_source("quote", "https://aeroregu.local/quote", "ASSUMPTION")],
                method_version="span_quote@1.0.0",
                inputs={"name": field.name},
                confidence="deterministic",
                result={"name": field.name},
            )
            digest = record(
                ledger,
                {
                    "event_type": "agent_turn",
                    "tenant_id": "bench",
                    "actor_id": "orchestrator",
                    "created_at": f"2026-11-03T21:20:{index:02d}Z",
                    "payload": {"name": field.name},
                    "envelope": envelope,
                },
            )
            ScribeOutput(
                sentences=[ScribeSentence(text="The span is recorded.", ledger_event_hash=digest)]
            )
            hashes.append(digest)
    return hashes, abstains


def _assumption_span(text: str) -> bool:
    fragment = "assumed to be a beam"
    start = text.find(fragment)
    if start < 0:
        return False
    return text[start : start + len(fragment)] == fragment


_LOAD_CASE_IDS = ("V3101", "V3103", "V3105", "V3106", "V3109", "V3111")


def _load_case_ids(text: str) -> dict[str, Any]:
    start = text.find("six flight conditions, V3101")
    if start < 0:
        return {"found": False, "ids": []}
    window = text[start : start + 160]
    found = tuple(re.findall(r"\bV\d{4}\b", window))
    return {"found": found == _LOAD_CASE_IDS, "ids": list(found)}


def _record_load_factor_abstain(column: bool) -> str | None:
    import tempfile

    from evidence_kernel.disagreement import enqueue
    from evidence_kernel.ledger import Ledger

    if not column:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "b3-load.sqlite3", "bench")
        return enqueue(
            ledger,
            tenant_id="bench",
            actor_id="orchestrator",
            created_at="2026-11-04T19:05:00Z",
            reason="unreadable_table",
        )


def _load_factor_column_abstains(text: str) -> bool:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "Load Factor" or index + 1 >= len(lines):
            continue
        follower = lines[index + 1].strip()
        if re.fullmatch(r"\d+\.\d+", follower):
            return True
    return False


def _pdf_pages(path: Path) -> list[str]:
    return read_pdf_pages(path)


def _accepted(text: str, field: dict[str, str]) -> bool:
    from evidence_kernel.contracts import ExtractorOutput, SpanQuote
    from evidence_kernel.disagreement import decide

    from evidence_eval.quote_pipeline import challenge, measured_value_ok

    quoted = _quote(text, field)
    if not judged_field(field["name"], quoted, field["value_text"]):
        return False
    if quoted is None or not measured_value_ok(quoted["value_text"], field["unit_text"]):
        return False
    span = SpanQuote.model_validate(quoted)
    extractor = ExtractorOutput(fields=[span], clause_ids=[], assumptions=[])
    return decide(extractor, challenge(text, span)) == "continue"


def _hit_count(text: str) -> int:
    return sum(1 for field in GOLD_FIELDS if _accepted(text, field))


def _false_alarms(text: str) -> tuple[int, int]:
    alarms = 0
    emitted = 0
    for field in GOLD_FIELDS:
        if _quote(text, field) is None:
            continue
        emitted += 1
        if not _accepted(text, field):
            alarms += 1
    return alarms, emitted


def _abstention_hits(empty_text: bool, load_factor: bool, assumption: bool) -> int:
    return int(empty_text) + int(load_factor) + int(assumption)


def _field_pages(pages: list[str]) -> dict[str, int | None]:
    found: dict[str, int | None] = {}
    for field in GOLD_FIELDS:
        page_no = None
        for index, page in enumerate(pages, start=1):
            if _accepted(page, field):
                page_no = index
                break
        found[field["name"]] = page_no
    return found


def _missed_fields(text: str) -> list[str]:
    return [field["name"] for field in GOLD_FIELDS if not _accepted(text, field)]


def judged_field(name: str, quote: dict[str, Any] | None, gold: str) -> bool:
    """Score one quoted field. JudgeInput never receives the page text."""
    from evidence_kernel.contracts import ExtractorOutput, JudgeInput, SpanQuote
    from pydantic import ValidationError

    if quote is None:
        return False
    try:
        extractor = ExtractorOutput(
            fields=[SpanQuote.model_validate(quote)],
            clause_ids=[],
            assumptions=[],
        )
    except ValidationError:
        return False
    judged = JudgeInput(
        case_id=name,
        verdict=extractor.fields[0].value_text,
        gold_label=gold,
    )
    from evidence_eval.quote_pipeline import _values_match

    return _values_match(judged.verdict, judged.gold_label)


def _quote(text: str, field: dict[str, str]) -> dict[str, Any] | None:
    match = re.search(field["pattern"], text)
    if match is None:
        return None
    return {
        "name": field["name"],
        "value_text": match.group(1),
        "unit_text": field["unit_text"],
        "span_start": match.start(1),
        "span_end": match.end(1),
    }


def _extract(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    if match is None:
        return None
    return match.group(1)


def _unit_error_detected() -> bool:
    mutated = "gravitational acceleration (ft/s2) = 9.8"
    gold_unit = "m/s2"
    found = re.search(r"gravitational acceleration \(([^)]+)\) = 9\.8", mutated)
    if found is None:
        return False
    return found.group(1) != gold_unit


def _empty_text_abstains() -> bool:
    return _extract("", r"number of blades = (\d+)") is None


def _ratio(hits: int, total: int) -> str:
    from decimal import Decimal

    return str((Decimal(hits) / Decimal(total)).quantize(Decimal("0.001")))


B3_AUTHOR_SENTENCE = "I did not write the checker in b3.py."


def validate_b3_holdout(folder: Path | None = None) -> dict[str, Any]:
    """Schema check only. This does not score an expert file."""
    target = folder or (repo_root() / "bench" / "b3" / "expert_holdout")
    author = target / "AUTHOR.md"
    text = author.read_text(encoding="utf-8") if author.is_file() else ""
    statement = B3_AUTHOR_SENTENCE in text
    valid = 0
    rejected = 0
    files = 0
    reasons: dict[str, int] = {}
    if target.is_dir():
        for path in sorted(target.glob("*.json")):
            files += 1
            reason = _b3_reason(path)
            if reason is None:
                valid += 1
            else:
                rejected += 1
                reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "files": files,
        "valid": valid,
        "rejected": rejected,
        "reject_reasons": reasons,
        "author_statement": statement,
        "ready": bool(statement and valid > 0 and rejected == 0),
        "scored": False,
        "label": "NOT_VERIFIED",
    }


def score_b3_holdout(folder: Path | None = None) -> dict[str, Any]:
    """Score a holdout case only when its document path matches the stated hash.

    The two development NASA files are rejected before this runs.
    A missing document is an abstention, not a detection.
    """
    import json

    from evidence_eval.holdout_gate import outside_repo

    if folder is None or not outside_repo(folder):
        return {
            "scored": False,
            "read": False,
            "ready": False,
            "label": "NOT_VERIFIED",
            "note": "The folder must be outside the repository. No case file was opened.",
        }
    target = folder
    checked = validate_b3_holdout(target)
    if not checked["ready"]:
        return {
            "scored": False,
            "ready": False,
            "abstained": 0,
            "label": "NOT_VERIFIED",
            "reject_reasons": checked.get("reject_reasons", {}),
            "note": "The B3 expert directory is not ready to score.",
        }
    judged = 0
    hits = 0
    total = 0
    abstained = 0
    abstain_reasons: dict[str, int] = {}
    violations = 0
    import tempfile
    from decimal import Decimal

    from evidence_kernel.disagreement import enqueue
    from evidence_kernel.envelope import make_envelope, project_source
    from evidence_kernel.ledger import Ledger
    from evidence_kernel.numbers import stray_physical_numbers
    from evidence_kernel.orchestrator import record

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "b3-holdout.sqlite3", "bench")
        try:
            for index, path in enumerate(sorted(target.glob("*.json"))):
                if not _accept_b3_holdout(path):
                    continue
                case = json.loads(path.read_text(encoding="utf-8"))
                reason = _document_reason(case, target)
                if reason is not None:
                    enqueue(
                        ledger,
                        tenant_id="bench",
                        actor_id="orchestrator",
                        created_at=f"2026-11-09T16:10:{index:02d}Z",
                        reason=reason,
                    )
                    abstained += 1
                    abstain_reasons[reason] = abstain_reasons.get(reason, 0) + 1
                    continue
                document = _holdout_text(case, target)
                judged += 1
                for field_index, field in enumerate(case["fields"]):
                    total += 1
                    if not _field_hit(field, document):
                        continue
                    hits += 1
                    value = str(Decimal(str(field.get("value_text", ""))))
                    envelope = make_envelope(
                        sources=[
                            project_source(
                                "quote",
                                "https://aeroregu.local/holdout",
                                "ASSUMPTION",
                            )
                        ],
                        method_version="holdout_quote@1.0.0",
                        inputs={"name": str(field.get("name", ""))},
                        confidence="deterministic",
                        result={"value": value, "unit": str(field.get("unit_text", "1"))},
                    )
                    record(
                        ledger,
                        {
                            "event_type": "recompute_flag",
                            "tenant_id": "bench",
                            "actor_id": "orchestrator",
                            "created_at": f"2026-11-09T16:11:{field_index:02d}Z",
                            "payload": {"name": str(field.get("name", ""))},
                            "envelope": envelope,
                        },
                    )
            for event in ledger.events():
                result = (event["body"].get("envelope") or {}).get("result") or {}
                value = result.get("value") if isinstance(result, dict) else None
                allowed = {value} if isinstance(value, str) else set()
                violations += len(stray_physical_numbers(result, allowed))
        except Exception as exc:
            return {
                "scored": False,
                "stopped": type(exc).__name__,
                "ready": False,
                "label": "NOT_VERIFIED",
                "note": "The scorer stopped. The case text is not in this report.",
            }
    if judged == 0:
        return {
            "scored": False,
            "ready": False,
            "abstained": abstained,
            "abstain_reasons": abstain_reasons,
            "label": "NOT_VERIFIED",
            "note": "Nothing was scored. abstain_reasons does not name the file.",
        }
    from evidence_eval.score import wilson

    return {
        "scored": True,
        "ready": False,
        "judge_correct": f"{hits}/{total}",
        "judge_ci95": wilson(hits, total),
        "llm_numeric_violation": violations,
        "abstained": abstained,
        "abstain_reasons": abstain_reasons,
        "label": "ESTIMATE",
        "note": "The named document was scored. ready stays false.",
    }


def _field_hit(field: dict[str, Any], document: str) -> bool:
    from evidence_kernel.contracts import ExtractorOutput, SpanQuote
    from evidence_kernel.disagreement import decide

    from evidence_eval.quote_pipeline import challenge

    value = str(field.get("value_text", ""))
    if not _value_token(value, document):
        return False
    unit = str(field.get("unit_text", "1"))
    if unit not in {"", "1", "dimensionless"} and not _declared_unit_follows(value, unit, document):
        return False
    match = _first_equal_measurement(value, document)
    if match is None:
        return False
    span = SpanQuote(
        name=str(field.get("name", "field")),
        value_text=value,
        unit_text=unit or "1",
        span_start=match.start(),
        span_end=match.end(),
    )
    extractor = ExtractorOutput(fields=[span], clause_ids=[], assumptions=[])
    return decide(extractor, challenge(document, span)) == "continue"


def _declared_unit_follows(value: str, unit: str, document: str) -> bool:
    import re
    from decimal import Decimal

    from evidence_calc.units import same_unit

    try:
        target = Decimal(value)
    except Exception:
        return False
    for match in _measurement_matches(document):
        try:
            if Decimal(match.group()) != target:
                continue
        except Exception:
            continue
        tail = document[match.end() : match.end() + 16].lstrip()
        token = re.match(r"[A-Za-z][A-Za-z0-9/^]*", tail)
        if token is not None and same_unit(unit, token.group()):
            return True
    return False


def _first_equal_measurement(value: str, document: str):
    from decimal import Decimal

    try:
        target = Decimal(value)
    except Exception:
        return None
    for match in _measurement_matches(document):
        try:
            if Decimal(match.group()) == target:
                return match
        except Exception:
            continue
    return None


def _value_token(value: str, document: str) -> bool:
    from decimal import Decimal

    try:
        Decimal(value)
    except Exception:
        return False
    return _first_equal_measurement(value, document) is not None


def _measurement_matches(document: str):
    """Numbers that are not the tail of an identifier such as CS-27.301."""
    import re

    for match in re.finditer(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", document):
        if match.start() > 0:
            previous = document[match.start() - 1]
            if previous.isalpha() or previous in "-.":
                continue
        yield match


def _document_reason(case: dict[str, Any], base: Path) -> str | None:
    """Why the document was not read. The code has no path and no file text."""
    import hashlib

    relative = case.get("document_path")
    if not isinstance(relative, str) or not relative:
        return "path_missing"
    root = base.resolve()
    path = (base / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return "path_outside"
    if not path.is_file():
        return "document_absent"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != str(case.get("document_sha256", "")).strip().casefold():
        return "hash_mismatch"
    return None


def _holdout_text(case: dict[str, Any], base: Path) -> str | None:
    if _document_reason(case, base) is not None:
        return None
    relative = case.get("document_path")
    assert isinstance(relative, str)
    path = (base / relative).resolve()
    if path.suffix.casefold() == ".pdf":
        from evidence_ingest.pdf import read_pdf_pages

        return "\n".join(read_pdf_pages(path, (1, 500)))
    return path.read_text(encoding="utf-8", errors="replace")


def _accept_b3_holdout(path: Path) -> bool:
    return _b3_reason(path) is None


def _b3_reason(path: Path) -> str | None:
    """A rejection code, or None when the file counts. The code has no field text."""
    import json

    try:
        case = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "json"
    except OSError:
        return "unreadable"
    if not isinstance(case, dict):
        return "schema"
    if not str(case.get("case_id", "")).strip():
        return "case_id"
    if not str(case.get("document_sha256", "")).strip():
        return "document_sha256"
    if _dev_document(str(case.get("document_sha256", ""))):
        return "dev_document"
    fields = case.get("fields")
    if (
        not isinstance(fields, list)
        or not fields
        or any(not _field_shape(field) for field in fields)
    ):
        return "fields"
    provenance = case.get("provenance")
    if not isinstance(provenance, dict):
        return "provenance"
    author = str(provenance.get("author", "")).strip()
    if not author or author.casefold() == "aeroregu":
        return "author"
    statement = str(provenance.get("statement", "")).casefold()
    if "no employer" not in statement and "not employer" not in statement:
        return "statement"
    if _copies_dev_gold(fields):
        return "copied_dev_gold"
    return None


def _dev_document(digest: str) -> bool:
    from evidence_eval.b3_second import EXPECTED_SHA256 as second_sha256

    known = {EXPECTED_SHA256.casefold(), second_sha256.casefold()}
    return digest.strip().casefold() in known


def _field_shape(field: object) -> bool:
    if not isinstance(field, dict):
        return False
    name = str(field.get("name", "")).strip()
    value = str(field.get("value_text", "")).strip()
    return bool(name and value)


def _copies_dev_gold(fields: list[object]) -> bool:
    got: set[tuple[str, str]] = set()
    for field in fields:
        if not _field_shape(field):
            return False
        assert isinstance(field, dict)
        name = str(field.get("name", "")).strip()
        value = str(field.get("value_text", "")).strip()
        got.add((name, value))
    dev = {(item["name"], item["value_text"]) for item in GOLD_FIELDS}
    from evidence_eval.b3_second import GOLD_FIELDS as second_fields

    second = {(item["name"], item["value_text"]) for item in second_fields}
    return got == dev or got == second
