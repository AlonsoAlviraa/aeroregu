from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.registry import load_card, run_method

from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.gateway import prompt_hash
from evidence_kernel.ledger import Ledger
from evidence_kernel.numbers import (
    collect_decimals,
    only_new_physical_tokens_are_integers,
    stray_physical_numbers,
)
from evidence_kernel.orchestrator import record
from evidence_kernel.spans import quotation_in_blocks, substring_slice

READER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requirements"],
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "label", "quotation", "span_start", "span_end"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {
                        "enum": [
                            "VERIFIED",
                            "PARTIAL",
                            "NOT_VERIFIED",
                            "ASSUMPTION",
                            "ESTIMATE",
                        ]
                    },
                    "quotation": {"type": "string"},
                    "span_start": {"type": "string", "pattern": "^\\d+$"},
                    "span_end": {"type": "string", "pattern": "^\\d+$"},
                },
            },
        }
    },
}

CHECKER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requirements", "narrative"],
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "label"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {
                        "enum": [
                            "VERIFIED",
                            "PARTIAL",
                            "NOT_VERIFIED",
                            "ASSUMPTION",
                            "ESTIMATE",
                        ]
                    },
                },
            },
        },
        "narrative": {"type": "string"},
    },
}

REFUTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["attack", "reason", "evidence_span"],
    "properties": {
        "attack": {"enum": ["hit", "miss"]},
        "reason": {"type": "string"},
        "evidence_span": {"type": "string"},
    },
}

SCRIBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["paragraph"],
    "properties": {"paragraph": {"type": "string"}},
}

DECISION_GATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "gate_probability"],
    "properties": {
        "decision": {"enum": ["continue", "abstain"]},
        "gate_probability": {"type": "string", "pattern": "^(?:0\\.\\d{3}|1\\.000)$"},
    },
}

GATE_THRESHOLD = "0.800"

SCHEMAS = {
    "reader": READER_SCHEMA,
    "checker": CHECKER_SCHEMA,
    "refuter": REFUTER_SCHEMA,
    "scribe": SCRIBE_SCHEMA,
    "decision_gate": DECISION_GATE_SCHEMA,
}


class CaseAbstain(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class CaseSpec:
    tenant_id: str
    actor_id: str
    created_at: str
    blocks: list[dict[str, Any]]
    method_id: str | None = None
    calc_inputs: dict[str, Any] | None = None
    stated_outputs: dict[str, Any] | None = None
    reader_label: str = "NOT_VERIFIED"
    use_decision_gate: bool = False


@dataclass
class Outcome:
    envelope: dict[str, Any]
    event_hashes: list[str] = field(default_factory=list)
    paragraph: str = ""


def run_case(ledger: Ledger, gateway: Any, case: CaseSpec) -> Outcome:
    try:
        return _run(ledger, gateway, case)
    except CaseAbstain as exc:
        envelope = _abstain_envelope(case, exc.reason)
        digest = record(
            ledger,
            _event_body(
                case,
                "abstain",
                {"reason": exc.reason},
                envelope,
            ),
        )
        return Outcome(envelope=envelope, event_hashes=[digest])


def _run(ledger: Ledger, gateway: Any, case: CaseSpec) -> Outcome:
    source_text = "\n".join(str(block.get("text", "")) for block in case.blocks)
    if not source_text.strip():
        raise CaseAbstain("no_text_layer")
    gate_output: dict[str, Any] | None = None
    if case.use_decision_gate:
        gate_output = _complete(
            gateway,
            "decision_gate",
            {"task": "decision_gate", "source_text": source_text},
        )
        _reject_stray(gate_output, set())
        if _gate_abstains(gate_output):
            raise CaseAbstain("decision_gate")
    quotation = case.blocks[0]["text"]
    span_start = str(case.blocks[0].get("span_start", 0))
    span_end = str(case.blocks[0].get("span_end", len(quotation)))
    reader = _complete(
        gateway,
        "reader",
        {
            "task": "reader",
            "quotation": quotation,
            "span_start": span_start,
            "span_end": span_end,
            "reader_label": case.reader_label,
            "source_text": source_text,
            "allowed_decimals": [],
        },
    )
    _reject_stray(reader, set())
    for item in reader.get("requirements", []):
        if not quotation_in_blocks(
            case.blocks, item["quotation"], item["span_start"], item["span_end"]
        ):
            raise CaseAbstain("bad_span")
    calc_outputs: dict[str, Any] | None = None
    method_version = "supervisor@1.0.0"
    allowed: set[str] = set()
    if case.method_id:
        if _missing(case.method_id, case.calc_inputs):
            raise CaseAbstain("missing_input")
        try:
            ran = run_method(case.method_id, case.calc_inputs or {})
        except AbstainError as exc:
            raise CaseAbstain(exc.reason) from exc
        calc_outputs = ran["outputs"]
        method_version = ran["method_version"]
        allowed = collect_decimals(calc_outputs) | collect_decimals(case.calc_inputs)
        if case.stated_outputs is not None and only_new_physical_tokens_are_integers(
            case.stated_outputs, calc_outputs
        ):
            raise CaseAbstain("unrecomputed_integer")
    checker = _complete(
        gateway,
        "checker",
        _context(quotation, span_start, span_end, source_text, case.reader_label, allowed),
    )
    _reject_stray(checker, allowed)
    if _labels_disagree(reader, checker):
        raise CaseAbstain("agent_disagreement")
    refuter = _complete(
        gateway,
        "refuter",
        _context(quotation, span_start, span_end, source_text, case.reader_label, allowed),
    )
    _reject_stray(refuter, allowed)
    if not substring_slice(source_text, str(refuter.get("evidence_span", ""))):
        raise CaseAbstain("bad_span")
    if refuter.get("attack") == "hit":
        raise CaseAbstain("refuter_hit")
    scribe = _complete(
        gateway,
        "scribe",
        _context(quotation, span_start, span_end, source_text, case.reader_label, allowed),
    )
    paragraph = _filter_sentences(str(scribe.get("paragraph", "")), allowed)
    if not paragraph:
        raise CaseAbstain("scribe_empty")
    scribe = dict(scribe)
    scribe["paragraph"] = paragraph
    hashes: list[str] = []
    calc_hash = ""
    public = _quote_envelope(case, "No numeric method was requested.", "supervisor@1.0.0")
    if calc_outputs is not None:
        public = make_envelope(
            sources=ran["sources"],
            method_version=method_version,
            inputs=case.calc_inputs,
            confidence="deterministic",
            result=calc_outputs,
        )
        calc_hash = record(
            ledger,
            _event_body(
                case,
                "calc",
                {"method_id": case.method_id, "inputs": case.calc_inputs, "outputs": calc_outputs},
                public,
            ),
        )
        hashes.append(calc_hash)
        if case.stated_outputs is not None and case.stated_outputs != calc_outputs:
            flag_env = make_envelope(
                sources=ran["sources"],
                method_version=method_version,
                inputs=case.calc_inputs,
                confidence="deterministic",
                result={"flag": "recomputed_mismatch", "recomputed": calc_outputs},
            )
            hashes.append(
                record(
                    ledger,
                    _event_body(
                        case,
                        "recompute_flag",
                        {
                            "stated_outputs": case.stated_outputs,
                            "recomputed_outputs": calc_outputs,
                        },
                        flag_env,
                    ),
                )
            )
    input_hashes = [calc_hash] if calc_hash else []
    turns: list[tuple[str, dict[str, Any]]] = []
    if gate_output is not None:
        turns.append(("decision_gate", gate_output))
    turns.extend(
        (
            ("reader", reader),
            ("checker", checker),
            ("refuter", refuter),
            ("scribe", scribe),
        )
    )
    for agent_id, output in turns:
        turn_env = _agent_envelope(
            case, agent_id, output, case.calc_inputs or {"blocks": source_text}
        )
        turn = {
            "agent_id": agent_id,
            "prompt_hash": prompt_hash(agent_id),
            "temperature": "0",
            "input_event_hashes": input_hashes,
            "output": output,
            "envelope": turn_env,
        }
        hashes.append(record(ledger, _event_body(case, "agent_turn", turn, turn_env)))
    return Outcome(envelope=public, event_hashes=hashes, paragraph=paragraph)


def _context(
    quotation: str,
    span_start: str,
    span_end: str,
    source_text: str,
    reader_label: str,
    allowed: set[str],
) -> dict[str, Any]:
    return {
        "quotation": quotation,
        "span_start": span_start,
        "span_end": span_end,
        "source_text": source_text,
        "reader_label": reader_label,
        "allowed_decimals": sorted(allowed),
    }


def _complete(gateway: Any, agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
    messages = [{"role": "user", "content": json.dumps(context, sort_keys=True)}]
    completion = gateway.complete(agent_id, messages, SCHEMAS[agent_id])
    if completion.abstained or completion.output is None:
        raise CaseAbstain(completion.abstain_reason or "model_abstain")
    return completion.output


def _reject_stray(output: dict[str, Any], allowed: set[str]) -> None:
    stray = stray_physical_numbers(output, allowed)
    if stray:
        raise CaseAbstain("stray_number")


def _gate_abstains(output: dict[str, Any]) -> bool:
    if output.get("decision") != "continue":
        return True
    return Decimal(str(output.get("gate_probability", "0.000"))) < Decimal(GATE_THRESHOLD)


def _labels_disagree(reader: dict[str, Any], checker: dict[str, Any]) -> bool:
    left = {item["id"]: item["label"] for item in reader.get("requirements", [])}
    right = {item["id"]: item["label"] for item in checker.get("requirements", [])}
    for item_id, label in left.items():
        if item_id not in right or right[item_id] != label:
            return True
    return False


def _filter_sentences(paragraph: str, allowed: set[str]) -> str:
    parts = re.split(r"(?<=\.)\s+", paragraph.strip())
    kept = [part for part in parts if not stray_physical_numbers(part, allowed)]
    return " ".join(kept).strip()


def _missing(method_id: str, inputs: dict[str, Any] | None) -> bool:
    if inputs is None:
        return True
    card = load_card(method_id)
    required = card.get("required") or list(card.get("inputs", {}))
    for key in required:
        if key not in inputs or inputs[key] in (None, ""):
            return True
    return False


def _event_body(
    case: CaseSpec,
    event_type: str,
    payload: dict[str, Any],
    envelope: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "tenant_id": case.tenant_id,
        "actor_id": case.actor_id,
        "created_at": case.created_at,
        "payload": payload,
        "envelope": envelope,
    }


def _abstain_envelope(case: CaseSpec, reason: str) -> dict[str, Any]:
    return make_envelope(
        sources=[
            project_source(
                "supervisor",
                "https://aeroregu.local/supervisor",
                "ASSUMPTION",
            )
        ],
        method_version="supervisor@1.0.0",
        inputs={"method_id": case.method_id or "", "reason": reason},
        confidence="abstain",
        abstain_reason=reason,
    )


def _quote_envelope(case: CaseSpec, text: str, method_version: str) -> dict[str, Any]:
    return make_envelope(
        sources=[project_source("supervisor", "https://aeroregu.local/supervisor", "ASSUMPTION")],
        method_version=method_version,
        inputs={"tenant_id": case.tenant_id},
        confidence="draft",
        result={"note": text},
    )


def _agent_envelope(
    case: CaseSpec, agent_id: str, output: dict[str, Any], inputs: Any
) -> dict[str, Any]:
    digest = prompt_hash(agent_id)
    confidence = "quoted" if agent_id == "reader" else "draft"
    return make_envelope(
        sources=[
            project_source(
                agent_id,
                f"https://aeroregu.local/prompts/{agent_id}",
                "ASSUMPTION",
                digest,
            )
        ],
        method_version=f"llm_extract@{digest}",
        inputs=inputs if isinstance(inputs, dict) else {"value": str(inputs)},
        confidence=confidence,
        result=output,
    )
