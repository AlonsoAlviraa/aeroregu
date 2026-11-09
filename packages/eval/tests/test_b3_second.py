from evidence_eval.b3_second import gold_sha256, score_second


def test_second_memo_is_dev_gold_not_a_held_out_set() -> None:
    report = score_second()
    if not report["pdf_present"]:
        assert report["scored"] is False
        return
    assert report["scored"] is True
    assert report["expert_holdout"] is False
    assert report["fields_correct"] == "5/5"
    assert report["page_limited_fields_correct"] == "0/5"
    assert report["no_agent_fields_correct"] == "0/5"
    assert report["beats_single_llm"] == "NOT_VERIFIED"
    assert report["field_pages"] == {
        "blade_count_word": 5,
        "rotor_radius_m": 4,
        "lift_curve_slope": 3,
        "level_flight_ratio_low": 8,
        "level_flight_ratio_high": 8,
    }
    assert report["field_accuracy_ci95"]["method"] == "wilson"
    assert "not a held-out set" in report["note"]
    assert report["decimal_fields_correct"] == "4/4"
    assert report["word_labels_not_recomputed"] == ["blade_count_word"]
    assert len(report["event_hashes"]) == 4
    assert report["llm_numeric_violation"] == 0
    assert report["recorded_fields"] == [
        {"name": "rotor_radius_m", "value": "5.25", "unit": "m"},
        {"name": "lift_curve_slope", "value": "5.7", "unit": "1"},
        {"name": "level_flight_ratio_low", "value": "0.14", "unit": "1"},
        {"name": "level_flight_ratio_high", "value": "0.37", "unit": "1"},
    ]
    assert report["unit_abstain_hashes"] == []
    assert report["shared_with_first_memo"] == ["V3101", "V3103", "V3105", "V3106"]
    assert report["absent_from_second_memo"] == ["V3109", "V3111"]
    assert report["table_magnitudes_stored"] is False
    assert report["flight_table_column_abstained"] is True
    assert len(report["column_abstain_hash"]) == 64
    assert all(len(item) == 64 for item in report["event_hashes"])


def test_an_unknown_unit_is_an_abstain_not_a_span() -> None:
    from evidence_eval.b3_second import _record_fields

    field = {
        "name": "bad",
        "value_text": "5.25",
        "unit_text": "not-a-unit",
        "pattern": r"([0-9.]+)",
    }
    hashes, abstains = _record_fields("5.25", (field,))[:2]
    assert hashes == []
    assert len(abstains) == 1
    assert len(abstains[0]) == 64
    from evidence_eval.b3_second import _measured_ok

    assert _measured_ok("5.25", "m") is True
    assert _measured_ok("5.25", "not-a-unit") is False
    assert _measured_ok("three", "1") is True
    assert _measured_ok("9.8", "m/s2") is True


def test_three_bare_lines_are_a_column() -> None:
    from evidence_eval.quote_pipeline import stacked_bare_numbers

    text = "V1\n1.0\n2.0\n3.0\nnext"
    assert stacked_bare_numbers(text, "V1") is True
    assert stacked_bare_numbers("V1\n1.0\nwords here\n2.0", "V1") is False
    assert stacked_bare_numbers("V1\n1.0\n2.0\n1 .o\n3.0", "V1") is True
    from evidence_eval.quote_pipeline import _damaged_number

    assert _damaged_number("1 .o") is True
    assert _damaged_number("December 1988") is False


def test_second_gold_hash_is_stable() -> None:
    from evidence_kernel.paths import repo_root

    frozen = (repo_root() / "bench" / "b3" / "second_gold.sha256").read_text(encoding="utf-8")
    assert gold_sha256() == frozen.strip()


def test_a_wrong_second_pdf_hash_is_not_scored(tmp_path, monkeypatch) -> None:
    import hashlib
    import json

    from evidence_eval import b3_second

    fake = tmp_path / "NASA-19890004039.pdf"
    fake.write_bytes(b"not-the-pinned-nasa-pdf")
    digest = hashlib.sha256(fake.read_bytes()).hexdigest()
    assert digest != b3_second.EXPECTED_SHA256
    monkeypatch.setattr(b3_second, "PDF_RELATIVE", fake)
    quotes = (
        "three-bladed helicopter\n"
        "rotor radius = 5.25 m\n"
        "lift curve slope = 5.7\n"
        "advance ratio from 0.14 to 0.37\n"
    )
    monkeypatch.setattr(b3_second, "read_pdf_pages", lambda _path, _span: [quotes])

    report = score_second()
    body = json.dumps(report)
    assert report["pdf_present"] is True
    assert report["scored"] is False
    assert report["label"] == "NOT_VERIFIED"
    assert report.get("ready") is not True
    assert report.get("complete") is not True
    assert report.get("programme_complete") is not True
    assert "fields_correct" not in report
    assert "decimal_fields_correct" not in report
    assert "recorded_fields" not in report
    assert "event_hashes" not in report
    for token in ("three", "5.25", "5.7", "0.14", "0.37"):
        assert token not in body
