from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in (start, *start.parents):
        schemas = candidate / "schemas" / "envelope.schema.json"
        project = candidate / "pyproject.toml"
        if schemas.is_file() and project.is_file():
            return candidate
    raise FileNotFoundError("repository root not found from kernel package")


def schemas_dir() -> Path:
    return repo_root() / "schemas"


def prompts_dir() -> Path:
    return repo_root() / "packages" / "kernel" / "prompts"
