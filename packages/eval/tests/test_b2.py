from evidence_eval.b2 import b1_status, judged_match, predict, score_b2


def test_dev_cases_use_only_seen_headings() -> None:
    from evidence_eval.b2 import PUBLIC_HEADINGS, dev_cases

    for case in dev_cases():
        for requirement_id, _evidence_id in case["gold_links"]:
            assert requirement_id in PUBLIC_HEADINGS
        for claim in case["false_claims"]:
            assert claim["requirement_id"] in PUBLIC_HEADINGS


def test_an_unseen_identifier_is_not_linked() -> None:
    links, flags = predict(
        "Pack ev-1 addresses VTOL.9999 with a stored hash.",
        [{"id": "ev-1", "hash": "ab" * 32}],
    )
    assert links == []
    assert flags == set()


def test_b2_dev_links_and_false_coverage() -> None:
    report = score_b2()
    assert report["beats_no_agent"] is False
    assert report["public_headings_only"] is True
    assert report["beats_hash_blind"] is True
    assert report["beats_single_llm"] == "NOT_VERIFIED"
    assert report["expert_holdout_cases"] == 0
    assert report["expert_holdout_ready"] is False
    assert report["expert_holdout_score"]["scored"] is False
    assert report["verifier"]["recall"] == "1.000"
    assert report["verifier"]["precision"] == "1.000"
    assert report["hash_blind"]["precision"] == "0.750"
    assert report["verifier"]["false_coverage_recall"] == "1.000"
    assert report["hash_blind"]["false_coverage_recall"] == "0.000"
    assert report["verifier"]["span_accuracy"] == "1.000"
    assert report["verifier"]["judge_correct"] == "8/8"
    assert report["hash_blind"]["judge_correct"] == "6/8"
    assert report["agent_chain"]["judge_correct"] == "8/8"
    assert report["agent_chain"]["judge_ci95"]["low"] == "0.676"
    assert report["agent_chain"]["judge_ci95"]["high"] == "1.000"
    assert report["agent_chain"]["link_recall"] == "6/6"
    assert report["agent_chain"]["false_coverage_recall"] == "2/2"
    assert report["agent_chain"]["false_alarms"] == "0/6"
    assert report["agent_chain"]["abstentions"] == 0
    assert report["agent_chain"]["llm_numeric_violation"] == 0
    assert "span probe" in report["agent_chain"]["note"]
    notes = " ".join(report["notes"])
    assert "CS 27.301 Loads" in notes
    assert "VTOL.2225" in notes
    assert "not copied" in notes
    probe = report["span_probe"]
    assert probe["frozen_set"] is False
    assert probe["verifier_links"] is True
    assert probe["chain_abstains"] is True
    assert probe["event_type"] == "abstain"
    assert len(probe["event_hash"]) == 64


def test_an_empty_b2_holdout_file_is_rejected(tmp_path) -> None:
    from evidence_eval.b2 import validate_b2_holdout
    from evidence_eval.holdout_gate import REQUIRED_SENTENCE

    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text("{}", encoding="utf-8")
    report = validate_b2_holdout(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 1
    assert report["ready"] is False
    assert report["scored"] is False


def test_a_complete_b2_holdout_case_is_valid_and_not_scored(tmp_path) -> None:
    import json

    from evidence_eval.b2 import validate_b2_holdout
    from evidence_eval.holdout_gate import REQUIRED_SENTENCE

    case = {
        "case_id": "expert-b2-1",
        "report": "Pack ev-9 addresses VTOL.2210 with a stored hash.",
        "gold_links": [["VTOL.2210", "ev-9"]],
        "provenance": {
            "author": "domain-expert",
            "statement": "No employer material.",
        },
    }
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b2_holdout(tmp_path)
    assert report["valid"] == 1
    assert report["rejected"] == 0
    assert report["ready"] is True
    assert report["scored"] is False


def test_a_holdout_case_with_a_hash_can_be_scored(tmp_path) -> None:
    import json

    from evidence_eval.b2 import score_expert_holdout
    from evidence_eval.holdout_gate import REQUIRED_SENTENCE

    case = {
        "case_id": "expert-b2-hashed",
        "report": "Pack ev-9 addresses VTOL.2210 with a stored hash.",
        "gold_links": [["VTOL.2210", "ev-9"]],
        "evidence": [{"id": "ev-9", "hash": "ab" * 32}],
        "provenance": {
            "author": "domain-expert",
            "statement": "No employer material.",
        },
    }
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    scored = score_expert_holdout(tmp_path)
    assert scored["scored"] is True
    assert scored["judge_correct"] == "1/1"
    assert scored["abstained"] == 0
    assert scored["judge_ci95"]["method"] == "wilson"
    assert scored["false_alarms"] == "0/1"
    assert scored["abstentions_correct"] == "0/0"
    assert scored["llm_numeric_violation"] == 0


def test_an_empty_evidence_list_abstains_when_there_is_no_gold_link(tmp_path) -> None:
    import json

    from evidence_eval.b2 import score_expert_holdout
    from evidence_eval.holdout_gate import REQUIRED_SENTENCE

    case = {
        "case_id": "expert-b2-empty",
        "report": "Pack ev-9 names no requirement.",
        "gold_links": [],
        "evidence": [],
        "provenance": {
            "author": "domain-expert",
            "statement": "No employer material.",
        },
    }
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    scored = score_expert_holdout(tmp_path)
    assert scored["scored"] is False
    assert scored["abstained"] == 1
    assert scored["abstentions_correct"] == "1/1"
    assert scored["abstention_ci95"]["method"] == "wilson"
    assert scored["false_alarms"] == "0/0"
    assert scored["llm_numeric_violation"] == 0


def test_a_b2_case_without_the_employer_phrase_is_rejected(tmp_path) -> None:
    import json

    from evidence_eval.b2 import validate_b2_holdout
    from evidence_eval.holdout_gate import REQUIRED_SENTENCE

    case = {
        "case_id": "expert-b2-1",
        "report": "Pack ev-9 addresses VTOL.2210 with a stored hash.",
        "gold_links": [["VTOL.2210", "ev-9"]],
        "provenance": {"author": "domain-expert", "statement": "Written for this set."},
    }
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b2_holdout(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 1
    assert report["ready"] is False
    assert report["reject_reasons"] == {"statement": 1}
    assert "expert-b2-1" not in json.dumps(report)


def test_a_dev_report_is_rejected_as_holdout(tmp_path) -> None:
    import json

    from evidence_eval.b2 import dev_cases, validate_b2_holdout
    from evidence_eval.holdout_gate import REQUIRED_SENTENCE

    case = {
        "case_id": "expert-b2-copy",
        "report": dev_cases()[0]["report"],
        "gold_links": [["VTOL.2210", "ev-1"]],
        "provenance": {
            "author": "domain-expert",
            "statement": "No employer material.",
        },
    }
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b2_holdout(tmp_path)
    assert report["valid"] == 0
    assert report["rejected"] == 1
    assert report["scored"] is False


def test_judge_rejects_a_reasoning_field() -> None:
    links = [
        {
            "requirement_id": "VTOL.2210",
            "evidence_id": "ev-1",
            "span_start": 0,
            "span_end": 10,
            "reasoning": "because the model said so",
        }
    ]
    assert judged_match("b2-dev-true-00", links, [("VTOL.2210", "ev-1")]) is False


def test_a_flat_gold_link_is_rejected(tmp_path) -> None:
    import json

    from evidence_eval.b2 import validate_b2_holdout
    from evidence_eval.holdout_gate import REQUIRED_SENTENCE

    case = {
        "case_id": "expert-b2-flat-link",
        "report": "Pack ev-9 addresses VTOL.2210.",
        "gold_links": ["SECRET-HEADING", "ev-9"],
        "evidence": [{"id": "ev-9", "hash": "ab" * 32}],
        "provenance": {"author": "domain-expert", "statement": "No employer material."},
    }
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b2_holdout(tmp_path)
    assert report["reject_reasons"] == {"gold_links": 1}
    assert "SECRET-HEADING" not in json.dumps(report)


def test_a_string_evidence_item_is_rejected(tmp_path) -> None:
    import json

    from evidence_eval.b2 import validate_b2_holdout
    from evidence_eval.holdout_gate import REQUIRED_SENTENCE

    case = {
        "case_id": "expert-b2-bad-evidence",
        "report": "Pack SECRET-EV addresses VTOL.2210.",
        "gold_links": [["VTOL.2210", "ev-9"]],
        "evidence": ["SECRET-EV"],
        "provenance": {"author": "domain-expert", "statement": "No employer material."},
    }
    (tmp_path / "AUTHOR.md").write_text(REQUIRED_SENTENCE + "\n", encoding="utf-8")
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    report = validate_b2_holdout(tmp_path)
    assert report["reject_reasons"] == {"evidence": 1}
    assert "SECRET-EV" not in json.dumps(report)


def test_zero_hash_is_not_a_link() -> None:
    report = "Pack ev-9 claims VTOL.2210 without a real hash."
    links, flags = predict(report, [{"id": "ev-9", "hash": "0" * 64}])
    assert links == []
    assert ("VTOL.2210", "ev-9") in flags


def test_a_missing_hash_still_links() -> None:
    links, flags = predict("Pack ev-9 addresses VTOL.2210.", [{"id": "ev-9"}])
    assert [link["requirement_id"] for link in links] == ["VTOL.2210"]
    assert flags == set()


def test_b1_expert_set_is_not_ready() -> None:
    status = b1_status()
    assert status["ready"] is False
    assert status["expert_holdout_cases"] == 0
    assert status["fault_types"] == 0
    assert status["scored"] is False
