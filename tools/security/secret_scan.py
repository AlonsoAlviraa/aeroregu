"""Grep for common secret shapes. Not a substitute for gitleaks when it is installed."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9]{16,}['\"]", re.IGNORECASE),
)
SKIP = {".git", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def scan(root: Path | None = None) -> list[str]:
    base = root or repo_root()
    hits: list[str] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP for part in path.parts):
            continue
        if path.suffix in {".png", ".sqlite3", ".whl"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in PATTERNS:
            if pattern.search(text):
                hits.append(str(path.relative_to(base)))
                break
    return hits


def main() -> int:
    hits = scan()
    if hits:
        print("secret scan failed:")
        for hit in hits:
            print(hit)
        return 1
    print("secret scan ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
