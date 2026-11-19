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
from evidence_kernel.queue_store import PersistentQueueOps, apply_versioned_migrations
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
        self._cached_head_hash: str | None = None
        self._cached_head_fp: tuple[int, int, int, int] | None = None
        self._enable_wal()
        with self._connect(immediate=True) as conn:
            self._migrate(conn)
        self.queue = PersistentQueueOps(
            dialect="sqlite",
            tenant_id=self.tenant_id,
            tx_fn=self._queue_tx,
        )

    @contextmanager
    def _queue_tx(self, *, write: bool = False):
        with self._connect(immediate=write) as conn:
            yield conn.cursor()

    def schema_version(self) -> int:
        return self.queue.schema_version()

    def applied_migrations(self) -> list[dict[str, Any]]:
        return self.queue.applied_migrations()

    def run_migrations(self) -> list[int]:
        with self._connect(immediate=True) as conn:
            return apply_versioned_migrations(conn.cursor(), "sqlite")

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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_checkpoints (
                checkpoint_seq INTEGER PRIMARY KEY,
                head_hash TEXT NOT NULL,
                merkle_root TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_stats (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                event_count INTEGER NOT NULL DEFAULT 0,
                max_seq INTEGER NOT NULL DEFAULT 0,
                head_hash TEXT NOT NULL,
                by_event_type_json TEXT NOT NULL,
                abstain_count INTEGER NOT NULL DEFAULT 0,
                negative_margin_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        apply_versioned_migrations(conn.cursor(), "sqlite")

    def _wal_fingerprint(self) -> tuple[int, int, int, int]:
        try:
            st_db = self.path.stat()
            db_key = (int(st_db.st_mtime_ns), int(st_db.st_size))
        except OSError:
            db_key = (-1, -1)
        try:
            st_wal = Path(f"{self.path}-wal").stat()
            wal_key = (int(st_wal.st_mtime_ns), int(st_wal.st_size))
        except OSError:
            wal_key = (-1, -1)
        return (db_key[0], db_key[1], wal_key[0], wal_key[1])

    def head_hash(self) -> str:
        fp = self._wal_fingerprint()
        with self._lock:
            if (
                self._cached_head_hash is not None
                and self._cached_head_fp == fp
                and fp != (-1, -1, -1, -1)
            ):
                return self._cached_head_hash
        with self._connect() as conn:
            row = conn.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        val = row["event_hash"] if row else GENESIS
        with self._lock:
            self._cached_head_hash = val
            self._cached_head_fp = fp
        return val

    def append(self, body: dict[str, Any]) -> str:
        self._validate_body(body)
        canonical = canonicalize(body)
        et, is_abs, is_neg = self._classify_event_stats(body)
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
                self._update_stats_conn(
                    conn,
                    added_count=1,
                    new_max_seq=new_seq,
                    new_head_hash=digest,
                    type_deltas={et: 1},
                    abstain_delta=1 if is_abs else 0,
                    neg_delta=1 if is_neg else 0,
                )
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
            self._cached_head_hash = digest
            self._cached_head_fp = None
            return digest

    def append_many(self, bodies: list[dict[str, Any]]) -> list[str]:
        """Atomically validate and append multiple ledger events in a single WAL transaction."""
        if not bodies:
            return []
        prepared = [(body, canonicalize(body)) for body in bodies]
        for body, _ in prepared:
            self._validate_body(body)
        digests: list[str] = []
        type_deltas: dict[str, int] = {}
        abs_delta = 0
        neg_delta = 0
        with self._lock:
            with self._connect(immediate=True) as conn:
                row = conn.execute(
                    "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                prev = row["event_hash"] if row else GENESIS
                prev_seq = int(row["seq"]) if row else 0
                in_sync = prev_seq == self._cached_last_seq
                new_items: list[tuple[int, str, str, str]] = []
                last_seq = prev_seq
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
                    last_seq = new_seq
                    et, is_abs, is_neg = self._classify_event_stats(body)
                    type_deltas[et] = type_deltas.get(et, 0) + 1
                    if is_abs:
                        abs_delta += 1
                    if is_neg:
                        neg_delta += 1
                self._update_stats_conn(
                    conn,
                    added_count=len(prepared),
                    new_max_seq=last_seq,
                    new_head_hash=prev,
                    type_deltas=type_deltas,
                    abstain_delta=abs_delta,
                    neg_delta=neg_delta,
                )
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
            self._cached_head_hash = None
            self._cached_head_fp = None
        return digests

    def _classify_event_stats(self, body: dict[str, Any]) -> tuple[str, bool, bool]:
        et = str(body.get("event_type") or "unknown")
        env = body.get("envelope") or {}
        is_abstain = str(env.get("confidence", "")) == "abstain"
        neg_ms = False
        result = env.get("result")
        if isinstance(result, dict):
            ms_raw = result.get("margin_of_safety")
            if ms_raw is not None:
                try:
                    if float(str(ms_raw)) < 0.0:
                        neg_ms = True
                except ValueError:
                    pass
        return et, is_abstain, neg_ms

    def _update_stats_conn(
        self,
        conn: sqlite3.Connection,
        *,
        added_count: int,
        new_max_seq: int,
        new_head_hash: str,
        type_deltas: dict[str, int],
        abstain_delta: int,
        neg_delta: int,
    ) -> None:
        row = conn.execute(
            "SELECT event_count, by_event_type_json, abstain_count, negative_margin_count "
            "FROM ledger_stats WHERE id = 1"
        ).fetchone()
        if row is None:
            cnt_row = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()
            total = int(cnt_row["cnt"]) if cnt_row else added_count
            by_type = dict(type_deltas)
            abs_total = abstain_delta
            neg_total = neg_delta
        else:
            total = int(row["event_count"]) + added_count
            by_type = json.loads(row["by_event_type_json"])
            for k, v in type_deltas.items():
                by_type[k] = int(by_type.get(k, 0)) + v
            abs_total = int(row["abstain_count"]) + abstain_delta
            neg_total = int(row["negative_margin_count"]) + neg_delta
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT OR REPLACE INTO ledger_stats "
            "(id, event_count, max_seq, head_hash, by_event_type_json, "
            "abstain_count, negative_margin_count, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?)",
            (
                total,
                new_max_seq,
                new_head_hash,
                json.dumps(by_type, sort_keys=True),
                abs_total,
                neg_total,
                now,
            ),
        )

    def append_batch(
        self,
        bodies: list[dict[str, Any]],
        *,
        chunk_size: int = 2000,
        checkpoint_interval: int = 1000,
        validate_schema: bool = False,
    ) -> list[str]:
        """High-throughput chunked append with periodic checkpoints & low RSS for 100k+ events."""
        if not bodies:
            return []
        digests: list[str] = []
        type_deltas: dict[str, int] = {}
        abs_delta = 0
        neg_delta = 0
        with self._lock:
            with self._connect(immediate=True) as conn:
                row = conn.execute(
                    "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                prev = str(row["event_hash"]) if row else GENESIS
                prev_seq = int(row["seq"]) if row else 0
                cnt_row = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()
                running_count = int(cnt_row["cnt"]) if cnt_row else 0
                running_seq = prev_seq
                for start in range(0, len(bodies), max(1, chunk_size)):
                    chunk = bodies[start : start + max(1, chunk_size)]
                    rows_batch: list[tuple[str, str, str]] = []
                    for i, body in enumerate(chunk):
                        if validate_schema or (start == 0 and i < 5):
                            self._validate_body(
                                body,
                                validate_schema=validate_schema or (start == 0 and i < 5),
                            )
                        canonical = canonicalize(body)
                        inner_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                        digest = hashlib.sha256((prev + inner_hash).encode("ascii")).hexdigest()
                        rows_batch.append((digest, prev, canonical))
                        digests.append(digest)
                        prev = digest
                        running_seq += 1
                        et, is_abs, is_neg = self._classify_event_stats(body)
                        type_deltas[et] = type_deltas.get(et, 0) + 1
                        if is_abs:
                            abs_delta += 1
                        if is_neg:
                            neg_delta += 1
                    conn.executemany(
                        "INSERT INTO events (event_hash, prev_hash, body_json) VALUES (?, ?, ?)",
                        rows_batch,
                    )
                    running_count += len(chunk)
                    if checkpoint_interval > 0 and (
                        running_count % checkpoint_interval < len(chunk)
                        or start + len(chunk) >= len(bodies)
                    ):
                        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                        conn.execute(
                            "INSERT OR REPLACE INTO ledger_checkpoints "
                            "(checkpoint_seq, head_hash, merkle_root, event_count, created_at) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (running_seq, prev, prev, running_count, now),
                        )
                self._update_stats_conn(
                    conn,
                    added_count=len(bodies),
                    new_max_seq=running_seq,
                    new_head_hash=prev,
                    type_deltas=type_deltas,
                    abstain_delta=abs_delta,
                    neg_delta=neg_delta,
                )
            # Reset cache so stale 100k dicts are not held in memory unnecessarily
            self._cached_events = []
            self._cached_hashes = []
            self._cached_seqs = []
            self._cached_last_seq = -1
            self._cached_merkle_root = None
            self._cached_head_hash = None
            self._cached_head_fp = None
        return digests

    def create_checkpoint(self) -> dict[str, Any] | None:
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT seq, event_hash FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            seq = int(row["seq"])
            head = str(row["event_hash"])
            cnt = int(conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"])
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "INSERT OR REPLACE INTO ledger_checkpoints "
                "(checkpoint_seq, head_hash, merkle_root, event_count, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (seq, head, head, cnt, now),
            )
            return {"checkpoint_seq": seq, "head_hash": head, "event_count": cnt}

    def verify_incremental(self, *, from_latest_checkpoint: bool = True) -> dict[str, Any]:
        with self._connect() as conn:
            prev = GENESIS
            start_seq = 0
            if from_latest_checkpoint:
                ck = conn.execute(
                    "SELECT checkpoint_seq, head_hash FROM ledger_checkpoints "
                    "ORDER BY checkpoint_seq DESC LIMIT 1"
                ).fetchone()
                if ck is not None:
                    ck_seq = int(ck["checkpoint_seq"])
                    ck_hash = str(ck["head_hash"])
                    anchor = conn.execute(
                        "SELECT event_hash FROM events WHERE seq = ?",
                        (ck_seq,),
                    ).fetchone()
                    if anchor is not None and str(anchor["event_hash"]) == ck_hash:
                        start_seq = ck_seq
                        prev = ck_hash
            cur = conn.execute(
                "SELECT seq, event_hash, prev_hash, body_json "
                "FROM events WHERE seq > ? ORDER BY seq",
                (start_seq,),
            )
            verified_tail = 0
            last_seq = start_seq
            while True:
                batch = cur.fetchmany(2000)
                if not batch:
                    break
                for row in batch:
                    if str(row["prev_hash"]) != prev:
                        return {
                            "ok": False,
                            "verified_from_seq": start_seq,
                            "failed_seq": int(row["seq"]),
                        }
                    body = json.loads(row["body_json"])
                    if event_hash(prev, body) != str(row["event_hash"]):
                        return {
                            "ok": False,
                            "verified_from_seq": start_seq,
                            "failed_seq": int(row["seq"]),
                        }
                    prev = str(row["event_hash"])
                    last_seq = int(row["seq"])
                    verified_tail += 1
        return {
            "ok": True,
            "verified_from_seq": start_seq,
            "tail_verified_events": verified_tail,
            "head_seq": last_seq,
            "head_hash": prev,
        }

    def coverage_summary_fast(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT event_count, max_seq, head_hash, by_event_type_json, "
                "abstain_count, negative_margin_count, updated_at "
                "FROM ledger_stats WHERE id = 1"
            ).fetchone()
            ck_row = conn.execute(
                "SELECT COALESCE(MAX(checkpoint_seq), 0) AS m, COUNT(*) AS c "
                "FROM ledger_checkpoints"
            ).fetchone()
            latest_ck = int(ck_row["m"]) if ck_row else 0
            ck_cnt = int(ck_row["c"]) if ck_row else 0
            if row is not None:
                return {
                    "tenant_id": self.tenant_id,
                    "event_count": int(row["event_count"]),
                    "max_seq": int(row["max_seq"]),
                    "head_hash": str(row["head_hash"]),
                    "by_event_type": json.loads(row["by_event_type_json"]),
                    "abstain_count": int(row["abstain_count"]),
                    "negative_margin_count": int(row["negative_margin_count"]),
                    "latest_checkpoint_seq": latest_ck,
                    "checkpoint_count": ck_cnt,
                    "updated_at": str(row["updated_at"]),
                }
            cnt_row = conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(MAX(seq), 0) AS max_seq FROM events"
            ).fetchone()
            return {
                "tenant_id": self.tenant_id,
                "event_count": int(cnt_row["cnt"]) if cnt_row else 0,
                "max_seq": int(cnt_row["max_seq"]) if cnt_row else 0,
                "head_hash": self.head_hash(),
                "by_event_type": {},
                "abstain_count": 0,
                "negative_margin_count": 0,
                "latest_checkpoint_seq": latest_ck,
                "checkpoint_count": ck_cnt,
                "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

    def _validate_body(self, body: dict[str, Any], *, validate_schema: bool = True) -> None:
        if validate_schema:
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
            head = self.head_hash()
            cached = getattr(self, "_cached_merkle_by_head", None)
            if cached is not None and cached[0] == head:
                return str(cached[1])
            with self._connect() as conn:
                hashes = [
                    str(r["event_hash"])
                    for r in conn.execute("SELECT event_hash FROM events ORDER BY seq").fetchall()
                ]
            root = merkle_root(hashes)
            self._cached_merkle_root = root
            self._cached_merkle_by_head = (head, root)
            return root

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
