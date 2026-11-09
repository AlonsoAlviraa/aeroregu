"""The empty B1 expert holdout is not a result anyone may cite."""

from pathlib import Path

from evidence_kernel.paths import repo_root

_CASE_SUFFIXES = {".json", ".jsonl"}


def _case_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in _CASE_SUFFIXES
    )


def test_empty_expert_holdout_cannot_be_cited() -> None:
    from evidence_eval.cite_holdout import cite_expert_holdout

    folder = repo_root() / "bench" / "b1" / "expert_holdout"
    assert _case_files(folder) == []

    report = cite_expert_holdout()
    assert report["ready"] is False
    assert report["reason"] == "empty"
