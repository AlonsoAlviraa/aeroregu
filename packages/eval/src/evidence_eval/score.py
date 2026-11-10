from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from evidence_kernel.paths import repo_root
from evidence_kernel.schema import validate_instance

from evidence_eval.detect import DETERMINISTIC_FAULTS, assess, llm_numeric_violations

_QUANTUM = Decimal("0.001")
_Z = Decimal("1.96")
SCORED_FAULTS = DETERMINISTIC_FAULTS + (
    "stale_revision",
    "false_coverage",
    "broken_hash",
    "bad_span",
    "missing_input",
)


def load_split(split: str) -> list[dict[str, Any]]:
    folder = repo_root() / "bench" / split
    cases = []
    for path in sorted(folder.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        validate_instance("benchmark_case.schema.json", case)
        cases.append(case)
    return cases


def wilson(hits: int, total: int) -> dict[str, str] | None:
    """95% Wilson interval. Endpoints are decimal strings, clipped to [0, 1]."""
    if total <= 0:
        return None
    n = Decimal(total)
    phat = Decimal(hits) / n
    z2 = _Z * _Z
    denom = Decimal(1) + z2 / n
    center = (phat + z2 / (Decimal(2) * n)) / denom
    radicand = phat * (Decimal(1) - phat) / n + z2 / (Decimal(4) * n * n)
    margin = _Z * radicand.sqrt() / denom
    low = max(Decimal(0), center - margin)
    high = min(Decimal(1), center + margin)
    return {
        "low": str(low.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)),
        "high": str(high.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)),
        "method": "wilson",
        "z": "1.96",
    }


def _rate(hits: int, total: int) -> str | None:
    if total <= 0:
        return None
    return str((Decimal(hits) / Decimal(total)).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN))


def score_cases(
    cases: list[dict[str, Any]],
    assess_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if assess_fn is None:
        assess_fn = assess
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"hit": 0, "total": 0})
    clean_total = 0
    false_alarms = 0
    missing_total = 0
    missing_ok = 0
    violations = 0
    mismatches: list[dict[str, str]] = []
    false_alarm_hits: dict[str, int] = defaultdict(int)
    false_alarm_eligible: dict[str, int] = defaultdict(int)
    abstain_hits: dict[str, int] = defaultdict(int)
    abstain_total: dict[str, int] = defaultdict(int)
    for case in cases:
        violations += llm_numeric_violations(case)
        assessed = assess_fn(case["artifact"])
        got = assessed["verdict"]
        expected = case["expected"]
        found = set(assessed.get("faults") or [])
        gold = set(case.get("faults") or [])
        envelope = assessed.get("envelope") or {}
        correct_abstain = (
            got == "abstain"
            and "result" not in envelope
            and envelope.get("confidence") == "abstain"
        )
        if expected == "abstain":
            abstain_total["missing_input"] += 1
            abstain_hits["missing_input"] += int(correct_abstain)
        elif got == "abstain":
            for fault in gold:
                if fault in SCORED_FAULTS:
                    abstain_total[fault] += 1
        for fault in SCORED_FAULTS:
            if fault in gold:
                continue
            false_alarm_eligible[fault] += 1
            false_alarm_hits[fault] += int(fault in found)
        if expected == "clean":
            clean_total += 1
            if got != "clean":
                false_alarms += 1
                mismatches.append({"case_id": case["case_id"], "expected": expected, "got": got})
        elif expected == "abstain":
            missing_total += 1
            envelope = assessed["envelope"]
            if (
                got == "abstain"
                and "result" not in envelope
                and envelope["confidence"] == "abstain"
            ):
                missing_ok += 1
            else:
                mismatches.append({"case_id": case["case_id"], "expected": expected, "got": got})
        else:
            fault = expected.split(":", 1)[1]
            buckets[fault]["total"] += 1
            if got == expected:
                buckets[fault]["hit"] += 1
            else:
                mismatches.append({"case_id": case["case_id"], "expected": expected, "got": got})
    fault_recall = {}
    fault_counts = {}
    fault_recall_ci95 = {}
    for fault, counts in buckets.items():
        fault_recall[fault] = _rate(counts["hit"], counts["total"])
        fault_counts[fault] = f"{counts['hit']}/{counts['total']}"
        fault_recall_ci95[fault] = wilson(counts["hit"], counts["total"])
    recall = {}
    recall_ci95 = {}
    for fault in DETERMINISTIC_FAULTS:
        total = buckets[fault]["total"]
        hits = buckets[fault]["hit"]
        recall[fault] = None if total == 0 else hits / total
        recall_ci95[fault] = wilson(hits, total)
    trace = {}
    trace_ci95 = {}
    for fault in ("stale_revision", "false_coverage", "broken_hash", "bad_span"):
        total = buckets[fault]["total"]
        hits = buckets[fault]["hit"]
        trace[fault] = None if total == 0 else hits / total
        trace_ci95[fault] = wilson(hits, total)
    return {
        "cases": len(cases),
        "deterministic_recall": recall,
        "deterministic_recall_ci95": recall_ci95,
        "trace_recall": trace,
        "trace_recall_ci95": trace_ci95,
        "false_alarms": false_alarms,
        "clean_total": clean_total,
        "false_alarm_rate": _rate(false_alarms, clean_total),
        "false_alarm_rate_ci95": wilson(false_alarms, clean_total),
        "missing_input_ok": missing_ok,
        "missing_input_total": missing_total,
        "abstention_correctness": _rate(missing_ok, missing_total),
        "abstention_correctness_ci95": wilson(missing_ok, missing_total),
        "false_alarm_by_fault": {
            fault: f"{false_alarm_hits[fault]}/{false_alarm_eligible[fault]}"
            for fault in SCORED_FAULTS
        },
        "false_alarm_by_fault_ci95": {
            fault: wilson(false_alarm_hits[fault], false_alarm_eligible[fault])
            for fault in SCORED_FAULTS
        },
        "abstention_by_fault": {
            fault: f"{abstain_hits[fault]}/{abstain_total[fault]}" for fault in SCORED_FAULTS
        },
        "abstention_by_fault_ci95": {
            fault: wilson(abstain_hits[fault], abstain_total[fault]) for fault in SCORED_FAULTS
        },
        "note": "Same-author split. Not the expert holdout.",
        "llm_numeric_violation": violations,
        "fault_recall": fault_recall,
        "fault_counts": fault_counts,
        "fault_recall_ci95": fault_recall_ci95,
        "mismatches": mismatches,
    }


def holdout_freeze_hash() -> str:
    path = repo_root() / "bench" / "holdout" / "SHA256.txt"
    return path.read_text(encoding="utf-8").strip()


def assert_holdout_frozen() -> None:
    from evidence_eval.generate import directory_hash

    folder = repo_root() / "bench" / "holdout"
    actual = directory_hash(folder)
    expected = holdout_freeze_hash()
    if actual != expected:
        raise AssertionError("holdout files do not match the frozen hash")
