"""Merge check for frozen benchmarks.

A worktree cannot be created until the repository has a commit. This gate is
the check a later merge would run. It does not mark the 12-month programme done.
"""

from __future__ import annotations

from typing import Any

from evidence_kernel.paths import repo_root

from evidence_eval.b2 import b4_status, dev_sha256, score_b2
from evidence_eval.b3 import gold_sha256, score_b3
from evidence_eval.b3_second import gold_sha256 as second_gold_sha256
from evidence_eval.b4 import drill_sha256
from evidence_eval.holdout_gate import holdout_gate


def _open_legal_rows() -> int:
    path = repo_root() / "docs" / "legal" / "open_items.md"
    if not path.is_file():
        return 0
    rows = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and "| OPEN |" in line:
            rows += 1
    return rows


def _signed_reviews() -> int:
    folder = repo_root() / "docs" / "reviews"
    if not folder.is_dir():
        return 0
    signed = 0
    for path in folder.glob("*.md"):
        if path.name == "external_request.md":
            continue
        text = path.read_text(encoding="utf-8")
        if "Signed:" in text and "Date:" in text and "Files:" in text:
            signed += 1
    return signed


def freeze_gate() -> dict[str, Any]:
    root = repo_root()
    b2_frozen = (root / "bench" / "b2" / "dev_cases.sha256").read_text(encoding="utf-8")
    b3_frozen = (root / "bench" / "b3" / "dev_gold.sha256").read_text(encoding="utf-8")
    second_path = root / "bench" / "b3" / "second_gold.sha256"
    second_frozen = second_path.read_text(encoding="utf-8") if second_path.is_file() else ""
    b2_ok = b2_frozen.strip() == dev_sha256()
    b3_ok = b3_frozen.strip() == gold_sha256()
    second_ok = second_frozen.strip() == second_gold_sha256()
    drill_path = root / "bench" / "b4" / "drill.sha256"
    drill_frozen = drill_path.read_text(encoding="utf-8") if drill_path.is_file() else ""
    drill_ok = drill_frozen.strip() == drill_sha256()
    b1 = holdout_gate(root / "bench" / "b1" / "expert_holdout")
    b2_holdout = holdout_gate(root / "bench" / "b2" / "expert_holdout")
    b3_names = holdout_gate(root / "bench" / "b3" / "expert_holdout")
    b4_ready = bool(b4_status()["ready"])
    legal_open = _open_legal_rows()
    reviewers = _signed_reviews()
    b2_report = score_b2()
    single_llm = b2_report.get("beats_single_llm")
    single_llm_known = single_llm is True or single_llm is False
    b3_single = score_b3().get("beats_single_llm")
    b3_single_known = b3_single is True or b3_single is False
    b1_scored = False
    unsigned = bool(
        (b1["cases"] and not b1["author_statement"])
        or (b2_holdout["cases"] and not b2_holdout["author_statement"])
        or (b3_names["cases"] and not b3_names["author_statement"])
    )
    return {
        "b2_dev_frozen": b2_ok,
        "b3_dev_frozen": b3_ok,
        "b3_second_frozen": second_ok,
        "b4_drill_frozen": drill_ok,
        "unsigned_expert_cases": unsigned,
        "allowed": b2_ok and b3_ok and second_ok and drill_ok and not unsigned,
        "open_legal_rows": legal_open,
        "signed_reviews": reviewers,
        "single_llm_known": single_llm_known,
        "b3_single_llm_known": b3_single_known,
        "b1_scored": b1_scored,
        "b2_holdout_scored": False,
        "b3_holdout_scored": False,
        "b4_ready": b4_ready,
        "expert_cases_opened": False,
        "programme_complete": False,
        "label": "ESTIMATE",
        "note": (
            "allowed protects the frozen dev files. This gate does not open expert "
            "case files, so programme_complete stays false. B2 and B3 single-LLM "
            "results must be true or false, not NOT_VERIFIED."
        ),
    }
