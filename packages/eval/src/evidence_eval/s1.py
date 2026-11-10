"""S1 mega-synthetic generator.

Cases are invented here. They are not the expert held-out set and must not be
written into bench/b1/expert_holdout.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from json import dumps
from pathlib import Path
from typing import Any

from evidence_kernel.paths import repo_root

from evidence_eval.baseline import naive_assess
from evidence_eval.detect import assess, llm_numeric_violations
from evidence_eval.faults import clean_artifact, inject
from evidence_eval.generate import _bolt, _point
from evidence_eval.score import wilson

S1_VERSION = "s1@1.0.0"
S1_SEED = 20261103
S1_COUNT = 100_000
_PER_FAULT = 7_000
_N_CLEAN = 8_000
_N_COMPOUND = 8_000

SINGLE_FAULTS = (
    "unit_scale",
    "sign",
    "arithmetic",
    "wrong_input",
    "stale_revision",
    "outside_validity",
    "false_coverage",
    "broken_hash",
    "bad_citation",
    "contradictory_requirements",
    "unit_mismatch",
    "missing_input",
)

DIFFICULTY = {
    "unit_scale": "easy",
    "broken_hash": "easy",
    "missing_input": "easy",
    "bad_citation": "medium",
    "sign": "medium",
    "arithmetic": "medium",
    "stale_revision": "medium",
    "false_coverage": "medium",
    "outside_validity": "medium",
    "unit_mismatch": "medium",
    "wrong_input": "hard",
    "contradictory_requirements": "hard",
    "compound": "hard",
    "clean": "easy",
}


def plan_size() -> int:
    return len(SINGLE_FAULTS) * _PER_FAULT + _N_CLEAN + _N_COMPOUND


def iter_cases(limit: int | None = None):
    produced = 0
    for fault in SINGLE_FAULTS:
        for slot in range(_PER_FAULT):
            if limit is not None and produced >= limit:
                return
            yield _single(fault, slot)
            produced += 1
    for slot in range(_N_CLEAN):
        if limit is not None and produced >= limit:
            return
        yield _single(None, slot)
        produced += 1
    for slot in range(_N_COMPOUND):
        if limit is not None and produced >= limit:
            return
        yield _compound(slot)
        produced += 1


def run_s1(limit: int = S1_COUNT) -> dict[str, Any]:
    if limit > plan_size():
        raise ValueError("limit exceeds the pinned S1 plan")
    return _score(iter_cases(limit))


def score_exemplars() -> dict[str, Any]:
    return _score(exemplars())


def _score(cases) -> dict[str, Any]:
    checker_hits: dict[str, int] = defaultdict(int)
    checker_total: dict[str, int] = defaultdict(int)
    naive_hits: dict[str, int] = defaultdict(int)
    shift_hits: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    shift_total: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    clean_total = 0
    false_alarms = 0
    naive_false_alarms = 0
    abstain_total = 0
    abstain_ok = 0
    shift_clean: dict[str, int] = defaultdict(int)
    shift_false_alarms: dict[str, int] = defaultdict(int)
    shift_abstain_total: dict[str, int] = defaultdict(int)
    shift_abstain_ok: dict[str, int] = defaultdict(int)
    compound_total = 0
    compound_any = 0
    compound_complete = 0
    violations = 0
    seen = 0
    difficulty_hits: dict[str, int] = defaultdict(int)
    difficulty_total: dict[str, int] = defaultdict(int)
    false_alarm_hits: dict[str, int] = defaultdict(int)
    false_alarm_eligible: dict[str, int] = defaultdict(int)
    abstain_hits_by: dict[str, int] = defaultdict(int)
    abstain_total_by: dict[str, int] = defaultdict(int)
    for case in cases:
        seen += 1
        violations += llm_numeric_violations(case)
        assessed = assess(case["artifact"])
        got = assessed["verdict"]
        found = set(assessed.get("faults") or [])
        naive = naive_assess(case["artifact"])["verdict"]
        expected = case["expected"]
        shift = case["artifact"]["distribution"]
        difficulty = case["artifact"]["difficulty"]
        difficulty_total[difficulty] += 1
        gold = set(case["faults"])
        for fault in SINGLE_FAULTS:
            if fault in gold:
                if expected == "abstain":
                    abstain_total_by[fault] += 1
                    abstain_hits_by[fault] += int(got == "abstain")
                elif got == "abstain":
                    abstain_total_by[fault] += 1
            else:
                false_alarm_eligible[fault] += 1
                false_alarm_hits[fault] += int(fault in found)
        if expected == "clean":
            clean_total += 1
            shift_clean[shift] += 1
            if got == "clean":
                difficulty_hits[difficulty] += 1
            else:
                false_alarms += 1
                shift_false_alarms[shift] += 1
            if naive != "clean":
                naive_false_alarms += 1
            continue
        if expected == "abstain":
            abstain_total += 1
            shift_abstain_total[shift] += 1
            envelope_ok = got == "abstain"
            if envelope_ok:
                abstain_ok += 1
                shift_abstain_ok[shift] += 1
                difficulty_hits[difficulty] += 1
            continue
        if expected == "detect:compound":
            compound_total += 1
            gold = set(case["faults"])
            if found & gold:
                compound_any += 1
            if got == "detect:compound" and found == gold:
                compound_complete += 1
                difficulty_hits[difficulty] += 1
            continue
        fault_id = expected.split(":", 1)[1]
        checker_total[fault_id] += 1
        shift_total[shift][fault_id] += 1
        if got == expected:
            checker_hits[fault_id] += 1
            shift_hits[shift][fault_id] += 1
            difficulty_hits[difficulty] += 1
        if naive == expected:
            naive_hits[fault_id] += 1
    recall = {fault: f"{checker_hits[fault]}/{checker_total[fault]}" for fault in SINGLE_FAULTS}
    naive_recall = {fault: f"{naive_hits[fault]}/{checker_total[fault]}" for fault in SINGLE_FAULTS}
    return {
        "generator_version": S1_VERSION,
        "seed": S1_SEED,
        "seed_controls_sampling": False,
        "planned_cases": plan_size(),
        "cases": seen,
        "label": "ESTIMATE",
        "date": "2026-11-03",
        "expert_holdout_used": False,
        "checker_recall": recall,
        "checker_recall_ci95": {
            fault: wilson(checker_hits[fault], checker_total[fault]) for fault in SINGLE_FAULTS
        },
        "naive_recall": naive_recall,
        "false_alarms": false_alarms,
        "clean_total": clean_total,
        "false_alarm_rate": _ratio(false_alarms, clean_total),
        "false_alarm_rate_ci95": wilson(false_alarms, clean_total),
        "false_alarm_by_fault": {
            fault: f"{false_alarm_hits[fault]}/{false_alarm_eligible[fault]}"
            for fault in SINGLE_FAULTS
        },
        "false_alarm_by_fault_rate": {
            fault: _ratio(false_alarm_hits[fault], false_alarm_eligible[fault])
            for fault in SINGLE_FAULTS
        },
        "false_alarm_by_fault_ci95": {
            fault: wilson(false_alarm_hits[fault], false_alarm_eligible[fault])
            for fault in SINGLE_FAULTS
        },
        "naive_false_alarms": naive_false_alarms,
        "abstain_ok": abstain_ok,
        "abstain_total": abstain_total,
        "abstention_correctness": _ratio(abstain_ok, abstain_total),
        "abstention_correctness_ci95": wilson(abstain_ok, abstain_total),
        "abstention_by_fault": {
            fault: f"{abstain_hits_by[fault]}/{abstain_total_by[fault]}" for fault in SINGLE_FAULTS
        },
        "abstention_by_fault_rate": {
            fault: _ratio(abstain_hits_by[fault], abstain_total_by[fault])
            for fault in SINGLE_FAULTS
        },
        "abstention_by_fault_ci95": {
            fault: wilson(abstain_hits_by[fault], abstain_total_by[fault])
            for fault in SINGLE_FAULTS
        },
        "llm_numeric_violation": violations,
        "compound_any_hit": _ratio(compound_any, compound_total),
        "compound_complete": _ratio(compound_complete, compound_total),
        "compound_complete_ci95": wilson(compound_complete, compound_total),
        "compound_complete_is_a_pass": compound_total > 0 and compound_complete == compound_total,
        "shift_recall": {
            shift: {
                fault: f"{shift_hits[shift][fault]}/{shift_total[shift][fault]}"
                for fault in SINGLE_FAULTS
            }
            for shift in ("in_distribution", "shifted")
        },
        "shift_recall_ci95": {
            shift: {
                fault: wilson(shift_hits[shift][fault], shift_total[shift][fault])
                for fault in SINGLE_FAULTS
            }
            for shift in ("in_distribution", "shifted")
        },
        "shift_false_alarms": {
            shift: f"{shift_false_alarms[shift]}/{shift_clean[shift]}"
            for shift in ("in_distribution", "shifted")
        },
        "shift_false_alarm_ci95": {
            shift: wilson(shift_false_alarms[shift], shift_clean[shift])
            for shift in ("in_distribution", "shifted")
        },
        "shift_abstention_correctness": {
            shift: _ratio(shift_abstain_ok[shift], shift_abstain_total[shift])
            for shift in ("in_distribution", "shifted")
        },
        "shift_abstention_ci95": {
            shift: wilson(shift_abstain_ok[shift], shift_abstain_total[shift])
            for shift in ("in_distribution", "shifted")
        },
        "difficulty_recall": {
            level: f"{difficulty_hits[level]}/{difficulty_total[level]}"
            for level in ("easy", "medium", "hard")
        },
        "difficulty_recall_ci95": {
            level: wilson(difficulty_hits[level], difficulty_total[level])
            for level in ("easy", "medium", "hard")
        },
        "notes": [
            "Rates are this run's counts. They are not a certification result.",
            "compound_complete counts a case only when every injected fault is returned.",
            "bench/b1/expert_holdout was not read.",
            "A per-fault false alarm is a fault named when it was not injected.",
            "missing_input is the only fault whose correct action is to abstain.",
            "0/0 abstention means that fault never abstained.",
        ],
    }


def checker_single_faults_pass(report: dict[str, Any]) -> bool:
    if report["llm_numeric_violation"] != 0 or report["false_alarms"] != 0:
        return False
    if report["abstain_total"] <= 0 or report["abstain_ok"] != report["abstain_total"]:
        return False
    for fault, value in report["checker_recall"].items():
        if fault == "missing_input":
            continue
        hits, total = value.split("/")
        if total == "0" or hits != total:
            return False
    for value in report.get("false_alarm_by_fault", {}).values():
        hits, _, total = str(value).partition("/")
        if total == "" or hits != "0":
            return False
    return True


def naive_baseline_still_naive(report: dict[str, Any]) -> bool:
    if report["naive_false_alarms"] != 0:
        return False
    for fault, value in report["naive_recall"].items():
        if fault == "missing_input":
            continue
        hits, _total = value.split("/")
        if hits != "0":
            return False
    return True


def public_summary(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "generator_version",
        "seed",
        "seed_controls_sampling",
        "cases",
        "label",
        "date",
        "checker_recall",
        "checker_recall_ci95",
        "naive_recall",
        "false_alarm_rate",
        "false_alarm_rate_ci95",
        "false_alarm_by_fault",
        "false_alarm_by_fault_rate",
        "false_alarm_by_fault_ci95",
        "abstention_correctness",
        "abstention_correctness_ci95",
        "abstention_by_fault",
        "abstention_by_fault_rate",
        "abstention_by_fault_ci95",
        "llm_numeric_violation",
        "shift_recall",
        "shift_recall_ci95",
        "shift_false_alarms",
        "shift_false_alarm_ci95",
        "shift_abstention_correctness",
        "shift_abstention_ci95",
        "difficulty_recall",
        "difficulty_recall_ci95",
        "compound_complete",
        "compound_complete_ci95",
        "compound_complete_is_a_pass",
        "expert_holdout_used",
    )
    return {key: report[key] for key in keys}


def shift_gap_note(report: dict[str, Any]) -> str:
    """Say whether the shifted split changed single-fault recall."""
    left = report["shift_recall"]["in_distribution"]
    right = report["shift_recall"]["shifted"]
    scored = [fault for fault, value in left.items() if not str(value).endswith("/0")]
    differ = [fault for fault in scored if right.get(fault) != left[fault]]
    if scored and not differ:
        return (
            "ESTIMATE: shifted recall equals in-distribution recall on every scored "
            "single fault. This split did not lower the checker."
        )
    if differ:
        names = ", ".join(differ)
        return f"ESTIMATE: shifted recall differs for {names}."
    return "ESTIMATE: no scored single-fault rows in the shift split."


def write_report(report: dict[str, Any]) -> Path:
    folder = repo_root() / "docs" / "benchmarks"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "s1_latest.json"
    path.write_text(dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    from datetime import date

    lines = [
        "# S1 latest run",
        "",
        f"Process date: {date.today().isoformat()}. Scorer date field: {report['date']}.",
        f"Generator: {report['generator_version']}. Seed label: {report['seed']}.",
        "The seed does not drive a random sampler. The case list is a fixed schedule.",
        "",
        "The rates below are ESTIMATE: hits divided by cases in this run, quantized to 0.001.",
        "VERIFIED: this command did not read bench/b1/expert_holdout.",
        "ASSUMPTION: compound complete means the returned fault set equals the injected set.",
        "NOT VERIFIED: this run is not B1, B2, B3, B4, or an expert-authored held-out set.",
        "",
        f"Cases: {report['cases']} of {report['planned_cases']}.",
        f"Checker single-fault hits match the case totals: {checker_single_faults_pass(report)}.",
        f"Naive baseline still misses those faults: {naive_baseline_still_naive(report)}.",
        f"False alarms on clean cases: {report['false_alarms']} / {report['clean_total']}.",
        (
            "False alarms by shift: "
            f"in_distribution {report['shift_false_alarms']['in_distribution']}, "
            f"shifted {report['shift_false_alarms']['shifted']}."
        ),
        (
            "Abstention by shift: "
            f"in_distribution {report['shift_abstention_correctness']['in_distribution']}, "
            f"shifted {report['shift_abstention_correctness']['shifted']}."
        ),
        f"llm_numeric_violation: {report['llm_numeric_violation']}.",
        f"Compound any-hit: {report['compound_any_hit']}.",
        f"Compound complete: {report['compound_complete']}. "
        f"Wilson 95%: {report['compound_complete_ci95']}.",
        f"Compound complete is a pass: {report['compound_complete_is_a_pass']}.",
        shift_gap_note(report),
        "",
        "Per-fault recall is checker_recall. Per-fault false alarms are",
        "false_alarm_by_fault. Per-fault abstention is abstention_by_fault.",
        "Shift intervals and easy/medium/hard recall are in the same file.",
        "Label: ESTIMATE.",
        "",
    ]
    text_path = folder / "s1_latest.md"
    text_path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _ratio(hits: int, total: int) -> str | None:
    if total <= 0:
        return None
    quantum = Decimal("0.001")
    return str((Decimal(hits) / Decimal(total)).quantize(quantum))


def exemplars() -> list[dict[str, Any]]:
    cases = [_single(fault, 1) for fault in SINGLE_FAULTS]
    cases.append(_single(None, 0))
    cases.append(_compound(0))
    return cases


def _single(fault: str | None, slot: int) -> dict[str, Any]:
    shift = "shifted" if slot % 2 else "in_distribution"
    method_id, inputs = _parent_for(fault, shift, slot)
    artifact = clean_artifact(method_id, inputs)
    if fault is None:
        faults: list[str] = []
        expected = "clean"
        name = "clean"
    else:
        artifact = inject(fault, artifact, slot)
        faults = [fault]
        expected = "abstain" if fault == "missing_input" else f"detect:{fault}"
        name = fault
    artifact["distribution"] = shift
    artifact["difficulty"] = DIFFICULTY[name]
    return _case(f"s1-{name}-{shift}-{slot}", faults, expected, artifact)


def _compound(slot: int) -> dict[str, Any]:
    shift = "shifted" if slot % 2 else "in_distribution"
    method_id, inputs = _parent_for("compound", shift, slot)
    artifact = clean_artifact(method_id, inputs)
    artifact = inject("arithmetic", artifact, slot)
    artifact = inject("broken_hash", artifact, slot)
    artifact["distribution"] = shift
    artifact["difficulty"] = "hard"
    faults = ["arithmetic", "broken_hash"]
    return _case(f"s1-compound-{shift}-{slot}", faults, "detect:compound", artifact)


def _parent_for(fault: str | None, shift: str, slot: int) -> tuple[str, dict[str, Any]]:
    if fault == "unit_scale":
        # A 1000x input must stay inside the method card, or the checker abstains
        # for validity instead of naming the scale fault.
        if slot % 2 == 0:
            shear = Decimal("4") if shift == "shifted" else Decimal("3")
            return "bolt_screen", _bolt(shear)
        mass = Decimal("4") if shift == "shifted" else Decimal("2")
        return "rigid_body_point_mass", _point(mass, "1.500")
    return _parent(shift, slot)


def _parent(shift: str, slot: int) -> tuple[str, dict[str, Any]]:
    if slot % 2 == 0:
        shear = Decimal("90000") if shift == "shifted" else Decimal("3000")
        return "bolt_screen", _bolt(shear)
    mass = Decimal("4500") if shift == "shifted" else Decimal("800")
    load = "1.500"
    point = _point(mass, load)
    if shift == "shifted":
        point["altitude_m"] = "4000.000"
        point["cg_x_m"] = "1.250"
    return "rigid_body_point_mass", point


def _case(
    case_id: str, faults: list[str], expected: str, artifact: dict[str, Any]
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "artifact_kind": "note" if artifact["method_id"] == "bolt_screen" else "matrix",
        "faults": faults,
        "expected": expected,
        "artifact": artifact,
        "provenance": {
            "origin": "synthetic",
            "author": "aeroregu",
            "generator_version": S1_VERSION,
            "seed": S1_SEED,
            "statement": "Invented S1 case. Not an expert held-out case.",
            "label": "ASSUMPTION",
        },
    }
