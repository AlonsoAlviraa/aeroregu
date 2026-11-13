from __future__ import annotations

from typing import Any

from evidence_calc.diagnostics import classify_numeric_delta
from evidence_calc.errors import AbstainError
from evidence_calc.registry import load_card, run_method
from evidence_kernel.canonical import inputs_hash
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.numbers import only_new_physical_tokens_are_integers, stray_physical_numbers

from evidence_eval.numbers import DECIMAL

DETERMINISTIC_FAULTS = (
    "unit_scale",
    "arithmetic",
    "wrong_input",
    "sign",
    "outside_validity",
)


def assess(artifact: dict[str, Any]) -> dict[str, Any]:
    method_id = str(artifact.get("method_id", ""))
    inputs = artifact.get("inputs")
    if not isinstance(inputs, dict):
        inputs = {}
    if method_id:
        try:
            card = load_card(method_id)
        except AbstainError as exc:
            return _done("abstain", _abstain(None, inputs, exc.reason))
    else:
        card = None
    required = []
    if card:
        required = list(card.get("required") or card.get("inputs", {}))
    if any(key not in inputs or inputs[key] in (None, "") for key in required):
        return _done("abstain", _abstain(card, inputs, "missing_input"))
    try:
        ran = run_method(method_id, inputs)
    except AbstainError as exc:
        if exc.reason in {"outside_validity", "unit_mismatch"}:
            return _done(f"detect:{exc.reason}", _abstain(card, inputs, exc.reason))
        return _done("abstain", _abstain(card, inputs, exc.reason))
    recomputed = ran["outputs"]
    found: list[str] = []
    if _contradictory(artifact):
        found.append("contradictory_requirements")
    if not _span_ok(artifact):
        found.append("bad_span")
    if _bad_citation(artifact):
        found.append("bad_citation")
    if artifact.get("inputs_hash") != inputs_hash(inputs):
        found.append("broken_hash")
    if artifact.get("method_version") != ran["method_version"]:
        found.append("stale_revision")
    stated = artifact.get("stated_outputs")
    if artifact.get("coverage_status") == "calc":
        if artifact.get("coverage_evidence_hash") != inputs_hash(recomputed):
            found.append("false_coverage")
    numeric = classify_numeric_delta(method_id, inputs, stated, recomputed)
    if numeric == "unexplained" and only_new_physical_tokens_are_integers(stated, recomputed):
        if not found:
            return _done("abstain", _abstain(card, inputs, "unrecomputed_integer"))
    elif numeric != "clean":
        found.append(numeric)
    if not found:
        return _flag("clean", ran, inputs, recomputed)
    if len(found) == 1:
        return _flag(found[0], ran, inputs, recomputed)
    return _many(found, ran, inputs, recomputed)


def llm_numeric_violations(case: dict[str, Any]) -> int:
    turns = case.get("agent_turns") or []
    if not turns:
        return 0
    artifact = case.get("artifact") or {}
    allowed: set[str] = set()
    try:
        ran = run_method(str(artifact.get("method_id")), artifact.get("inputs") or {})
        allowed = set(_decimals(ran["outputs"]))
    except (AbstainError, KeyError, TypeError):
        allowed = set()
    count = 0
    for turn in turns:
        if stray_physical_numbers(turn, allowed):
            count += 1
    return count


def _contradictory(artifact: dict[str, Any]) -> bool:
    seen: dict[str, str] = {}
    for claim in artifact.get("requirement_claims") or []:
        if not isinstance(claim, dict):
            continue
        ident = str(claim.get("id", ""))
        status = str(claim.get("status", ""))
        if ident in seen and seen[ident] != status:
            return True
        seen[ident] = status
    return False


def _bad_citation(artifact: dict[str, Any]) -> bool:
    cited = artifact.get("citation_requirement_id")
    if not cited:
        return False
    allowed = artifact.get("requirement_ids")
    if not isinstance(allowed, list):
        return True
    return cited not in allowed


def _span_ok(artifact: dict[str, Any]) -> bool:
    quote = artifact.get("quotation") or {}
    text = str(artifact.get("source_text", ""))
    snippet = str(quote.get("text", ""))
    try:
        start = int(quote.get("span_start"))
        end = int(quote.get("span_end"))
    except (TypeError, ValueError):
        return False
    if start < 0 or end > len(text) or start > end or snippet == "":
        return False
    return text[start:end] == snippet


def _flag(
    flag: str, ran: dict[str, Any], inputs: dict[str, Any], recomputed: dict[str, Any]
) -> dict[str, Any]:
    verdict = "clean" if flag == "clean" else f"detect:{flag}"
    envelope = make_envelope(
        sources=ran["sources"],
        method_version=ran["method_version"],
        inputs=inputs,
        confidence="deterministic",
        result={"flag": flag, "recomputed": recomputed},
    )
    done = _done(verdict, envelope)
    done["faults"] = [] if flag == "clean" else [flag]
    return done


def _many(
    flags: list[str], ran: dict[str, Any], inputs: dict[str, Any], recomputed: dict[str, Any]
) -> dict[str, Any]:
    ordered = sorted(set(flags))
    envelope = make_envelope(
        sources=ran["sources"],
        method_version=ran["method_version"],
        inputs=inputs,
        confidence="deterministic",
        result={"flag": "compound", "faults": ordered, "recomputed": recomputed},
    )
    done = _done("detect:compound", envelope)
    done["faults"] = ordered
    return done


def _abstain(card: dict[str, Any] | None, inputs: dict[str, Any], reason: str) -> dict[str, Any]:
    sources = (
        card["sources"]
        if card
        else [project_source("calc", "https://aeroregu.local/calc", "ASSUMPTION")]
    )
    version = card["method_version"] if card else "calc@0"
    return make_envelope(
        sources=sources,
        method_version=version,
        inputs=inputs,
        confidence="abstain",
        abstain_reason=reason,
    )


def _done(verdict: str, envelope: dict[str, Any]) -> dict[str, Any]:
    return {"verdict": verdict, "envelope": envelope}


def _decimals(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str) and DECIMAL.fullmatch(value):
        found.append(value)
    elif isinstance(value, list):
        for item in value:
            found.extend(_decimals(item))
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_decimals(item))
    return found
