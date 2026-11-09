from evidence_eval.detect import assess
from evidence_eval.s1 import S1_COUNT, SINGLE_FAULTS, exemplars, plan_size
from evidence_kernel.schema import validate_instance


def test_s1_plan_is_one_hundred_thousand() -> None:
    assert plan_size() == S1_COUNT == 100_000
    assert len(SINGLE_FAULTS) >= 12


def test_s1_sample_schema_and_checker() -> None:
    seen: set[str] = set()
    for case in exemplars():
        validate_instance("benchmark_case.schema.json", case)
        if not case["faults"]:
            assert assess(case["artifact"])["verdict"] == "clean"
            continue
        if case["expected"] == "detect:compound":
            assessed = assess(case["artifact"])
            assert assessed["verdict"] == "detect:compound"
            assert set(assessed["faults"]) == set(case["faults"])
            continue
        fault = case["faults"][0]
        seen.add(fault)
        verdict = assess(case["artifact"])["verdict"]
        if fault == "missing_input":
            envelope = assess(case["artifact"])["envelope"]
            assert verdict == "abstain"
            assert "result" not in envelope
        else:
            assert verdict == f"detect:{fault}"
    assert seen == set(SINGLE_FAULTS)


def test_s1_missing_input_parents_omit_a_required_field() -> None:
    from evidence_calc.registry import load_card
    from evidence_eval.s1 import _single

    expected = {
        0: ("bolt_screen", "area_mm2"),
        1: ("rigid_body_point_mass", "mass_kg"),
    }
    for slot, (method_id, field) in expected.items():
        case = _single("missing_input", slot)
        artifact = case["artifact"]
        card = load_card(method_id)
        required = list(card.get("required") or card["inputs"])
        assert case["expected"] == "abstain"
        assert artifact["method_id"] == method_id
        assert field in required
        assert field not in artifact["inputs"]
        if method_id == "bolt_screen":
            assert "thickness_mm" in artifact["inputs"]
        assessed = assess(artifact)
        assert assessed["verdict"] == "abstain"
        assert "result" not in assessed["envelope"]


def test_shifted_parent_uses_the_high_mass_band() -> None:
    found = False
    for case in exemplars():
        artifact = case["artifact"]
        if artifact.get("distribution") != "shifted":
            continue
        if artifact["method_id"] != "rigid_body_point_mass":
            continue
        if artifact["inputs"]["mass_kg"] == "4500.000":
            found = True
            break
    assert found
