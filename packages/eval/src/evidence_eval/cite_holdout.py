"""Whether bench/b1/expert_holdout may be cited as a benchmark."""

from __future__ import annotations

from evidence_kernel.paths import repo_root

_CASE_SUFFIXES = {".json", ".jsonl"}


def cite_expert_holdout() -> dict[str, object]:
    """The checker author must not cite this set while it has no expert cases."""
    folder = repo_root() / "bench" / "b1" / "expert_holdout"
    has_case = folder.is_dir() and any(
        path.is_file() and path.suffix.lower() in _CASE_SUFFIXES for path in folder.iterdir()
    )
    if has_case:
        return {"ready": False, "reason": "author_unrecorded"}
    return {"ready": False, "reason": "empty"}
