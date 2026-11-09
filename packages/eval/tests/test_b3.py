from evidence_eval.b3 import judged_field, score_b3


def test_b3_scores_the_local_nasa_tm_when_present() -> None:
    report = score_b3()
    if not report["pdf_present"]:
        assert report["ready"] is False
        assert report["label"] == "NOT_VERIFIED"
        return
    assert report["sha256"].startswith("5ee682ca")
    assert report["ready"] is False
    assert report["dev_pdf_scored"] is True
    assert report["expert_holdout"] is False
    assert report["expert_holdout_llm_numeric_violation"] == 0
    assert report["fields_correct"].endswith("/8")
    assert report["fields_correct"].startswith("8/")
    assert report["field_accuracy_ci95"]["method"] == "wilson"
    assert report["page_limited_ci95"]["method"] == "wilson"
    assert report["no_agent_ci95"]["method"] == "wilson"
    assert report["beats_page_limited_reader"] is True
    assert report["beats_no_agent"] is True
    assert report["no_agent_fields_correct"] == "0/8"
    assert report["page_limited_fields_correct"].startswith("2/")
    assert len(report["page_limited_misses"]) == 6
    assert "blade_count" not in report["page_limited_misses"]
    assert "gravity" not in report["page_limited_misses"]
    pages = report["field_pages"]
    assert pages == {
        "blade_count": 2,
        "gravity": 2,
        "strain_gage_count": 7,
        "flight_condition_count": 6,
        "level_flight_ratio_low": 6,
        "level_flight_ratio_high": 6,
        "turning_flight_ratio_low": 6,
        "turning_flight_ratio_high": 6,
    }
    assert report["unit_error_detected"] is True
    assert report["empty_text_abstained"] is True
    assert report["assumption_span_found"] is True
    assert report["assumption_value"] is None
    assert report["load_case_ids_found"] is True
    assert report["load_case_ids"] == [
        "V3101",
        "V3103",
        "V3105",
        "V3106",
        "V3109",
        "V3111",
    ]
    assert report["load_case_value"] is None
    assert report["load_factor_column_abstained"] is True
    assert report["load_factor_value"] is None
    assert len(report["load_factor_abstain_hash"]) == 64
    assert report["load_factor_value"] is None
    assert len(report["quoted_span_hashes"]) == 3
    assert all(len(item) == 64 for item in report["quoted_span_hashes"])
    assert report["expert_holdout"] is False


def test_b3_judge_rejects_reasoning() -> None:
    quote = {
        "name": "blade_count",
        "value_text": "3",
        "unit_text": "1",
        "span_start": 0,
        "span_end": 1,
        "reasoning": "the model guessed",
    }
    assert judged_field("blade_count", quote, "3") is False


def test_the_quote_path_matches_the_field_score() -> None:
    import tempfile
    from pathlib import Path

    from evidence_eval.quote_pipeline import score_nasa_quotes
    from evidence_kernel.ledger import Ledger

    report = score_b3()
    if not report["pdf_present"]:
        return
    with tempfile.TemporaryDirectory() as tmp:
        quotes = score_nasa_quotes(Ledger(Path(tmp) / "quotes.sqlite3", "bench"))
    assert quotes["matched"] == report["fields_correct"]
    assert quotes["false_alarms"] == 0
    assert quotes["llm_numeric_violation"] == 0
    assert quotes["recorded_fields"] == [
        {"name": "blade_count", "value": "3", "unit": "dimensionless"},
        {"name": "gravity", "value": "9.8", "unit": "meter / second ** 2"},
        {"name": "strain_gage_count", "value": "31", "unit": "dimensionless"},
        {"name": "flight_condition_count", "value": "23", "unit": "dimensionless"},
        {"name": "level_flight_ratio_low", "value": "0.14", "unit": "dimensionless"},
        {"name": "level_flight_ratio_high", "value": "0.37", "unit": "dimensionless"},
        {"name": "turning_flight_ratio_low", "value": "0.26", "unit": "dimensionless"},
        {"name": "turning_flight_ratio_high", "value": "0.35", "unit": "dimensionless"},
    ]
    assert quotes["abstain_ok"] is True


def test_a_wrong_first_pdf_hash_is_not_scored(tmp_path, monkeypatch) -> None:
    import hashlib
    import json

    from evidence_eval import b3

    fake = tmp_path / "NASA-TM-101040.pdf"
    fake.write_bytes(b"not-the-pinned-nasa-pdf")
    digest = hashlib.sha256(fake.read_bytes()).hexdigest()
    assert digest != b3.EXPECTED_SHA256
    assert b3.EXPECTED_SHA256 == "5ee682caf7d0ce2f95f327fcb3f9ea2ba5ff7ab25d79f8f4aba08a9a6f79fbed"
    monkeypatch.setattr(b3, "PDF_RELATIVE", fake)
    text = (
        "number of blades = 3\n"
        "gravitational acceleration (m/s2) = 9.8\n"
        "31 strain gages\n"
        "Data from 23 flight conditions\n"
        "level flights ranging from p. = 0.14 to 0.37\n"
        "turning flights from p = 0.26 to 0.35\n"
        "assumed to be a beam\n"
        "six flight conditions, V3101, V3103, V3105, V3106, V3109, and V3111\n"
        "Load Factor\n"
        "1.5\n"
    )
    monkeypatch.setattr(b3, "read_pdf_pages", lambda _path: [text])

    report = score_b3()
    body = json.dumps(report)
    assert report["pdf_present"] is True
    assert report["ready"] is False
    assert report["label"] == "NOT_VERIFIED"
    assert report["sha256"] == digest
    assert report.get("dev_pdf_scored") is not True
    assert report.get("complete") is not True
    assert report.get("programme_complete") is not True
    for key in (
        "fields_correct",
        "field_accuracy",
        "quoted_span_hashes",
        "load_case_ids",
        "load_case_value",
        "load_factor_value",
        "load_factor_abstain_hash",
        "assumption_value",
    ):
        assert key not in report
    for token in (
        "9.8",
        "0.14",
        "0.37",
        "0.26",
        "0.35",
        "1.5",
        "V3101",
        "V3103",
        "V3105",
        "V3106",
        "V3109",
        "V3111",
        "assumed to be a beam",
    ):
        assert token not in body
