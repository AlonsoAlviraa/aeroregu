"""Foreign fixtures are scored without copying their prose into the report."""

import json
from pathlib import Path

from evidence_eval.ood_bench import (
    count_fields,
    ood_report,
    render_ood_audit,
    score_assurance_file,
    score_cldr_units,
    score_requirement_classes,
    score_trace_file,
)

_MARKER = "hover-foreign-marker"
_HIT = "Pack ev-1 addresses CS-27.301."


def _write_fixture(root: Path) -> None:
    (root / "cldr").mkdir()
    (root / "mobstr").mkdir()
    (root / "dosspre").mkdir()
    (root / "cldr" / "units.xml").write_text(
        "<supplementalData>"
        f"<comment>{_MARKER}</comment>"
        "<convertUnits>"
        '<convertUnit source="gram" baseUnit="kilogram" factor="0.001"/>'
        '<convertUnit source="pascal" baseUnit="kilogram-per-meter-square-second"/>'
        '<convertUnit source="widget" baseUnit="meter" factor="1"/>'
        '<convertUnit source="fahrenheit" baseUnit="kelvin" factor="5/9" offset="1"/>'
        "</convertUnits>"
        "</supplementalData>",
        encoding="utf-8",
    )
    (root / "mobstr" / "traceModel.xmi").write_text(
        '<?xml version="1.0"?>'
        '<tim:MobstrTIM xmlns:tim="urn:tim" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<traces xsi:type="tim:SpecifiedByRequirement" '
        f'name="{_MARKER}">'
        '<source href="left"/><target href="right"/>'
        "</traces>"
        "</tim:MobstrTIM>",
        encoding="utf-8",
    )
    (root / "mobstr" / "mobstr-safetycase.integration").write_text(
        '<?xml version="1.0"?>'
        '<integration_:DDIPackage xmlns:integration_="urn:i" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:argumentation_="urn:a">'
        '<argumentationElement xsi:type="argumentation_:Claim">'
        f'<value content="{_MARKER}"/>'
        "</argumentationElement>"
        "</integration_:DDIPackage>",
        encoding="utf-8",
    )
    (root / "dosspre" / "DOSSPRE-2.0Binary.csv").write_text(
        f"Project ID,Class,Requirement\n1,SR,{_MARKER}\n1,NSR,other\n",
        encoding="utf-8",
    )


def test_fixture_hides_prose_counts_a_miss_and_repeats(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    first = ood_report(tmp_path, check_pin=False)
    second = ood_report(tmp_path, check_pin=False)
    encoded = json.dumps(first)
    assert _MARKER not in encoded
    assert _MARKER not in render_ood_audit(first)
    assert _MARKER not in json.dumps(second)
    gaps = [item for item in first["datasets"] if item["scored"] == 0]
    assert gaps
    assert all(item["missing_component"] for item in gaps)
    requirement = score_requirement_classes(tmp_path / "dosspre" / "DOSSPRE-2.0Binary.csv")
    assert requirement["scored"] == 0
    assert requirement["missing_component"] == "requirement-quality classifier"
    assurance = score_assurance_file(tmp_path / "mobstr" / "mobstr-safetycase.integration")
    assert assurance["scored"] == 0
    assert assurance["missing_component"] == "assurance-case linker"
    trace = score_trace_file(tmp_path / "mobstr" / "traceModel.xmi")
    assert trace["scored"] == 0
    assert trace["missing_component"]
    assert trace["counts"]["publisher_links"] == 1
    assert trace["counts"]["comparable_links"] == 0
    assert "linker_recall" not in trace["counts"]
    hit_path = tmp_path / "hit-trace.xmi"
    hit_path.write_text(
        '<?xml version="1.0"?>'
        '<tim:MobstrTIM xmlns:tim="urn:tim">'
        '<traces name="' + _HIT + '">'
        '<source href="CS-27.301"/><target href="ev-1"/>'
        "</traces>"
        "</tim:MobstrTIM>",
        encoding="utf-8",
    )
    hit = score_trace_file(hit_path)
    assert _HIT not in json.dumps(hit)
    assert hit["counts"]["predicted_links"] >= 1
    assert hit["counts"]["gold_hits"] == 1
    assert hit["counts"]["comparable_links"] == 1
    assert hit["counts"]["linker_recall"] == "1/1"
    units = next(item for item in first["datasets"] if item["id"] == "CLDR-units")
    assert units["counts"]["agree"] == 2
    assert units["counts"]["incompatible"] == 0
    assert units["counts"]["unparsed"] == 1
    assert units["reasons"]["unparsed"]
    assert units["counts"]["offset_not_scored"] == 1
    assert units["reasons"]["offset_not_scored"]
    assert count_fields(first) == count_fields(second)
    assert count_fields(first)["datasets"]


def test_pascal_binding_agrees_without_epsilon(tmp_path: Path) -> None:
    path = tmp_path / "units.xml"
    path.write_text(
        "<supplementalData><convertUnits>"
        '<convertUnit source="pascal" baseUnit="kilogram-per-meter-square-second"/>'
        "</convertUnits></supplementalData>",
        encoding="utf-8",
    )
    report = score_cldr_units(path)
    assert report["counts"]["agree"] == 1
    assert report["counts"]["disagree"] == 0
    assert report["counts"]["incompatible"] == 0
    assert report["counts"]["unparsed"] == 0
    assert report["checker"] == "evidence_calc.units.conversion_interval"


def test_real_ood_files_when_present() -> None:
    report = ood_report()
    if not report["acquired"]:
        return
    encoded = json.dumps(report)
    assert _MARKER not in encoded
    ids = {item["id"] for item in report["datasets"]}
    assert ids.isdisjoint({"UnitSafe", "Dronology", "JCS", "NIST-SP811-B8", "QuRE"})
    assert len(report["problems"]) >= 3
    assert any(item["numeric_from_existing_checker"] for item in report["datasets"])
    assert any(item["scored"] == 0 and item["missing_component"] for item in report["datasets"])
    units = next(item for item in report["datasets"] if item["id"] == "CLDR-units")
    counts = units["counts"]
    assert counts["bad_factor"] == 0
    assert counts["offset_not_scored"] == 2
    assert (
        counts["agree"]
        + counts["disagree"]
        + counts["unparsed"]
        + counts["incompatible"]
        + counts["offset_not_scored"]
        + counts["bad_factor"]
        == counts["convert_rows"]
    )
    spelled = units["incompatible_pairs"] + units["unparsed_pairs"]
    for name in (
        "pascal",
        "nautical_mile",
        "nautical-mile",
        "astronomical_unit",
        "astronomical-unit",
        "pound_force",
        "pound-force",
        "kilogram_force",
        "kilogram-force",
    ):
        assert not any(name in pair.split("|") for pair in spelled)
    trace = next(item for item in report["datasets"] if item["id"] == "MobSTr-traces")
    assert trace["scored"] == 0
    assert trace["missing_component"]
    assert "linker_recall" not in trace["counts"]
    assert trace["counts"]["comparable_links"] == 0
    assert trace["counts"]["publisher_links"] == trace["counts"]["trace_elements"]
    assert trace["counts"]["publisher_links"] > 0
    assert "0/174" not in encoded
    assurance = next(item for item in report["datasets"] if item["id"] == "MobSTr-safetycase")
    assert assurance["scored"] == 0
    assert assurance["missing_component"] == "assurance-case linker"
    assert assurance["counts"]["argumentation_elements"] > 0
    requirement = next(item for item in report["datasets"] if item["id"] == "DOSSPRE-2.0-binary")
    assert requirement["scored"] == 0
    assert requirement["missing_component"] == "requirement-quality classifier"
    assert requirement["counts"]["rows"] == 1316
    assert requirement["class_counts"] == {"NSR": 802, "SR": 514}
    assert requirement["abstract_matches_file"] is False
    assert report["b4_ready"] is False
    assert report["certifies"] is False
    assert report["programme_complete"] is False
    assert report["expert_holdout_written_by_this_run"] is False
    again = ood_report()
    assert count_fields(report) == count_fields(again)
    text = render_ood_audit(report)
    for item in report["datasets"]:
        for value in item["counts"].values():
            assert str(value) in text
        for detail in item.get("disagree_detail") or []:
            assert (
                f"Disagree {detail['pair']} pint {detail['pint']} "
                f"published {detail['published']}."
            ) in text
        if "class_counts" in item:
            assert json.dumps(item["class_counts"], sort_keys=True) in text
