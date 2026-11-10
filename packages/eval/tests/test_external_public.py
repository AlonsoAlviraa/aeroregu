"""Published datasets are scored without copying their prose into the report."""

import json
from pathlib import Path

from evidence_kernel.paths import repo_root


def test_parse_si_signature() -> None:
    from evidence_eval.external_public import parse_si_signature

    assert parse_si_signature("dimensionless") == {}
    assert parse_si_signature("M·L²·T⁻²") == {"M": 1, "L": 2, "T": -2}
    assert parse_si_signature("not a signature") is None


def test_unitsafe_rows_do_not_score_answers_or_koq() -> None:
    from evidence_eval.external_public import score_unitsafe_rows

    rows = [
        {
            "expected_error": None,
            "si_signature": "L",
            "answer": {"value": 3.5, "unit": "meter"},
            "source": {"dataset": "unitsafe"},
        },
        {
            "expected_error": "koq_mismatch",
            "si_signature": "M·L²·T⁻²",
            "answer": {"value": 0, "unit": "J"},
            "source": {"dataset": "unitsafe"},
        },
        {
            "expected_error": None,
            "si_signature": "L²·T⁻²",
            "answer": {"value": 9.9, "unit": "no-such-unit"},
            "source": {"dataset": "SciBench"},
        },
    ]
    report = score_unitsafe_rows(rows)
    encoded = json.dumps(report)
    assert "3.5" not in encoded
    assert "9.9" not in encoded
    assert report["signature_match"] == 1
    assert report["unit_unparsed"] == 1
    assert report["koq_scored"] == 0
    assert report["numeric_answers_scored"] == 0
    assert report["scibench_rows"] == 1


def test_a_reversed_dronology_pair_is_not_a_hit() -> None:
    from evidence_eval.external_public import is_gold_link

    gold = {("ev-1", "VTOL.2210")}
    assert is_gold_link("VTOL.2210", "ev-1", gold) is False
    assert is_gold_link("ev-1", "VTOL.2210", gold) is True


def test_dronology_linker_on_a_foreign_id_is_a_miss() -> None:
    from evidence_eval.external_public import score_dronology

    def write(folder: Path) -> None:
        (folder / "traces.csv").write_text("s_id,t_id,label\nRE-1,DD-1,1\n", encoding="utf-8")
        (folder / "artifacts.csv").write_text(
            "id,content,layer,summary\nRE-1,The vehicle shall hover.,Requirement,x\n",
            encoding="utf-8",
        )

    folder = repo_root() / "data" / "external" / "_fixture_dronology"
    folder.mkdir(parents=True, exist_ok=True)
    write(folder)
    try:
        report = score_dronology(folder)
    finally:
        for path in folder.glob("*.csv"):
            path.unlink()
        folder.rmdir()
    assert report["gold_positive_links"] == 1
    assert report["predicted_links"] == 0
    assert report["linker_recall"] == "0/1"
    assert report["false_alarms"] == "0/0"
    assert report["false_alarm_ci95"] is None
    assert "hover" not in json.dumps(report)


def test_acquired_public_files_match_the_pins() -> None:
    from evidence_eval.external_public import external_public_report

    report = external_public_report()
    if not report["acquired"]:
        return
    assert report["unitsafe"]["rows"] == 500
    assert report["unitsafe"]["conversion_rows"] == 376
    assert report["unitsafe"]["koq_rows"] == 62
    assert report["unitsafe"]["dimension_mismatch_rows"] == 62
    assert report["unitsafe"]["numeric_answers_scored"] == 0
    assert report["dronology"]["traces"] == 1063
    assert report["dronology"]["gold_hits"] == 0
    assert report["expert_holdout_written_by_this_run"] is False
    jcs = report.get("jcs") or {}
    if jcs.get("acquired"):
        assert jcs["mismatched"] == []
        assert set(jcs["matched"]) == {"arrays.json", "french.json", "unicode.json", "weird.json"}
        assert set(jcs["float_skipped"]) == {"structures.json", "values.json"}
        assert jcs["byte_mismatched"] == []
        assert set(jcs["byte_matched"]) == set(jcs["matched"])
    published_path = repo_root() / "docs" / "benchmarks" / "external_public_latest.json"
    published = json.loads(published_path.read_text(encoding="utf-8"))
    assert published["unitsafe"]["parsed_agreement"] == report["unitsafe"]["parsed_agreement"]
    assert published["unitsafe"]["signature_match"] == report["unitsafe"]["signature_match"]
    assert published["unitsafe"]["mismatch_detail"] == report["unitsafe"]["mismatch_detail"]
    assert sum(item["rows"] for item in report["unitsafe"]["mismatch_detail"]) == 27
    assert report["unitsafe"]["dimension_mismatch_scored"] == 0
    assert report["unitsafe"]["dimension_mismatch_signature_same"] == 14
    assert report["unitsafe"]["dimension_mismatch_signature_differ"] == 48
    assert published["unitsafe"]["dimension_mismatch_signature_same"] == 14
    assert published["unitsafe"]["koq_signature_same"] == 47
    assert published["unitsafe"]["koq_signature_differ"] == 9
    assert published["unitsafe"]["koq_signature_unparsed"] == 6
    assert published["dronology"]["linker_recall"] == report["dronology"]["linker_recall"]
    assert published["jcs"]["matched"] == report["jcs"]["matched"]
    assert published["jcs"]["byte_matched"] == report["jcs"]["byte_matched"]
    assert published["jcs"]["byte_mismatched"] == []
    nist = report.get("nist_b8") or {}
    if nist.get("acquired"):
        assert nist["rows"] == 445
        assert nist["agree"] == 105
        assert nist["disagree"] == 7
        assert published["nist_b8"]["agree"] == 105
        assert published["nist_b8"]["disagree_pairs"] == nist["disagree_pairs"]
        assert published["nist_b8"]["disagree_detail"] == nist["disagree_detail"]
        assert {item["pair"] for item in nist["disagree_detail"]} == {
            "Btu>J",
            "bbl>L",
            "kcal>J",
            "lb>kg",
        }
    qure = report.get("qure") or {}
    if qure.get("acquired"):
        assert qure["scored"] == 0
        assert qure["requirements_copied"] == 0
        assert qure["rows"] == 2187
        assert qure["defect"] == 651
        assert qure["weak_word_on_both_labels"] == 21
        assert qure["weak_word_only_on_ok"] == ["common", "comparable"]
        assert published["qure"]["weak_word_on_both_labels"] == 21
    assert published["expert_holdout_written_by_this_run"] is False


def test_qure_weak_word_is_not_the_defect_label() -> None:
    import csv

    path = repo_root() / "data" / "external" / "qure" / "QuRE.csv"
    if not path.is_file():
        return
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2187
    assert sum(row["defect"] == "defect" for row in rows) == 651
    assert sum(row["defect"] == "ok" for row in rows) == 1536
    ok_tokens = {row["weak_word"].strip() for row in rows if row["defect"] == "ok"}
    defect_tokens = {row["weak_word"].strip() for row in rows if row["defect"] == "defect"}
    assert "" not in ok_tokens
    assert "" not in defect_tokens
    assert len(ok_tokens | defect_tokens) == 23
    assert len(ok_tokens & defect_tokens) == 21
    assert ok_tokens - defect_tokens == {"common", "comparable"}
    assert defect_tokens - ok_tokens == set()
    split = (repo_root() / "docs" / "benchmarks" / "measurement_split.md").read_text(
        encoding="utf-8"
    )
    assert "23 `weak_word` tokens" in split
    assert "21 of those tokens appear on both labels" in split
    assert "`common` and `comparable` appear only on `ok`" in split
