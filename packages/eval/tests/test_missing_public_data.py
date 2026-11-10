"""A clean checkout has no gitignored public files. Bench must not crash."""

import io
import os
from pathlib import Path

from evidence_eval.b2 import b3_status, b4_status
from evidence_eval.b3_second import score_second
from evidence_eval.quote_pipeline import quotes_ok, score_nasa_quotes
from evidence_eval.repro import collect_manifest
from evidence_kernel.ledger import Ledger
from evidence_kernel.paths import repo_root

PUBLIC_PATHS = (
    Path("data/ntrs/NASA-TM-101040.pdf"),
    Path("data/ntrs/NASA-19890004039.pdf"),
    Path("data/b4/data_SSF.zip"),
    Path("data/as365/DataFiles_Type58UFF_AS365K2_AccelData.uff"),
)
_ABSENT_DIRS = {
    ("data",),
    ("data", "ntrs"),
    ("data", "b4"),
    ("data", "as365"),
}
_ABSENT_FILES = {tuple(part.casefold() for part in path.parts) for path in PUBLIC_PATHS}


def _relative(path: Path, root: Path) -> tuple[str, ...] | None:
    try:
        relative = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    parts = tuple(part.casefold() for part in relative.parts)
    if not parts or parts[0] != "data":
        return None
    return parts


def _hide_public_data(monkeypatch, root: Path) -> None:
    """Report the gitignored data paths as absent. Leave the files on disk."""
    is_file = Path.is_file
    is_dir = Path.is_dir

    def hidden_file(self: Path) -> bool:
        relative = _relative(self, root)
        if relative in _ABSENT_FILES:
            return False
        return is_file(self)

    def hidden_dir(self: Path) -> bool:
        relative = _relative(self, root)
        if relative in _ABSENT_DIRS:
            return False
        return is_dir(self)

    monkeypatch.setattr(Path, "is_file", hidden_file)
    monkeypatch.setattr(Path, "is_dir", hidden_dir)


def _assert_absent(root: Path, ledger_dir: Path) -> None:
    for relative in PUBLIC_PATHS:
        assert not (root / relative).is_file()

    manifest = collect_manifest()
    assert manifest["nasa_tm_101040_sha256"] is None
    assert manifest["nasa_tm_hash_matches"] is False
    assert manifest["nasa_19890004039_sha256"] is None
    assert manifest["nasa_19890004039_hash_matches"] is False
    assert manifest["bearing_zip_sha256"] is None
    assert manifest["as365_uff_sha256"] is None
    assert manifest["as365_uff_hash_matches"] is False

    b3 = b3_status()
    assert b3["ready"] is False
    assert b3["pdf_present"] is False
    assert b3["label"] == "NOT_VERIFIED"
    assert b3.get("dev_pdf_scored") is not True
    assert "not scored" in b3["note"]

    second = score_second()
    assert second["pdf_present"] is False
    assert second["scored"] is False
    assert second["label"] == "NOT_VERIFIED"

    quotes = score_nasa_quotes(Ledger(ledger_dir / "quotes-missing.sqlite3", "bench"))
    assert quotes["ready"] is False
    assert quotes["label"] == "NOT_VERIFIED"
    assert quotes["matched"] == "0/0"
    assert "recorded_fields" not in quotes
    assert quotes_ok(quotes) is True

    b4 = b4_status()
    assert b4["ready"] is False
    assert b4["label"] == "NOT_VERIFIED"
    assert b4["public_archive"] is None
    assert b4["in_file_probe"]["public_result"] is False
    assert b4["in_file_probe"]["consulted_for_ready"] is False
    as365 = b4["as365"]
    assert as365["file_present"] is False
    assert as365["scored"] is False
    assert as365["samples_counted"] is False
    assert "samples" not in as365
    assert b4["drill"]["public_file"] is False
    assert "20200002067" in b4["note"]
    assert "DASHLINK_644" in b4["note"]
    assert "License not specified" in b4["note"]
    assert "does not make B4 ready" in b4["note"]


def _crash_public_open(monkeypatch, root: Path) -> None:
    """Opening a gitignored public file raises. Other files still open."""
    real_open = io.open

    def crashing_open(file, *args, **kwargs):
        if isinstance(file, (str, Path, os.PathLike)):
            relative = _relative(Path(file), root)
            if relative in _ABSENT_FILES:
                raise FileNotFoundError(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(io, "open", crashing_open)


def test_absent_public_files_are_not_scored(tmp_path: Path, monkeypatch) -> None:
    real = repo_root().resolve()
    existed = [os.path.isfile(real / relative) for relative in PUBLIC_PATHS]
    _hide_public_data(monkeypatch, real)
    _assert_absent(real, tmp_path)
    for relative, was_file in zip(PUBLIC_PATHS, existed, strict=True):
        assert os.path.isfile(real / relative) is was_file


def test_public_open_error_leaves_b3_b4_unscored(tmp_path: Path, monkeypatch) -> None:
    """A missing-file open raises. Scorers stay quiet and S1 does not read them."""
    from evidence_eval.s1 import S1_COUNT, iter_cases, plan_size

    real = repo_root().resolve()
    _hide_public_data(monkeypatch, real)
    _crash_public_open(monkeypatch, real)
    _assert_absent(real, tmp_path)
    assert plan_size() == S1_COUNT
    case = next(iter_cases(1))
    assert case["provenance"]["origin"] == "synthetic"
    assert "data/ntrs" not in str(case)
    assert "data/b4" not in str(case)
    assert "data/as365" not in str(case)
