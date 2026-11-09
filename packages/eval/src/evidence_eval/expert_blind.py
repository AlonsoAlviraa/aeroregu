"""Score an expert directory and return counts only.

The printed report has no case id, no artifact, and no stated number.
An empty directory, or one without the independent-author sentence, is not scored.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evidence_eval.expert_validate import validate_b1
from evidence_eval.holdout_gate import REQUIRED_SENTENCE, holdout_gate
from evidence_eval.score import score_cases


def expert_tree_hash(folder: Path) -> dict[str, object]:
    """Hash every file in an expert folder. The result has no names and no text."""
    digest = hashlib.sha256()
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(folder).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {"files": len(files), "sha256": digest.hexdigest()}


def _read_cases(folder: Path) -> list[dict[str, Any]]:
    """Load expert JSON for scoring. Callers must not print a failure from this read."""
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]


def score_blind_b1(folder: Path | None = None) -> dict[str, Any]:
    from evidence_eval.holdout_gate import outside_repo

    if folder is None or not outside_repo(folder):
        return {
            "scored": False,
            "ready": False,
            "read": False,
            "case_ids_included": False,
            "label": "NOT_VERIFIED",
            "note": "The folder must be outside the repository. No case file was opened.",
        }
    gate = holdout_gate(folder)
    checked = validate_b1(folder)
    if not gate["author_statement"] or checked["valid"] == 0 or checked["rejected"]:
        return {
            "scored": False,
            "ready": False,
            "valid": checked["valid"],
            "rejected": checked["rejected"],
            "fault_types": checked["fault_types"],
            "author_statement": checked["author_statement"],
            "reject_reasons": checked.get("reject_reasons", {}),
            "required_sentence": REQUIRED_SENTENCE,
            "case_ids_included": False,
            "label": "NOT_VERIFIED",
            "note": "Not scored. The directory needs the author sentence and only valid cases.",
        }
    try:
        cases = _read_cases(folder)
        raw = score_cases(cases)
    except Exception as exc:
        return {
            "scored": False,
            "ready": False,
            "stopped": type(exc).__name__,
            "case_ids_included": False,
            "label": "NOT_VERIFIED",
            "note": "The scorer stopped. The case text is not in this report.",
        }
    raw.pop("mismatches", None)
    raw["scored"] = True
    raw["ready"] = checked["ready"]
    raw["valid"] = checked["valid"]
    raw["fault_types"] = checked["fault_types"]
    raw["case_ids_included"] = False
    raw["label"] = "ESTIMATE"
    raw["note"] = (
        "Counts only. Case ids and artifacts are not in this report. "
        "Ready still requires 150 valid cases and 12 fault types."
    )
    return raw
