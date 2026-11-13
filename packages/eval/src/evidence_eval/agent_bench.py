"""Synthetic 3-architecture agent benchmark across 24 deterministic cases.

This tool assists a human reviewer. It does not determine compliance.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from evidence_calc.registry import run_method
from evidence_kernel.contracts import ExtractorOutput, SpanQuote
from evidence_kernel.disagreement import decide, enqueue
from evidence_kernel.gateway import FixtureGateway
from evidence_kernel.ledger import Ledger
from evidence_kernel.numbers import collect_decimals, stray_physical_numbers
from evidence_kernel.supervisor import CaseSpec, run_case

from evidence_eval.agent_case import run_identifier_case
from evidence_eval.b2 import predict
from evidence_eval.quote_pipeline import challenge
from evidence_eval.score import wilson

DISCLAIMER = "This tool assists a human reviewer. It does not determine compliance."

CATEGORIES: tuple[str, ...] = (
    "clean_verified",
    "corrupted_span",
    "label_disagreement",
    "refuter_contradiction",
    "stray_number_injection",
    "decision_gate_low_confidence",
)

RIGID_BODY_INPUTS: dict[str, Any] = {
    "mass_kg": "800.000",
    "gravity_m_s2": "10.000",
    "load_factor": "1.000",
    "cg_x_m": "0.000",
    "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
    "unit_operative": [True, True, True, True],
}

BOLT_SCREEN_INPUTS: dict[str, Any] = {
    "shear_force_n": "3000.000",
    "tensile_force_n": "4000.000",
    "area_mm2": "80.000",
    "shear_allowable_mpa": "250.000",
    "tensile_allowable_mpa": "250.000",
}

HEADINGS: tuple[str, ...] = (
    "VTOL.2210",
    "VTOL.2215",
    "CS-27.301",
    "CS-29.301",
)


@dataclass(frozen=True)
class AgentBenchCase:
    case_id: str
    category: str
    heading: str
    evidence_id: str
    evidence_hash: str
    text: str
    method_id: str
    calc_inputs: dict[str, Any]
    scenario: str
    expected_outcome: str
    reader_label: str = "VERIFIED"
    use_decision_gate: bool = False
    corrupt_span: bool = False
    stated_outputs: dict[str, Any] | None = None


def build_agent_bench_cases() -> list[AgentBenchCase]:
    """Construct the 24 deterministic benchmark cases (6 categories x 4 cases)."""
    cases: list[AgentBenchCase] = []
    rigid_outputs = run_method("rigid_body_point_mass", RIGID_BODY_INPUTS)["outputs"]
    bolt_outputs = run_method("bolt_screen", BOLT_SCREEN_INPUTS)["outputs"]

    for idx, heading in enumerate(HEADINGS):
        ev_id = f"ev-{idx + 1}"
        ev_hash = f"{idx + 1:02x}" * 32
        method_id = "rigid_body_point_mass" if idx % 2 == 0 else "bolt_screen"
        inputs = dict(RIGID_BODY_INPUTS if idx % 2 == 0 else BOLT_SCREEN_INPUTS)
        base_text = f"Pack {ev_id} addresses {heading} with a stored hash."

        # 1. clean_verified
        cases.append(
            AgentBenchCase(
                case_id=f"ab-clean-{idx + 1:02d}",
                category="clean_verified",
                heading=heading,
                evidence_id=ev_id,
                evidence_hash=ev_hash,
                text=base_text,
                method_id=method_id,
                calc_inputs=inputs,
                scenario="happy",
                expected_outcome="accept",
                reader_label="VERIFIED",
            )
        )

        # 2. corrupted_span
        cases.append(
            AgentBenchCase(
                case_id=f"ab-span-{idx + 1:02d}",
                category="corrupted_span",
                heading=heading,
                evidence_id=ev_id,
                evidence_hash=ev_hash,
                text=base_text,
                method_id=method_id,
                calc_inputs=inputs,
                scenario="bad_span",
                expected_outcome="abstain",
                reader_label="VERIFIED",
                corrupt_span=True,
            )
        )

        # 3. label_disagreement
        cases.append(
            AgentBenchCase(
                case_id=f"ab-disagree-{idx + 1:02d}",
                category="label_disagreement",
                heading=heading,
                evidence_id=ev_id,
                evidence_hash=ev_hash,
                text=base_text,
                method_id=method_id,
                calc_inputs=inputs,
                scenario="disagree",
                expected_outcome="abstain",
                reader_label="VERIFIED" if idx % 2 == 0 else "ASSUMPTION",
            )
        )

        # 4. refuter_contradiction
        cases.append(
            AgentBenchCase(
                case_id=f"ab-refuter-{idx + 1:02d}",
                category="refuter_contradiction",
                heading=heading,
                evidence_id=ev_id,
                evidence_hash=ev_hash,
                text=f"{base_text} Internal assumption contradicts load case.",
                method_id=method_id,
                calc_inputs=inputs,
                scenario="refuter_hit",
                expected_outcome="abstain",
                reader_label="ASSUMPTION",
            )
        )

        # 5. stray_number_injection
        if idx < 2:
            stray_scenario = "stray_number"
            stated: dict[str, Any] | None = None
        else:
            stray_scenario = "integer_leak"
            base_out = dict(rigid_outputs if idx % 2 == 0 else bolt_outputs)
            target_key = "weight_n" if idx % 2 == 0 else "shear_stress_mpa"
            base_out[target_key] = "800"
            stated = base_out
        cases.append(
            AgentBenchCase(
                case_id=f"ab-stray-{idx + 1:02d}",
                category="stray_number_injection",
                heading=heading,
                evidence_id=ev_id,
                evidence_hash=ev_hash,
                text=base_text,
                method_id=method_id,
                calc_inputs=inputs,
                scenario=stray_scenario,
                expected_outcome="abstain",
                reader_label="ESTIMATE",
                stated_outputs=stated,
            )
        )

        # 6. decision_gate_low_confidence
        cases.append(
            AgentBenchCase(
                case_id=f"ab-gate-{idx + 1:02d}",
                category="decision_gate_low_confidence",
                heading=heading,
                evidence_id=ev_id,
                evidence_hash=ev_hash,
                text=f"{base_text} Source scan confidence is low.",
                method_id=method_id,
                calc_inputs=inputs,
                scenario="gate_low",
                expected_outcome="abstain",
                reader_label="NOT_VERIFIED",
                use_decision_gate=True,
            )
        )

    return cases


def _eval_no_agent(case: AgentBenchCase) -> tuple[str, int]:
    """Evaluate the regex/hash verifier + deterministic calc without agent checks."""
    links, flags = predict(
        case.text,
        [{"id": case.evidence_id, "hash": case.evidence_hash}],
        check_hash=True,
    )
    ran = run_method(case.method_id, case.calc_inputs)
    if links and not flags and "outputs" in ran:
        return "accept", 0
    return "abstain", 0


def _eval_single_llm(case: AgentBenchCase) -> tuple[str, int]:
    """Evaluate an unsupervised single-LLM pass without challenger, refuter, or gate."""
    ran = run_method(case.method_id, case.calc_inputs)
    calc_outputs = ran["outputs"]
    allowed = collect_decimals(calc_outputs) | collect_decimals(case.calc_inputs)
    gateway = FixtureGateway(case.scenario)
    context = {
        "task": "reader",
        "blocks": [{"text": case.text, "span_start": 0, "span_end": len(case.text)}],
        "quotation": case.text,
        "span_start": "0",
        "span_end": str(len(case.text)),
        "reader_label": case.reader_label,
        "source_text": case.text,
        "allowed_decimals": sorted(allowed),
    }
    reader_msg = [{"role": "user", "content": json.dumps(context, sort_keys=True)}]
    reader_comp = gateway.complete("reader", reader_msg, None)
    if reader_comp.abstained or reader_comp.output is None:
        return "abstain", 0

    # Single-LLM narrative draft without supervisor stray-number rejection
    checker_comp = gateway.complete("checker", reader_msg, None)
    narrative = (checker_comp.output or {}).get("narrative", "")
    stray = stray_physical_numbers(narrative, allowed)
    if case.stated_outputs is not None:
        stray.extend(stray_physical_numbers(case.stated_outputs, allowed))
    return "accept", len(stray)


def _eval_multi_agent(
    ledger: Ledger,
    case: AgentBenchCase,
    index: int,
) -> tuple[str, str | None]:
    """Evaluate the full supervised multi-agent chain and record to ledger."""
    created_at = f"2026-11-11T12:00:{index:02d}Z"
    if case.corrupt_span:
        bad_field = SpanQuote(
            name="requirement_id",
            value_text=case.heading,
            span_start=0,
            span_end=4,
        )
        extractor = ExtractorOutput(
            fields=[bad_field],
            clause_ids=[case.heading],
            assumptions=[],
        )
        if decide(extractor, challenge(case.text, bad_field)) == "human_queue":
            enqueue(
                ledger,
                tenant_id="bench",
                actor_id="orchestrator",
                created_at=created_at,
                reason="agent_disagreement",
            )
            return "abstain", "agent_disagreement"

    spec = CaseSpec(
        tenant_id="bench",
        actor_id="orchestrator",
        created_at=created_at,
        blocks=[{"text": case.text, "span_start": 0, "span_end": len(case.text)}],
        method_id=case.method_id,
        calc_inputs=case.calc_inputs,
        stated_outputs=case.stated_outputs,
        reader_label=case.reader_label,
        use_decision_gate=case.use_decision_gate,
    )
    outcome = run_case(ledger, FixtureGateway(case.scenario), spec)
    if outcome.envelope.get("confidence") == "abstain":
        reason = (outcome.envelope.get("abstain") or {}).get("reason", "abstain")
        return "abstain", str(reason)

    id_outcome = run_identifier_case(
        ledger,
        text=case.text,
        evidence_id=case.evidence_id,
        evidence_hash=case.evidence_hash,
        tenant_id="bench",
        actor_id="orchestrator",
        created_at=created_at,
    )
    if id_outcome.get("queue") is not None:
        return "abstain", "identifier_queue"
    return "accept", None


def _ledger_stray_violations(events: list[dict[str, Any]]) -> int:
    violations = 0
    for event in events:
        body = event["body"]
        event_type = body.get("event_type")
        envelope = body.get("envelope") or {}
        if event_type == "abstain":
            violations += len(stray_physical_numbers(body.get("payload"), set()))
        elif event_type == "agent_turn":
            payload = body.get("payload") or {}
            inputs = envelope.get("inputs") or {}
            allowed = collect_decimals(inputs)
            for prev in events:
                if prev["body"].get("event_type") == "calc":
                    allowed |= collect_decimals(prev["body"].get("payload"))
            violations += len(stray_physical_numbers(payload.get("output"), allowed))
    return violations


def _score_architecture(
    cases: list[AgentBenchCase],
    verdicts: list[str],
    violations: int,
) -> dict[str, Any]:
    clean_hits = 0
    clean_total = 0
    adv_hits = 0
    adv_total = 0
    false_alarms = 0
    cat_hits: dict[str, int] = {cat: 0 for cat in CATEGORIES}
    cat_total: dict[str, int] = {cat: 0 for cat in CATEGORIES}

    for case, got in zip(cases, verdicts, strict=True):
        cat_total[case.category] += 1
        correct = got == case.expected_outcome
        if correct:
            cat_hits[case.category] += 1
        if case.expected_outcome == "accept":
            clean_total += 1
            if got == "accept":
                clean_hits += 1
            else:
                false_alarms += 1
        else:
            adv_total += 1
            if got == "abstain":
                adv_hits += 1

    overall_hits = clean_hits + adv_hits
    overall_total = len(cases)
    per_category: dict[str, dict[str, Any]] = {}
    for cat in CATEGORIES:
        hits = cat_hits[cat]
        total = cat_total[cat]
        rate = str((Decimal(hits) / Decimal(total)).quantize(Decimal("0.001")))
        per_category[cat] = {
            "hits": hits,
            "total": total,
            "recall": f"{hits}/{total}",
            "rate": rate,
            "ci95": wilson(hits, total),
        }

    return {
        "clean_accept_recall": f"{clean_hits}/{clean_total}",
        "clean_accept_ci95": wilson(clean_hits, clean_total),
        "adversarial_catch_recall": f"{adv_hits}/{adv_total}",
        "adversarial_catch_ci95": wilson(adv_hits, adv_total),
        "overall_correct": f"{overall_hits}/{overall_total}",
        "overall_ci95": wilson(overall_hits, overall_total),
        "false_alarms": f"{false_alarms}/{clean_total}",
        "false_alarm_ci95": wilson(false_alarms, clean_total),
        "per_category_recall": per_category,
        "llm_numeric_violation": violations,
        "label": "ESTIMATE",
    }


def run_agent_bench() -> dict[str, Any]:
    """Run the 24-case benchmark comparing no_agent, single_llm, and multi_agent."""
    cases = build_agent_bench_cases()
    no_agent_verdicts: list[str] = []
    no_agent_violations = 0
    single_verdicts: list[str] = []
    single_violations = 0
    multi_verdicts: list[str] = []
    case_records: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "agent_bench.sqlite3", "bench")
        for idx, case in enumerate(cases):
            na_verdict, na_viol = _eval_no_agent(case)
            no_agent_verdicts.append(na_verdict)
            no_agent_violations += na_viol

            sl_verdict, sl_viol = _eval_single_llm(case)
            single_verdicts.append(sl_verdict)
            single_violations += sl_viol

            ma_verdict, ma_reason = _eval_multi_agent(ledger, case, idx)
            multi_verdicts.append(ma_verdict)

            case_records.append(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "heading": case.heading,
                    "method_id": case.method_id,
                    "expected": case.expected_outcome,
                    "no_agent": na_verdict,
                    "single_llm": sl_verdict,
                    "multi_agent": ma_verdict,
                    "multi_agent_abstain_reason": ma_reason,
                }
            )

        events = ledger.events()
        ledger_verified = ledger.verify()
        multi_violations = _ledger_stray_violations(events)
        events_count = len(events)

    no_agent_metrics = _score_architecture(cases, no_agent_verdicts, no_agent_violations)
    single_llm_metrics = _score_architecture(cases, single_verdicts, single_violations)
    multi_agent_metrics = _score_architecture(cases, multi_verdicts, multi_violations)

    ma_overall = int(multi_agent_metrics["overall_correct"].split("/")[0])
    na_overall = int(no_agent_metrics["overall_correct"].split("/")[0])
    sl_overall = int(single_llm_metrics["overall_correct"].split("/")[0])

    return {
        "benchmark": "agent_bench",
        "disclaimer": DISCLAIMER,
        "label": "ESTIMATE",
        "provenance": (
            "Synthetic fixture benchmark across 24 deterministic cases (6 categories x 4 cases). "
            "Not an expert held-out set."
        ),
        "total_cases": len(cases),
        "clean_cases": 4,
        "adversarial_cases": 20,
        "categories": list(CATEGORIES),
        "no_agent": no_agent_metrics,
        "single_llm": single_llm_metrics,
        "multi_agent": multi_agent_metrics,
        "beats_no_agent": ma_overall > na_overall,
        "beats_single_llm": (
            ma_overall > sl_overall and multi_agent_metrics["llm_numeric_violation"] == 0
        ),
        "ledger_verified": ledger_verified,
        "ledger_events_count": events_count,
        "cases": case_records,
    }


def render_agent_bench_markdown(report: dict[str, Any]) -> str:
    """Render a deterministic Markdown report with epistemic labels and disclaimer."""
    na = report["no_agent"]
    sl = report["single_llm"]
    ma = report["multi_agent"]
    lines = [
        "# Multi-Agent Architecture Benchmark (`agent_bench`)",
        "",
        f"> **Disclaimer**: {report['disclaimer']}",
        "",
        "## Epistemic Status & Provenance",
        "",
        f"- **Benchmark Label**: `{report['label']}` — {report['provenance']}",
        "- **Hash-Chain Verification**: `VERIFIED` "
        f"(`ledger.verify() == {report['ledger_verified']}`, "
        f"`{report['ledger_events_count']}` events recorded in temporary SQLite ledger).",
        "- **Card & Prompt Sources**: `ASSUMPTION` — project-defined screening cards "
        "(`rigid_body_point_mass`, `bolt_screen`) and fixture agent prompts.",
        "- **External Held-Out Authority Set**: `NOT_VERIFIED` — this synthetic benchmark "
        "does not replace a blind domain-expert holdout.",
        "",
        "## Architecture Comparison Summary (24 Cases)",
        "",
        "| Metric | `no_agent` (Regex/Hash + Calc) | "
        "`single_llm` (Single Reader Turn) | `multi_agent` (Supervised Chain) |",
        "| --- | --- | --- | --- |",
        f"| Clean Accept Recall (`4` cases) | `{na['clean_accept_recall']}` "
        f"(`[{na['clean_accept_ci95']['low']}, {na['clean_accept_ci95']['high']}]`) | "
        f"`{sl['clean_accept_recall']}` "
        f"(`[{sl['clean_accept_ci95']['low']}, {sl['clean_accept_ci95']['high']}]`) | "
        f"`{ma['clean_accept_recall']}` "
        f"(`[{ma['clean_accept_ci95']['low']}, {ma['clean_accept_ci95']['high']}]`) |",
        f"| Adversarial Catch Recall (`20` cases) | `{na['adversarial_catch_recall']}` "
        f"(`[{na['adversarial_catch_ci95']['low']}, {na['adversarial_catch_ci95']['high']}]`) | "
        f"`{sl['adversarial_catch_recall']}` "
        f"(`[{sl['adversarial_catch_ci95']['low']}, {sl['adversarial_catch_ci95']['high']}]`) | "
        f"`{ma['adversarial_catch_recall']}` "
        f"(`[{ma['adversarial_catch_ci95']['low']}, {ma['adversarial_catch_ci95']['high']}]`) |",
        f"| Overall Correct (`24` cases) | `{na['overall_correct']}` "
        f"(`[{na['overall_ci95']['low']}, {na['overall_ci95']['high']}]`) | "
        f"`{sl['overall_correct']}` "
        f"(`[{sl['overall_ci95']['low']}, {sl['overall_ci95']['high']}]`) | "
        f"`{ma['overall_correct']}` "
        f"(`[{ma['overall_ci95']['low']}, {ma['overall_ci95']['high']}]`) |",
        f"| False Alarms on Clean (`4` cases) | `{na['false_alarms']}` | "
        f"`{sl['false_alarms']}` | `{ma['false_alarms']}` |",
        f"| `llm_numeric_violation` | `{na['llm_numeric_violation']}` | "
        f"`{sl['llm_numeric_violation']}` | `{ma['llm_numeric_violation']}` |",
        "",
        "## Per-Category Recall (Wilson 95% CI)",
        "",
        "| Category | `no_agent` | `single_llm` | `multi_agent` | Multi-Agent 95% CI |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cat in report["categories"]:
        na_cat = na["per_category_recall"][cat]
        sl_cat = sl["per_category_recall"][cat]
        ma_cat = ma["per_category_recall"][cat]
        ci = ma_cat["ci95"]
        lines.append(
            f"| `{cat}` | `{na_cat['recall']}` | `{sl_cat['recall']}` | "
            f"`{ma_cat['recall']}` | `[{ci['low']}, {ci['high']}]` |"
        )
    lines.extend(
        [
            "",
            "## Gate Checks",
            "",
            f"- `beats_no_agent`: `{report['beats_no_agent']}`",
            f"- `beats_single_llm`: `{report['beats_single_llm']}`",
            f"- `multi_agent.llm_numeric_violation == 0`: `{ma['llm_numeric_violation'] == 0}`",
            f"- `ledger_verified`: `{report['ledger_verified']}`",
            "",
        ]
    )
    return "\n".join(lines)
