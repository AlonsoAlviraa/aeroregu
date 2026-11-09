"""Fail if packages/kernel contains domain vocabulary."""

from __future__ import annotations

import re
import sys
from pathlib import Path

DENY = re.compile(r"VTOL|EASA|rotor|helicopter|eVTOL|Airbus|SC-VTOL", re.IGNORECASE)
SUFFIXES = {".py", ".md", ".json", ".txt", ".yml", ".yaml"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def scan_kernel(root: Path | None = None) -> list[str]:
    base = (root or repo_root()) / "packages" / "kernel"
    hits: list[str] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        if DENY.search(text):
            hits.append(str(path.relative_to(base.parent.parent)))
    return hits


def main() -> int:
    hits = scan_kernel()
    if hits:
        print("kernel denylist failed:")
        for hit in hits:
            print(hit)
        return 1
    print("kernel denylist ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
