"""Schema check for expert B1 files. This does not score them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evidence_kernel.paths import repo_root
from evidence_kernel.schema import validate_instance

from evidence_eval.holdout_gate import holdout_gate

_CHECKER_AUTHOR = "aeroregu"


def validate_b1(folder: Path | None = None) -> dict[str, Any]:
    target = folder or (repo_root() / "bench" / "b1" / "expert_holdout")
    gate = holdout_gate(target)
    faults: set[str] = set()
    valid = 0
    rejected = 0
    reasons: dict[str, int] = {}
    if target.is_dir():
        for path in sorted(target.glob("*.json")):
            reason = _reason(path, faults)
            if reason is None:
                valid += 1
            else:
                rejected += 1
                reasons[reason] = reasons.get(reason, 0) + 1
    ready = bool(gate["author_statement"] and valid >= 150 and len(faults) >= 12 and rejected == 0)
    return {
        "files": gate["cases"],
        "valid": valid,
        "rejected": rejected,
        "reject_reasons": reasons,
        "fault_types": len(faults),
        "author_statement": gate["author_statement"],
        "ready": ready,
        "scored": False,
        "label": "NOT_VERIFIED",
    }


def _reason(path: Path, faults: set[str]) -> str | None:
    """A rejection code, or None when the file counts. The code has no case text."""
    try:
        case = json.loads(path.read_text(encoding="utf-8"))
        validate_instance("benchmark_case.schema.json", case)
    except json.JSONDecodeError:
        return "json"
    except OSError:
        return "unreadable"
    except Exception:
        return "schema"
    provenance = case.get("provenance")
    if not isinstance(provenance, dict):
        return "provenance"
    author = str(provenance.get("author", "")).strip()
    if author == "" or _CHECKER_AUTHOR in author.casefold():
        return "author"
    statement = str(provenance.get("statement", "")).casefold()
    if "no employer" not in statement and "not employer" not in statement:
        return "statement"
    faults_in_case = [item for item in case.get("faults") or [] if isinstance(item, str) and item]
    if not _expected_matches(faults_in_case, str(case.get("expected", ""))):
        return "expected"
    for fault in faults_in_case:
        if fault != "unexplained":
            faults.add(fault)
    return None


def _expected_matches(faults: list[str], expected: str) -> bool:
    if "missing_input" in faults:
        return expected == "abstain" and faults == ["missing_input"]
    if expected == "clean":
        return faults == []
    if expected == "detect:compound":
        return len(faults) >= 2
    if expected.startswith("detect:"):
        return faults == [expected.removeprefix("detect:")]
    return False
