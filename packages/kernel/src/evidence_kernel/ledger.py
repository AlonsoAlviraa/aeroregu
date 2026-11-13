from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from evidence_kernel.canonical import canonicalize, event_hash
from evidence_kernel.merkle import consistency_proof, inclusion_proof, merkle_root
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
        self._lock = threading.RLock()
        self._cached_events: list[dict[str, Any]] = []
        self._cached_hashes: list[str] = []
        self._cached_seqs: list[int] = []
        self._cached_last_seq: int = 0
        self._cached_merkle_root: str | None = None
        self._enable_wal()
        with self._connect(immediate=True) as conn:
            self._migrate(conn)

    def _enable_wal(self) -> None:
        for attempt in range(5):
            conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
            try:
                conn.execute("PRAGMA busy_timeout = 5000")
                conn.execute("PRAGMA journal_mode = WAL")
                return
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                if attempt == 4 or ("locked" not in msg and "busy" not in msg):
                    raise
                time.sleep(0.01 * (attempt + 1))
            finally:
                conn.close()

    @contextmanager
    def _connect(self, *, immediate: bool = False):
        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        if immediate:
            for attempt in range(6):
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    break
                except sqlite3.OperationalError as exc:
                    msg = str(exc).lower()
                    if attempt == 5 or ("locked" not in msg and "busy" not in msg):
                        conn.close()
                        raise
                    time.sleep(0.01 * (attempt + 1))
        try:
            yield conn
            if immediate and conn.in_transaction:
                conn.execute("COMMIT")
        except Exception:
            if immediate and conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
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
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS events_unique_prev_hash
            ON events(prev_hash)
            """
        )

    def head_hash(self) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        return row["event_hash"] if row else GENESIS

    def append(self, body: dict[str, Any]) -> str:
        self._validate_body(body)
        canonical = canonicalize(body)
        with self._lock:
            with self._connect(immediate=True) as conn:
                row = conn.execute(
                    "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                prev = row["event_hash"] if row else GENESIS
                prev_seq = int(row["seq"]) if row else 0
                digest = event_hash(prev, body)
                cursor = conn.execute(
                    "INSERT INTO events (event_hash, prev_hash, body_json) VALUES (?, ?, ?)",
                    (digest, prev, canonical),
                )
                new_seq = int(cursor.lastrowid or (prev_seq + 1))
            if prev_seq == self._cached_last_seq and new_seq > prev_seq:
                self._cached_events.append(
                    {"event_hash": digest, "prev_hash": prev, "body": json.loads(canonical)}
                )
                self._cached_hashes.append(digest)
                self._cached_seqs.append(new_seq)
                self._cached_last_seq = new_seq
            else:
                self._cached_last_seq = -1
            self._cached_merkle_root = None
            return digest

    def append_many(self, bodies: list[dict[str, Any]]) -> list[str]:
        """Atomically validate and append multiple ledger events in a single WAL transaction."""
        if not bodies:
            return []
        prepared = [(body, canonicalize(body)) for body in bodies]
        for body, _ in prepared:
            self._validate_body(body)
        digests: list[str] = []
        with self._lock:
            with self._connect(immediate=True) as conn:
                row = conn.execute(
                    "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                prev = row["event_hash"] if row else GENESIS
                prev_seq = int(row["seq"]) if row else 0
                in_sync = prev_seq == self._cached_last_seq
                new_items: list[tuple[int, str, str, str]] = []
                for body, canonical in prepared:
                    digest = event_hash(prev, body)
                    cursor = conn.execute(
                        "INSERT INTO events (event_hash, prev_hash, body_json) VALUES (?, ?, ?)",
                        (digest, prev, canonical),
                    )
                    new_seq = int(cursor.lastrowid or (prev_seq + len(new_items) + 1))
                    digests.append(digest)
                    new_items.append((new_seq, digest, prev, canonical))
                    prev = digest
            if in_sync:
                for new_seq, digest, prev_h, canonical in new_items:
                    self._cached_events.append(
                        {"event_hash": digest, "prev_hash": prev_h, "body": json.loads(canonical)}
                    )
                    self._cached_hashes.append(digest)
                    self._cached_seqs.append(new_seq)
                    self._cached_last_seq = new_seq
            else:
                self._cached_last_seq = -1
            self._cached_merkle_root = None
        return digests

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

    def _sync_cache_locked(self) -> None:
        with self._connect() as conn:
            meta = conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(MAX(seq), 0) AS max_seq FROM events"
            ).fetchone()
            db_count = int(meta["cnt"])
            db_max_seq = int(meta["max_seq"])
            if (
                self._cached_last_seq >= 0
                and db_count == len(self._cached_events)
                and db_max_seq == self._cached_last_seq
            ):
                return
            if self._cached_last_seq < 0 or db_count < len(self._cached_events):
                self._cached_events = []
                self._cached_hashes = []
                self._cached_seqs = []
                self._cached_last_seq = 0
                self._cached_merkle_root = None
            rows = conn.execute(
                (
                    "SELECT seq, event_hash, prev_hash, body_json "
                    "FROM events WHERE seq > ? ORDER BY seq"
                ),
                (self._cached_last_seq,),
            ).fetchall()
        if rows:
            for row in rows:
                self._cached_events.append(
                    {
                        "event_hash": row["event_hash"],
                        "prev_hash": row["prev_hash"],
                        "body": json.loads(row["body_json"]),
                    }
                )
                self._cached_hashes.append(str(row["event_hash"]))
                self._cached_seqs.append(int(row["seq"]))
                self._cached_last_seq = int(row["seq"])
            self._cached_merkle_root = None

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            self._sync_cache_locked()
            return [
                {
                    "event_hash": item["event_hash"],
                    "prev_hash": item["prev_hash"],
                    "body": item["body"],
                }
                for item in self._cached_events
            ]

    def verify(self) -> bool:
        # Integrity verification always bypasses the cache so direct DB tampering is caught.
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_hash, prev_hash, body_json FROM events ORDER BY seq"
            ).fetchall()
        prev = GENESIS
        for row in rows:
            body = json.loads(row["body_json"])
            if row["prev_hash"] != prev:
                return False
            if event_hash(prev, body) != row["event_hash"]:
                return False
            prev = row["event_hash"]
        return True

    def merkle_root(self) -> str:
        with self._lock:
            self._sync_cache_locked()
            if self._cached_merkle_root is None:
                self._cached_merkle_root = merkle_root(self._cached_hashes)
            return self._cached_merkle_root

    def inclusion_proof(self, target_hash: str) -> dict[str, Any]:
        with self._lock:
            self._sync_cache_locked()
            return inclusion_proof(self._cached_hashes, target_hash)

    def consistency_snapshot(self, old_count: int) -> dict[str, Any]:
        with self._lock:
            self._sync_cache_locked()
            return consistency_proof(self._cached_hashes, old_count)

    def query_events(
        self,
        *,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 200))
        bounded_offset = max(0, int(offset))
        with self._lock:
            self._sync_cache_locked()
            filtered: list[dict[str, Any]] = []
            for seq, event in zip(self._cached_seqs, self._cached_events, strict=True):
                body = event["body"]
                if event_type and body.get("event_type") != event_type:
                    continue
                if actor_id and body.get("actor_id") != actor_id:
                    continue
                filtered.append({"seq": seq, **event})
            page = filtered[bounded_offset : bounded_offset + bounded_limit]
            return {
                "tenant_id": self.tenant_id,
                "total": len(filtered),
                "limit": bounded_limit,
                "offset": bounded_offset,
                "events": page,
            }

    def ensure_actor(self, actor_id: str, role: str, password: str) -> None:
        predictable = hashlib.sha256(f"{self.tenant_id}:{actor_id}".encode()).hexdigest()
        with self._connect(immediate=True) as conn:
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
