from evidence_eval.detect import llm_numeric_violations
from evidence_eval.generate import write_split
from evidence_eval.score import assert_holdout_frozen, load_split, score_cases
from evidence_kernel.paths import repo_root


def test_bolt_missing_input_omits_a_required_area() -> None:
    from decimal import Decimal

    from evidence_eval.detect import assess
    from evidence_eval.faults import clean_artifact, inject
    from evidence_eval.generate import _bolt

    artifact = clean_artifact("bolt_screen", _bolt(Decimal("3000")))
    mutated = inject("missing_input", artifact, 0)
    assert "area_mm2" not in mutated["inputs"]
    assessed = assess(mutated)
    assert assessed["verdict"] == "abstain"
    assert "result" not in assessed["envelope"]


def test_dev_deterministic_recall_is_one() -> None:
    write_split("dev")
    write_split("holdout")
    report = score_cases(load_split("dev"))
    assert report["mismatches"] == []
    for fault, value in report["deterministic_recall"].items():
        assert value == 1.0, fault
    for fault, value in report["trace_recall"].items():
        assert value == 1.0, fault
    assert report["false_alarms"] == 0
    assert report["missing_input_total"] >= 2
    assert report["missing_input_ok"] == report["missing_input_total"]
    assert report["llm_numeric_violation"] == 0
    for fault, value in report["false_alarm_by_fault"].items():
        assert value == "0/22", fault
        assert report["false_alarm_by_fault_ci95"][fault]["method"] == "wilson"
    assert report["abstention_by_fault"]["missing_input"] == "2/2"
    assert report["abstention_by_fault_ci95"]["missing_input"]["method"] == "wilson"
    assert report["abstention_by_fault"]["unit_scale"] == "0/0"
    assert report["abstention_by_fault_ci95"]["unit_scale"] is None
    assert report["note"] == "Same-author split. Not the expert holdout."
    for case in load_split("dev"):
        if case["expected"] != "abstain":
            continue
        assessed_ok = "result" not in score_cases([case]) or True
        del assessed_ok
    from evidence_eval.detect import assess

    for case in load_split("dev"):
        if case["expected"] != "abstain":
            continue
        envelope = assess(case["artifact"])["envelope"]
        assert "result" not in envelope
        assert envelope["confidence"] == "abstain"


def test_holdout_is_frozen_and_not_scored() -> None:
    write_split("holdout")
    assert_holdout_frozen()
    detector_path = repo_root() / "packages" / "eval" / "src" / "evidence_eval" / "detect.py"
    detector = detector_path.read_text(encoding="utf-8")
    assert "case_id" not in detector
    assert "holdout" not in detector
    from evidence_eval.__main__ import main

    assert main(["score", "--split", "holdout"]) == 2


def test_an_unrecomputed_integer_abstains_instead_of_a_detection() -> None:
    from decimal import Decimal

    from evidence_eval.detect import assess
    from evidence_eval.faults import clean_artifact, inject
    from evidence_eval.generate import _bolt

    artifact = clean_artifact("bolt_screen", _bolt(Decimal("3000")))
    stated = dict(artifact["stated_outputs"])
    stated["shear_stress_mpa"] = "800"
    artifact["stated_outputs"] = stated
    assessed = assess(artifact)
    assert assessed["verdict"] == "abstain"
    assert assessed["envelope"]["confidence"] == "abstain"
    assert assessed["envelope"]["abstain"]["reason"] == "unrecomputed_integer"
    assert "result" not in assessed["envelope"]
    scaled = inject("unit_scale", clean_artifact("bolt_screen", _bolt(Decimal("3"))), 0)
    assert assess(scaled)["verdict"] == "detect:unit_scale"


def test_an_integer_in_an_agent_turn_fails_the_bench_gate() -> None:
    from evidence_eval.__main__ import _checker_failed

    case = {
        "artifact": {
            "method_id": "bolt_screen",
            "inputs": {
                "shear_force_n": "3000.000",
                "tensile_force_n": "4000.000",
                "area_mm2": "80.000",
                "shear_allowable_mpa": "250.000",
                "tensile_allowable_mpa": "250.000",
            },
        },
        "agent_turns": [{"output": {"note": "The load is 800 N."}}],
    }
    assert llm_numeric_violations(case) == 1
    report = {
        "deterministic_recall": {"arithmetic": 1.0},
        "trace_recall": {},
        "llm_numeric_violation": llm_numeric_violations(case),
        "missing_input_total": 0,
        "missing_input_ok": 0,
        "false_alarms": 0,
    }
    assert _checker_failed(report) is True


def test_llm_numeric_violation_is_counted() -> None:
    case = {
        "artifact": {
            "method_id": "bolt_screen",
            "inputs": {
                "shear_force_n": "3000.000",
                "tensile_force_n": "4000.000",
                "area_mm2": "80.000",
                "shear_allowable_mpa": "250.000",
                "tensile_allowable_mpa": "250.000",
                "thickness_mm": "5.000",
            },
        },
        "agent_turns": [{"output": {"note": "9.999"}}],
    }
    assert llm_numeric_violations(case) == 1


def test_trace_recall_below_one_fails_the_bench_gate() -> None:
    from evidence_eval.__main__ import _checker_failed

    report = {
        "deterministic_recall": {"arithmetic": 1.0},
        "trace_recall": {"broken_hash": 0.0},
        "llm_numeric_violation": 0,
        "missing_input_total": 0,
        "missing_input_ok": 0,
        "false_alarms": 0,
    }
    assert _checker_failed(report) is True


def test_an_absent_trace_fault_does_not_fail_the_bench_gate() -> None:
    from evidence_eval.__main__ import _checker_failed

    report = {
        "deterministic_recall": {"arithmetic": 1.0},
        "trace_recall": {"bad_span": None},
        "llm_numeric_violation": 0,
        "missing_input_total": 0,
        "missing_input_ok": 0,
        "false_alarms": 0,
    }
    assert _checker_failed(report) is False


def _gate_report(deterministic: dict, trace: dict | None = None) -> dict:
    return {
        "deterministic_recall": deterministic,
        "trace_recall": {} if trace is None else trace,
        "llm_numeric_violation": 0,
        "missing_input_total": 0,
        "missing_input_ok": 0,
        "false_alarms": 0,
    }


def test_present_fault_recall_zero_fails_and_empty_recall_does_not() -> None:
    from evidence_eval.__main__ import _checker_failed

    assert _checker_failed(_gate_report({"arithmetic": 0.0})) is True
    assert _checker_failed(_gate_report({"arithmetic": 0.0, "unit_scale": None})) is True
    assert _checker_failed(_gate_report({"arithmetic": 1.0}, {"broken_hash": 0.0})) is True
    assert _checker_failed(_gate_report({"arithmetic": 1.0, "unit_scale": None})) is False
    assert _checker_failed(_gate_report({"arithmetic": 1.0})) is False
    assert _checker_failed(_gate_report({"arithmetic": 1.0}, {"bad_span": None})) is False
