"""Pinned inputs for a bench run. This file does not claim the 12-month goal is met."""

from __future__ import annotations

import hashlib
import platform
import sys
from datetime import date
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from evidence_kernel.paths import repo_root

from evidence_eval.b2 import dev_sha256
from evidence_eval.b3 import EXPECTED_SHA256, PDF_RELATIVE, gold_sha256
from evidence_eval.b3_second import EXPECTED_SHA256 as SECOND_PDF_SHA256
from evidence_eval.b3_second import PDF_RELATIVE as SECOND_PDF
from evidence_eval.b3_second import gold_sha256 as second_gold_sha256
from evidence_eval.b4 import AS365_SHA256, AS365_UFF, drill_sha256
from evidence_eval.s1 import S1_COUNT, S1_SEED, S1_VERSION

PACKAGES = (
    "evidence-eval",
    "evidence-calc",
    "evidence-kernel",
    "evidence-ingest",
    "pydantic",
    "pint",
    "pypdf",
)


def collect_manifest() -> dict[str, Any]:
    root = repo_root()
    pdf_hash = _sha256(root / PDF_RELATIVE)
    second_hash = _sha256(root / SECOND_PDF)
    bearing_hash = _sha256(root / "data" / "b4" / "data_SSF.zip")
    as365_hash = _sha256(root / AS365_UFF)
    register = root / "docs" / "data_register.md"
    register_text = register.read_text(encoding="utf-8") if register.is_file() else ""
    lock_hash = _sha256(root / "uv.lock", text=True)
    packages: dict[str, str] = {}
    for name in PACKAGES:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "NOT_INSTALLED"
    docling = _package_version("docling")
    return {
        "date": date.today().isoformat(),
        "label": "VERIFIED",
        "command": "make bench",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "s1_version": S1_VERSION,
        "s1_seed": S1_SEED,
        "s1_seed_controls_sampling": False,
        "s1_planned_cases": S1_COUNT,
        "uv_lock_sha256": lock_hash,
        "nasa_tm_101040_sha256": pdf_hash,
        "nasa_tm_101040_expected_sha256": EXPECTED_SHA256,
        "nasa_tm_hash_matches": pdf_hash == EXPECTED_SHA256 if pdf_hash else False,
        "nasa_19890004039_sha256": second_hash,
        "nasa_19890004039_expected_sha256": SECOND_PDF_SHA256,
        "nasa_19890004039_hash_matches": second_hash == SECOND_PDF_SHA256 if second_hash else False,
        "bearing_zip_sha256": bearing_hash,
        "bearing_zip_in_register": bool(bearing_hash and bearing_hash in register_text),
        "as365_uff_sha256": as365_hash,
        "as365_uff_expected_sha256": AS365_SHA256,
        "as365_uff_hash_matches": as365_hash == AS365_SHA256 if as365_hash else False,
        "as365_uff_in_register": bool(as365_hash and as365_hash in register_text),
        "frozen": _frozen(root),
        "packages": packages,
        "docling": docling,
        "notes": [
            "VERIFIED means these versions and hashes were read in this process.",
            "date is the day this process ran, not the retrieval date of each file.",
            "This file is not a B1, B2, B3, B4, or single-LLM result.",
            "Package versions are the versions importlib saw in this environment.",
            "The expert held-out sets are not part of this manifest.",
            "docling NOT_INSTALLED means the reader abstains.",
            "s1_seed_controls_sampling is false. The seed labels the fixed schedule.",
        ],
    }


def write_manifest() -> Path:
    import json

    folder = repo_root() / "docs" / "reproducibility"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    path.write_text(
        json.dumps(collect_manifest(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha256(path: Path, *, text: bool = False) -> str | None:
    if not path.is_file():
        return None
    data = path.read_bytes()
    if text:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _frozen(root: Path) -> dict[str, bool]:
    checks = {
        "b2_dev": (root / "bench" / "b2" / "dev_cases.sha256", dev_sha256()),
        "b3_dev_gold": (root / "bench" / "b3" / "dev_gold.sha256", gold_sha256()),
        "b3_second_gold": (root / "bench" / "b3" / "second_gold.sha256", second_gold_sha256()),
        "b4_drill": (root / "bench" / "b4" / "drill.sha256", drill_sha256()),
    }
    result: dict[str, bool] = {}
    for name, (path, current) in checks.items():
        recorded = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        result[name] = recorded == current
    return result


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "NOT_INSTALLED"
