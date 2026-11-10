from evidence_eval.b2 import b4_status
from evidence_eval.b4 import unregistered_files


def test_a_file_missing_from_the_register_is_listed(tmp_path) -> None:
    path = tmp_path / "series.csv"
    path.write_text("0.1\n", encoding="utf-8")
    missing = unregistered_files(tmp_path, "no hashes here")
    assert missing == ["series.csv"]


def test_a_registered_hash_is_accepted(tmp_path) -> None:
    path = tmp_path / "series.csv"
    path.write_bytes(b"0.1\n")
    import hashlib

    digest = hashlib.sha256(b"0.1\n").hexdigest()
    assert unregistered_files(tmp_path, digest) == []


def test_live_b4_is_not_ready() -> None:
    status = b4_status()
    assert status["ready"] is False
    assert status["label"] == "NOT_VERIFIED"
    assert status["unregistered_files"] == []
    drill = status["drill"]
    assert drill["public_file"] is False
    assert drill["detector_correct"] == "2/2"
    assert drill["naive_correct"] == "1/2"
    assert drill["false_alarms"] == "0/1"
    assert drill["abstain_ok"] is True
    assert drill["label"] == "ESTIMATE"
    assert len(drill["event_hashes"]) == 2
    assert len(drill["abstain_hash"]) == 64
    archive = status["public_archive"]
    if archive is not None:
        assert archive["scored"] is False
        assert archive["pyc_executed"] is False
        assert archive["abstain_reason"] == "unit_not_in_file"
        assert archive["sensor_range_applied"] is False


def test_as365_header_is_not_scored() -> None:
    from evidence_eval.b4 import inspect_as365_header

    report = inspect_as365_header()
    if not report["file_present"]:
        assert report["scored"] is False
        assert report["samples_counted"] is False
        return
    assert report["hash_match"] is True
    assert report["ordinate_unit"] == "m/s^2"
    assert report["ordinate_units"] == ["m/s^2", "m/s^2", "m/s^2"]
    assert report["abscissa_unit"] == "s"
    assert report["pint_accepts_ordinate"] is True
    assert report["limit_in_header"] is False
    assert report["suas_clip_limit_in_header"] is False
    assert report["external_limit_applied"] is False
    assert report["samples_counted"] is False
    assert report["record_count"] == 3
    assert report["function_ids"] == ["P11X", "P11Y", "P11Z"]
    assert report["declared_counts"] == [737280, 737280, 737280]
    assert report["value_counts"] == [737280, 737280, 737280]
    assert report["structure_matches"] is True
    assert report["abscissa_steps"] == ["1.22070E-04", "1.22070E-04", "1.22070E-04"]
    assert report["step_matches_8192_hz"] is True
    assert report["duration_at_8192_s"] == ["90", "90", "90"]
    assert report["duration_matches_paper_60s"] is False
    assert report["length_abstain_reason"] == "record_length_disagrees"
    assert len(report["length_abstain_hash"]) == 64
    assert report["scored"] is False
    assert report["label"] == "PARTIAL"
    assert report["abstain_reason"] == "limit_not_in_file"
    assert len(report["abstain_hash"]) == 64


def test_live_bearing_archive_shape() -> None:
    status = b4_status()
    archive = status["public_archive"]
    if archive is None:
        return
    assert archive["bare_first_lines"] == archive["acceleration_files"]
    assert archive["first_file_lines"] == 80128
    assert archive["length_matches_claim"] is True
    assert archive["files_matching_published_length"] == 150
    assert archive["shortest_file_lines"] == 80128
    assert archive["longest_file_lines"] == 80128
    assert archive["path_tokens"] == ["Ball", "CA", "H", "IN", "OU"]
    assert archive["files_whose_class_token_is_published"] == 30
    assert archive["grid_cells"] == 15
    assert archive["grid_cells_with_ten_files"] == 15
    assert archive["speeds"] == ["1000", "1500", "2000"]
    assert archive["speeds_match_claim"] is True


def test_a_bare_number_is_not_a_unit(tmp_path) -> None:
    import zipfile

    from evidence_eval.b4 import inspect_acceleration_zip, line_is_bare_number

    assert line_is_bare_number("0.25\n") is True
    assert line_is_bare_number("g\n") is False
    path = tmp_path / "series.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/H/1000/1-acceleration.txt", "0.25\n0.50\n")
        archive.writestr("data/model.pyc", b"not-run")
    report = inspect_acceleration_zip(path)
    assert report["unit_in_first_line"] is False
    assert report["scored"] is False
    assert report["abstain_reason"] == "unit_not_in_file"
    assert report["sensor_range_applied"] is False
    assert report["pyc_executed"] is False
    assert report["acceleration_files"] == 1
    assert report["bare_first_lines"] == 1
    assert report["first_file_lines"] == 2
    assert report["files_matching_published_length"] == 0
    assert report["shortest_file_lines"] == 2
    assert report["longest_file_lines"] == 2
    assert report["path_tokens"] == ["H"]
    assert report["files_whose_class_token_is_published"] == 1
    assert report["grid_cells"] == 1
    assert report["grid_cells_with_ten_files"] == 0
    assert report["speeds_match_claim"] is False
    assert report["length_matches_claim"] is False
    assert len(report["abstain_hash"]) == 64


def test_the_drill_series_is_frozen() -> None:
    from evidence_eval.b4 import drill_sha256
    from evidence_kernel.paths import repo_root

    frozen = (repo_root() / "bench" / "b4" / "drill.sha256").read_text(encoding="utf-8")
    assert drill_sha256() == frozen.strip()


def test_exceedance_counts_with_decimal_and_abstains_when_ambiguous() -> None:
    from evidence_calc.errors import AbstainError
    from evidence_eval.b4 import exceedance_count, naive_stated_count

    assert exceedance_count(["1.0", "3.0", "2.5"], "2.0", "meter / second ** 2") == 2
    try:
        exceedance_count(["1.0 or 3.0"], "2.0", "meter / second ** 2")
    except AbstainError as caught:
        assert caught.reason == "ambiguous_input"
    else:
        raise AssertionError("ambiguous sample was counted")
    try:
        exceedance_count(["1.0"], "2.0", "not-a-unit")
    except AbstainError as caught:
        assert caught.reason == "unit_mismatch"
    else:
        raise AssertionError("an unknown unit was accepted")
    try:
        exceedance_count(["1.0"], "2.0", "meter", "second")
    except AbstainError as caught:
        assert caught.reason == "unit_mismatch"
    else:
        raise AssertionError("a different unit was compared")
    assert naive_stated_count("0") == 0
    counted = exceedance_count(["1.0", "3.0", "2.5"], "2.0", "meter / second ** 2")
    assert naive_stated_count("0") != counted


def test_a_temp_file_with_unit_and_limit_is_counted_while_live_files_abstain(
    tmp_path,
) -> None:
    from evidence_calc.errors import AbstainError
    from evidence_eval.b4 import inspect_acceleration_zip, inspect_as365_header, score_series_file
    from evidence_kernel.paths import repo_root

    series = tmp_path / "series.txt"
    series.write_text(
        "unit: meter / second ** 2\nlimit: 2.0\n1.0\n3.0\n2.5\n",
        encoding="utf-8",
    )
    assert not series.is_relative_to(repo_root() / "data")
    assert score_series_file(series) == 2

    no_limit = tmp_path / "no-limit.txt"
    no_limit.write_text("unit: meter / second ** 2\n1.0\n3.0\n", encoding="utf-8")
    try:
        score_series_file(no_limit)
    except AbstainError as caught:
        assert caught.reason == "limit_not_in_file"
    else:
        raise AssertionError("a file without an in-file limit was scored")

    header = inspect_as365_header()
    assert header["scored"] is False
    assert header["samples_counted"] is False
    assert "samples" not in header
    if header["file_present"]:
        assert header["external_limit_applied"] is False
        assert header["limit_in_header"] is False
        assert header["abstain_reason"] == "limit_not_in_file"
        assert header["length_abstain_reason"] == "record_length_disagrees"
    else:
        assert header["label"] == "NOT_VERIFIED"

    zip_path = repo_root() / "data" / "b4" / "data_SSF.zip"
    if zip_path.is_file():
        archive = inspect_acceleration_zip(zip_path)
        assert archive["scored"] is False
        assert archive["abstain_reason"] == "unit_not_in_file"
        assert archive["sensor_range_applied"] is False
        assert archive["unit_in_first_line"] is False
        assert "samples" not in archive


def test_unit_mismatch_stores_no_samples_and_returns_no_count(tmp_path, monkeypatch) -> None:
    from evidence_calc.errors import AbstainError
    from evidence_eval import b4

    def _stored(_path: object) -> list[str]:
        raise AssertionError("samples were stored")

    monkeypatch.setattr(b4, "_series_samples", _stored)
    bodies = (
        "unit: meter\nlimit_unit: foot\nlimit: 2.0\n1.0\n3.0\n2.5\n",
        "unit: meter / second ** 2\nlimit_unit: gravity\nlimit: 2.0\n1.0\n3.0\n2.5\n",
        "unit: meter\nlimit_unit: kilometer\nlimit: 2.0\n1.0\n3.0\n2.5\n",
    )
    for index, body in enumerate(bodies):
        path = tmp_path / f"mismatch-{index}.txt"
        path.write_text(body, encoding="utf-8")
        try:
            counted = b4.score_series_file(path)
        except AbstainError as caught:
            assert caught.reason == "unit_mismatch"
            assert caught.args == ("unit_mismatch",)
        else:
            raise AssertionError(f"exceedance count returned: {counted}")


def test_a_temp_file_abstains_when_sample_and_limit_units_differ(tmp_path) -> None:
    from evidence_calc.errors import AbstainError
    from evidence_eval.b4 import score_series_file
    from evidence_kernel.paths import repo_root

    root = repo_root() / "data"
    length = tmp_path / "meters-feet.txt"
    length.write_text(
        "unit: meter\nlimit_unit: foot\nlimit: 2.0\n1.0\n3.0\n2.5\n",
        encoding="utf-8",
    )
    accel = tmp_path / "accel-gravity.txt"
    accel.write_text(
        "unit: meter / second ** 2\nlimit_unit: gravity\nlimit: 2.0\n1.0\n3.0\n2.5\n",
        encoding="utf-8",
    )
    for path in (length, accel):
        assert not path.is_relative_to(root)
        try:
            score_series_file(path)
        except AbstainError as caught:
            assert caught.reason == "unit_mismatch"
        else:
            raise AssertionError("different units were compared")


def test_in_file_count_is_not_the_public_b4_result(tmp_path) -> None:
    from evidence_calc.errors import AbstainError
    from evidence_eval.b4 import score_series_file
    from evidence_eval.bench_snapshot import _b4_lines, _brief
    from evidence_kernel.paths import repo_root

    body = "unit: meter / second ** 2\nlimit: 2.0\n1.0\n3.0\n2.5\n"
    probe = tmp_path / "series.txt"
    probe.write_text(body, encoding="utf-8")
    assert score_series_file(probe) == 2

    other = tmp_path / "data" / "other" / "series.txt"
    other.parent.mkdir(parents=True)
    other.write_text(body, encoding="utf-8")
    assert score_series_file(other) == 2

    for name in ("as365", "b4"):
        live = tmp_path / "data" / name / "series.txt"
        live.parent.mkdir(parents=True)
        live.write_text(body, encoding="utf-8")
        try:
            score_series_file(live)
        except AbstainError as caught:
            assert caught.reason == "live_series_not_scored"
        else:
            raise AssertionError("a live series directory was scored")

    root = repo_root()
    for relative in (
        "data/as365",
        "data/as365/DataFiles_Type58UFF_AS365K2_AccelData.uff",
        "data/b4",
        "data/b4/data_SSF.zip",
    ):
        try:
            score_series_file(root / relative)
        except AbstainError as caught:
            assert caught.reason == "live_series_not_scored"
        else:
            raise AssertionError("a live series path was scored")

    status = b4_status()
    assert status["ready"] is False
    assert status["in_file_probe"] == {
        "public_result": False,
        "consulted_for_ready": False,
    }
    assert status["drill"]["public_file"] is False
    poisoned = {
        "ready": False,
        "in_file_probe": {"public_result": False, "count": 2},
        "public_archive": {
            "abstain_reason": "unit_not_in_file",
            "sensor_range_applied": False,
        },
    }
    rendered = "\n".join(_b4_lines(poisoned))
    assert "B4 ready: False." in rendered
    assert "B4 in-file probe public result: False." in rendered
    assert "2" not in rendered
    brief = _brief({"b4": status}, note="ESTIMATE: focused.")
    assert "B4 ready: False." in brief
    assert "B4 in-file probe public result: False." in brief
    assert "public result: 2" not in brief
    assert "detector 2/2" in brief
    assert "Not a public dataset. B4 is not ready." in brief


def test_an_unpinned_series_file_is_not_the_registered_one(tmp_path, monkeypatch) -> None:
    import io
    import json
    import os
    import zipfile
    from pathlib import Path

    from evidence_eval import b4
    from evidence_eval.b2 import b4_status
    from evidence_eval.bench_snapshot import _b4_lines
    from evidence_kernel.paths import repo_root

    assert b4.BEARING_SHA256 == "816ccb70e9866692276bc3ab2095c885bdb39fe69b146e4163072d177d5aab0f"
    assert b4.AS365_SHA256 == "b8f1a54300f12b05bb7f4f4802cd2d3f89b9aae6cf9fda81f4c287a263fb3c41"
    root = repo_root()
    real_zip = root / "data" / "b4" / "data_SSF.zip"
    real_uff = root / "data" / "as365" / "DataFiles_Type58UFF_AS365K2_AccelData.uff"
    banned = {
        str(real_zip.resolve()).casefold(),
        str(real_uff.resolve()).casefold(),
    }

    def blocked(path: Path) -> bool:
        try:
            return str(path.resolve()).casefold() in banned
        except OSError:
            return False

    real_open = io.open

    def guarded_open(file: object, *args: object, **kwargs: object):
        if isinstance(file, (str, Path, os.PathLike)):
            if blocked(Path(file)):
                raise AssertionError("real series was opened")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", guarded_open)

    fake_zip = tmp_path / "data_SSF.zip"
    with zipfile.ZipFile(fake_zip, "w") as archive:
        archive.writestr("data/H/1000/1-acceleration.txt", "UNREGISTERED-ZIP-99.5\n80 g\n")
    fake_uff = tmp_path / "as365.uff"
    fake_uff.write_bytes(b"UNREGISTERED-UFF-77.25\nAcceleration m/s^2\n60 m/s2\n490\n")
    monkeypatch.setattr(b4, "BEARING_ZIP", fake_zip)
    monkeypatch.setattr(b4, "AS365_UFF", fake_uff)

    def parsed_zip(_path: object) -> dict[str, object]:
        raise AssertionError("unpinned zip was parsed")

    def parsed_uff(_path: object) -> dict[str, object]:
        raise AssertionError("unpinned UFF was parsed")

    monkeypatch.setattr(b4, "inspect_acceleration_zip", parsed_zip)
    monkeypatch.setattr(b4, "_uff_structure", parsed_uff)

    bearing = b4.registered_bearing_zip()
    as365 = b4.inspect_as365_header()
    assert isinstance(bearing, dict)
    for report in (bearing, as365):
        assert report["file_present"] is True
        assert report["hash_match"] is False
        assert report["scored"] is False
        assert report["samples_counted"] is False
        assert report["samples_stored"] is False
        assert report["limit_applied"] is False
        assert report["sensor_range_applied"] is False
        assert report["external_limit_applied"] is False
        assert report["ready"] is False
        assert report["label"] == "NOT_VERIFIED"
        assert report["note"] == "The file is not the registered one."
        assert report.get("programme_complete") is not True
        assert "samples" not in report

    body = json.dumps({"bearing": bearing, "as365": as365})
    for token in (
        "UNREGISTERED-ZIP-99.5",
        "UNREGISTERED-UFF-77.25",
        "80 g",
        "60 m/s2",
        "490",
    ):
        assert token not in body

    def no_folder_read(_folder: object, _text: object) -> list[str]:
        return []

    monkeypatch.setattr(b4, "unregistered_files", no_folder_read)
    status = b4_status()
    assert status["ready"] is False
    assert status["label"] == "NOT_VERIFIED"
    assert status["bearing_registered"] is False
    assert status["public_archive"] is None
    assert status["note"] == "The file is not the registered one."
    assert status["as365"]["hash_match"] is False
    assert status["as365"]["samples_counted"] is False
    assert status["in_file_probe"]["public_result"] is False
    assert status["in_file_probe"]["consulted_for_ready"] is False
    assert status.get("programme_complete") is not True
    rendered = "\n".join(_b4_lines(status))
    assert "B4 ready: False." in rendered
    assert "The file is not the registered one." in rendered
    assert "UNREGISTERED-ZIP-99.5" not in rendered
    assert "UNREGISTERED-UFF-77.25" not in rendered
    assert "80 g" not in rendered


def test_m_s2_and_m_s_caret_2_are_the_same_unit(tmp_path) -> None:
    from evidence_eval.b4 import score_series_file

    series = tmp_path / "accel.txt"
    series.write_text(
        "unit: m/s2\nlimit_unit: m/s^2\nlimit: 2.0\n1.0\n3.0\n2.5\n",
        encoding="utf-8",
    )
    assert score_series_file(series) == 2


def test_the_drill_reports_intervals_and_is_not_b4() -> None:
    from evidence_eval.b4 import drill

    report = drill()
    assert report["public_file"] is False
    assert report["detector_correct"] == "2/2"
    assert report["naive_correct"] == "1/2"
    assert report["false_alarms"] == "0/1"
    assert report["false_alarm_ci95"]["method"] == "wilson"
    assert report["abstention_correctness"] == "1/1"
    assert report["abstention_ci95"]["method"] == "wilson"
    assert report["beats_single_llm"] == "NOT_VERIFIED"
    assert report["note"] == "Not a public dataset. B4 is not ready."


def test_unlimited_is_not_an_exceedance_limit(tmp_path) -> None:
    from evidence_eval.b4 import _uff_structure

    header = tmp_path / "series.uff"
    header.write_text(
        "\n".join(
            [
                "-1",
                "58",
                "P11X",
                "NONE",
                "unlimited channel",
                "NONE",
                "12 0 0 0 Acceleration m/s^2",
                "0 0 0 0 NONE NONE",
                "0 0 0 0 NONE NONE",
                "1.0",
                "-1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert _uff_structure(header)["header_limit"] is False
    stated = tmp_path / "stated.uff"
    stated.write_text("Limit 2.0 m/s^2\n", encoding="utf-8")
    assert _uff_structure(stated)["header_limit"] is True


def test_a_bare_60_is_not_the_suas_clip(tmp_path) -> None:
    from evidence_eval.b4 import _uff_structure

    bare = tmp_path / "seconds.uff"
    bare.write_text("duration 60 s\n", encoding="utf-8")
    assert _uff_structure(bare)["header_token_60"] is False
    clip = tmp_path / "clip.uff"
    clip.write_text("saturation 60 m/s^2\n", encoding="utf-8")
    assert _uff_structure(clip)["header_token_60"] is True
