import json

from evidence_eval.b3 import GOLD_FIELDS, validate_b3_holdout


def _case(fields: list[dict[str, str]], author: str = "Ada") -> dict[str, object]:
    return {
        "case_id": "ext-1",
        "document_sha256": "abc",
        "fields": fields,
        "provenance": {"author": author, "statement": "This is not employer material."},
    }


def test_the_live_b3_holdout_is_empty() -> None:
    report = validate_b3_holdout()
    assert report["files"] == 0
    assert report["ready"] is False
    assert report["scored"] is False


def test_a_field_without_a_value_is_not_copied_gold(tmp_path) -> None:
    fields = [{"name": "blade_count", "unit_text": "1"}]
    (tmp_path / "thin.json").write_text(json.dumps(_case(fields)), encoding="utf-8")
    report = validate_b3_holdout(tmp_path)
    assert report["reject_reasons"] == {"fields": 1}
    assert "blade_count" not in json.dumps(report)


def test_a_copy_of_the_dev_gold_is_rejected(tmp_path) -> None:
    fields = [
        {"name": item["name"], "value_text": item["value_text"], "unit_text": item["unit_text"]}
        for item in GOLD_FIELDS
    ]
    (tmp_path / "copy.json").write_text(json.dumps(_case(fields)), encoding="utf-8")
    report = validate_b3_holdout(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 1
    assert report["scored"] is False
    assert report["reject_reasons"] == {"copied_dev_gold": 1}
    assert "ext-1" not in json.dumps(report)


def test_the_checker_author_is_rejected(tmp_path) -> None:
    fields = [{"name": "other", "value_text": "1", "unit_text": "1"}]
    (tmp_path / "self.json").write_text(
        json.dumps(_case(fields, author="AeroRegu")),
        encoding="utf-8",
    )
    report = validate_b3_holdout(tmp_path)
    assert report["rejected"] == 1
    assert report["ready"] is False


def test_a_longer_checker_name_is_not_a_b3_author(tmp_path) -> None:
    fields = [{"name": "other", "value_text": "1", "unit_text": "1"}]
    (tmp_path / "self.json").write_text(
        json.dumps(_case(fields, author="aeroregu helper")),
        encoding="utf-8",
    )
    report = validate_b3_holdout(tmp_path)
    assert report["rejected"] == 1
    assert report["reject_reasons"] == {"author": 1}
    assert report["ready"] is False
    assert report["scored"] is False


def test_a_dev_document_hash_is_rejected(tmp_path) -> None:
    from evidence_eval.b3 import EXPECTED_SHA256

    fields = [{"name": "other", "value_text": "1", "unit_text": "1"}]
    case = _case(fields)
    case["document_sha256"] = EXPECTED_SHA256
    (tmp_path / "same.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b3_holdout(tmp_path)
    assert report["rejected"] == 1
    assert report["scored"] is False


def test_one_other_case_is_not_scored(tmp_path) -> None:
    fields = [{"name": "other", "value_text": "1", "unit_text": "1"}]
    (tmp_path / "ext.json").write_text(json.dumps(_case(fields)), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    report = validate_b3_holdout(tmp_path)
    assert report["valid"] == 1
    assert report["ready"] is True
    assert report["scored"] is False


def test_a_missing_document_is_not_scored(tmp_path) -> None:
    from evidence_eval.b3 import score_b3_holdout

    fields = [{"name": "other", "value_text": "1", "unit_text": "1"}]
    (tmp_path / "ext.json").write_text(json.dumps(_case(fields)), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    scored = score_b3_holdout(tmp_path)
    assert scored["scored"] is False
    assert scored["ready"] is False
    assert scored["abstained"] == 1
    assert scored["abstain_reasons"] == {"path_missing": 1}
    assert "ext-1" not in json.dumps(scored)


def test_a_wrong_document_hash_is_not_a_missing_file(tmp_path) -> None:
    from evidence_eval.b3 import score_b3_holdout

    name = "SECRET-DOC.txt"
    note = tmp_path / name
    note.write_text("blade count 4\n", encoding="utf-8")
    fields = [{"name": "blade_count", "value_text": "4", "unit_text": "1"}]
    case = _case(fields)
    case["document_sha256"] = "abc"
    case["document_path"] = name
    (tmp_path / "ext.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    scored = score_b3_holdout(tmp_path)
    dumped = json.dumps(scored)
    assert scored["scored"] is False
    assert scored["abstain_reasons"] == {"hash_mismatch": 1}
    assert name not in dumped
    assert "blade count" not in dumped


def test_a_local_text_file_can_be_scored(tmp_path) -> None:
    import hashlib

    from evidence_eval.b3 import score_b3_holdout

    note = tmp_path / "note.txt"
    note.write_text("blade count 4\n", encoding="utf-8")
    fields = [{"name": "blade_count", "value_text": "4", "unit_text": "1"}]
    case = _case(fields)
    case["document_sha256"] = hashlib.sha256(note.read_bytes()).hexdigest()
    case["document_path"] = "note.txt"
    (tmp_path / "ext.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    scored = score_b3_holdout(tmp_path)
    assert scored["scored"] is True
    assert scored["ready"] is False
    assert scored["judge_correct"] == "1/1"


def test_a_digit_inside_a_longer_number_is_not_a_hit(tmp_path) -> None:
    import hashlib

    from evidence_eval.b3 import score_b3_holdout

    note = tmp_path / "note.txt"
    note.write_text("counts 14 and 4.5\n", encoding="utf-8")
    fields = [{"name": "blade_count", "value_text": "4", "unit_text": "1"}]
    case = _case(fields)
    case["document_sha256"] = hashlib.sha256(note.read_bytes()).hexdigest()
    case["document_path"] = "note.txt"
    (tmp_path / "ext.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    scored = score_b3_holdout(tmp_path)
    assert scored["scored"] is True
    assert scored["judge_correct"] == "0/1"


def test_an_identifier_number_is_not_a_holdout_hit() -> None:
    from evidence_eval.b3 import _field_hit

    document = "See CS-27.301 and VTOL.2210."
    assert _field_hit({"value_text": "27", "unit_text": "1"}, document) is False
    assert _field_hit({"value_text": "301", "unit_text": "1"}, document) is False
    assert _field_hit({"value_text": "2210", "unit_text": "1"}, document) is False
    assert _field_hit({"value_text": "27", "unit_text": "1"}, "the count is 27") is True


def test_an_equivalent_decimal_integer_is_a_hit(tmp_path) -> None:
    import hashlib

    from evidence_eval.b3 import score_b3_holdout

    note = tmp_path / "note.txt"
    note.write_text("blade count 4.0\n", encoding="utf-8")
    fields = [{"name": "blade_count", "value_text": "4", "unit_text": "1"}]
    case = _case(fields)
    case["document_sha256"] = hashlib.sha256(note.read_bytes()).hexdigest()
    case["document_path"] = "note.txt"
    (tmp_path / "ext.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    scored = score_b3_holdout(tmp_path)
    assert scored["scored"] is True
    assert scored["judge_correct"] == "1/1"
    assert scored["abstained"] == 0
    assert scored["llm_numeric_violation"] == 0


def test_a_different_unit_string_is_not_a_hit(tmp_path) -> None:
    import hashlib

    from evidence_eval.b3 import score_b3_holdout

    note = tmp_path / "note.txt"
    note.write_text("radius 5.25 ft\n", encoding="utf-8")
    fields = [{"name": "rotor_radius_m", "value_text": "5.25", "unit_text": "m"}]
    case = _case(fields)
    case["document_sha256"] = hashlib.sha256(note.read_bytes()).hexdigest()
    case["document_path"] = "note.txt"
    (tmp_path / "ext.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    scored = score_b3_holdout(tmp_path)
    assert scored["judge_correct"] == "0/1"


def test_the_file_spelling_m_s2_matches(tmp_path) -> None:
    import hashlib

    from evidence_eval.b3 import score_b3_holdout

    note = tmp_path / "note.txt"
    note.write_text("gravity 9.8 m/s2\n", encoding="utf-8")
    fields = [{"name": "gravity", "value_text": "9.8", "unit_text": "m/s2"}]
    case = _case(fields)
    case["document_sha256"] = hashlib.sha256(note.read_bytes()).hexdigest()
    case["document_path"] = "note.txt"
    (tmp_path / "ext.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    scored = score_b3_holdout(tmp_path)
    assert scored["judge_correct"] == "1/1"
    assert scored["judge_ci95"]["method"] == "wilson"
    assert scored["llm_numeric_violation"] == 0


def test_a_scoring_error_does_not_echo_the_case(tmp_path, monkeypatch) -> None:
    import hashlib

    from evidence_eval.b3 import score_b3_holdout

    secret = "SECRET-HOLD-OUT-VALUE"
    note = tmp_path / "note.txt"
    note.write_text(f"blade count 4 {secret}\n", encoding="utf-8")
    fields = [{"name": "blade_count", "value_text": "4", "unit_text": "1"}]
    case = _case(fields)
    case["document_sha256"] = hashlib.sha256(note.read_bytes()).hexdigest()
    case["document_path"] = "note.txt"
    (tmp_path / "ext.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr("evidence_kernel.orchestrator.record", boom)
    scored = score_b3_holdout(tmp_path)
    dumped = json.dumps(scored)
    assert secret not in dumped
    assert "blade count" not in dumped
    assert scored["stopped"] == "RuntimeError"
    assert scored["scored"] is False
