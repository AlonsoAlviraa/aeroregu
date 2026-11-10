from pathlib import Path

from evidence_kernel.gateway import Completion, FixtureGateway, OpenAICompatibleGateway
from evidence_kernel.ledger import Ledger
from evidence_kernel.numbers import stray_physical_numbers
from evidence_kernel.supervisor import CaseSpec, run_case

TEXT = "Alpha item is listed in the source block."


def _case(tmp_path: Path, *, gate: bool) -> tuple[Ledger, object]:
    ledger = Ledger(tmp_path / "tenant.sqlite3", "demo")
    case = CaseSpec(
        tenant_id="demo",
        actor_id="author",
        created_at="2026-11-10T12:00:00Z",
        blocks=[{"text": TEXT, "span_start": 0, "span_end": len(TEXT)}],
        method_id="rigid_body_point_mass",
        calc_inputs={
            "mass_kg": "800.000",
            "gravity_m_s2": "10.000",
            "load_factor": "1.000",
            "altitude_m": "0.000",
            "cg_x_m": "0.000",
            "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
            "unit_operative": [True, True, True, True],
        },
        use_decision_gate=gate,
    )
    return ledger, case


def test_low_probability_abstains_without_a_result(tmp_path: Path) -> None:
    ledger, case = _case(tmp_path, gate=True)
    outcome = run_case(ledger, FixtureGateway("gate_low"), case)
    assert outcome.envelope["confidence"] == "abstain"
    assert "result" not in outcome.envelope
    assert outcome.envelope["abstain"]["reason"] == "decision_gate"
    assert [event["body"]["event_type"] for event in ledger.events()] == ["abstain"]


def test_abstain_decision_stores_no_calc(tmp_path: Path) -> None:
    ledger, case = _case(tmp_path, gate=True)
    outcome = run_case(ledger, FixtureGateway("gate_abstain"), case)
    assert outcome.envelope["abstain"]["reason"] == "decision_gate"
    assert "result" not in outcome.envelope


def test_continue_keeps_the_calc_result(tmp_path: Path) -> None:
    ledger, case = _case(tmp_path, gate=True)
    outcome = run_case(ledger, FixtureGateway("happy"), case)
    assert outcome.envelope["confidence"] == "deterministic"
    assert "result" in outcome.envelope
    ids = [
        event["body"]["payload"].get("agent_id")
        for event in ledger.events()
        if event["body"]["event_type"] == "agent_turn"
    ]
    assert ids[0] == "decision_gate"


def test_a_stray_quantity_on_the_gate_is_rejected(tmp_path: Path) -> None:
    class StrayGate:
        def complete(self, agent_id: str, messages: list, schema: dict | None) -> Completion:
            if agent_id == "decision_gate":
                return Completion(
                    {
                        "decision": "continue",
                        "gate_probability": "0.950",
                        "note": "invented load 9.999",
                    },
                    None,
                    "0",
                    "ab" * 32,
                )
            return FixtureGateway("happy").complete(agent_id, messages, schema)

    ledger, case = _case(tmp_path, gate=True)
    outcome = run_case(ledger, StrayGate(), case)
    assert outcome.envelope["abstain"]["reason"] == "stray_number"
    assert "result" not in outcome.envelope


def test_a_gate_probability_is_not_a_physical_quantity() -> None:
    assert stray_physical_numbers({"gate_probability": "0.950"}, set()) == []
    assert stray_physical_numbers({"gate_probability": "800.000"}, set()) == ["800.000"]


def test_hosted_adapter_does_not_call_the_network_for_the_gate() -> None:
    gateway = OpenAICompatibleGateway("http://127.0.0.1:9")
    done = gateway.complete("decision_gate", [{"role": "user", "content": "{}"}], None)
    assert done.abstain_reason == "decision_gate_fixture_only"
    assert done.output is None
