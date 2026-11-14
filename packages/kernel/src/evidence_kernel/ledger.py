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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence_kernel.canonical import canonicalize, event_hash
from evidence_kernel.merkle import consistency_proof, inclusion_proof, merkle_root
from evidence_kernel.numbers import stray_physical_numbers
from evidence_kernel.schema import validate_instance

GENESIS = "0" * 64
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SIGN_OFF_STATEMENT = "reviewed this event"
PBKDF2_ITERATIONS = 600_000
LEGACY_PBKDF2_ITERATIONS = 20_000
_DUMMY_SALT = "0" * 32


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

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        return conn

    def close(self) -> None:
        return None

    def _enable_wal(self) -> None:
        for attempt in range(5):
            conn = self._open_connection()
            try:
                row = conn.execute("PRAGMA journal_mode").fetchone()
                if row and str(row[0]).lower() == "wal":
                    return
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
        conn = self._open_connection()
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
            CREATE TABLE IF NOT EXISTS revoked_tokens (
                token_hash TEXT PRIMARY KEY,
                revoked_at TEXT NOT NULL,
                expires_at TEXT
            )
            """
        )
        cols = [r[1] for r in conn.execute("PRAGMA table_info(revoked_tokens)").fetchall()]
        if "expires_at" not in cols:
            try:
                conn.execute("ALTER TABLE revoked_tokens ADD COLUMN expires_at TEXT")
            except sqlite3.OperationalError:
                pass
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhooks (
                webhook_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                events_json TEXT NOT NULL,
                secret TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                webhook_id TEXT NOT NULL,
                delivery_id TEXT NOT NULL,
                event_name TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                ok INTEGER NOT NULL,
                error TEXT,
                delivered_at TEXT NOT NULL
            )
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
            if actor_id is None:
                with self._connect() as conn:
                    if event_type:
                        cnt_row = conn.execute(
                            (
                                "SELECT COUNT(*) AS cnt FROM events "
                                "WHERE json_extract(body_json, '$.event_type') = ?"
                            ),
                            (event_type,),
                        ).fetchone()
                        total = int(cnt_row["cnt"]) if cnt_row else 0
                        rows = conn.execute(
                            (
                                "SELECT seq, event_hash, prev_hash, body_json "
                                "FROM events WHERE json_extract(body_json, '$.event_type') = ? "
                                "ORDER BY seq LIMIT ? OFFSET ?"
                            ),
                            (event_type, bounded_limit, bounded_offset),
                        ).fetchall()
                    else:
                        cnt_row = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()
                        total = int(cnt_row["cnt"]) if cnt_row else 0
                        rows = conn.execute(
                            (
                                "SELECT seq, event_hash, prev_hash, body_json "
                                "FROM events ORDER BY seq LIMIT ? OFFSET ?"
                            ),
                            (bounded_limit, bounded_offset),
                        ).fetchall()
                page = [
                    {
                        "seq": int(r["seq"]),
                        "event_hash": str(r["event_hash"]),
                        "prev_hash": str(r["prev_hash"]),
                        "body": json.loads(r["body_json"]),
                    }
                    for r in rows
                ]
                return {
                    "tenant_id": self.tenant_id,
                    "total": total,
                    "limit": bounded_limit,
                    "offset": bounded_offset,
                    "events": page,
                }
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
            if row is not None and not _verify_password_digest(
                password, row["password_salt"], row["password_hash"]
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
            _verify_password_digest(password, _DUMMY_SALT, _get_dummy_hash())
            return False
        stored_hash = str(row["password_hash"])
        salt = str(row["password_salt"])
        if not _verify_password_digest(password, salt, stored_hash):
            return False
        # Upgrade legacy 20k digests transparently on successful verification.
        if not stored_hash.startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"):
            new_salt = secrets.token_hex(16)
            new_hash = _password_digest(password, new_salt)
            with self._connect(immediate=True) as conn:
                conn.execute(
                    "UPDATE actors SET password_hash = ?, password_salt = ? WHERE actor_id = ?",
                    (new_hash, new_salt, actor_id),
                )
        return True

    def revoke_token(
        self,
        token_hash: str,
        revoked_at: str,
        expires_at: str | None = None,
        max_age_seconds: int = 86400,
    ) -> None:
        if expires_at is None:
            try:
                t = datetime.fromisoformat(revoked_at.replace("Z", "+00:00"))
                exp_t = t.timestamp() + max_age_seconds
                expires_at = datetime.fromtimestamp(exp_t, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                expires_at = revoked_at
        with self._connect(immediate=True) as conn:
            conn.execute(
                (
                    "INSERT OR REPLACE INTO revoked_tokens "
                    "(token_hash, revoked_at, expires_at) VALUES (?, ?, ?)"
                ),
                (token_hash, revoked_at, expires_at),
            )
            now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "DELETE FROM revoked_tokens WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now_iso,),
            )

    def is_token_revoked(self, token_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM revoked_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return row is not None

    def set_actor_role(self, actor_id: str, role: str) -> bool:
        """Assign or update an existing or SSO actor's RBAC role."""
        clean_role = str(role or "").strip().lower()
        if clean_role not in {"author", "cve", "admin", "human"}:
            raise LedgerError("invalid_role")
        with self._connect(immediate=True) as conn:
            row = conn.execute("SELECT 1 FROM actors WHERE actor_id = ?", (actor_id,)).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE actors SET role = ? WHERE actor_id = ?",
                    (clean_role, actor_id),
                )
            else:
                salt = secrets.token_hex(16)
                digest = _password_digest(secrets.token_urlsafe(32), salt)
                conn.execute(
                    """
                    INSERT INTO actors (actor_id, role, password_hash, password_salt)
                    VALUES (?, ?, ?, ?)
                    """,
                    (actor_id, clean_role, digest, salt),
                )
        return True

    def ensure_sso_actor(self, actor_id: str, role: str) -> str:
        """Provision or update an external SSO-authenticated actor without password overwrite."""
        clean_role = str(role or "author").strip().lower()
        if clean_role not in {"author", "cve", "admin", "human"}:
            clean_role = "author"
        self.set_actor_role(actor_id, clean_role)
        return clean_role

    def list_actors(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT actor_id, role FROM actors ORDER BY actor_id").fetchall()
        return [{"actor_id": str(r["actor_id"]), "role": str(r["role"])} for r in rows]

    def register_webhook(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO webhooks
                (webhook_id, url, events_json, secret, description, created_at, active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record["webhook_id"]),
                    str(record["url"]),
                    json.dumps(list(record.get("events") or ["envelope_invalidated"])),
                    str(record["secret"]),
                    str(record.get("description") or ""),
                    str(record["created_at"]),
                    1 if record.get("active", True) else 0,
                ),
            )
        return record

    def list_webhooks(self, *, include_secret: bool = False) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT webhook_id, url, events_json, secret, description, created_at, active "
                "FROM webhooks WHERE active = 1 ORDER BY created_at"
            ).fetchall()
        items: list[dict[str, Any]] = []
        for r in rows:
            entry: dict[str, Any] = {
                "webhook_id": str(r["webhook_id"]),
                "url": str(r["url"]),
                "events": json.loads(r["events_json"]),
                "description": str(r["description"]),
                "created_at": str(r["created_at"]),
                "active": bool(r["active"]),
            }
            if include_secret:
                entry["secret"] = str(r["secret"])
            items.append(entry)
        return items

    def delete_webhook(self, webhook_id: str) -> bool:
        with self._connect(immediate=True) as conn:
            cur = conn.execute("DELETE FROM webhooks WHERE webhook_id = ?", (webhook_id,))
        return cur.rowcount > 0

    def record_webhook_delivery(self, delivery: dict[str, Any]) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                INSERT INTO webhook_deliveries
                (webhook_id, delivery_id, event_name, status_code, ok, error, delivered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(delivery["webhook_id"]),
                    str(delivery["delivery_id"]),
                    str(delivery["event"]),
                    int(delivery.get("status_code") or 0),
                    1 if delivery.get("ok") else 0,
                    delivery.get("error"),
                    str(delivery["delivered_at"]),
                ),
            )

    def list_webhook_deliveries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        capped = max(1, min(limit, 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT webhook_id, delivery_id, event_name, status_code, ok, error, delivered_at "
                "FROM webhook_deliveries ORDER BY seq DESC LIMIT ?",
                (capped,),
            ).fetchall()
        return [
            {
                "webhook_id": str(r["webhook_id"]),
                "delivery_id": str(r["delivery_id"]),
                "event": str(r["event_name"]),
                "status_code": int(r["status_code"]),
                "ok": bool(r["ok"]),
                "error": r["error"],
                "delivered_at": str(r["delivered_at"]),
            }
            for r in rows
        ]


_DUMMY_HASH: str | None = None


def _get_dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _password_digest("dummy_password_timing_safe", _DUMMY_SALT, PBKDF2_ITERATIONS)
    return _DUMMY_HASH


def _password_digest(password: str, salt: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
    ).hex()
    return f"pbkdf2_sha256${iterations}${derived}"


def _verify_password_digest(password: str, salt: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        parts = stored_hash.split("$", 2)
        if len(parts) != 3:
            return False
        try:
            iterations = int(parts[1])
        except ValueError:
            return False
        if iterations < 1:
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), iterations
        ).hex()
        return hmac.compare_digest(derived, parts[2])
    legacy = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), LEGACY_PBKDF2_ITERATIONS
    ).hex()
    return hmac.compare_digest(legacy, stored_hash)


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
