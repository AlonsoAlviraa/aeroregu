from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from evidence_kernel.canonical import canonicalize, event_hash
from evidence_kernel.numbers import stray_physical_numbers
from evidence_kernel.schema import validate_instance

GENESIS = "0" * 64
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SIGN_OFF_STATEMENT = "reviewed this event"


class LedgerError(ValueError):
    pass


def _physical_key(key: Any) -> bool:
    if isinstance(key, bool) or key is None:
        return False
    if isinstance(key, (int, float)):
        return True
    if isinstance(key, str):
        return bool(stray_physical_numbers(key, set()))
    return False


def _physical_in_payload(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(stray_physical_numbers(value, set()))
    if isinstance(value, list):
        return any(_physical_in_payload(item) for item in value)
    if isinstance(value, dict):
        for key, item in value.items():
            if _physical_key(key) or _physical_in_payload(item):
                return True
        return False
    return False


def _physical_in_envelope(envelope: dict[str, Any]) -> bool:
    for key, value in envelope.items():
        if key == "method_version":
            continue
        if _physical_in_payload(value):
            return True
    return False


class Ledger:
    def __init__(self, path: Path, tenant_id: str) -> None:
        self.path = Path(path)
        self.tenant_id = tenant_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._migrate(conn)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_hash TEXT NOT NULL UNIQUE,
                prev_hash TEXT NOT NULL,
                body_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS actors (
                actor_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS events_no_update
            BEFORE UPDATE ON events
            BEGIN
                SELECT RAISE(ABORT, 'append-only: update rejected');
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS events_no_delete
            BEFORE DELETE ON events
            BEGIN
                SELECT RAISE(ABORT, 'append-only: delete rejected');
            END
            """
        )
        conn.commit()

    def head_hash(self) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return row["event_hash"] if row else GENESIS

    def append(self, body: dict[str, Any]) -> str:
        self._validate_body(body)
        canonical = canonicalize(body)
        prev = self.head_hash()
        digest = event_hash(prev, body)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events (event_hash, prev_hash, body_json) VALUES (?, ?, ?)",
                (digest, prev, canonical),
            )
            conn.commit()
        return digest

    def _validate_body(self, body: dict[str, Any]) -> None:
        validate_instance("ledger_event.schema.json", body)
        if body["tenant_id"] != self.tenant_id:
            raise LedgerError("tenant mismatch")
        if not ISO_TIME.fullmatch(body["created_at"]):
            raise LedgerError("created_at must be ISO-8601 UTC seconds")
        envelope = body["envelope"]
        if envelope["confidence"] == "abstain":
            if "result" in envelope:
                raise LedgerError("abstain envelope cannot carry result")
            if _physical_in_payload(body["payload"]):
                raise LedgerError("abstain events have no numeric payload")
            if _physical_in_envelope(envelope):
                raise LedgerError("abstain envelope cannot carry a physical number")
        if body["event_type"] == "human_signoff":
            statement = body["payload"].get("statement", "")
            if not isinstance(statement, str) or "compliant" in statement.lower():
                raise LedgerError("sign-off statement must not contain compliant")
            if statement != SIGN_OFF_STATEMENT:
                raise LedgerError("sign-off statement must be the recorded acknowledgement")
            if body["payload"].get("actor_id") != body["actor_id"]:
                raise LedgerError("sign-off actor mismatch")
            target = body["payload"].get("target_event_hash", "")
            if not re.fullmatch(r"[0-9a-f]{64}", str(target)):
                raise LedgerError("sign-off target hash is missing")

    def events(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_hash, prev_hash, body_json FROM events ORDER BY seq"
            ).fetchall()
        parsed: list[dict[str, Any]] = []
        for row in rows:
            parsed.append(
                {
                    "event_hash": row["event_hash"],
                    "prev_hash": row["prev_hash"],
                    "body": json.loads(row["body_json"]),
                }
            )
        return parsed

    def verify(self) -> bool:
        prev = GENESIS
        for event in self.events():
            if event["prev_hash"] != prev:
                return False
            if event_hash(prev, event["body"]) != event["event_hash"]:
                return False
            prev = event["event_hash"]
        return True

    def ensure_actor(self, actor_id: str, role: str, password: str) -> None:
        predictable = hashlib.sha256(f"{self.tenant_id}:{actor_id}".encode()).hexdigest()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash, password_salt FROM actors WHERE actor_id = ?",
                (actor_id,),
            ).fetchone()
            if row is not None and row["password_salt"] != predictable:
                return
            if row is not None and not hmac.compare_digest(
                _password_digest(password, row["password_salt"]), row["password_hash"]
            ):
                return
            salt = secrets.token_hex(16)
            digest = _password_digest(password, salt)
            if row is None:
                conn.execute(
                    """
                    INSERT INTO actors (actor_id, role, password_hash, password_salt)
                    VALUES (?, ?, ?, ?)
                    """,
                    (actor_id, role, digest, salt),
                )
            else:
                conn.execute(
                    """
                    UPDATE actors
                    SET role = ?, password_hash = ?, password_salt = ?
                    WHERE actor_id = ?
                    """,
                    (role, digest, salt, actor_id),
                )
            conn.commit()

    def actor_role(self, actor_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT role FROM actors WHERE actor_id = ?", (actor_id,)).fetchone()
        return row["role"] if row else None

    def check_password(self, actor_id: str, password: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash, password_salt FROM actors WHERE actor_id = ?",
                (actor_id,),
            ).fetchone()
        if row is None:
            return False
        digest = _password_digest(password, row["password_salt"])
        return hmac.compare_digest(digest, row["password_hash"])


def _password_digest(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), 20_000
    ).hex()


def verify_chain_document(events: list[dict[str, Any]]) -> bool:
    prev = GENESIS
    for event in events:
        body = event["body"]
        if event["prev_hash"] != prev:
            return False
        if event_hash(prev, body) != event["event_hash"]:
            return False
        prev = event["event_hash"]
    return True
