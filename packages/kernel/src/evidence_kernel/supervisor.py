from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx
from evidence_calc.diagnostics import classify_numeric_delta
from evidence_calc.errors import AbstainError
from evidence_calc.registry import load_card, run_method
from evidence_calc.units import require_declared_units

from evidence_kernel.edge import compact_blocks_for_edge, get_edge_preset
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.formal import SMTProofResult, SMTSolverProofEngine
from evidence_kernel.gateway import prompt_hash
from evidence_kernel.guardrails import check_structure_safety, validate_blocks_safety
from evidence_kernel.ledger import Ledger
from evidence_kernel.numbers import (
    collect_decimals,
    only_new_physical_tokens_are_integers,
    stray_physical_numbers,
)
from evidence_kernel.orchestrator import record
from evidence_kernel.spans import quotation_in_blocks, resolve_block_location, substring_slice

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
    require_declared_units: bool = False
    formal_verification: bool = False
    formal_bounds: dict[str, Any] | None = None
    record_requirements: bool = False
    compact_for_edge: bool = False
    edge_preset: str | None = None


@dataclass
class Outcome:
    envelope: dict[str, Any]
    event_hashes: list[str] = field(default_factory=list)
    paragraph: str = ""
    fault_kind: str | None = None
    formal_proof: dict[str, Any] | None = None
    agent_telemetry: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)


def _prepare_blocks(case: CaseSpec) -> tuple[list[dict[str, Any]], str]:
    safety_reason = validate_blocks_safety(case.blocks)
    if safety_reason is not None:
        raise CaseAbstain(safety_reason)
    active_blocks = case.blocks
    if case.compact_for_edge:
        preset = get_edge_preset(case.edge_preset)
        active_blocks = compact_blocks_for_edge(
            case.blocks, max_chars=int(preset["max_context_chars"])
        )
    source_text = "\n".join(str(block.get("text", "")) for block in active_blocks)
    if not source_text.strip():
        raise CaseAbstain("no_text_layer")
    return active_blocks, source_text


def _validate_reader_spans(active_blocks: list[dict[str, Any]], reader: dict[str, Any]) -> None:
    _reject_stray(reader, set())
    for item in reader.get("requirements", []):
        if not quotation_in_blocks(
            active_blocks, item["quotation"], item["span_start"], item["span_end"]
        ):
            raise CaseAbstain("bad_span")


def _run_deterministic_calc(
    case: CaseSpec,
) -> tuple[dict[str, Any] | None, str, set[str], str | None, dict[str, Any] | None]:
    calc_outputs: dict[str, Any] | None = None
    method_version = "supervisor@1.0.0"
    allowed: set[str] = set()
    fault_kind: str | None = None
    ran: dict[str, Any] | None = None
    if case.method_id:
        if _missing(case.method_id, case.calc_inputs):
            raise CaseAbstain("missing_input")
        try:
            if case.require_declared_units:
                require_declared_units(case.calc_inputs or {}, load_card(case.method_id))
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
        if case.stated_outputs is not None and case.stated_outputs != calc_outputs:
            fault_kind = classify_numeric_delta(
                case.method_id, case.calc_inputs or {}, case.stated_outputs, calc_outputs
            )
    return calc_outputs, method_version, allowed, fault_kind, ran


def _run_formal_proof(case: CaseSpec) -> dict[str, Any] | None:
    if not case.formal_verification:
        return None
    engine = SMTSolverProofEngine()
    spec = case.formal_bounds or {}
    formal_res: SMTProofResult | None = None
    if "bounds" in spec and "area_mm2" in spec["bounds"]:
        formal_res = engine.prove_structural_margin(
            bounds=spec["bounds"],
            allowables=spec.get("allowables", {}),
            safety_factor=spec.get("safety_factor", "1.500"),
        )
    elif "bounds" in spec and "mass_kg" in spec["bounds"]:
        formal_res = engine.prove_station_equilibrium(
            bounds=spec["bounds"],
            stations=spec.get("stations", ["-1.000", "-0.300", "0.300", "1.000"]),
            max_station_force_n=spec.get("max_station_force_n", "15000.000"),
            gravity_m_s2=spec.get("gravity_m_s2", "9.807"),
            active_stations_min=int(spec.get("active_stations_min", 3)),
        )
    elif case.method_id and "bolt_screen" in case.method_id and case.calc_inputs:
        c_in = case.calc_inputs
        b_calc = {
            "area_mm2": (c_in["area_mm2"], c_in["area_mm2"]),
            "shear_force_n": (c_in["shear_force_n"], c_in["shear_force_n"]),
            "tensile_force_n": (c_in["tensile_force_n"], c_in["tensile_force_n"]),
        }
        a_calc = {
            "shear_allowable_mpa": c_in["shear_allowable_mpa"],
            "tensile_allowable_mpa": c_in["tensile_allowable_mpa"],
        }
        formal_res = engine.prove_structural_margin(b_calc, a_calc)
    elif case.method_id and "rigid_body_point_mass" in case.method_id and case.calc_inputs:
        c_in = case.calc_inputs
        b_calc = {
            "mass_kg": (
                (str(c_in["mass_kg"]), str(c_in["mass_kg"]))
                if "mass_kg" in c_in
                else ("800.000", "1200.000")
            ),
            "load_factor": (
                (str(c_in["load_factor"]), str(c_in["load_factor"]))
                if "load_factor" in c_in
                else ("-1.000", "2.500")
            ),
            "cg_x_m": (
                (str(c_in["cg_x_m"]), str(c_in["cg_x_m"]))
                if "cg_x_m" in c_in
                else ("-0.200", "0.200")
            ),
        }
        st_pos = c_in.get("unit_x_m") or ["-1.000", "-0.300", "0.300", "1.000"]
        operative = c_in.get("unit_operative")
        active_min = (
            sum(1 for flag in operative if flag)
            if isinstance(operative, list) and any(operative)
            else 3
        )
        formal_res = engine.prove_station_equilibrium(
            bounds=b_calc,
            stations=[str(pos) for pos in st_pos],
            max_station_force_n=str(spec.get("max_station_force_n", "15000.000")),
            gravity_m_s2=str(c_in.get("gravity_m_s2", "9.810")),
            active_stations_min=int(spec.get("active_stations_min", active_min)),
        )
    if formal_res is not None:
        if not formal_res.proved:
            raise CaseAbstain("refuter_hit")
        return formal_res.to_dict()
    return None


def _finalize_and_record(
    ledger: Ledger,
    case: CaseSpec,
    *,
    reader: dict[str, Any],
    checker: dict[str, Any],
    refuter: dict[str, Any],
    scribe: dict[str, Any],
    gate_output: dict[str, Any] | None,
    calc_outputs: dict[str, Any] | None,
    method_version: str,
    ran: dict[str, Any] | None,
    fault_kind: str | None,
    formal_proof_dict: dict[str, Any] | None,
    source_text: str,
    telemetry: list[dict[str, Any]],
    paragraph: str,
) -> Outcome:
    hashes: list[str] = []
    calc_hash = ""
    public = _quote_envelope(case, "No numeric method was requested.", "supervisor@1.0.0")
    if calc_outputs is not None:
        assert ran is not None
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
                result={
                    "flag": "recomputed_mismatch",
                    "fault_kind": fault_kind or "unexplained",
                    "recomputed": calc_outputs,
                },
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
                            "fault_kind": fault_kind or "unexplained",
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
    telemetry_by_agent = {item["agent_id"]: item for item in telemetry}
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
            "telemetry": telemetry_by_agent.get(agent_id, {}),
            "envelope": turn_env,
        }
        hashes.append(record(ledger, _event_body(case, "agent_turn", turn, turn_env)))
    citations: list[dict[str, Any]] = []
    for req_item in reader.get("requirements", []):
        quotation = str(req_item.get("quotation", ""))
        span_start_str = str(req_item.get("span_start", "0"))
        span_end_str = str(req_item.get("span_end", "0"))
        loc = resolve_block_location(case.blocks, quotation, span_start_str, span_end_str) or {}
        citation_entry = {
            "id": str(req_item.get("id", "ITEM-1")),
            "label": str(req_item.get("label", "NOT_VERIFIED")),
            "quotation": quotation,
            "span_start": str(loc.get("span_start", span_start_str)),
            "span_end": str(loc.get("span_end", span_end_str)),
            "page_no": loc.get("page_no"),
            "bbox": loc.get("bbox"),
            "block_kind": loc.get("block_kind", "text"),
        }
        citations.append(citation_entry)
        if case.record_requirements:
            req_payload: dict[str, Any] = {
                "id": citation_entry["id"],
                "title": quotation,
                "title_label": citation_entry["label"],
                "source_file_hash": str(
                    loc.get("source_hash")
                    or (case.blocks[0].get("source_hash", "") if case.blocks else "")
                ),
                "quotation": quotation,
                "span_start": citation_entry["span_start"],
                "span_end": citation_entry["span_end"],
                "page_no": citation_entry["page_no"],
                "bbox": citation_entry["bbox"],
            }
            req_env = make_envelope(
                sources=[project_source("supervisor", "https://aeroregu.local/req", "ASSUMPTION")],
                method_version="requirement_extract@1.0.0",
                inputs={"id": req_payload["id"], "span_start": req_payload["span_start"]},
                confidence="quoted",
                result={"id": req_payload["id"], "title_label": req_payload["title_label"]},
            )
            hashes.append(
                record(ledger, _event_body(case, "requirement_recorded", req_payload, req_env))
            )
    if formal_proof_dict is not None:
        formal_env = make_envelope(
            sources=[project_source("formal-smt-solver", "smt://z3/proof", "ASSUMPTION")],
            method_version="z3-solver@5.4.1.0",
            inputs=formal_proof_dict.get("assumptions", {}),
            confidence="deterministic",
            result={
                "proof_status": formal_proof_dict.get("status"),
                "property_name": formal_proof_dict.get("property_name"),
                "assertion": formal_proof_dict.get("assertion"),
                "proof_hash": formal_proof_dict.get("proof_hash"),
                "solver_stats": formal_proof_dict.get("solver_stats"),
            },
        )
        formal_h = record(
            ledger,
            _event_body(
                case,
                "calc",
                {
                    "method_id": "z3_formal_solver",
                    "inputs": formal_proof_dict.get("assumptions", {}),
                    "outputs": {
                        "proof_status": str(formal_proof_dict.get("status")),
                        "property_name": str(formal_proof_dict.get("property_name")),
                        "proof_hash": str(formal_proof_dict.get("proof_hash")),
                    },
                },
                formal_env,
            ),
        )
        hashes.append(formal_h)
    return Outcome(
        envelope=public,
        event_hashes=hashes,
        paragraph=paragraph,
        fault_kind=fault_kind,
        formal_proof=formal_proof_dict,
        agent_telemetry=telemetry,
        citations=citations,
    )


def _record_abstain_outcome(ledger: Ledger, case: CaseSpec, reason: str) -> Outcome:
    envelope = _abstain_envelope(case, reason)
    digest = record(
        ledger,
        _event_body(
            case,
            "abstain",
            {"reason": reason},
            envelope,
        ),
    )
    return Outcome(envelope=envelope, event_hashes=[digest])


def run_case(ledger: Ledger, gateway: Any, case: CaseSpec) -> Outcome:
    try:
        return _run(ledger, gateway, case)
    except CaseAbstain as exc:
        return _record_abstain_outcome(ledger, case, exc.reason)


def _run(ledger: Ledger, gateway: Any, case: CaseSpec) -> Outcome:
    telemetry: list[dict[str, Any]] = []
    active_blocks, source_text = _prepare_blocks(case)
    gate_output: dict[str, Any] | None = None
    if case.use_decision_gate:
        try:
            gate_output = _complete(
                gateway,
                "decision_gate",
                {"task": "decision_gate", "source_text": source_text},
                telemetry=telemetry,
            )
            _reject_stray(gate_output, set())
            if _gate_abstains(gate_output):
                raise CaseAbstain("decision_gate")
        except CaseAbstain as exc:
            if exc.reason != "decision_gate_fixture_only":
                raise
            gate_output = None

    quotation = active_blocks[0]["text"]
    span_start = str(active_blocks[0].get("span_start", 0))
    span_end = str(active_blocks[0].get("span_end", len(quotation)))
    reader = _complete(
        gateway,
        "reader",
        {
            "task": "reader",
            "blocks": active_blocks,
            "quotation": quotation,
            "span_start": span_start,
            "span_end": span_end,
            "reader_label": case.reader_label,
            "source_text": source_text,
            "allowed_decimals": [],
        },
        telemetry=telemetry,
    )
    _validate_reader_spans(active_blocks, reader)
    calc_outputs, method_version, allowed, fault_kind, ran = _run_deterministic_calc(case)
    checker = _complete(
        gateway,
        "checker",
        _context(
            quotation,
            span_start,
            span_end,
            source_text,
            case.reader_label,
            allowed,
            fault_kind=fault_kind,
        ),
        telemetry=telemetry,
    )
    _reject_stray(checker, allowed)
    if _labels_disagree(reader, checker):
        raise CaseAbstain("agent_disagreement")
    formal_proof_dict = _run_formal_proof(case)
    refuter = _complete(
        gateway,
        "refuter",
        _context(
            quotation,
            span_start,
            span_end,
            source_text,
            case.reader_label,
            allowed,
            fault_kind=fault_kind,
        ),
        telemetry=telemetry,
    )
    _reject_stray(refuter, allowed)
    if not substring_slice(source_text, str(refuter.get("evidence_span", ""))):
        raise CaseAbstain("bad_span")
    if refuter.get("attack") == "hit":
        raise CaseAbstain("refuter_hit")
    scribe = _complete(
        gateway,
        "scribe",
        _context(
            quotation,
            span_start,
            span_end,
            source_text,
            case.reader_label,
            allowed,
            fault_kind=fault_kind,
        ),
        telemetry=telemetry,
    )
    paragraph = _filter_sentences(str(scribe.get("paragraph", "")), allowed)
    if not paragraph:
        raise CaseAbstain("scribe_empty")
    scribe = {**scribe, "paragraph": paragraph}
    return _finalize_and_record(
        ledger,
        case,
        reader=reader,
        checker=checker,
        refuter=refuter,
        scribe=scribe,
        gate_output=gate_output,
        calc_outputs=calc_outputs,
        method_version=method_version,
        ran=ran,
        fault_kind=fault_kind,
        formal_proof_dict=formal_proof_dict,
        source_text=source_text,
        telemetry=telemetry,
        paragraph=paragraph,
    )


async def _acomplete(
    gateway: Any,
    agent_id: str,
    context: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
    telemetry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    messages = [{"role": "user", "content": json.dumps(context, sort_keys=True)}]
    if hasattr(gateway, "acomplete"):
        completion = await gateway.acomplete(agent_id, messages, SCHEMAS[agent_id], client=client)
    else:
        completion = gateway.complete(agent_id, messages, SCHEMAS[agent_id])
    entry = _telemetry_entry(agent_id, completion)
    if telemetry is not None:
        telemetry.append(entry)
    if completion.abstained or completion.output is None:
        raise CaseAbstain(completion.abstain_reason or "model_abstain")
    out_safety = check_structure_safety(completion.output, mode="output")
    if out_safety is not None:
        raise CaseAbstain(out_safety)
    return completion.output


async def astream_case(
    ledger: Ledger,
    gateway: Any,
    case: CaseSpec,
) -> AsyncIterator[dict[str, Any]]:
    """Asynchronously execute the supervised agent pipeline while yielding per-stage events."""
    telemetry: list[dict[str, Any]] = []
    try:
        active_blocks, source_text = _prepare_blocks(case)
        yield {
            "event": "stage",
            "data": {
                "stage": "preflight",
                "block_count": str(len(active_blocks)),
                "compact_for_edge": case.compact_for_edge,
            },
        }
        async with httpx.AsyncClient() as client:
            gate_output: dict[str, Any] | None = None
            if case.use_decision_gate:
                try:
                    gate_output = await _acomplete(
                        gateway,
                        "decision_gate",
                        {"task": "decision_gate", "source_text": source_text},
                        client=client,
                        telemetry=telemetry,
                    )
                    _reject_stray(gate_output, set())
                    if _gate_abstains(gate_output):
                        raise CaseAbstain("decision_gate")
                    yield {
                        "event": "agent_turn",
                        "data": {"agent_id": "decision_gate", "telemetry": telemetry[-1]},
                    }
                except CaseAbstain as exc:
                    if exc.reason != "decision_gate_fixture_only":
                        raise
                    gate_output = None
                    yield {
                        "event": "stage",
                        "data": {"stage": "decision_gate", "status": "skipped_live"},
                    }

            quotation = active_blocks[0]["text"]
            span_start = str(active_blocks[0].get("span_start", 0))
            span_end = str(active_blocks[0].get("span_end", len(quotation)))
            reader = await _acomplete(
                gateway,
                "reader",
                {
                    "task": "reader",
                    "blocks": active_blocks,
                    "quotation": quotation,
                    "span_start": span_start,
                    "span_end": span_end,
                    "reader_label": case.reader_label,
                    "source_text": source_text,
                    "allowed_decimals": [],
                },
                client=client,
                telemetry=telemetry,
            )
            _validate_reader_spans(active_blocks, reader)
            yield {
                "event": "agent_turn",
                "data": {"agent_id": "reader", "telemetry": telemetry[-1]},
            }

            calc_outputs, method_version, allowed, fault_kind, ran = _run_deterministic_calc(case)
            yield {
                "event": "calc",
                "data": {
                    "method_id": case.method_id or "",
                    "method_version": method_version,
                    "fault_kind": fault_kind,
                    "outputs": calc_outputs,
                },
            }

            checker = await _acomplete(
                gateway,
                "checker",
                _context(
                    quotation,
                    span_start,
                    span_end,
                    source_text,
                    case.reader_label,
                    allowed,
                    fault_kind=fault_kind,
                ),
                client=client,
                telemetry=telemetry,
            )
            _reject_stray(checker, allowed)
            if _labels_disagree(reader, checker):
                raise CaseAbstain("agent_disagreement")
            yield {
                "event": "agent_turn",
                "data": {"agent_id": "checker", "telemetry": telemetry[-1]},
            }

            formal_proof_dict = _run_formal_proof(case)
            if formal_proof_dict is not None:
                yield {"event": "formal_proof", "data": formal_proof_dict}

            refuter = await _acomplete(
                gateway,
                "refuter",
                _context(
                    quotation,
                    span_start,
                    span_end,
                    source_text,
                    case.reader_label,
                    allowed,
                    fault_kind=fault_kind,
                ),
                client=client,
                telemetry=telemetry,
            )
            _reject_stray(refuter, allowed)
            if not substring_slice(source_text, str(refuter.get("evidence_span", ""))):
                raise CaseAbstain("bad_span")
            if refuter.get("attack") == "hit":
                raise CaseAbstain("refuter_hit")
            yield {
                "event": "agent_turn",
                "data": {"agent_id": "refuter", "telemetry": telemetry[-1]},
            }

            scribe = await _acomplete(
                gateway,
                "scribe",
                _context(
                    quotation,
                    span_start,
                    span_end,
                    source_text,
                    case.reader_label,
                    allowed,
                    fault_kind=fault_kind,
                ),
                client=client,
                telemetry=telemetry,
            )
            paragraph = _filter_sentences(str(scribe.get("paragraph", "")), allowed)
            if not paragraph:
                raise CaseAbstain("scribe_empty")
            scribe = {**scribe, "paragraph": paragraph}
            yield {
                "event": "agent_turn",
                "data": {"agent_id": "scribe", "telemetry": telemetry[-1]},
            }

        outcome = _finalize_and_record(
            ledger,
            case,
            reader=reader,
            checker=checker,
            refuter=refuter,
            scribe=scribe,
            gate_output=gate_output,
            calc_outputs=calc_outputs,
            method_version=method_version,
            ran=ran,
            fault_kind=fault_kind,
            formal_proof_dict=formal_proof_dict,
            source_text=source_text,
            telemetry=telemetry,
            paragraph=paragraph,
        )
        yield {
            "event": "done",
            "data": {
                "envelope": outcome.envelope,
                "event_hashes": outcome.event_hashes,
                "paragraph": outcome.paragraph,
                "fault_kind": outcome.fault_kind,
                "formal_proof": outcome.formal_proof,
                "agent_telemetry": outcome.agent_telemetry,
                "citations": outcome.citations,
            },
        }
    except CaseAbstain as exc:
        abstained = _record_abstain_outcome(ledger, case, exc.reason)
        yield {
            "event": "abstain",
            "data": {
                "reason": exc.reason,
                "envelope": abstained.envelope,
                "event_hashes": abstained.event_hashes,
            },
        }


async def arun_case(ledger: Ledger, gateway: Any, case: CaseSpec) -> Outcome:
    """Asynchronously execute the supervised verification pipeline using httpx.AsyncClient."""
    final_data: dict[str, Any] = {}
    async for event in astream_case(ledger, gateway, case):
        if event["event"] in {"done", "abstain"}:
            final_data = event["data"]
    return Outcome(
        envelope=final_data["envelope"],
        event_hashes=final_data.get("event_hashes", []),
        paragraph=str(final_data.get("paragraph", "")),
        fault_kind=final_data.get("fault_kind"),
        formal_proof=final_data.get("formal_proof"),
        agent_telemetry=final_data.get("agent_telemetry", []),
    )


def _context(
    quotation: str,
    span_start: str,
    span_end: str,
    source_text: str,
    reader_label: str,
    allowed: set[str],
    *,
    fault_kind: str | None = None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "quotation": quotation,
        "span_start": span_start,
        "span_end": span_end,
        "source_text": source_text,
        "reader_label": reader_label,
        "allowed_decimals": sorted(allowed),
    }
    if fault_kind is not None:
        ctx["fault_kind"] = fault_kind
    return ctx


def _telemetry_entry(agent_id: str, completion: Any) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "provider": str(getattr(completion, "provider", "fixture")),
        "model_id": str(getattr(completion, "model_id", "fixture")),
        "routed_via": str(getattr(completion, "routed_via", "local")),
        "escalated": bool(getattr(completion, "escalated", False)),
        "latency_ms": str(getattr(completion, "latency_ms", 0)),
        "input_tokens": str(getattr(completion, "input_tokens", 0)),
        "output_tokens": str(getattr(completion, "output_tokens", 0)),
        "prompt_hash": str(getattr(completion, "prompt_hash", prompt_hash(agent_id))),
    }


def _complete(
    gateway: Any,
    agent_id: str,
    context: dict[str, Any],
    *,
    telemetry: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    messages = [{"role": "user", "content": json.dumps(context, sort_keys=True)}]
    completion = gateway.complete(agent_id, messages, SCHEMAS[agent_id])
    if telemetry is not None:
        telemetry.append(_telemetry_entry(agent_id, completion))
    if completion.abstained or completion.output is None:
        raise CaseAbstain(completion.abstain_reason or "model_abstain")
    out_safety = check_structure_safety(completion.output, mode="output")
    if out_safety is not None:
        raise CaseAbstain(out_safety)
    return completion.output


def invoke_single_agent(
    gateway: Any,
    agent_id: str,
    context: dict[str, Any],
    *,
    allowed_decimals: set[str] | None = None,
) -> dict[str, Any]:
    """Execute one verification agent with guardrails, schema constraints, and numeric checks."""
    if agent_id not in SCHEMAS:
        raise CaseAbstain("unknown_agent")
    blocks_payload = context.get("blocks")
    if isinstance(blocks_payload, list) and blocks_payload:
        safety_reason = validate_blocks_safety(blocks_payload)
        if safety_reason is not None:
            raise CaseAbstain(safety_reason)
    text = str(context.get("source_text") or context.get("quotation") or "")
    if text:
        safety_reason = validate_blocks_safety([{"text": text}])
        if safety_reason is not None:
            raise CaseAbstain(safety_reason)
    telemetry: list[dict[str, Any]] = []
    output = _complete(gateway, agent_id, context, telemetry=telemetry)
    _reject_stray(output, allowed_decimals or set())
    if agent_id == "scribe":
        filtered = _filter_sentences(str(output.get("paragraph", "")), allowed_decimals or set())
        if not filtered:
            raise CaseAbstain("scribe_empty")
        output = {**output, "paragraph": filtered}
    return {"output": output, "telemetry": telemetry[0]}


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
    kept = [part for part in parts if not stray_physical_numbers(part.rstrip("."), allowed)]
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
