"""B2 dev scorer: synthetic reports against public requirement identifiers.

Clause text is not copied. The headings CS 27.301 Loads and CS 29.301 Loads
were seen on public EASA pages on 2026-11-09. The paragraphs are not stored.
The expert held-out directory is not read.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from evidence_kernel.paths import repo_root

from evidence_eval.score import wilson

ID_RE = re.compile(r"\b(?:VTOL\.\d{4}|CS-27\.\d{3,4}|CS-29\.\d{3,4})\b")
PUBLIC_HEADINGS = frozenset(
    {
        "CS-27.301",
        "CS-29.301",
        "VTOL.2200",
        "VTOL.2210",
        "VTOL.2215",
        "VTOL.2220",
        "VTOL.2225",
        "VTOL.2230",
    }
)
EV_RE = re.compile(r"\bev-\d+\b")
ZERO_HASH = "0" * 64

# Headings were read on 2026-11-09. Paragraphs are not stored.
# CS 27.301 Loads, CS 29.301 Loads, and the six VTOL.22xx headings below.


def validate_b2_holdout(folder: Path | None = None) -> dict[str, Any]:
    """Schema check only. This does not score the expert files."""
    from evidence_eval.holdout_gate import holdout_gate

    target = folder or (repo_root() / "bench" / "b2" / "expert_holdout")
    gate = holdout_gate(target)
    valid = 0
    rejected = 0
    reasons: dict[str, int] = {}
    if target.is_dir():
        for path in sorted(target.glob("*.json")):
            reason = _holdout_reason(path)
            if reason is None:
                valid += 1
            else:
                rejected += 1
                reasons[reason] = reasons.get(reason, 0) + 1
    ready = bool(gate["author_statement"] and valid > 0 and rejected == 0)
    return {
        "valid": valid,
        "rejected": rejected,
        "reject_reasons": reasons,
        "author_statement": gate["author_statement"],
        "ready": ready,
        "scored": False,
    }


def score_expert_holdout(folder: Path | None = None) -> dict[str, Any]:
    """Score accepted holdout files with the frozen hash verifier.

    A file with no evidence hash is an abstention. It is not a detection.
    An empty directory is not scored.
    """
    import json

    from evidence_eval.holdout_gate import outside_repo

    if folder is None or not outside_repo(folder):
        return {
            "scored": False,
            "read": False,
            "judge_correct": "0/0",
            "label": "NOT_VERIFIED",
            "note": "The folder must be outside the repository. No case file was opened.",
        }
    target = folder
    checked = validate_b2_holdout(target)
    if not checked["ready"]:
        return {
            "scored": False,
            "judge_correct": "0/0",
            "abstained": 0,
            "label": "NOT_VERIFIED",
            "reject_reasons": checked.get("reject_reasons", {}),
            "note": "The expert held-out directory is not ready to score.",
        }
    judged = 0
    judged_hits = 0
    abstained = 0
    try:
        for path in sorted(target.glob("*.json")):
            if not _accept_holdout_case(path):
                continue
            case = json.loads(path.read_text(encoding="utf-8"))
            evidence = case.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                abstained += 1
                continue
            links, _flags = predict(str(case["report"]), evidence, check_hash=True)
            judged += 1
            if judged_match(str(case["case_id"]), links, case["gold_links"]):
                judged_hits += 1
    except Exception as exc:
        return {
            "scored": False,
            "stopped": type(exc).__name__,
            "judge_correct": "0/0",
            "label": "NOT_VERIFIED",
            "note": "The scorer stopped. The case text is not in this report.",
        }
    if judged == 0:
        return {
            "scored": False,
            "judge_correct": "0/0",
            "abstained": abstained,
            "label": "NOT_VERIFIED",
            "note": "Nothing was scored. An empty evidence list abstains.",
        }
    from evidence_eval.score import wilson

    return {
        "scored": True,
        "judge_correct": f"{judged_hits}/{judged}",
        "judge_ci95": wilson(judged_hits, judged),
        "abstained": abstained,
        "label": "ESTIMATE",
        "note": "Scored with the frozen hash verifier. Not used to change the checker.",
    }


def _link_pair(item: object) -> bool:
    if not isinstance(item, (list, tuple)) or len(item) != 2:
        return False
    left, right = item
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and bool(left.strip())
        and bool(right.strip())
    )


def _evidence_shape(item: object) -> bool:
    return isinstance(item, dict) and bool(str(item.get("id", "")).strip())


def _accept_holdout_case(path: Path) -> bool:
    return _holdout_reason(path) is None


def _holdout_reason(path: Path) -> str | None:
    """A rejection code, or None when the file counts. The code has no report text."""
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
    if not str(case.get("report", "")).strip():
        return "report"
    links = case.get("gold_links")
    if not isinstance(links, list) or any(not _link_pair(item) for item in links):
        return "gold_links"
    evidence = case.get("evidence", [])
    if evidence not in (None, []) and (
        not isinstance(evidence, list) or any(not _evidence_shape(item) for item in evidence)
    ):
        return "evidence"
    provenance = case.get("provenance")
    if not isinstance(provenance, dict):
        return "provenance"
    author = str(provenance.get("author", "")).strip()
    if not author or author.casefold() == "aeroregu":
        return "author"
    statement = str(provenance.get("statement", "")).casefold()
    if "no employer" not in statement and "not employer" not in statement:
        return "statement"
    report = str(case.get("report", "")).strip()
    if report in {str(item["report"]).strip() for item in dev_cases()}:
        return "copied_dev_report"
    return None


def dev_cases() -> list[dict[str, Any]]:
    true_pairs = (
        ("ev-1", "VTOL.2210"),
        ("ev-2", "VTOL.2215"),
        ("ev-3", "VTOL.2200"),
        ("ev-4", "CS-27.301"),
        ("ev-5", "CS-29.301"),
        ("ev-6", "VTOL.2230"),
    )
    cases = [
        _true_case(index, evidence_id, requirement_id)
        for index, (evidence_id, requirement_id) in enumerate(true_pairs)
    ]
    cases.append(_false_case(6, "ev-7", "VTOL.2220"))
    cases.append(_false_case(7, "ev-8", "VTOL.2225"))
    return cases


def dev_sha256() -> str:
    import json

    slim = []
    for case in dev_cases():
        slim.append(
            {
                "case_id": case["case_id"],
                "false_claims": case["false_claims"],
                "gold_links": [list(link) for link in case["gold_links"]],
                "hashes": [item["hash"] for item in case["evidence"]],
                "report": case["report"],
            }
        )
    payload = json.dumps(slim, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unopened_holdout() -> dict[str, Any]:
    """File count only. make bench must not parse an expert case."""
    return {
        "scored": False,
        "label": "NOT_VERIFIED",
        "note": "make bench does not open expert case files.",
    }


def score_b2() -> dict[str, Any]:
    from evidence_eval.holdout_gate import holdout_gate

    hash_blind = _score_links(check_hash=False)
    verifier = _score_links(check_hash=True)
    names = holdout_gate(repo_root() / "bench" / "b2" / "expert_holdout")
    chain = _agent_chain_dev()
    holdout_score = _unopened_holdout()
    return {
        "benchmark": "B2",
        "split": "dev",
        "cases": len(dev_cases()),
        "expert_holdout_cases": 0,
        "expert_holdout_files": names["cases"],
        "expert_holdout_parsed": False,
        "expert_holdout_author_statement": names["author_statement"],
        "expert_holdout_ready": False,
        "expert_holdout_score": holdout_score,
        "label": "ESTIMATE",
        "date": "2026-11-03",
        "hash_blind": hash_blind,
        "verifier": verifier,
        "no_agent": verifier,
        "agent": chain,
        "beats_hash_blind": _beats(verifier, hash_blind),
        "beats_no_agent": _chain_beats_verifier(chain, verifier),
        "beats_single_llm": "NOT_VERIFIED",
        "agent_chain": chain,
        "span_probe": span_probe(),
        "public_headings_only": heading_gate_ok(),
        "notes": [
            "The hash-blind linker ignores the hash. The verifier drops a zero hash.",
            "The spec no-agent baseline is that verifier. It is not an LLM.",
            "The specialist chain ties the verifier on these cases, so it does not beat it.",
            "Chain intervals cover the 8 dev cases only. The span probe is excluded.",
            "A live single-LLM baseline was not run.",
            "Headings CS 27.301 Loads and CS 29.301 Loads were seen on 2026-11-09.",
            "SC-VTOL-02 headings seen the same day: VTOL.2200, VTOL.2210, VTOL.2215,",
            "VTOL.2220, VTOL.2225, and VTOL.2230. Paragraphs were not copied.",
            "An identifier outside that heading list is not linked.",
            "The old CS-27 document-library URL returned 404 on 2026-11-03.",
            "The CS-29 Amendment 12 page was read on 2026-11-03 and states no licence.",
            "The expert held-out directory is empty, so it was not scored.",
        ],
    }


def span_probe() -> dict[str, Any]:
    """A bad span the hash verifier still links. Not part of the frozen dev hash."""
    import tempfile
    from pathlib import Path

    from evidence_kernel.contracts import ExtractorOutput, SpanQuote
    from evidence_kernel.disagreement import decide, enqueue
    from evidence_kernel.ledger import Ledger

    from evidence_eval.quote_pipeline import challenge

    text = "Pack ev-1 addresses VTOL.2210 with a stored hash."
    links, _flags = predict(text, [{"id": "ev-1", "hash": "ab" * 32}], check_hash=True)
    field = SpanQuote(
        name="requirement_id",
        value_text="VTOL.2210",
        span_start=0,
        span_end=4,
    )
    extractor = ExtractorOutput(fields=[field], clause_ids=["VTOL.2210"], assumptions=[])
    abstain = decide(extractor, challenge(text, field)) == "human_queue"
    event_hash = None
    event_type = None
    if abstain:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp) / "span.sqlite3", "bench")
            event_hash = enqueue(
                ledger,
                tenant_id="bench",
                actor_id="orchestrator",
                created_at="2026-11-04T17:40:00Z",
                reason="agent_disagreement",
            )
            event_type = ledger.events()[-1]["body"]["event_type"]
    return {
        "frozen_set": False,
        "verifier_links": len(links) == 1,
        "chain_abstains": abstain,
        "queue": "human_engineer" if abstain else None,
        "event_hash": event_hash,
        "event_type": event_type,
        "label": "ESTIMATE",
        "note": "One synthetic sentence. Not in the frozen dev hash.",
    }


def _chain_beats_verifier(chain: dict[str, Any], verifier: dict[str, Any]) -> bool:
    chain_hits, chain_total = chain["judge_correct"].split("/")
    verifier_hits, verifier_total = verifier["judge_correct"].split("/")
    if chain_total != verifier_total or chain_total == "0":
        return False
    return int(chain_hits) > int(verifier_hits)


def _score_links(check_hash: bool) -> dict[str, Any]:
    true_positive = 0
    predicted = 0
    gold = 0
    span_hits = 0
    span_total = 0
    false_gold = 0
    false_hits = 0
    judge_hits = 0
    judge_total = 0
    for case in dev_cases():
        links, flags = predict(case["report"], case["evidence"], check_hash=check_hash)
        gold_set = {tuple(item) for item in case["gold_links"]}
        pred_set = {(link["requirement_id"], link["evidence_id"]) for link in links}
        true_positive += len(pred_set & gold_set)
        predicted += len(pred_set)
        gold += len(gold_set)
        judge_total += 1
        if judged_match(case["case_id"], links, case["gold_links"]):
            judge_hits += 1
        for link in links:
            span_total += 1
            report = case["report"]
            start = link["span_start"]
            end = link["span_end"]
            if report[start:end] == link["requirement_id"]:
                span_hits += 1
        for claim in case["false_claims"]:
            false_gold += 1
            if (claim["requirement_id"], claim["evidence_id"]) in flags:
                false_hits += 1
    return {
        "precision": _ratio(true_positive, predicted),
        "recall": _ratio(true_positive, gold),
        "precision_ci95": wilson(true_positive, predicted),
        "recall_ci95": wilson(true_positive, gold),
        "false_coverage_recall": _ratio(false_hits, false_gold),
        "false_coverage_recall_ci95": wilson(false_hits, false_gold),
        "span_accuracy": _ratio(span_hits, span_total),
        "span_accuracy_ci95": wilson(span_hits, span_total),
        "judge_correct": f"{judge_hits}/{judge_total}",
        "judge_ci95": wilson(judge_hits, judge_total),
    }


def judged_match(case_id: str, links: list[dict[str, Any]], gold_links: list[Any]) -> bool:
    """Compare link sets through JudgeInput. Extra fields, including reasoning, fail."""
    from evidence_kernel.contracts import JudgeInput, MapperLink, MapperOutput
    from pydantic import ValidationError

    try:
        mapper = MapperOutput(links=[MapperLink.model_validate(link) for link in links])
    except ValidationError:
        return False
    verdict = _canon((link.requirement_id, link.evidence_id) for link in mapper.links)
    gold_label = _canon(tuple(item) for item in gold_links)
    judged = JudgeInput(case_id=case_id, verdict=verdict, gold_label=gold_label)
    return judged.verdict == judged.gold_label


def _canon(pairs) -> str:
    return "|".join(sorted(f"{requirement}>{evidence}" for requirement, evidence in pairs))


def _beats(agent: dict[str, Any], no_agent: dict[str, Any]) -> bool:
    if agent["recall"] is None or no_agent["recall"] is None:
        return False
    if agent["precision"] is None or no_agent["precision"] is None:
        return False
    return agent["precision"] > no_agent["precision"] and agent["recall"] >= no_agent["recall"]


def heading_gate_ok() -> bool:
    """Dev cases may cite only headings that were seen, and an unseen id is not linked."""
    for case in dev_cases():
        for requirement_id, _evidence_id in case["gold_links"]:
            if requirement_id not in PUBLIC_HEADINGS:
                return False
        for claim in case["false_claims"]:
            if claim["requirement_id"] not in PUBLIC_HEADINGS:
                return False
    links, flags = predict(
        "Pack ev-1 addresses VTOL.9999 with a stored hash.",
        [{"id": "ev-1", "hash": "ab" * 32}],
    )
    return links == [] and flags == set()


def predict(
    report: str,
    evidence: list[dict[str, str]],
    check_hash: bool = True,
) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    by_id = {item["id"]: item for item in evidence}
    links: list[dict[str, Any]] = []
    flags: set[tuple[str, str]] = set()
    for match in ID_RE.finditer(report):
        window_start = max(0, match.start() - 80)
        window = report[window_start : match.end() + 80]
        evidence_ids = EV_RE.findall(window)
        if not evidence_ids:
            continue
        evidence_id = evidence_ids[-1]
        if match.group() not in PUBLIC_HEADINGS:
            continue
        record = by_id.get(evidence_id)
        pair = (match.group(), evidence_id)
        bad_hash = record is None or record.get("hash") == ZERO_HASH
        if check_hash and bad_hash:
            flags.add(pair)
            continue
        links.append(
            {
                "requirement_id": match.group(),
                "evidence_id": evidence_id,
                "span_start": match.start(),
                "span_end": match.end(),
            }
        )
    return links, flags


def _true_case(index: int, evidence_id: str, requirement_id: str) -> dict[str, Any]:
    report = f"Pack {evidence_id} addresses {requirement_id} with a stored hash."
    return {
        "case_id": f"b2-dev-true-{index:02d}",
        "report": report,
        "evidence": [{"id": evidence_id, "hash": "ab" * 32}],
        "gold_links": [(requirement_id, evidence_id)],
        "false_claims": [],
    }


def _false_case(index: int, evidence_id: str, requirement_id: str) -> dict[str, Any]:
    report = f"Pack {evidence_id} claims {requirement_id} without a real hash."
    return {
        "case_id": f"b2-dev-false-{index:02d}",
        "report": report,
        "evidence": [{"id": evidence_id, "hash": ZERO_HASH}],
        "gold_links": [],
        "false_claims": [{"requirement_id": requirement_id, "evidence_id": evidence_id}],
    }


def _agent_chain_dev() -> dict[str, Any]:
    import tempfile
    from pathlib import Path

    from evidence_kernel.ledger import Ledger

    from evidence_eval.agent_case import run_identifier_case

    hits = 0
    link_hits = 0
    link_total = 0
    false_hits = 0
    false_total = 0
    false_alarms = 0
    abstentions = 0
    cases = dev_cases()
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "b2.sqlite3", "bench")
        for index, case in enumerate(cases):
            evidence = case["evidence"][0]
            outcome = run_identifier_case(
                ledger,
                text=case["report"],
                evidence_id=evidence["id"],
                evidence_hash=evidence["hash"],
                tenant_id="bench",
                actor_id="orchestrator",
                created_at=f"2026-11-03T21:10:{index:02d}Z",
            )
            if outcome.get("queue"):
                abstentions += 1
            if case["gold_links"]:
                link_total += 1
                expected = case["gold_links"][0][0]
                ok = outcome["requirement_id"] == expected and outcome["false_coverage"] is False
                link_hits += int(ok)
                if outcome.get("false_coverage"):
                    false_alarms += 1
            else:
                false_total += 1
                ok = outcome["requirement_id"] is None and outcome["false_coverage"] is True
                false_hits += int(ok)
                if outcome.get("requirement_id"):
                    false_alarms += 1
            hits += int(ok)
        violations = _result_number_violations(ledger.events())
    return {
        "judge_correct": f"{hits}/{len(cases)}",
        "judge_ci95": wilson(hits, len(cases)),
        "link_recall": f"{link_hits}/{link_total}",
        "link_recall_ci95": wilson(link_hits, link_total),
        "false_coverage_recall": f"{false_hits}/{false_total}",
        "false_coverage_recall_ci95": wilson(false_hits, false_total),
        "false_alarms": f"{false_alarms}/{link_total}",
        "abstentions": abstentions,
        "llm_numeric_violation": violations,
        "label": "ESTIMATE",
        "note": (
            "Synthetic reports. Identifier shapes, not clause quotations. "
            "The span probe is not in these counts."
        ),
    }


def _result_number_violations(events: list[dict[str, Any]]) -> int:
    from evidence_kernel.numbers import stray_physical_numbers

    count = 0
    for event in events:
        envelope = event["body"].get("envelope") or {}
        count += len(stray_physical_numbers(envelope.get("result"), set()))
    return count


def b1_status() -> dict[str, Any]:
    from evidence_eval.holdout_gate import holdout_gate

    gate = holdout_gate(repo_root() / "bench" / "b1" / "expert_holdout")
    return {
        "benchmark": "B1",
        "expert_holdout_cases": 0,
        "expert_holdout_files": gate["cases"],
        "expert_holdout_parsed": False,
        "fault_types": 0,
        "author_statement": gate["author_statement"],
        "ready": False,
        "scored": False,
        "label": "NOT_VERIFIED",
        "note": "make bench does not open expert case files. The file count is names only.",
    }


def b3_status() -> dict[str, Any]:
    from evidence_eval.b3 import score_b3

    return score_b3()


def b4_status() -> dict[str, Any]:
    from evidence_eval.b4 import (
        drill,
        inspect_as365_header,
        registered_bearing_zip,
        unregistered_files,
    )

    register = repo_root() / "docs" / "data_register.md"
    text = register.read_text(encoding="utf-8") if register.is_file() else ""
    folder = repo_root() / "data" / "b4"
    missing = unregistered_files(folder, text)
    as365 = inspect_as365_header()
    bearing = registered_bearing_zip()
    present: list[str] = []
    archive = None
    bearing_registered = True
    if folder.is_dir():
        present = [path.name for path in sorted(folder.iterdir()) if path.is_file()]
    if isinstance(bearing, dict) and bearing.get("hash_match") is False:
        bearing_registered = False
        note = "The file is not the registered one."
    elif missing:
        names = ", ".join(missing)
        note = f"Local B4 files are not in the data register: {names}. They are not scored."
    elif present:
        from evidence_eval.b4 import BEARING_ZIP, inspect_acceleration_zip

        if isinstance(bearing, dict) and bearing.get("hash_match") is True:
            archive = inspect_acceleration_zip(repo_root() / BEARING_ZIP)
        else:
            archive = inspect_acceleration_zip(folder / present[0])
        names = ", ".join(present)
        note = (
            f"Registered local files: {names}. Acceleration files: "
            f"{archive['acceleration_files']}. Bare first lines: "
            f"{archive['bare_first_lines']}. Files at the published length: "
            f"{archive['files_matching_published_length']}. "
            f"Shortest {archive['shortest_file_lines']}, longest {archive['longest_file_lines']}. "
            f"Path tokens: {archive['path_tokens']}. "
            f"Files whose class token is a published code: "
            f"{archive['files_whose_class_token_is_published']}. "
            f"Abstain reason: {archive['abstain_reason']}. "
            "No exceedance count was computed. "
            f"Compiled Python files: {archive['pyc_files']}. They were not executed. "
            "The exceedance drill is founder-owned synthetic and is not B4."
        )
    else:
        note = (
            "No licensed public series is on disk in data/b4. The exceedance drill "
            "below is founder-owned synthetic and is not B4. The AS365-K2 UFF "
            "under data/as365/ states Acceleration m/s^2 in its header and is "
            "not scored, because that header states no exceedance limit. "
            "The Stanford helicopter page and the Ottawa bearing version 5 page, "
            "read on 2026-11-04, stated no copyright licence. The Paderborn paper "
            "states CC BY-NC 4.0 for the data, so that set was rejected. "
            "NASA/TM-2019-220311, citation 20200002067, was opened on 2026-11-10. "
            "It lists channel units and is not a sample file, so it does not make B4 ready."
        )
    status = {
        "benchmark": "B4",
        "ready": False,
        "in_file_probe": {
            "public_result": False,
            "consulted_for_ready": False,
        },
        "label": "NOT_VERIFIED",
        "candidate_url": "https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data",
        "unregistered_files": missing,
        "public_archive": archive,
        "as365": as365,
        "drill": drill(),
        "note": note,
    }
    if not bearing_registered:
        status["bearing_registered"] = False
    return status


def holdout_dir() -> Path:
    return repo_root() / "bench" / "b2" / "expert_holdout"


def _ratio(hits: int, total: int) -> str | None:
    if total <= 0:
        return None
    from decimal import Decimal

    return str((Decimal(hits) / Decimal(total)).quantize(Decimal("0.001")))
