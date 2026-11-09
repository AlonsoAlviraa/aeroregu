"""Held-out cases count only with an author statement from someone else."""

from __future__ import annotations

from pathlib import Path

REQUIRED_SENTENCE = "I did not write the checker in detect.py or b2.py."


def outside_repo(folder: Path) -> bool:
    """True when the folder is not inside this repository."""
    from evidence_kernel.paths import repo_root

    try:
        folder.resolve().relative_to(repo_root().resolve())
    except ValueError:
        return True
    return False


def holdout_gate(folder: Path) -> dict[str, object]:
    if not folder.is_dir():
        cases = 0
        statement = False
    else:
        cases = len(list(folder.glob("*.json")))
        author = folder / "AUTHOR.md"
        text = author.read_text(encoding="utf-8") if author.is_file() else ""
        statement = REQUIRED_SENTENCE in text
    return {
        "cases": cases,
        "author_statement": statement,
        "admissible": cases > 0 and statement,
        "ready_for_b1": cases >= 150 and statement,
    }
