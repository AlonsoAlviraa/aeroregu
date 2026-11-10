from evidence_eval.quote_pipeline import quotes_ok, run_quote, score_nasa_quotes
from evidence_kernel.contracts import SpanQuote
from evidence_kernel.ledger import Ledger

TEXT = "number of blades = 3"
WHEN = "2026-11-03T20:30:00Z"


def test_quoted_integer_is_parsed_by_code(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_quote(
        ledger,
        text=TEXT,
        pattern=r"number of blades = (\d+)",
        name="blade_count",
        unit_text="dimensionless",
        expected_unit="dimensionless",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["queue"] is None
    assert outcome["value"] == "3"
    assert outcome["scribe"] == outcome["event_hash"]
    body = ledger.events()[-1]["body"]
    assert body["event_type"] == "recompute_flag"
    assert body["envelope"]["result"]["value"] == "3"
    assert body["envelope"]["result"]["unit"] == "dimensionless"


def test_a_word_is_not_parsed_as_a_number(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_quote(
        ledger,
        text="three-bladed helicopter",
        pattern=r"(three)-bladed",
        name="blade_count_word",
        unit_text="dimensionless",
        expected_unit="dimensionless",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["value"] is None
    assert outcome["queue"] == "human_engineer"
    assert len(outcome["event_hash"]) == 64


def test_an_equivalent_decimal_is_not_a_quote_false_alarm() -> None:
    from evidence_eval.quote_pipeline import _values_match

    assert _values_match("9.8", "9.80") is True
    assert _values_match("9.8", "9.81") is False
    assert _values_match("three", "3") is False


def test_a_decimal_equivalent_span_matches() -> None:
    from evidence_eval.quote_pipeline import challenge

    text = "blade count 4.0"
    start = text.index("4.0")
    field = SpanQuote(
        name="blade_count",
        value_text="4",
        unit_text="1",
        span_start=start,
        span_end=start + 3,
    )
    result = challenge(text, field)
    assert result.attack == "miss"
    assert result.reason == "span_matches"


def test_bad_span_goes_to_the_human_queue(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    forged = SpanQuote(
        name="blade_count", value_text="3", unit_text="dimensionless", span_start=0, span_end=1
    )
    outcome = run_quote(
        ledger,
        text=TEXT,
        pattern=r"number of blades = (\d+)",
        name="blade_count",
        unit_text="dimensionless",
        expected_unit="dimensionless",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
        field=forged,
    )
    assert outcome["queue"] == "human_engineer"
    assert outcome["value"] is None
    assert ledger.events()[-1]["body"]["event_type"] == "abstain"


def test_incompatible_unit_queues(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_quote(
        ledger,
        text="gravitational acceleration (m/s2) = 9.8",
        pattern=r"gravitational acceleration \(m/s2\) = ([0-9.]+)",
        name="gravity",
        unit_text="meter / second ** 2",
        expected_unit="meter",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["queue"] == "human_engineer"
    assert outcome["value"] is None


def test_nasa_tm_quotes_match_the_dev_gold(tmp_path) -> None:
    from evidence_eval.b3 import PDF_RELATIVE
    from evidence_kernel.paths import repo_root

    if not (repo_root() / PDF_RELATIVE).is_file():
        return
    ledger = Ledger(tmp_path / "nasa.sqlite3", "demo")
    report = score_nasa_quotes(ledger)
    assert report["matched"] == "8/8"
    assert report["false_alarms"] == 0
    assert report["abstain_ok"] is True
    assert report["recall_ci95"]["method"] == "wilson"
    assert quotes_ok(report) is True
    assert report["expert_holdout"] is False


def test_a_bare_number_row_abstains(tmp_path) -> None:
    ledger = Ledger(tmp_path / "t.sqlite3", "demo")
    outcome = run_quote(
        ledger,
        text="1.20 3.40 5.60 7.80",
        pattern=r"([0-9.]+)",
        name="cell",
        unit_text="dimensionless",
        expected_unit="dimensionless",
        tenant_id="demo",
        actor_id="orchestrator",
        created_at=WHEN,
    )
    assert outcome["value"] is None
    assert outcome["queue"] == "human_engineer"
    body = ledger.events()[-1]["body"]
    assert body["event_type"] == "abstain"
    assert body["payload"]["reason"] == "unreadable_table"


def test_a_wrong_quote_pdf_hash_stores_no_numbers(tmp_path, monkeypatch) -> None:
    import hashlib
    import json

    from evidence_eval import b3

    fake = tmp_path / "NASA-TM-101040.pdf"
    fake.write_bytes(b"not-the-pinned-nasa-pdf")
    digest = hashlib.sha256(fake.read_bytes()).hexdigest()
    assert digest != b3.EXPECTED_SHA256
    assert b3.EXPECTED_SHA256 == "5ee682caf7d0ce2f95f327fcb3f9ea2ba5ff7ab25d79f8f4aba08a9a6f79fbed"
    monkeypatch.setattr(b3, "PDF_RELATIVE", fake)
    planted = (
        "number of blades = 3\n"
        "gravitational acceleration (m/s2) = 9.8\n"
        "31 strain gages\n"
        "Data from 23 flight conditions\n"
        "level flights ranging from p. = 0.14 to 0.37\n"
        "turning flights from p = 0.26 to 0.35\n"
    )
    opened: list[object] = []

    def _pages(path: object) -> list[str]:
        opened.append(path)
        return [planted]

    monkeypatch.setattr(b3, "read_pdf_pages", _pages)
    ledger = Ledger(tmp_path / "quotes.sqlite3", "bench")
    report = score_nasa_quotes(ledger)
    body = json.dumps(report)
    assert opened == []
    assert report["ready"] is False
    assert report["label"] == "NOT_VERIFIED"
    assert report["matched"] == "0/0"
    assert report["llm_numeric_violation"] == 0
    assert report["sha256"] == digest
    assert report.get("programme_complete") is not True
    assert "recorded_fields" not in report
    assert ledger.events() == []
    for token in ("9.8", "0.14", "0.37", "0.26", "0.35"):
        assert token not in body


def test_quote_gate_ready_is_not_benchmark_ready(tmp_path) -> None:
    from evidence_eval.quote_pipeline import quotes_ok

    ledger = Ledger(tmp_path / "quotes.sqlite3", "bench")
    report = score_nasa_quotes(ledger)
    if report["matched"] == "0/0":
        assert report["ready"] is False
        return
    assert report["matched"] == "8/8"
    assert report["ready"] is True
    assert report["benchmark_ready"] is False
    assert report["llm_numeric_violation"] == 0
    assert quotes_ok(report) is True
    assert "does not mean B3 is ready" in report["note"]


def test_quotes_ok_rejects_an_extra_decimal() -> None:
    report = {
        "ready": True,
        "matched": "1/1",
        "false_alarms": 0,
        "abstain_ok": True,
        "llm_numeric_violation": 1,
    }
    assert quotes_ok(report) is False


def test_the_bench_rejects_a_chain_decimal() -> None:
    from evidence_eval.__main__ import _ledger_numbers_ok

    clean = {"b2": {"agent_chain": {"llm_numeric_violation": 0}}, "b3_second": {}}
    dirty = {"b2": {"agent_chain": {"llm_numeric_violation": 1}}, "b3_second": {}}
    scored = {
        "b2": {"agent_chain": {"llm_numeric_violation": 0}},
        "b3_second": {"scored": True, "llm_numeric_violation": 2},
    }
    absent = {
        "b2": {"agent_chain": {"llm_numeric_violation": 0}},
        "b3_second": {"scored": False, "llm_numeric_violation": 2},
    }
    assert _ledger_numbers_ok(clean) is True
    assert _ledger_numbers_ok(dirty) is False
    assert _ledger_numbers_ok(scored) is False
    assert _ledger_numbers_ok(absent) is True
    holdout = {
        "b2": {"agent_chain": {"llm_numeric_violation": 0}},
        "b3_second": {},
        "b3": {"expert_holdout": True, "expert_holdout_llm_numeric_violation": 1},
    }
    idle = {
        "b2": {"agent_chain": {"llm_numeric_violation": 0}},
        "b3_second": {},
        "b3": {"expert_holdout": False, "expert_holdout_llm_numeric_violation": 1},
    }
    assert _ledger_numbers_ok(holdout) is False
    assert _ledger_numbers_ok(idle) is True
    memo = {
        "b2": {"agent_chain": {"llm_numeric_violation": 0}},
        "b3_second": {},
        "b3": {"llm_numeric_violation": 1},
    }
    assert _ledger_numbers_ok(memo) is False
    drill_hit = {
        "b2": {"agent_chain": {"llm_numeric_violation": 0}},
        "b3_second": {},
        "b4": {"drill": {"llm_numeric_violation": 1}},
    }
    assert _ledger_numbers_ok(drill_hit) is False
    series_hit = {
        "b2": {"agent_chain": {"llm_numeric_violation": 0}},
        "b3_second": {},
        "b4": {"as365": {"llm_numeric_violation": 1}},
    }
    assert _ledger_numbers_ok(series_hit) is False
