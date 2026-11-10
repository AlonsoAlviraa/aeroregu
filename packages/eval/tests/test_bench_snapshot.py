from evidence_eval.bench_snapshot import write_bench_snapshot


def test_snapshot_keeps_the_b3_page_map(tmp_path):
    path = write_bench_snapshot(
        {
            "b1": {"ready": False, "expert_holdout_cases": 0},
            "b2": {
                "beats_no_agent": False,
                "beats_single_llm": "NOT_VERIFIED",
                "span_probe": {"verifier_links": True, "chain_abstains": True},
            },
            "b3": {
                "fields_correct": "8/8",
                "field_accuracy_ci95": {"low": "0.676", "high": "1.000"},
                "page_limited_fields_correct": "2/8",
                "page_limited_ci95": {"low": "0.071", "high": "0.591"},
                "no_agent_fields_correct": "0/8",
                "no_agent_ci95": {"low": "0.000", "high": "0.324"},
                "beats_no_agent": True,
                "page_limited_misses": ["strain_gage_count"],
                "field_pages": {"blade_count": 2, "strain_gage_count": 7},
                "beats_single_llm": "NOT_VERIFIED",
                "load_factor_column_abstained": True,
                "load_factor_abstain_hash": "a" * 64,
            },
            "b3_second": {
                "fields_correct": "3/3",
                "page_limited_fields_correct": "0/3",
                "field_accuracy_ci95": {"low": "0.438", "high": "1.000"},
                "event_hashes": ["a" * 64, "b" * 64, "c" * 64],
                "shared_with_first_memo": ["V3101"],
                "absent_from_second_memo": ["V3109"],
                "flight_table_column_abstained": True,
            },
            "b4": {
                "ready": False,
                "public_archive": {
                    "abstain_reason": "unit_not_in_file",
                    "sensor_range_applied": False,
                },
            },
            "quarantine_duplicate_citation": {"recall": "0/1", "system_verdict": "abstain"},
            "programme": {
                "programme_complete": False,
                "open_legal_rows": 5,
                "signed_reviews": 0,
                "single_llm_known": False,
                "b3_second_frozen": True,
                "b4_drill_frozen": True,
            },
            "s1": {
                "cases": 100000,
                "checker_recall": {"sign": "1/1"},
                "checker_recall_ci95": {"sign": {"low": "0.207", "high": "1.000"}},
                "naive_recall": {"sign": "0/1"},
                "false_alarm_rate": "0.000",
                "false_alarm_rate_ci95": {"low": "0.000", "high": "0.000"},
                "abstention_correctness": "1.000",
                "abstention_correctness_ci95": {"low": "0.999", "high": "1.000"},
                "difficulty_recall": {"easy": "1/1"},
                "difficulty_recall_ci95": {"easy": {"low": "0.207", "high": "1.000"}},
                "shift_recall": {
                    "in_distribution": {"sign": "1/1"},
                    "shifted": {"sign": "1/1"},
                },
                "shift_recall_ci95": {
                    "shifted": {"sign": {"low": "0.207", "high": "1.000"}},
                },
                "compound_complete": "1.000",
            },
        },
        note="ESTIMATE: test fixture.",
        folder=tmp_path,
    )
    text = path.read_text(encoding="utf-8")
    assert '"blade_count": 2' in text
    brief = (tmp_path / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "B3 ready: None. dev_pdf_scored: None." in brief
    assert "strain_gage_count" in brief
    assert "B2 public headings only: None." in brief
    assert "NOT VERIFIED" in brief
    assert "unit_not_in_file" in brief
    assert "0.676 to 1.000" in brief
    assert "trivial" in brief
    assert "S1 sign: checker 1/1, naive 0/1" in brief
    assert "did not lower the checker" in brief
    assert "S1 shifted sign: 1/1. Wilson 95% 0.207 to 1.000." in brief
    assert "S1 easy: 1/1" in brief
    assert "B3 second memorandum: 3/3" in brief
    assert "Ledger events: 3" in brief
    assert "V3101" in brief
    assert "V3109" in brief
    assert "chain abstains True" in brief
    assert "Programme complete: False" in brief
    assert "Dev false alarms by fault: absent." in brief
    assert "Drill frozen: True" in brief
    assert "Flight-table column abstained: True" in brief
    assert "Unit abstains: 0" in brief
    assert "Sensor range applied: False" in brief
    assert "load-factor column abstained" in brief


def test_a_missing_second_pdf_is_not_scored(tmp_path):
    write_bench_snapshot(
        {"b3_second": {"pdf_present": False, "scored": False, "label": "NOT_VERIFIED"}},
        note="ESTIMATE: test fixture.",
        folder=tmp_path,
    )
    brief = (tmp_path / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "not on disk" in brief
    assert "Not scored" in brief
    assert "NOT_VERIFIED" in brief
    assert "5/5" not in brief


def test_absent_nasa_pdfs_and_b4_series_are_not_scored(tmp_path):
    path = write_bench_snapshot(
        {
            "b3": {
                "ready": False,
                "pdf_present": False,
                "label": "NOT_VERIFIED",
                "note": "Local PDF is absent. The NTRS record was read; the file was not scored.",
            },
            "b3_second": {
                "pdf_present": False,
                "scored": False,
                "label": "NOT_VERIFIED",
            },
            "b3_quotes": {"ready": False, "label": "NOT_VERIFIED", "matched": "0/0"},
            "b4": {
                "ready": False,
                "label": "NOT_VERIFIED",
                "public_archive": None,
                "as365": {
                    "file_present": False,
                    "scored": False,
                    "samples_counted": False,
                    "label": "NOT_VERIFIED",
                },
                "in_file_probe": {"public_result": False, "consulted_for_ready": False},
            },
        },
        note="ESTIMATE: test fixture. Public files are absent.",
        folder=tmp_path,
    )
    assert path.parent == tmp_path
    brief = (tmp_path / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "B3: not scored. NOT_VERIFIED." in brief
    assert "B3 second memorandum: not on disk. Not scored. NOT_VERIFIED." in brief
    assert "B4: not scored. NOT_VERIFIED." in brief
    assert "B4 AS365: not on disk. Not scored. NOT_VERIFIED." in brief
    assert "B3 ready: False." in brief
    assert "B4 ready: False." in brief
    assert "B3 fields: None" not in brief
    assert "B3 load-factor column: not abstained." not in brief
    assert "dev_pdf_scored: None" not in brief
    assert "B4 abstain: None" not in brief
    assert "Sensor range applied: None" not in brief
    assert "0/0" not in brief
    assert "8/8" not in brief
    assert "5/5" not in brief


def test_inspected_files_keep_field_scores_and_abstain_reasons(tmp_path):
    write_bench_snapshot(
        {
            "b3": {
                "ready": False,
                "pdf_present": True,
                "dev_pdf_scored": True,
                "fields_correct": "8/8",
                "field_accuracy_ci95": {"low": "0.676", "high": "1.000"},
            },
            "b4": {
                "ready": False,
                "public_archive": {
                    "scored": False,
                    "abstain_reason": "unit_not_in_file",
                    "sensor_range_applied": False,
                },
                "as365": {
                    "file_present": True,
                    "hash_match": True,
                    "scored": False,
                    "ordinate_unit": "m/s^2",
                    "record_count": 3,
                    "structure_matches": True,
                    "step_matches_8192_hz": True,
                    "duration_matches_paper_60s": False,
                    "length_abstain_reason": "record_length_disagrees",
                    "abstain_reason": "limit_not_in_file",
                },
            },
        },
        note="ESTIMATE: inspected files.",
        folder=tmp_path,
    )
    brief = (tmp_path / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "B3 ready: False. dev_pdf_scored: True." in brief
    assert "B3 fields: 8/8." in brief
    assert "B3: not scored. NOT_VERIFIED." not in brief
    assert "unit_not_in_file" in brief
    assert "limit_not_in_file" in brief
    assert "record_length_disagrees" in brief
    assert "Sensor range applied: False" in brief
    assert "B4: not scored. NOT_VERIFIED." not in brief
    assert "B4 AS365: not on disk" not in brief

    kept = tmp_path / "fields_kept"
    write_bench_snapshot(
        {
            "b3": {
                "ready": False,
                "pdf_present": False,
                "fields_correct": "8/8",
                "field_accuracy_ci95": {"low": "0.676", "high": "1.000"},
            }
        },
        note="ESTIMATE: field score kept.",
        folder=kept,
    )
    text = (kept / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "B3 fields: 8/8." in text
    assert "B3: not scored. NOT_VERIFIED." not in text


def test_second_memorandum_keeps_five_of_five_and_labels_an_absent_pdf(tmp_path):
    citation = {
        "recall": "0/1",
        "recall_ci95": {"low": "0.000", "high": "0.793"},
        "system_verdict": "abstain",
    }
    scored = tmp_path / "scored"
    write_bench_snapshot(
        {
            "b3_second": {
                "pdf_present": True,
                "scored": True,
                "fields_correct": "5/5",
                "page_limited_fields_correct": "0/5",
                "field_accuracy_ci95": {"low": "0.566", "high": "1.000"},
            },
            "quarantine_duplicate_citation": citation,
        },
        note="ESTIMATE: second memorandum scored.",
        folder=scored,
    )
    text = (scored / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "B3 second memorandum: 5/5 full text, 0/5 on the first two pages." in text
    assert "Wilson 95%: 0.566 to 1.000." in text
    assert "B3 second memorandum: not on disk" not in text
    assert "Duplicate citation recall: 0/1. Wilson 95%: 0.000 to 0.793." in text

    kept = tmp_path / "kept"
    write_bench_snapshot(
        {
            "b3_second": {
                "pdf_present": False,
                "scored": False,
                "fields_correct": "5/5",
                "page_limited_fields_correct": "0/5",
                "field_accuracy_ci95": {"low": "0.566", "high": "1.000"},
            },
            "quarantine_duplicate_citation": citation,
        },
        note="ESTIMATE: field score kept.",
        folder=kept,
    )
    kept_text = (kept / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "B3 second memorandum: 5/5 full text, 0/5 on the first two pages." in kept_text
    assert "Wilson 95%: 0.566 to 1.000." in kept_text
    assert "not on disk" not in kept_text
    assert "Duplicate citation recall: 0/1. Wilson 95%: 0.000 to 0.793." in kept_text

    absent = tmp_path / "absent"
    write_bench_snapshot(
        {
            "b3_second": {"pdf_present": False, "scored": False, "label": "NOT_VERIFIED"},
            "quarantine_duplicate_citation": citation,
        },
        note="ESTIMATE: second PDF absent.",
        folder=absent,
    )
    missing = (absent / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "B3 second memorandum: not on disk. Not scored. NOT_VERIFIED." in missing
    assert "5/5" not in missing
    assert "Duplicate citation recall: 0/1. Wilson 95%: 0.000 to 0.793." in missing

    scored_false = tmp_path / "scored_false"
    write_bench_snapshot(
        {"b3_second": {"scored": False, "label": "NOT_VERIFIED"}},
        note="ESTIMATE: scored false because the PDF is absent.",
        folder=scored_false,
    )
    only_scored = (scored_false / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "B3 second memorandum: not on disk. Not scored. NOT_VERIFIED." in only_scored

    mismatch = tmp_path / "mismatch"
    write_bench_snapshot(
        {"b3_second": {"pdf_present": True, "scored": False, "label": "NOT_VERIFIED"}},
        note="ESTIMATE: hash mismatch.",
        folder=mismatch,
    )
    mismatch_text = (mismatch / "make_bench_latest.md").read_text(encoding="utf-8")
    assert "hash does not match. Not scored. NOT_VERIFIED." in mismatch_text
    assert "not on disk" not in mismatch_text
