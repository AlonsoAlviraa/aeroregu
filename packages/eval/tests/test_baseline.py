from decimal import Decimal

from evidence_eval.baseline import naive_assess
from evidence_eval.generate import write_split
from evidence_eval.score import load_split, score_cases, wilson


def test_wilson_interval_covers_the_point_estimate() -> None:
    interval = wilson(0, 4)
    assert interval is not None
    assert interval["low"] == "0.000"
    assert Decimal(interval["low"]) <= Decimal(interval["high"]) <= Decimal("1")
    perfect = wilson(4, 4)
    assert perfect is not None
    assert Decimal(perfect["low"]) <= Decimal("1")
    assert perfect["high"] == "1.000"
    assert wilson(0, 0) is None


def test_naive_baseline_misses_deterministic_faults() -> None:
    write_split("dev")
    report = score_cases(load_split("dev"), assess_fn=naive_assess)
    assert report["false_alarms"] == 0
    assert report["missing_input_ok"] == report["missing_input_total"]
    assert report["llm_numeric_violation"] == 0
    for fault, value in report["deterministic_recall"].items():
        assert value == 0.0, fault
    assert report["deterministic_recall_ci95"]["unit_scale"]["method"] == "wilson"


def test_an_unrecomputed_integer_is_not_a_naive_detection() -> None:
    from evidence_eval.__main__ import _baseline_failed
    from evidence_eval.detect import assess
    from evidence_eval.faults import clean_artifact
    from evidence_eval.generate import _bolt

    dev = score_cases(load_split("dev"), assess_fn=naive_assess)
    assert dev["cases"] == 24
    for fault, value in dev["deterministic_recall"].items():
        assert value == 0.0, fault
    assert _baseline_failed(dev) is False

    artifact = clean_artifact("bolt_screen", _bolt(Decimal("3000")))
    stated = dict(artifact["stated_outputs"])
    stated["shear_stress_mpa"] = "800"
    artifact["stated_outputs"] = stated
    checker = assess(artifact)
    assert checker["verdict"] == "abstain"
    assert checker["envelope"]["abstain"]["reason"] == "unrecomputed_integer"

    case = {
        "case_id": "synthetic-unrecomputed-integer",
        "expected": "abstain",
        "artifact": artifact,
    }
    naive = score_cases([case], assess_fn=naive_assess)
    assert naive["fault_counts"] == {}
    assert naive["mismatches"] == [
        {"case_id": case["case_id"], "expected": "abstain", "got": "clean"}
    ]
    combined = score_cases(load_split("dev") + [case], assess_fn=naive_assess)
    for fault, value in combined["deterministic_recall"].items():
        assert value == 0.0, fault
    for counts in combined["fault_counts"].values():
        assert counts.startswith("0/")

    def shared_abstain(_artifact: dict) -> dict:
        return {"verdict": "abstain", "envelope": {"confidence": "abstain"}}

    shared = score_cases([case], assess_fn=shared_abstain)
    assert shared["mismatches"] == []
    assert shared["fault_counts"] == {}
    assert shared["missing_input_ok"] == shared["missing_input_total"] == 1
    assert all(value is None for value in shared["deterministic_recall"].values())
    assert _baseline_failed(shared) is False

    caught = {
        "deterministic_recall": {"arithmetic": 1.0, "unit_scale": None},
        "llm_numeric_violation": 0,
        "missing_input_total": 1,
        "missing_input_ok": 1,
        "false_alarms": 0,
    }
    assert _baseline_failed(caught) is True


def test_naive_assess_does_not_recompute(monkeypatch) -> None:
    def explode(method_id: str, inputs: dict) -> dict:
        raise AssertionError("naive baseline must not recompute")

    monkeypatch.setattr("evidence_calc.registry.run_method", explode)
    verdict = naive_assess(
        {
            "method_id": "bolt_screen",
            "inputs": {
                "shear_force_n": "3000.000",
                "tensile_force_n": "4000.000",
                "area_mm2": "80.000",
                "shear_allowable_mpa": "250.000",
                "tensile_allowable_mpa": "250.000",
                "thickness_mm": "5.000",
            },
        }
    )
    assert verdict["verdict"] == "clean"
