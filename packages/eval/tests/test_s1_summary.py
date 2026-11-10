from evidence_eval.s1 import SINGLE_FAULTS, public_summary, run_s1, score_exemplars, shift_gap_note


def test_small_run_reports_both_shifts_with_intervals() -> None:
    report = run_s1(limit=2)
    summary = public_summary(report)
    fault = SINGLE_FAULTS[0]
    assert summary["llm_numeric_violation"] == 0
    assert summary["seed_controls_sampling"] is False
    assert summary["expert_holdout_used"] is False
    assert summary["shift_recall"]["in_distribution"][fault] == "1/1"
    assert summary["shift_recall"]["shifted"][fault] == "1/1"
    for split in ("in_distribution", "shifted"):
        interval = summary["shift_recall_ci95"][split][fault]
        assert interval["method"] == "wilson"
        assert summary["shift_recall_ci95"][split][SINGLE_FAULTS[1]] is None
    assert summary["difficulty_recall"]["easy"] == "2/2"
    assert summary["difficulty_recall_ci95"]["easy"]["method"] == "wilson"
    assert summary["difficulty_recall_ci95"]["medium"] is None
    assert summary["difficulty_recall_ci95"]["hard"] is None


def test_exemplars_score_every_difficulty() -> None:
    summary = public_summary(score_exemplars())
    assert summary["difficulty_recall"] == {
        "easy": "4/4",
        "medium": "7/7",
        "hard": "3/3",
    }
    for level in ("easy", "medium", "hard"):
        assert summary["difficulty_recall_ci95"][level]["method"] == "wilson"
    assert summary["compound_complete_ci95"]["method"] == "wilson"
    assert summary["shift_false_alarms"]["in_distribution"] == "0/1"
    assert summary["shift_false_alarms"]["shifted"] == "0/0"
    assert summary["shift_false_alarm_ci95"]["shifted"] is None
    assert summary["shift_abstention_correctness"]["in_distribution"] is None
    assert summary["shift_abstention_correctness"]["shifted"] == "1.000"
    assert summary["shift_abstention_ci95"]["shifted"]["method"] == "wilson"


def test_exemplars_split_false_alarms_and_abstention_by_fault() -> None:
    summary = public_summary(score_exemplars())
    assert summary["false_alarm_by_fault"]["unit_scale"] == "0/13"
    assert summary["false_alarm_by_fault"]["arithmetic"] == "0/12"
    assert summary["false_alarm_by_fault"]["broken_hash"] == "0/12"
    assert summary["false_alarm_by_fault_ci95"]["sign"]["method"] == "wilson"
    assert summary["false_alarm_by_fault_rate"]["sign"] == "0.000"
    assert summary["abstention_by_fault"]["missing_input"] == "1/1"
    assert summary["abstention_by_fault_rate"]["missing_input"] == "1.000"
    assert summary["abstention_by_fault_ci95"]["missing_input"]["low"] == "0.207"
    assert summary["abstention_by_fault"]["sign"] == "0/0"
    assert summary["abstention_by_fault_ci95"]["sign"] is None


def test_equal_shift_recall_is_reported_as_no_drop() -> None:
    recalls = {fault: "1/1" for fault in ("unit_scale", "sign")}
    recalls["missing_input"] = "0/0"
    note = shift_gap_note({"shift_recall": {"in_distribution": recalls, "shifted": dict(recalls)}})
    assert "did not lower the checker" in note
