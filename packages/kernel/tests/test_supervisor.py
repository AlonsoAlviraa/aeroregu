import json
import re
from pathlib import Path

from evidence_calc.registry import run_method
from evidence_kernel.gateway import FixtureGateway
from evidence_kernel.ledger import Ledger
from evidence_kernel.paths import prompts_dir
from evidence_kernel.supervisor import CaseSpec, run_case

INPUTS = {
    "mass_kg": "800.000",
    "gravity_m_s2": "10.000",
    "load_factor": "1.000",
    "altitude_m": "0.000",
    "cg_x_m": "0.000",
    "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
    "unit_operative": [True, True, True, True],
}


def _run(tmp_path: Path, scenario: str, inputs: dict | None = INPUTS):
    ledger = Ledger(tmp_path / "tenant.sqlite3", "demo")
    text = "Alpha item is listed in the source block."
    case = CaseSpec(
        tenant_id="demo",
        actor_id="author",
        created_at="2026-11-03T18:00:00Z",
        blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
        method_id="rigid_body_point_mass",
        calc_inputs=inputs,
    )
    outcome = run_case(ledger, FixtureGateway(scenario), case)
    return ledger, outcome


def test_prompts_are_not_the_same_bytes() -> None:
    reader = (prompts_dir() / "reader.md").read_bytes()
    refuter = (prompts_dir() / "refuter.md").read_bytes()
    assert reader != refuter
    assert b"Reader" in reader
    assert b"Refuter" in refuter


def test_happy_path_appends_calc_and_turns(tmp_path: Path) -> None:
    ledger, outcome = _run(tmp_path, "happy")
    assert outcome.envelope["confidence"] == "deterministic"
    assert ledger.verify()
    kinds = [event["body"]["event_type"] for event in ledger.events()]
    assert "calc" in kinds
    assert kinds.count("agent_turn") == 4
    assert "abstain" not in kinds
    stored = [
        event["body"]["payload"]["output"]["paragraph"]
        for event in ledger.events()
        if event["body"]["event_type"] == "agent_turn"
        and event["body"]["payload"]["agent_id"] == "scribe"
    ][0]
    assert "8.888" not in stored
    assert re.search(r"\d+\.\d+", stored)


def test_refuter_hit_stores_no_draft(tmp_path: Path) -> None:
    ledger, outcome = _run(tmp_path, "refuter_hit")
    assert outcome.envelope["confidence"] == "abstain"
    assert "result" not in outcome.envelope
    assert outcome.envelope["abstain"]["reason"] == "refuter_hit"
    assert [event["body"]["event_type"] for event in ledger.events()] == ["abstain"]


def test_bad_span_abstains(tmp_path: Path) -> None:
    _ledger, outcome = _run(tmp_path, "bad_span")
    assert outcome.envelope["abstain"]["reason"] == "bad_span"


def test_label_disagreement_abstains_without_a_vote(tmp_path: Path) -> None:
    _ledger, outcome = _run(tmp_path, "disagree")
    assert outcome.envelope["abstain"]["reason"] == "agent_disagreement"


def test_stray_number_is_rejected(tmp_path: Path) -> None:
    _ledger, outcome = _run(tmp_path, "stray_number")
    assert outcome.envelope["abstain"]["reason"] == "stray_number"


def test_scribe_drops_sentences_with_new_numbers(tmp_path: Path) -> None:
    ledger, outcome = _run(tmp_path, "scribe_extra_number")
    assert outcome.envelope["confidence"] == "deterministic"
    paragraph = [
        event["body"]["payload"]["output"]["paragraph"]
        for event in ledger.events()
        if event["body"]["event_type"] == "agent_turn"
        and event["body"]["payload"]["agent_id"] == "scribe"
    ][0]
    assert "8.888" not in paragraph
    ran = run_method("rigid_body_point_mass", INPUTS)
    allowed = set()
    stack = [ran["outputs"], INPUTS]
    while stack:
        current = stack.pop()
        if isinstance(current, str) and re.fullmatch(r"-?\d+\.\d+", current):
            allowed.add(current)
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, dict):
            stack.extend(current.values())
    assert any(number in paragraph for number in allowed)


def test_an_unrecomputed_integer_abstains_before_record(tmp_path: Path) -> None:
    ran = run_method("rigid_body_point_mass", INPUTS)
    stated = dict(ran["outputs"])
    stated["weight_n"] = "800"
    ledger = Ledger(tmp_path / "tenant.sqlite3", "demo")
    text = "Alpha item is listed in the source block."
    case = CaseSpec(
        tenant_id="demo",
        actor_id="author",
        created_at="2026-11-03T18:00:00Z",
        blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
        method_id="rigid_body_point_mass",
        calc_inputs=INPUTS,
        stated_outputs=stated,
    )
    outcome = run_case(ledger, FixtureGateway("happy"), case)
    assert outcome.envelope["confidence"] == "abstain"
    assert outcome.envelope["abstain"]["reason"] == "unrecomputed_integer"
    assert [event["body"]["event_type"] for event in ledger.events()] == ["abstain"]
    stored = json.dumps(ledger.events()[-1]["body"])
    assert "800" not in stored


def test_a_recomputed_decimal_mismatch_is_still_recorded(tmp_path: Path) -> None:
    ran = run_method("rigid_body_point_mass", INPUTS)
    stated = dict(ran["outputs"])
    stated["weight_n"] = "1.250"
    ledger = Ledger(tmp_path / "tenant.sqlite3", "demo")
    text = "Alpha item is listed in the source block."
    case = CaseSpec(
        tenant_id="demo",
        actor_id="author",
        created_at="2026-11-03T18:00:00Z",
        blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
        method_id="rigid_body_point_mass",
        calc_inputs=INPUTS,
        stated_outputs=stated,
    )
    outcome = run_case(ledger, FixtureGateway("happy"), case)
    kinds = [event["body"]["event_type"] for event in ledger.events()]
    assert outcome.envelope["confidence"] == "deterministic"
    assert "recompute_flag" in kinds
    assert "abstain" not in kinds


def test_missing_input_abstains_without_a_numeric_payload(tmp_path: Path) -> None:
    ledger, outcome = _run(tmp_path, "happy", inputs={"gravity_m_s2": "10.000"})
    assert outcome.envelope["confidence"] == "abstain"
    assert "result" not in outcome.envelope
    payload = json.dumps(ledger.events()[-1]["body"]["payload"])
    assert not re.search(r"\d+\.\d+", payload)
