"""M&A Technical Due-Diligence Readiness & Permissive OSS License Audit (ADR-020)."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.metadata as importlib_metadata
import json
from pathlib import Path
from typing import Any

_FORBIDDEN_COPYLEFT = ("gpl", "agpl", "gnu general public", "affero")


def _classify_license(meta_license: str) -> tuple[str, bool, bool]:
    low = meta_license.lower().strip()
    if not low or low == "unknown":
        return "UNKNOWN", False, False
    if any(tok in low for tok in _FORBIDDEN_COPYLEFT) and "lgpl" not in low:
        if "commercial" in low or "dual licensed" in low or "dual-licensed" in low:
            return "COMMERCIAL_DUAL_LICENSED", False, True
        return meta_license, True, False
    return meta_license, False, False


def audit_oss_licenses() -> dict[str, Any]:
    """Inspect installed Python distribution license metadata for copyleft contamination."""
    audited: list[dict[str, Any]] = []
    copyleft_violations: list[dict[str, str]] = []
    commercial_dual_licensed: list[dict[str, str]] = []
    for dist in importlib_metadata.distributions():
        name = str(dist.metadata.get("Name") or dist.name)
        version = str(dist.version)
        lic_expr = str(
            dist.metadata.get("License-Expression") or dist.metadata.get("License") or "UNKNOWN"
        )
        first_line = next((ln.strip() for ln in lic_expr.splitlines() if ln.strip()), "UNKNOWN")
        classified, is_copyleft, is_commercial_dual = _classify_license(first_line[:120])
        rec = {
            "package": name,
            "version": version,
            "license": classified,
            "raw_license": first_line[:120],
            "copyleft_flagged": is_copyleft,
            "commercial_dual_licensed": is_commercial_dual,
        }
        audited.append(rec)
        if is_copyleft:
            copyleft_violations.append({"package": name, "license": first_line[:120]})
        elif is_commercial_dual:
            commercial_dual_licensed.append(
                {
                    "package": name,
                    "version": version,
                    "license": first_line[:120],
                    "classification": classified,
                }
            )

    audited.sort(key=lambda r: r["package"].lower())
    commercial_dual_licensed.sort(key=lambda r: r["package"].lower())
    return {
        "distributions_scanned": len(audited),
        "copyleft_violations": copyleft_violations,
        "commercial_dual_licensed": commercial_dual_licensed,
        "clean_permissive_hygiene": len(copyleft_violations) == 0,
    }


def evaluate_ma_technical_readiness(repo_root: Path) -> dict[str, Any]:
    """Evaluate technical & legal due-diligence readiness per ADR-020."""
    root = Path(repo_root)
    oss_audit = audit_oss_licenses()
    closure_path = root / "docs" / "legal" / "ma_due_diligence_closure.json"
    items: list[dict[str, Any]] = []
    approved_exceptions: set[str] = set()
    if closure_path.is_file():
        doc = json.loads(closure_path.read_text(encoding="utf-8"))
        items = list(doc.get("items") or [])
        approved_exceptions = {
            str(pkg).lower() for pkg in (doc.get("commercial_dual_licensed_exceptions") or [])
        }

    closed_count = sum(1 for item in items if item.get("status") == "CLOSED")
    all_nine_closed = len(items) >= 9 and closed_count == len(items)

    untracked_dual = [
        rec["package"]
        for rec in oss_audit["commercial_dual_licensed"]
        if str(rec["package"]).lower() not in approved_exceptions
    ]

    missing_evidence: list[str] = []
    for item in items:
        for rel_path in item.get("evidence_paths") or []:
            if not (root / rel_path).exists():
                missing_evidence.append(f"{item.get('id')}:{rel_path}")

    ready = bool(
        oss_audit["clean_permissive_hygiene"]
        and len(untracked_dual) == 0
        and all_nine_closed
        and len(missing_evidence) == 0
    )
    report = {
        "status": "READY" if ready else "INCOMPLETE",
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "oss_license_audit": oss_audit,
        "approved_commercial_exceptions": sorted(approved_exceptions),
        "untracked_dual_licensed": untracked_dual,
        "due_diligence_items_total": len(items),
        "due_diligence_items_closed": closed_count,
        "all_nine_items_closed": all_nine_closed,
        "missing_evidence_paths": missing_evidence,
        "items": items,
    }
    hashable = {k: v for k, v in report.items() if k != "generated_at"}
    report["readiness_sha256"] = hashlib.sha256(
        json.dumps(hashable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report
