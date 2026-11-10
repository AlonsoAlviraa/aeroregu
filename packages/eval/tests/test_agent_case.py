from evidence_eval.agent_case import map_report, run_identifier_case
from evidence_kernel.ledger import Ledger

WHEN = "2026-11-03T21:00:00Z"
TEXT = "Pack ev-1 addresses VTOL.2210 with a stored hash."


def test_one_identifier_is_mapped_and_scribed(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_identifier_case(
        ledger,
        text=TEXT,
        evidence_id="ev-1",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["queue"] is None
    assert outcome["requirement_id"] == "VTOL.2210"
    assert outcome["scribe"] == outcome["event_hash"]
    body = ledger.events()[-1]["body"]
    assert body["event_type"] == "requirement_recorded"
    assert body["actor_id"] == "orchestrator"


def test_a_pack_the_sentence_does_not_name_is_not_recorded(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_identifier_case(
        ledger,
        text=TEXT,
        evidence_id="ev-2",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["queue"] == "human_engineer"
    assert outcome["requirement_id"] is None
    body = ledger.events()[-1]["body"]
    assert body["event_type"] == "abstain"
    assert body["payload"]["reason"] == "evidence_not_in_text"
    assert all(event["body"]["event_type"] != "requirement_recorded" for event in ledger.events())


def test_an_unseen_heading_is_not_recorded(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_identifier_case(
        ledger,
        text="Pack ev-1 addresses VTOL.9999 with a stored hash.",
        evidence_id="ev-1",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["queue"] == "human_engineer"
    assert outcome["requirement_id"] is None
    body = ledger.events()[-1]["body"]
    assert body["event_type"] == "abstain"
    assert body["payload"]["reason"] == "unknown_heading"


def test_two_packs_are_recorded(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = map_report(
        ledger,
        text="Pack ev-1 addresses VTOL.2210. Pack ev-2 addresses VTOL.2215.",
        evidence=[
            {"id": "ev-1", "hash": "ab" * 32},
            {"id": "ev-2", "hash": "cd" * 32},
        ],
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    pairs = {(link["requirement_id"], link["evidence_id"]) for link in outcome["links"]}
    assert outcome["queue"] is None
    assert pairs == {("VTOL.2210", "ev-1"), ("VTOL.2215", "ev-2")}
    assert outcome["false_coverage"] == []
    assert outcome["llm_numeric_violation"] == 0
    recorded = [
        event["body"]["event_type"]
        for event in ledger.events()
        if event["body"]["event_type"] == "requirement_recorded"
    ]
    assert recorded == ["requirement_recorded", "requirement_recorded"]


def test_two_headings_without_a_pack_abstain(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = map_report(
        ledger,
        text="VTOL.2210 and VTOL.2215 are both named.",
        evidence=[{"id": "ev-1", "hash": "ab" * 32}],
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["queue"] == "human_engineer"
    assert outcome["reason"] == "ambiguous_input"
    assert outcome["links"] == []
    assert ledger.events()[-1]["body"]["event_type"] == "abstain"


def test_one_pack_can_support_two_headings(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = map_report(
        ledger,
        text="Pack ev-1 addresses VTOL.2210 and VTOL.2215.",
        evidence=[{"id": "ev-1", "hash": "ab" * 32}],
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    pairs = {(link["requirement_id"], link["evidence_id"]) for link in outcome["links"]}
    assert pairs == {("VTOL.2210", "ev-1"), ("VTOL.2215", "ev-1")}
    assert outcome["llm_numeric_violation"] == 0


def test_a_zero_hash_on_the_second_pack_is_not_linked(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = map_report(
        ledger,
        text="Pack ev-1 addresses VTOL.2210. Pack ev-2 addresses VTOL.2215.",
        evidence=[
            {"id": "ev-1", "hash": "ab" * 32},
            {"id": "ev-2", "hash": "0" * 64},
        ],
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert {(link["requirement_id"], link["evidence_id"]) for link in outcome["links"]} == {
        ("VTOL.2210", "ev-1")
    }
    assert {
        (item["requirement_id"], item["evidence_id"]) for item in outcome["false_coverage"]
    } == {("VTOL.2215", "ev-2")}
    types = [event["body"]["event_type"] for event in ledger.events()]
    assert types == ["requirement_recorded", "recompute_flag"]


def test_two_identifiers_abstain(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_identifier_case(
        ledger,
        text="VTOL.2210 and VTOL.2215 are both named.",
        evidence_id="ev-1",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["queue"] == "human_engineer"
    assert outcome["requirement_id"] is None
    assert ledger.events()[-1]["body"]["event_type"] == "abstain"


def test_low_confidence_abstains_without_a_link(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_identifier_case(
        ledger,
        text=TEXT,
        evidence_id="ev-1",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
        confidence="low",
    )
    assert outcome["queue"] == "human_engineer"
    assert ledger.events()[-1]["body"]["envelope"]["confidence"] == "abstain"


def test_zero_hash_is_refused_and_not_linked(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_identifier_case(
        ledger,
        text=TEXT,
        evidence_id="ev-1",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
        evidence_hash="0" * 64,
    )
    assert outcome["requirement_id"] is None
    assert outcome["false_coverage"] is True
    assert ledger.events()[-1]["body"]["event_type"] == "recompute_flag"
