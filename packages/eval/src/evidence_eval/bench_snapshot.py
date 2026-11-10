"""Write the bench objects to disk so a truncated print does not hide them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evidence_kernel.paths import repo_root


def write_bench_snapshot(
    benchmarks: dict[str, Any],
    *,
    note: str,
    folder: Path | None = None,
) -> Path:
    target = folder if folder is not None else repo_root() / "docs" / "benchmarks"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "make_bench_latest.json"
    path.write_text(
        json.dumps(benchmarks, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    brief = target / "make_bench_latest.md"
    brief.write_text(_brief(benchmarks, note), encoding="utf-8")
    return path


def _ci(block: object) -> str:
    if not isinstance(block, dict):
        return "absent"
    low = block.get("low")
    high = block.get("high")
    if low is None or high is None:
        return "absent"
    return f"{low} to {high}"


def _b3_alarm_line(b3: dict[str, Any]) -> str:
    if "false_alarms" not in b3:
        return "B3 false alarms: absent."
    return (
        f"B3 false alarms: {b3.get('false_alarms')}. "
        f"Wilson 95%: {_ci(b3.get('false_alarm_ci95'))}. "
        f"Page-limited false alarms: {b3.get('page_limited_false_alarms')}. "
        f"Abstentions correct: {b3.get('abstentions_correct')}. "
        f"Wilson 95%: {_ci(b3.get('abstention_ci95'))}. "
        "Beating the no-read baseline is trivial."
    )


def _b3_baseline_line(b3: dict[str, Any]) -> str:
    no_agent = str(b3.get("no_agent_fields_correct", ""))
    if b3.get("beats_no_agent") is True and no_agent.startswith("0/"):
        return (
            "B3 beats_no_agent is true because the no-read baseline scored 0. "
            "That comparison is trivial."
        )
    return f"B3 beats_no_agent: {b3.get('beats_no_agent')}."


def _s1_lines(s1: dict[str, Any]) -> list[str]:
    recall = s1.get("checker_recall") or {}
    intervals = s1.get("checker_recall_ci95") or {}
    naive = s1.get("naive_recall") or {}
    if not isinstance(recall, dict):
        return []
    lines = [
        (
            f"S1 {fault}: checker {recall[fault]}, naive {naive.get(fault)}, "
            f"Wilson 95% {_ci(intervals.get(fault))}."
        )
        for fault in sorted(recall)
    ]
    lines.append(
        f"S1 false-alarm rate: {s1.get('false_alarm_rate')}. "
        f"Wilson 95%: {_ci(s1.get('false_alarm_rate_ci95'))}."
    )
    lines.append(
        f"S1 abstention correctness: {s1.get('abstention_correctness')}. "
        f"Wilson 95%: {_ci(s1.get('abstention_correctness_ci95'))}."
    )
    return lines


def _s1_extra(s1: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    difficulty = s1.get("difficulty_recall") or {}
    intervals = s1.get("difficulty_recall_ci95") or {}
    if isinstance(difficulty, dict):
        for name in ("easy", "medium", "hard"):
            if name not in difficulty:
                continue
            lines.append(f"S1 {name}: {difficulty[name]}. Wilson 95% {_ci(intervals.get(name))}.")
    shift = s1.get("shift_recall") or {}
    left = shift.get("in_distribution") if isinstance(shift, dict) else None
    right = shift.get("shifted") if isinstance(shift, dict) else None
    if isinstance(left, dict) and isinstance(right, dict) and left:
        scored = [fault for fault, value in left.items() if not str(value).endswith("/0")]
        same = all(right.get(fault) == left[fault] for fault in scored)
        if scored and same:
            lines.append(
                "S1 shift: in-distribution equals shifted on every scored fault. "
                "This split did not lower the checker."
            )
        elif scored:
            lines.append("S1 shift: in-distribution and shifted differ.")
        intervals = s1.get("shift_recall_ci95") or {}
        shifted_ci = intervals.get("shifted") if isinstance(intervals, dict) else None
        if isinstance(shifted_ci, dict):
            for fault in sorted(scored):
                lines.append(
                    f"S1 shifted {fault}: {right.get(fault)}. "
                    f"Wilson 95% {_ci(shifted_ci.get(fault))}."
                )
    if s1.get("compound_complete") is not None:
        lines.append(
            f"S1 compound complete: {s1.get('compound_complete')}. "
            f"Wilson 95%: {_ci(s1.get('compound_complete_ci95'))}."
        )
    return lines


def _quote_line(report: dict[str, Any]) -> str:
    rows = report.get("recorded_fields") or []
    if not rows:
        return "B3 quote ledger: absent."
    parts = [f"{item.get('name')} {item.get('value')}" for item in rows]
    return (
        "B3 quote ledger: "
        + "; ".join(parts)
        + f". llm_numeric_violation: {report.get('llm_numeric_violation')}."
    )


def _load_factor_line(report: dict[str, Any]) -> str:
    if not report.get("load_factor_column_abstained"):
        return "B3 load-factor column: not abstained."
    digest = report.get("load_factor_abstain_hash") or ""
    recorded = "ledger event recorded" if len(str(digest)) == 64 else "no ledger event"
    return f"B3 load-factor column abstained. Value empty. {recorded}."


def _span_probe_line(probe: dict[str, Any]) -> str:
    if not probe:
        return "B2 span probe: absent."
    return (
        f"B2 span probe: verifier links {probe.get('verifier_links')}, "
        f"chain abstains {probe.get('chain_abstains')}. "
        "Not in the frozen dev set."
    )


def _second_pdf_absent(report: dict[str, Any]) -> bool:
    """True only when the second PDF was not scored because it is not on disk."""
    if report.get("pdf_present") is True:
        return False
    return report.get("pdf_present") is False or report.get("scored") is False


def _second_line(report: dict[str, Any]) -> str:
    # A field count keeps its Wilson interval. The generic line is only for a missing PDF.
    if not report.get("fields_correct"):
        if _second_pdf_absent(report):
            return "B3 second memorandum: not on disk. Not scored. NOT_VERIFIED."
        if report.get("pdf_present") is True and report.get("scored") is False:
            return "B3 second memorandum: hash does not match. Not scored. NOT_VERIFIED."
        return "B3 second memorandum: absent."
    return (
        f"B3 second memorandum: {report.get('fields_correct')} full text, "
        f"{report.get('page_limited_fields_correct')} on the first two pages. "
        f"Wilson 95%: {_ci(report.get('field_accuracy_ci95'))}. "
        f"{_decimal_bit(report)}"
        f"Ledger events: {len(report.get('event_hashes') or [])}. "
        f"{_numeric_bit(report)}"
        f"{_recorded_bit(report)}"
        f"Shared flight ids: {report.get('shared_with_first_memo')}. "
        f"Absent: {report.get('absent_from_second_memo')}. "
        f"Flight-table column abstained: {report.get('flight_table_column_abstained')}. "
        f"Unit abstains: {len(report.get('unit_abstain_hashes') or [])}. "
        "No table magnitude stored. "
        "Same-session gold. Not a held-out set."
        f"{_second_alarm_bit(report)}"
    )


def _second_alarm_bit(report: dict[str, Any]) -> str:
    if "false_alarms" not in report:
        return ""
    return (
        f" False alarms: {report.get('false_alarms')}. "
        f"Wilson 95%: {_ci(report.get('false_alarm_ci95'))}. "
        f"Page-limited false alarms: {report.get('page_limited_false_alarms')}. "
        f"Abstentions correct: {report.get('abstentions_correct')}. "
        f"Wilson 95%: {_ci(report.get('abstention_ci95'))}. "
        "Beating the no-read baseline is trivial."
    )


def _numeric_bit(report: dict[str, Any]) -> str:
    if "llm_numeric_violation" not in report:
        return ""
    return f"llm_numeric_violation: {report.get('llm_numeric_violation')}. "


def _recorded_bit(report: dict[str, Any]) -> str:
    rows = report.get("recorded_fields") or []
    if not rows:
        return ""
    parts = [f"{item.get('name')} {item.get('value')} {item.get('unit')}" for item in rows]
    return "Recorded: " + "; ".join(parts) + ". "


def _decimal_bit(report: dict[str, Any]) -> str:
    words = report.get("word_labels_not_recomputed") or []
    decimals = report.get("decimal_fields_correct")
    if not words and not decimals:
        return ""
    named = ", ".join(str(item) for item in words)
    return f"Decimals on the ledger: {decimals}. Word label not recomputed: {named}. "


def _as365_line(b4: dict[str, Any]) -> str:
    report = b4.get("as365")
    if not isinstance(report, dict) or not report:
        return "B4 AS365: absent."
    if report.get("file_present") is False:
        return "B4 AS365: not on disk. Not scored. NOT_VERIFIED."
    if report.get("hash_match") is False:
        return (
            "B4 AS365: hash does not match. The file is not the registered one. "
            "Not scored. NOT_VERIFIED."
        )
    return (
        f"B4 AS365 unit: {report.get('ordinate_unit')}. "
        f"Records: {report.get('record_count')}. "
        f"Structure matches: {report.get('structure_matches')}. "
        f"Header step matches 1/8192: {report.get('step_matches_8192_hz')}. "
        f"Duration at 8192 Hz matches 60 s: {report.get('duration_matches_paper_60s')}. "
        f"Length abstain: {report.get('length_abstain_reason')}. "
        f"Abstain: {report.get('abstain_reason')}. "
        "Samples were not stored. Not scored."
    )


def _chain_numeric_line(b2: dict[str, Any]) -> str:
    chain = b2.get("agent_chain") or {}
    if "llm_numeric_violation" not in chain:
        return "B2 chain llm_numeric_violation: absent."
    line = f"B2 chain llm_numeric_violation: {chain.get('llm_numeric_violation')}."
    if "judge_ci95" not in chain:
        return line
    return (
        f"{line} Judge {chain.get('judge_correct')} "
        f"Wilson 95%: {_ci(chain.get('judge_ci95'))}. "
        f"Link recall {chain.get('link_recall')} "
        f"Wilson 95%: {_ci(chain.get('link_recall_ci95'))}. "
        f"False-coverage recall {chain.get('false_coverage_recall')} "
        f"Wilson 95%: {_ci(chain.get('false_coverage_recall_ci95'))}. "
        f"False alarms {chain.get('false_alarms')}. "
        f"Abstentions {chain.get('abstentions')}. "
        "The span probe is not in these counts."
    )


def _programme_line(gate: dict[str, Any]) -> str:
    if not gate:
        return "Programme gate: absent."
    return (
        f"Programme complete: {gate.get('programme_complete')}. "
        f"Open legal rows: {gate.get('open_legal_rows')}. "
        f"Signed reviews: {gate.get('signed_reviews')}. "
        f"Single-LLM known: {gate.get('single_llm_known')}. "
        f"Second gold frozen: {gate.get('b3_second_frozen')}. "
        f"Drill frozen: {gate.get('b4_drill_frozen')}."
        f"{_programme_extra(gate)}"
    )


def _programme_extra(gate: dict[str, Any]) -> str:
    parts: list[str] = []
    if "b1_scored" in gate:
        parts.append(f"B1 scored: {gate.get('b1_scored')}.")
    if "b2_holdout_scored" in gate:
        parts.append(f"B2 holdout scored: {gate.get('b2_holdout_scored')}.")
    if "b3_holdout_scored" in gate:
        parts.append(f"B3 holdout scored: {gate.get('b3_holdout_scored')}.")
    if "b3_single_llm_known" in gate:
        parts.append(f"B3 single-LLM known: {gate.get('b3_single_llm_known')}.")
    if not parts:
        return ""
    return " " + " ".join(parts)


def _in_file_probe_line(b4: dict[str, Any]) -> str:
    """Report the probe flag. Never print its count as a public B4 result."""
    probe = b4.get("in_file_probe")
    if not isinstance(probe, dict):
        return ""
    return f"B4 in-file probe public result: {probe.get('public_result')}."


def _scored_public_series(b4: dict[str, Any]) -> bool:
    archive = b4.get("public_archive")
    if isinstance(archive, dict) and archive.get("scored") is True:
        return True
    as365 = b4.get("as365")
    return isinstance(as365, dict) and as365.get("scored") is True


def _abstain_line(archive: dict[str, Any]) -> str:
    return (
        f"B4 abstain: {archive.get('abstain_reason')}. "
        f"Sensor range applied: {archive.get('sensor_range_applied')}."
    )


def _b4_lines(b4: dict[str, Any]) -> list[str]:
    archive = b4.get("public_archive")
    inspected = archive if isinstance(archive, dict) else {}
    lines = [f"B4 ready: {b4.get('ready')}."]
    probe = _in_file_probe_line(b4)
    if probe:
        lines.append(probe)
    # The generic line is only for a missing zip. An inspected abstain keeps its reason.
    if not isinstance(archive, dict) and b4.get("ready") is False and not _scored_public_series(b4):
        lines.append("B4: not scored. NOT_VERIFIED.")
    if isinstance(archive, dict):
        lines.append(_abstain_line(inspected))
    if b4.get("bearing_registered") is False:
        lines.append(
            "B4 bearing zip: The file is not the registered one. Not scored. NOT_VERIFIED."
        )
    lines.append(_as365_line(b4))
    return lines


def _b3_lines(b3: dict[str, Any], benchmarks: dict[str, Any]) -> list[str]:
    if b3.get("pdf_present") is False and not b3.get("fields_correct"):
        ready = f"B3 ready: {b3.get('ready')}."
        if "dev_pdf_scored" in b3:
            ready = f"B3 ready: {b3.get('ready')}. dev_pdf_scored: {b3.get('dev_pdf_scored')}."
        return [ready, "B3: not scored. NOT_VERIFIED."]
    return [
        f"B3 ready: {b3.get('ready')}. dev_pdf_scored: {b3.get('dev_pdf_scored')}.",
        f"B3 fields: {b3.get('fields_correct')}. Wilson 95%: {_ci(b3.get('field_accuracy_ci95'))}.",
        _quote_line(benchmarks.get("b3_quotes") or {}),
        _load_factor_line(b3),
        f"B3 page-limited: {b3.get('page_limited_fields_correct')}. "
        f"Wilson 95%: {_ci(b3.get('page_limited_ci95'))}.",
        f"B3 no-agent: {b3.get('no_agent_fields_correct')}. "
        f"Wilson 95%: {_ci(b3.get('no_agent_ci95'))}.",
        _b3_baseline_line(b3),
        _b3_alarm_line(b3),
        f"B3 misses: {json.dumps(b3.get('page_limited_misses'))}.",
        f"B3 pages: {json.dumps(b3.get('field_pages'))}.",
        f"B3 beats_single_llm: {b3.get('beats_single_llm')}.",
    ]


def _brief(benchmarks: dict[str, Any], note: str) -> str:
    b1 = benchmarks.get("b1", {})
    b2 = benchmarks.get("b2", {})
    b3 = benchmarks.get("b3", {})
    b4 = benchmarks.get("b4", {})
    quarantine = benchmarks.get("quarantine_duplicate_citation", {})
    s1 = benchmarks.get("s1", {})
    lines = [
        "# make bench snapshot",
        "",
        note,
        "",
        "NOT VERIFIED: this file is not an expert-authored held-out result.",
        "",
        f"B1 ready: {b1.get('ready')}. Cases: {b1.get('expert_holdout_cases')}.",
        f"B2 beats_no_agent: {b2.get('beats_no_agent')}. "
        f"beats_single_llm: {b2.get('beats_single_llm')}.",
        f"B2 public headings only: {b2.get('public_headings_only')}.",
        _chain_numeric_line(b2),
        _span_probe_line(b2.get("span_probe") or {}),
        *_b3_lines(b3, benchmarks),
        _second_line(benchmarks.get("b3_second") or {}),
        *_b4_lines(b4),
        f"Duplicate citation recall: {quarantine.get('recall')}. "
        f"Wilson 95%: {_ci(quarantine.get('recall_ci95'))}. "
        f"System verdict: {quarantine.get('system_verdict')}.",
        f"S1 cases: {s1.get('cases')}.",
        *_s1_lines(s1),
        *_s1_extra(s1),
        _programme_line(benchmarks.get("programme") or {}),
        "",
    ]
    return "\n".join(lines)
