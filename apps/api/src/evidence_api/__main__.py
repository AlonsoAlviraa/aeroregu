from __future__ import annotations

import os

import uvicorn


def main() -> None:
    secret = os.environ.get("EVIDENCE_SESSION_SECRET", "")
    if len(secret) < 24 or secret == "local-demo-session":
        raise SystemExit(
            "Set EVIDENCE_SESSION_SECRET to a random string of at least 24 characters."
        )
    host = os.environ.get("EVIDENCE_HOST", "127.0.0.1")
    port = int(os.environ.get("EVIDENCE_PORT", "8000"))
    workers = max(1, int(os.environ.get("EVIDENCE_WORKERS", "1")))
    uvicorn.run(
        "evidence_api.app:app",
        host=host,
        port=port,
        workers=workers,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
