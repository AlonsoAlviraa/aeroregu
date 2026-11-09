"""Smoke the API with the model URL unset. Does not require Docker."""

from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    os.environ.pop("MODEL_BASE_URL", None)
    os.environ["EVIDENCE_HOME"] = str(Path(".smoke-data").resolve())
    if os.environ.get("MODEL_BASE_URL"):
        print("MODEL_BASE_URL must be unset")
        return 1
    from evidence_api.app import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    body = client.get("/health").json()
    if body["result"]["gateway"] != "fixture":
        print(body)
        return 1
    print("smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
