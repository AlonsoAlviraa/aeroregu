from evidence_eval.agent_case import run_identifier_case
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
