from __future__ import annotations

import os

import uvicorn


def main() -> None:
    secret = os.environ.get("EVIDENCE_SESSION_SECRET", "")
    if len(secret) < 24 or secret == "local-demo-session":
        raise SystemExit(
            "Set EVIDENCE_SESSION_SECRET to a random string of at least 24 characters."
        )
    uvicorn.run("evidence_api.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
