from evidence_eval.merge_gate import freeze_gate


def test_frozen_dev_files_allow_a_merge_and_the_programme_is_not_complete() -> None:
    gate = freeze_gate()
    assert gate["b2_dev_frozen"] is True
    assert gate["b3_dev_frozen"] is True
    assert gate["b3_second_frozen"] is True
    assert gate["b4_drill_frozen"] is True
    assert gate["unsigned_expert_cases"] is False
    assert gate["allowed"] is True
    assert gate["programme_complete"] is False
    assert gate["open_legal_rows"] > 0
    assert gate["signed_reviews"] == 0
    assert gate["single_llm_known"] is False
    assert gate["b3_single_llm_known"] is False
    assert gate["b1_scored"] is False
    assert gate["b2_holdout_scored"] is False
    assert gate["b3_holdout_scored"] is False
