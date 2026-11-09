"""The blind B1 command returns counts and does not echo a case."""

import json
from pathlib import Path


def test_b2_scorer_exception_does_not_include_its_message(
    tmp_path: Path, monkeypatch: object
) -> None:
    from evidence_eval.b2 import score_expert_holdout

    def boom(
        _report: str, _evidence: list[object], check_hash: bool = True
    ) -> tuple[list[object], set[object]]:
        raise RuntimeError("SECRET-B2-EXCEPTION")

    monkeypatch.setattr("evidence_eval.b2.predict", boom)  # type: ignore[attr-defined]
    case = {
        "case_id": "sealed-b2-boom",
        "report": "Pack ev-9 addresses VTOL.2210. SECRET-B2-BODY",
        "evidence": [{"id": "ev-9", "hash": "ab" * 32}],
        "gold_links": [["VTOL.2210", "ev-9"]],
        "provenance": {
            "author": "reviewing-engineer",
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in detect.py or b2.py.\n",
        encoding="utf-8",
    )
    report = score_expert_holdout(tmp_path)
    encoded = json.dumps(report)
    assert report["stopped"] == "RuntimeError"
    assert "SECRET-B2-EXCEPTION" not in encoded
    assert "SECRET-B2-BODY" not in encoded


def test_b2_and_b3_scores_do_not_open_the_repo_directory() -> None:
    import json as json_lib

    from evidence_eval.b2 import score_expert_holdout
    from evidence_eval.b3 import score_b3_holdout
    from evidence_kernel.paths import repo_root

    path = repo_root() / "bench" / "b2" / "expert_holdout" / "secret-case.json"
    path.write_text('{"report":"SECRET-B2-BODY"}', encoding="utf-8")
    try:
        report = score_expert_holdout()
        inside = score_expert_holdout(path.parent)
        b3 = score_b3_holdout()
    finally:
        path.unlink()
    encoded = json_lib.dumps({"report": report, "inside": inside, "b3": b3})
    assert report["read"] is False
    assert inside["read"] is False
    assert b3["read"] is False
    assert "SECRET-B2-BODY" not in encoded


def test_score_blind_b1_does_not_open_the_repo_directory() -> None:
    import json as json_lib

    from evidence_eval.expert_blind import score_blind_b1
    from evidence_kernel.paths import repo_root

    path = repo_root() / "bench" / "b1" / "expert_holdout" / "secret-case.json"
    path.write_text('{"case_id":"SECRET-CASE-BODY"}', encoding="utf-8")
    try:
        report = score_blind_b1()
        inside = score_blind_b1(path.parent)
    finally:
        path.unlink()
    assert report["read"] is False
    assert inside["read"] is False
    assert "SECRET-CASE-BODY" not in json_lib.dumps(report)
    assert "SECRET-CASE-BODY" not in json_lib.dumps(inside)


def test_a_scorer_exception_does_not_include_its_message(
    tmp_path: Path, monkeypatch: object
) -> None:
    from evidence_eval.expert_blind import score_blind_b1
    from evidence_eval.faults import clean_artifact

    def boom(_artifact: object) -> dict[str, object]:
        raise RuntimeError("SECRET-EXCEPTION")

    monkeypatch.setattr("evidence_eval.score.assess", boom)  # type: ignore[attr-defined]
    artifact = clean_artifact(
        "bolt_screen",
        {
            "shear_force_n": "3000.000",
            "tensile_force_n": "4000.000",
            "area_mm2": "80.000",
            "shear_allowable_mpa": "250.000",
            "tensile_allowable_mpa": "250.000",
        },
    )
    case = {
        "case_id": "sealed-boom",
        "artifact_kind": "note",
        "faults": [],
        "expected": "clean",
        "artifact": artifact,
        "provenance": {
            "origin": "owned",
            "author": "reviewing-engineer",
            "generator_version": "hand",
            "seed": 1,
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in detect.py or b2.py.\n",
        encoding="utf-8",
    )
    report = score_blind_b1(tmp_path)
    encoded = json.dumps(report)
    assert report["scored"] is False
    assert report["stopped"] == "RuntimeError"
    assert "SECRET-EXCEPTION" not in encoded


def test_a_second_read_error_does_not_include_the_file(tmp_path: Path, monkeypatch: object) -> None:
    from evidence_eval.expert_blind import score_blind_b1
    from evidence_eval.faults import clean_artifact

    artifact = clean_artifact(
        "bolt_screen",
        {
            "shear_force_n": "3000.000",
            "tensile_force_n": "4000.000",
            "area_mm2": "80.000",
            "shear_allowable_mpa": "250.000",
            "tensile_allowable_mpa": "250.000",
        },
    )
    case = {
        "case_id": "sealed-reread",
        "artifact_kind": "note",
        "faults": [],
        "expected": "clean",
        "artifact": artifact,
        "provenance": {
            "origin": "owned",
            "author": "reviewing-engineer",
            "generator_version": "hand",
            "seed": 1,
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in detect.py or b2.py.\n",
        encoding="utf-8",
    )

    def boom(_folder: Path) -> list[dict[str, object]]:
        raise json.JSONDecodeError("SECRET-LOAD", "SECRET-LOAD", 0)

    monkeypatch.setattr("evidence_eval.expert_blind._read_cases", boom)  # type: ignore[attr-defined]
    report = score_blind_b1(tmp_path)
    encoded = json.dumps(report)
    assert report["stopped"] == "JSONDecodeError"
    assert "SECRET-LOAD" not in encoded
    assert "sealed-reread" not in encoded
    assert "sealed-boom" not in encoded


def test_blind_score_hides_the_case(tmp_path: Path) -> None:
    from evidence_eval.expert_blind import score_blind_b1

    case = {
        "case_id": "sealed-case-do-not-print",
        "artifact_kind": "note",
        "faults": ["unit_scale"],
        "expected": "detect:unit_scale",
        "artifact": {"method_id": "bolt_screen"},
        "provenance": {
            "origin": "owned",
            "author": "reviewing-engineer",
            "generator_version": "hand",
            "seed": 1,
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "Reviewing engineer, 2026-11-09. I did not write the checker in detect.py or b2.py.\n",
        encoding="utf-8",
    )
    report = score_blind_b1(tmp_path)
    encoded = json.dumps(report)
    assert report["scored"] is True
    assert report["ready"] is False
    assert report["case_ids_included"] is False
    assert "sealed-case-do-not-print" not in encoded
    assert "stated_outputs" not in encoded
    assert "interaction_ratio" not in encoded


def test_b2_blind_score_hides_the_report(tmp_path: Path) -> None:
    from evidence_eval.b2 import score_expert_holdout

    case = {
        "case_id": "sealed-b2-do-not-print",
        "report": "Pack ev-9 addresses VTOL.2210. SEALED-B2-TOKEN",
        "evidence": [{"id": "ev-9", "hash": "ab" * 32}],
        "gold_links": [["VTOL.2210", "ev-9"]],
        "provenance": {
            "author": "reviewing-engineer",
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in detect.py or b2.py.\n",
        encoding="utf-8",
    )
    report = score_expert_holdout(tmp_path)
    encoded = json.dumps(report)
    assert report["scored"] is True
    assert report["judge_correct"] == "1/1"
    assert "SEALED-B2-TOKEN" not in encoded
    assert "sealed-b2-do-not-print" not in encoded


def test_b3_blind_score_hides_the_document(tmp_path: Path) -> None:
    import hashlib

    from evidence_eval.b3 import score_b3_holdout

    document = tmp_path / "note.txt"
    document.write_text("SEALED-B3-TOKEN span count 17 blades\n", encoding="utf-8")
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    case = {
        "case_id": "sealed-b3-do-not-print",
        "document_sha256": digest,
        "document_path": "note.txt",
        "fields": [{"name": "span_count", "value_text": "17", "unit_text": "1"}],
        "provenance": {
            "author": "reviewing-engineer",
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in b3.py.\n",
        encoding="utf-8",
    )
    report = score_b3_holdout(tmp_path)
    encoded = json.dumps(report)
    assert report["scored"] is True
    assert report["judge_correct"] == "1/1"
    assert "SEALED-B3-TOKEN" not in encoded
    assert "sealed-b3-do-not-print" not in encoded


def test_an_in_repo_expert_dir_is_not_read(monkeypatch: object, capsys: object) -> None:
    from evidence_eval.__main__ import main
    from evidence_kernel.paths import repo_root

    inside = repo_root() / "bench" / "b1" / "expert_holdout"
    monkeypatch.setenv("B1_EXPERT_DIR", str(inside))  # type: ignore[attr-defined]
    code = main(["validate-b1"])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert code == 2
    assert json.loads(out)["read"] is False
    assert json.loads(out)["outside_repo"] is False


def test_blind_commands_do_not_read_the_repo_when_unset(
    monkeypatch: object, capsys: object
) -> None:
    from evidence_eval.__main__ import main

    monkeypatch.delenv("B1_EXPERT_DIR", raising=False)  # type: ignore[attr-defined]
    code = main(["validate-b1"])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert code == 2
    assert json.loads(out) == {"variable": "B1_EXPERT_DIR", "set": False, "read": False}


def test_a_blind_command_exception_does_not_echo_the_message(
    tmp_path: Path, monkeypatch: object, capsys: object
) -> None:
    from evidence_eval.__main__ import main

    def boom(_folder: Path) -> dict[str, object]:
        raise RuntimeError("SECRET-CLI")

    monkeypatch.setattr("evidence_eval.expert_blind.score_blind_b1", boom)  # type: ignore[attr-defined]
    monkeypatch.setenv("B1_EXPERT_DIR", str(tmp_path))  # type: ignore[attr-defined]
    code = main(["score-blind-b1"])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 2
    assert "SECRET-CLI" not in captured.out
    assert "SECRET-CLI" not in captured.err
    assert json.loads(captured.out)["stopped"] == "RuntimeError"


def test_blind_score_keeps_recall_for_a_fault_outside_the_fixed_list(tmp_path: Path) -> None:
    from evidence_eval.expert_blind import score_blind_b1
    from evidence_eval.faults import clean_artifact

    artifact = clean_artifact(
        "bolt_screen",
        {
            "shear_force_n": "3000.000",
            "tensile_force_n": "4000.000",
            "area_mm2": "80.000",
            "shear_allowable_mpa": "250.000",
            "tensile_allowable_mpa": "250.000",
        },
    )
    case = {
        "case_id": "sealed-bad-citation",
        "artifact_kind": "note",
        "faults": ["bad_citation"],
        "expected": "detect:bad_citation",
        "artifact": artifact,
        "provenance": {
            "origin": "owned",
            "author": "reviewing-engineer",
            "generator_version": "hand",
            "seed": 1,
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in detect.py or b2.py.\n",
        encoding="utf-8",
    )
    report = score_blind_b1(tmp_path)
    encoded = json.dumps(report)
    assert report["fault_recall"]["bad_citation"] == "0.000"
    assert report["fault_counts"]["bad_citation"] == "0/1"
    assert "sealed-bad-citation" not in encoded
    assert "bad_citation" not in report["deterministic_recall"]


def test_protocol_case_without_coverage_fields_stays_clean() -> None:
    from evidence_eval.detect import assess
    from evidence_eval.faults import clean_artifact

    artifact = clean_artifact(
        "bolt_screen",
        {
            "shear_force_n": "3000.000",
            "tensile_force_n": "4000.000",
            "area_mm2": "80.000",
            "shear_allowable_mpa": "250.000",
            "tensile_allowable_mpa": "250.000",
        },
    )
    artifact.pop("coverage_status")
    artifact.pop("coverage_evidence_hash")
    assert assess(artifact)["verdict"] == "clean"


def test_protocol_rigid_body_inputs_score_clean() -> None:
    from evidence_eval.detect import assess
    from evidence_eval.faults import clean_artifact

    artifact = clean_artifact(
        "rigid_body_point_mass",
        {
            "mass_kg": "800.000",
            "gravity_m_s2": "9.810",
            "load_factor": "1.500",
            "cg_x_m": "0.000",
            "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
            "unit_operative": [True, True, True, True],
        },
    )
    stated = artifact["stated_outputs"]
    assert list(stated) == [
        "weight_n",
        "required_vertical_force_n",
        "unit_force_n",
        "vertical_residual_n",
        "moment_about_cg_n_m",
    ]
    assert len(stated["unit_force_n"]) == 4
    assert assess(artifact)["verdict"] == "clean"


def test_a_missing_output_key_is_not_clean() -> None:
    from evidence_eval.detect import assess
    from evidence_eval.faults import clean_artifact

    artifact = clean_artifact(
        "bolt_screen",
        {
            "shear_force_n": "3000.000",
            "tensile_force_n": "4000.000",
            "area_mm2": "80.000",
            "shear_allowable_mpa": "250.000",
            "tensile_allowable_mpa": "250.000",
        },
    )
    artifact["stated_outputs"].pop("interaction_ratio")
    assert assess(artifact)["verdict"] != "clean"


def test_protocol_clean_case_scores_without_printing_the_output(tmp_path: Path) -> None:
    from evidence_eval.expert_blind import score_blind_b1
    from evidence_eval.faults import clean_artifact

    artifact = clean_artifact(
        "bolt_screen",
        {
            "shear_force_n": "3000.000",
            "tensile_force_n": "4000.000",
            "area_mm2": "80.000",
            "shear_allowable_mpa": "250.000",
            "tensile_allowable_mpa": "250.000",
        },
    )
    hidden = artifact["stated_outputs"]["interaction_ratio"]
    case = {
        "case_id": "protocol-clean",
        "artifact_kind": "note",
        "faults": [],
        "expected": "clean",
        "artifact": artifact,
        "provenance": {
            "origin": "owned",
            "author": "reviewing-engineer",
            "generator_version": "hand",
            "seed": 1,
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in detect.py or b2.py.\n",
        encoding="utf-8",
    )
    report = score_blind_b1(tmp_path)
    encoded = json.dumps(report)
    assert report["scored"] is True
    assert report["false_alarms"] == 0
    assert hidden not in encoded
    assert "protocol-clean" not in encoded


def test_hash_inputs_at_artifact_inputs_ignores_the_rest(tmp_path: Path, capsys: object) -> None:
    from evidence_eval.__main__ import main
    from evidence_kernel.canonical import inputs_hash

    inputs = {"shear_force_n": "1.000"}
    case = {
        "case_id": "sealed-case",
        "artifact": {"inputs": inputs, "stated_outputs": {"hidden": "SEALED-OUTPUT-TOKEN"}},
    }
    path = tmp_path / "case.json"
    path.write_text(json.dumps(case), encoding="utf-8")
    code = main(["hash-inputs", str(path), "--at", "artifact.inputs"])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert code == 0
    assert out.strip() == inputs_hash(inputs)
    assert "SEALED-OUTPUT-TOKEN" not in out
    assert "sealed-case" not in out


def test_hash_file_prints_only_the_digest(tmp_path: Path, capsys: object) -> None:
    import hashlib

    from evidence_eval.__main__ import main

    path = tmp_path / "note.txt"
    path.write_bytes(b"SEALED-FILE-TOKEN")
    code = main(["hash-file", str(path)])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert code == 0
    assert out.strip() == hashlib.sha256(b"SEALED-FILE-TOKEN").hexdigest()
    assert "SEALED-FILE-TOKEN" not in out


def test_hash_inputs_prints_only_the_digest(tmp_path: Path, capsys: object) -> None:
    from evidence_eval.__main__ import main

    path = tmp_path / "inputs.json"
    path.write_text('{"sealed":"SEALED-INPUT-HASH"}', encoding="utf-8")
    code = main(["hash-inputs", str(path)])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert code == 0
    assert "SEALED-INPUT-HASH" not in out
    assert len(out.strip()) == 64


def test_unknown_method_abstains_and_the_blind_report_hides_inputs(tmp_path: Path) -> None:
    from evidence_eval.detect import assess
    from evidence_eval.expert_blind import score_blind_b1

    assessed = assess({"method_id": "not-a-method", "inputs": {}})
    assert assessed["verdict"] == "abstain"
    case = {
        "case_id": "sealed-unknown-method",
        "artifact_kind": "note",
        "faults": ["missing_input"],
        "expected": "abstain",
        "artifact": {
            "method_id": "not-a-method",
            "inputs": {"sealed_input": "SEALED-INPUT-TOKEN"},
        },
        "provenance": {
            "origin": "owned",
            "author": "reviewing-engineer",
            "generator_version": "hand",
            "seed": 1,
            "statement": "Hand written. No employer material.",
        },
    }
    (tmp_path / "one.json").write_text(json.dumps(case), encoding="utf-8")
    (tmp_path / "AUTHOR.md").write_text(
        "I did not write the checker in detect.py or b2.py.\n",
        encoding="utf-8",
    )
    report = score_blind_b1(tmp_path)
    encoded = json.dumps(report)
    assert report["scored"] is True
    assert "SEALED-INPUT-TOKEN" not in encoded
    assert "sealed-unknown-method" not in encoded


def test_expert_tree_hash_hides_names_and_text(tmp_path: Path) -> None:
    from evidence_eval.expert_blind import expert_tree_hash

    secret = tmp_path / "SEALED-NAME-TOKEN.json"
    secret.write_text('{"note":"SEALED-BODY-TOKEN"}', encoding="utf-8")
    report = expert_tree_hash(tmp_path)
    encoded = json.dumps(report)
    assert report["files"] == 1
    assert "SEALED-NAME-TOKEN" not in encoded
    assert "SEALED-BODY-TOKEN" not in encoded
    secret.write_text('{"note":"changed"}', encoding="utf-8")
    assert expert_tree_hash(tmp_path)["sha256"] != report["sha256"]


def test_blind_score_refuses_without_the_author_sentence(tmp_path: Path) -> None:
    from evidence_eval.expert_blind import score_blind_b1

    (tmp_path / "one.json").write_text("{}", encoding="utf-8")
    report = score_blind_b1(tmp_path)
    assert report["scored"] is False
