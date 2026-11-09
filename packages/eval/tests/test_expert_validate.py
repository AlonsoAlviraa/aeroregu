import json

from evidence_eval.expert_validate import validate_b1
from evidence_eval.holdout_gate import REQUIRED_SENTENCE


def _case(author: str) -> dict:
    return {
        "case_id": "expert-1",
        "artifact_kind": "note",
        "faults": ["unit_scale"],
        "expected": "detect:unit_scale",
        "artifact": {"method_id": "bolt_screen"},
        "provenance": {
            "origin": "owned",
            "author": author,
            "generator_version": "expert@1",
            "seed": 1,
            "statement": "Written for this held-out set. No employer material.",
        },
    }


def test_live_directory_is_not_ready() -> None:
    report = validate_b1()
    assert report["files"] == 0
    assert report["ready"] is False
    assert report["scored"] is False


def test_checker_author_is_rejected(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(_case("aeroregu")), encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 1
    assert report["ready"] is False


def test_a_capitalised_checker_author_is_rejected(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(_case("AeroRegu")), encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 1


def test_one_hundred_fifty_empty_files_are_not_ready(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    for index in range(150):
        (tmp_path / f"{index}.json").write_text("{}", encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 150
    assert report["ready"] is False
    assert report["scored"] is False


def test_a_statement_that_does_not_exclude_employer_material_is_rejected(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    case = _case("domain-expert")
    case["provenance"]["statement"] = "Written for this set."
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 1
    assert report["ready"] is False


def test_one_expert_file_is_valid_but_not_enough(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(_case("domain-expert")), encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["valid"] == 1
    assert report["fault_types"] == 1
    assert report["ready"] is False


def test_unexplained_does_not_count_as_a_fault_type(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    case = _case("domain-expert")
    case["faults"] = ["unexplained"]
    case["expected"] = "detect:unexplained"
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["valid"] == 1
    assert report["fault_types"] == 0
    assert report["ready"] is False


def test_a_mismatched_expected_fault_is_rejected(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    case = _case("domain-expert")
    case["faults"] = ["sign"]
    case["expected"] = "detect:arithmetic"
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b1(tmp_path)
    encoded = json.dumps(report)
    assert report["valid"] == 0
    assert report["rejected"] == 1
    assert report["fault_types"] == 0
    assert report["reject_reasons"] == {"expected": 1}
    assert "expert-1" not in encoded


def test_missing_input_cannot_be_compound(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    case = _case("domain-expert")
    case["faults"] = ["missing_input", "arithmetic"]
    case["expected"] = "detect:compound"
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 1


def test_a_string_seed_is_schema(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    case = _case("domain-expert")
    case["provenance"]["seed"] = "1"
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["reject_reasons"] == {"schema": 1}


def test_an_unknown_case_key_is_schema(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    case = _case("domain-expert")
    case["note"] = "do not accept"
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b1(tmp_path)
    assert report["reject_reasons"] == {"schema": 1}
    assert "do not accept" not in json.dumps(report)


def test_the_protocol_names_every_holdout_code() -> None:
    from evidence_kernel.paths import repo_root

    text = (repo_root() / "docs" / "benchmarks" / "blind_holdout_protocol.md").read_text(
        encoding="utf-8"
    )
    codes = (
        "json",
        "unreadable",
        "schema",
        "provenance",
        "author",
        "statement",
        "expected",
        "case_id",
        "report",
        "gold_links",
        "evidence",
        "copied_dev_report",
        "document_sha256",
        "dev_document",
        "fields",
        "copied_dev_gold",
        "path_missing",
        "path_outside",
        "document_absent",
        "hash_mismatch",
        "stopped",
        "abstain_reasons",
    )
    missing = [code for code in codes if f"`{code}`" not in text]
    assert missing == []
