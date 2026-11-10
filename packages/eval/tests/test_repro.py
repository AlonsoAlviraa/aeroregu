from evidence_eval.repro import collect_manifest
from evidence_eval.s1 import S1_COUNT, S1_SEED


def test_manifest_date_is_the_day_the_process_runs() -> None:
    from datetime import date

    assert collect_manifest()["date"] == date.today().isoformat()
    manifest = collect_manifest()
    assert manifest["s1_seed"] == S1_SEED
    assert manifest["s1_seed_controls_sampling"] is False
    assert manifest["s1_planned_cases"] == S1_COUNT
    assert manifest["command"] == "make bench"
    assert manifest["uv_lock_sha256"]
    assert manifest["docling"]
    if manifest["nasa_19890004039_sha256"]:
        assert manifest["nasa_19890004039_hash_matches"] is True
    if manifest["bearing_zip_sha256"]:
        assert manifest["bearing_zip_in_register"] is True
    if manifest["as365_uff_sha256"]:
        assert manifest["as365_uff_hash_matches"] is True
        assert manifest["as365_uff_in_register"] is True
    assert manifest["frozen"] == {
        "b2_dev": True,
        "b3_dev_gold": True,
        "b3_second_gold": True,
        "b4_drill": True,
    }


def test_a_crlf_lockfile_matches_the_lf_hash(tmp_path) -> None:
    import hashlib

    from evidence_eval.repro import _sha256

    body = b'name = "example"\n'
    path = tmp_path / "uv.lock"
    path.write_bytes(body.replace(b"\n", b"\r\n"))
    assert _sha256(path, text=True) == hashlib.sha256(body).hexdigest()


def test_checked_in_manifest_matches_the_lock() -> None:
    import json

    from evidence_kernel.paths import repo_root

    written = json.loads(
        (repo_root() / "docs" / "reproducibility" / "manifest.json").read_text(encoding="utf-8")
    )
    assert written["uv_lock_sha256"] == collect_manifest()["uv_lock_sha256"]
