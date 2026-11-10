from evidence_eval.holdout_gate import REQUIRED_SENTENCE, holdout_gate


def test_cases_without_author_statement_are_rejected(tmp_path) -> None:
    (tmp_path / "case.json").write_text("{}", encoding="utf-8")
    gate = holdout_gate(tmp_path)
    assert gate["cases"] == 1
    assert gate["admissible"] is False
    assert gate["ready_for_b1"] is False


def test_author_statement_is_required_for_readiness(tmp_path) -> None:
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    for index in range(150):
        (tmp_path / f"{index}.json").write_text("{}", encoding="utf-8")
    gate = holdout_gate(tmp_path)
    assert gate["file_count_at_least_150"] is True
    assert gate["ready_for_b1"] is False


def test_b1_status_counts_a_file_without_reading_it() -> None:
    import json

    from evidence_eval.b2 import b1_status
    from evidence_kernel.paths import repo_root

    path = repo_root() / "bench" / "b1" / "expert_holdout" / "secret-case.json"
    path.write_text('{"case_id":"SECRET-CASE-BODY"}', encoding="utf-8")
    try:
        status = b1_status()
    finally:
        path.unlink()
    encoded = json.dumps(status)
    assert "SECRET-CASE-BODY" not in encoded
    assert status["expert_holdout_parsed"] is False
    assert status["expert_holdout_files"] == 1
    assert status["expert_holdout_cases"] == 0
    assert status["ready"] is False


def test_live_b1_directory_is_not_ready() -> None:
    from evidence_eval.b2 import b1_status

    status = b1_status()
    assert status["ready"] is False
    assert status["expert_holdout_cases"] == 0
    assert status["scored"] is False
