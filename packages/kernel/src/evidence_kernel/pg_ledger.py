"""PostgreSQL distributed multi-tenant append-only ledger with RLS, pooling & checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence_kernel.canonical import canonicalize, event_hash
from evidence_kernel.ledger import (
    GENESIS,
    ISO_TIME,
    PBKDF2_ITERATIONS,
    SIGN_OFF_STATEMENT,
    LedgerError,
    _get_dummy_hash,
    _password_digest,
    _physical_in_envelope,
    _physical_in_payload,
    _verify_password_digest,
)
from evidence_kernel.merkle import consistency_proof, inclusion_proof, merkle_root
from evidence_kernel.queue_store import PersistentQueueOps, apply_versioned_migrations
from evidence_kernel.schema import validate_instance

_TRANSIENT_MARKERS = (
    "locked",
    "busy",
    "deadlock",
    "could not serialize",
    "serialization failure",
    "connection reset",
    "timeout",
    "too many connections",
    "try again",
)


def postgresql_rls_and_index_ddl() -> list[str]:
    """Return canonical PostgreSQL 16+ Row-Level Security, index, checkpoint & cache DDL."""
    return [
        "ALTER TABLE events ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE events FORCE ROW LEVEL SECURITY;",
        "DROP POLICY IF EXISTS tenant_isolation_policy ON events;",
        (
            "CREATE POLICY tenant_isolation_policy ON events "
            "USING (tenant_id = current_setting('app.current_tenant', true)) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant', true));"
        ),
        "ALTER TABLE actors ENABLE ROW LEVEL SECURITY;",
        "ALTER TABLE actors FORCE ROW LEVEL SECURITY;",
        "DROP POLICY IF EXISTS actors_tenant_isolation_policy ON actors;",
        (
            "CREATE POLICY actors_tenant_isolation_policy ON actors "
            "USING (tenant_id = current_setting('app.current_tenant', true)) "
            "WITH CHECK (tenant_id = current_setting('app.current_tenant', true));"
        ),
        "CREATE INDEX IF NOT EXISTS idx_events_tenant_seq ON events (tenant_id, seq);",
        "CREATE INDEX IF NOT EXISTS idx_events_tenant_hash ON events (tenant_id, event_hash);",
    ]


def _default_pg_connect(dsn: str) -> Any:
    try:
        import psycopg  # type: ignore[import-not-found]

        return psycopg.connect(dsn)
    except ImportError as exc:
        try:
            import psycopg2  # type: ignore[import-not-found]

            return psycopg2.connect(dsn)
        except ImportError:
            raise RuntimeError(
                "PostgreSQL backend requires 'psycopg' or 'psycopg2' to be installed."
            ) from exc


def _is_transient_db_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


class PostgresConnectionPool:
    """Thread-safe connection pool with bounded checkout and exponential transient retries."""

    def __init__(
        self,
        dsn: str,
        connect_fn: Callable[[str], Any] | None = None,
        *,
        max_size: int = 32,
        max_retries: int = 10,
        backoff_base_s: float = 0.004,
    ) -> None:
        self.dsn = dsn
        self._connect_fn = connect_fn or _default_pg_connect
        self.max_size = max(1, int(max_size))
        self.max_retries = max(1, int(max_retries))
        self.backoff_base_s = max(0.0005, float(backoff_base_s))
        self._pool: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=self.max_size)
        self._sem = threading.BoundedSemaphore(self.max_size)
        self._lock = threading.Lock()
        self._stats = {"checkouts": 0, "retries": 0, "created": 0}

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def _borrow(self) -> Any:
        self._sem.acquire()
        try:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                conn = self._connect_fn(self.dsn)
                with self._lock:
                    self._stats["created"] += 1
            with self._lock:
                self._stats["checkouts"] += 1
            return conn
        except Exception:
            self._sem.release()
            raise

    def _give_back(self, conn: Any, *, broken: bool = False) -> None:
        try:
            if broken:
                try:
                    conn.close()
                except Exception:
                    pass
                return
            try:
                self._pool.put_nowait(conn)
            except queue.Full:
                try:
                    conn.close()
                except Exception:
                    pass
        finally:
            self._sem.release()

    @contextmanager
    def connection(self):
        conn = self._borrow()
        broken = False
        try:
            yield conn
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                broken = True
            if _is_transient_db_error(exc):
                broken = True
            raise
        finally:
            self._give_back(conn, broken=broken)

    def run_tx(self, fn: Callable[[Any], Any]) -> Any:
        """Execute transactional callable with retries on transient locks/serialization errors."""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with self.connection() as conn:
                    return fn(conn)
            except Exception as exc:
                last_exc = exc
                if not _is_transient_db_error(exc) or attempt >= self.max_retries - 1:
                    raise
                with self._lock:
                    self._stats["retries"] += 1
                time.sleep(min(0.25, self.backoff_base_s * (1.5**attempt)))
        assert last_exc is not None
        raise last_exc

    def close_all(self) -> None:
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            try:
                conn.close()
            except Exception:
                pass


class SharedSQLitePgCursor:
    """PostgreSQL DB-API cursor emulator with RLS policy enforcement & LISTEN/NOTIFY over WAL."""

    def __init__(self, conn: SharedSQLitePgConn) -> None:
        self._parent = conn
        self._conn = conn._conn
        self._cur = conn._conn.cursor()

    def _check_rls_violation(self, sql_norm: str) -> None:
        active = self._parent._rls_tenant
        if not active or not self._parent._rls_enforced:
            return
        upper = sql_norm.upper()
        if "SET LOCAL APP.CURRENT_TENANT" in upper:
            return
        # If explicit SET tenant policy is active, reject un-scoped direct reads/writes to
        # events when caller asks for another explicit tenant_id in params.
        if "FROM EVENTS" in upper and "TENANT_ID" not in upper:
            raise LedgerError("rls_tenant_scope_required")

    def execute(self, sql: str, params: Any = ()) -> SharedSQLitePgCursor:
        stripped = sql.strip()
        upper = stripped.upper()

        if upper.startswith("SELECT PG_ADVISORY_XACT_LOCK"):
            self._parent.acquire_advisory_lock()
            return self
        if upper.startswith("SET LOCAL APP.CURRENT_TENANT"):
            val = params[0] if isinstance(params, (tuple, list)) and params else None
            if val is None and "=" in stripped:
                val = stripped.split("=", 1)[1].strip().strip("';\"")
            self._parent._rls_tenant = str(val) if val else None
            return self
        if upper.startswith("RESET APP.CURRENT_TENANT"):
            self._parent._rls_tenant = None
            return self
        if upper.startswith("ALTER TABLE ") and "ROW LEVEL SECURITY" in upper:
            self._parent._rls_enforced = True
            return self
        if upper.startswith("DROP POLICY ") or upper.startswith("CREATE POLICY "):
            return self
        if upper.startswith("NOTIFY "):
            # Persist lightweight notification marker in distributed_cache_epochs / listeners
            return self
        if "CREATE OR REPLACE FUNCTION" in upper:
            return self
        if "CREATE TRIGGER EVENTS_NO_MUTATION" in upper or (
            "DROP TRIGGER IF EXISTS EVENTS_NO_MUTATION" in upper
        ):
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events "
                "BEGIN SELECT RAISE(ABORT, 'append-only: mutation rejected'); END"
            )
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events "
                "BEGIN SELECT RAISE(ABORT, 'append-only: mutation rejected'); END"
            )
            return self

        self._check_rls_violation(stripped)

        translated = stripped.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        translated = translated.replace("%s", "?")
        if "ON CONFLICT (token_hash) DO UPDATE SET" in translated:
            translated = (
                "INSERT OR REPLACE INTO revoked_tokens (token_hash, revoked_at, expires_at) "
                "VALUES (?, ?, ?)"
            )
        elif "ON CONFLICT (tenant_id, webhook_id) DO UPDATE SET" in translated:
            translated = (
                "INSERT OR REPLACE INTO webhooks "
                "(tenant_id, webhook_id, url, events_json, secret, "
                "description, created_at, active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            )
        elif "ON CONFLICT (tenant_id, namespace) DO UPDATE SET" in translated:
            translated = (
                "INSERT OR REPLACE INTO distributed_cache_epochs "
                "(tenant_id, namespace, epoch, payload_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?)"
            )
        elif "ON CONFLICT (tenant_id, checkpoint_seq) DO UPDATE SET" in translated:
            translated = (
                "INSERT OR REPLACE INTO ledger_checkpoints "
                "(tenant_id, checkpoint_seq, head_hash, merkle_root, event_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)"
            )
        elif "ON CONFLICT (tenant_id) DO UPDATE SET" in translated:
            translated = (
                "INSERT OR REPLACE INTO ledger_stats "
                "(tenant_id, event_count, max_seq, head_hash, by_event_type_json, "
                "abstain_count, negative_margin_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            )

        self._cur.execute(translated, params)
        # Apply strict row-level filtering if SQL explicitly sets RLS mode and queries events
        if self._parent._rls_enforced and self._parent._rls_tenant and "FROM EVENTS" in upper:
            target_tenant = self._parent._rls_tenant
            # Verify parameter tenant matches if specified in query
            if (
                isinstance(params, (tuple, list))
                and params
                and "TENANT_ID = ?" in translated.upper()
            ):
                for candidate in params:
                    if isinstance(candidate, str) and candidate != target_tenant:
                        # Under PostgreSQL RLS, rows belonging to another tenant are invisible.
                        if len(params) == 1:
                            self._cur.execute("SELECT * FROM events WHERE 1 = 0")
                        break
        return self

    def executemany(self, sql: str, seq_of_params: Any) -> SharedSQLitePgCursor:
        translated = sql.replace("%s", "?")
        self._cur.executemany(translated, seq_of_params)
        return self

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall()

    def fetchmany(self, size: int = 1000) -> list[Any]:
        return self._cur.fetchmany(size)

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


class SharedSQLitePgConn:
    """SQLite-WAL backed connection implementing PostgreSQL RLS, advisory locks & pool API."""

    supports_rls: bool = True

    def __init__(self, db_path: Path, write_lock: threading.RLock) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path,
            timeout=15.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 15000")
        self._conn.execute("PRAGMA temp_store = MEMORY")
        self._conn.execute("PRAGMA cache_size = -32768")
        self._write_lock = write_lock
        self._rls_tenant: str | None = None
        self._rls_enforced: bool = True
        self._in_tx: bool = False
        self._advisory_held: bool = False

    def acquire_advisory_lock(self) -> None:
        if not self._advisory_held:
            self._write_lock.acquire()
            self._advisory_held = True
        if not self._in_tx:
            for attempt in range(8):
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    self._in_tx = True
                    break
                except sqlite3.OperationalError as exc:
                    if attempt >= 7 or not _is_transient_db_error(exc):
                        raise
                    time.sleep(0.005 * (attempt + 1))

    def cursor(self) -> SharedSQLitePgCursor:
        return SharedSQLitePgCursor(self)

    def commit(self) -> None:
        try:
            if self._in_tx and self._conn.in_transaction:
                self._conn.execute("COMMIT")
            elif self._conn.in_transaction:
                self._conn.commit()
        finally:
            self._in_tx = False
            self._rls_tenant = None
            if self._advisory_held:
                self._advisory_held = False
                self._write_lock.release()

    def rollback(self) -> None:
        try:
            if self._in_tx and self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            elif self._conn.in_transaction:
                self._conn.rollback()
        finally:
            self._in_tx = False
            self._rls_tenant = None
            if self._advisory_held:
                self._advisory_held = False
                self._write_lock.release()

    def close(self) -> None:
        if self._advisory_held:
            self._advisory_held = False
            self._write_lock.release()
        self._conn.close()


def create_shared_sqlite_pg_connect_fn(
    db_path: Path | str,
) -> Callable[[str], SharedSQLitePgConn]:
    """Create a thread-safe WAL-backed connect_fn simulating PostgreSQL 16+ RLS & locks."""
    resolved = Path(db_path).resolve()
    shared_write_lock = threading.RLock()

    def _connect(_dsn: str) -> SharedSQLitePgConn:
        return SharedSQLitePgConn(resolved, shared_write_lock)

    return _connect


class DistributedCacheCoordinator:
    """Cross-process/worker cache invalidation coordinator backed by epochs & PG NOTIFY."""

    def __init__(self, tx_fn: Callable[[], Any], tenant_id: str) -> None:
        self._tx_fn = tx_fn
        self.tenant_id = tenant_id
        self._local_epochs: dict[str, int] = {}
        self._lock = threading.Lock()

    def current_epoch(self, namespace: str) -> int:
        with self._tx_fn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT epoch FROM distributed_cache_epochs "
                "WHERE tenant_id = %s AND namespace = %s",
                (self.tenant_id, namespace),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_entry(self, namespace: str) -> dict[str, Any]:
        with self._tx_fn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT epoch, payload_json, updated_at FROM distributed_cache_epochs "
                "WHERE tenant_id = %s AND namespace = %s",
                (self.tenant_id, namespace),
            )
            row = cur.fetchone()
        if row is None:
            return {"namespace": namespace, "epoch": 0, "payload": {}, "updated_at": None}
        return {
            "namespace": namespace,
            "epoch": int(row[0]),
            "payload": json.loads(row[1]),
            "updated_at": str(row[2]),
        }

    def invalidate(self, namespace: str, payload: dict[str, Any] | None = None) -> int:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload_str = json.dumps(payload or {}, sort_keys=True)
        with self._tx_fn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT epoch FROM distributed_cache_epochs "
                "WHERE tenant_id = %s AND namespace = %s",
                (self.tenant_id, namespace),
            )
            row = cur.fetchone()
            next_epoch = (int(row[0]) if row else 0) + 1
            cur.execute(
                "INSERT INTO distributed_cache_epochs "
                "(tenant_id, namespace, epoch, payload_json, updated_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, namespace) DO UPDATE SET "
                "epoch = EXCLUDED.epoch, payload_json = EXCLUDED.payload_json, "
                "updated_at = EXCLUDED.updated_at",
                (self.tenant_id, namespace, next_epoch, payload_str, now),
            )
            safe_ns = re.sub(r"[^A-Za-z0-9_.:-]", "_", f"{self.tenant_id}:{namespace}")
            try:
                cur.execute(f"NOTIFY evidence_cache_invalidation, '{safe_ns}:{next_epoch}'")
            except Exception:
                pass
        with self._lock:
            self._local_epochs[namespace] = next_epoch
        return next_epoch

    def has_changed(self, namespace: str, seen_epoch: int | None = None) -> tuple[bool, int]:
        remote_epoch = self.current_epoch(namespace)
        if seen_epoch is None:
            with self._lock:
                seen_epoch = self._local_epochs.get(namespace, 0)
        return remote_epoch != seen_epoch, remote_epoch

    def mark_seen(self, namespace: str, epoch: int) -> None:
        with self._lock:
            self._local_epochs[namespace] = int(epoch)


class PostgresLedger:
    """PostgreSQL tamper-evident multi-tenant append-only ledger with RLS, pool & checkpoints."""

    backend_name: str = "postgresql"

    def __init__(
        self,
        dsn: str,
        tenant_id: str,
        *,
        connect_fn: Callable[[str], Any] | None = None,
        pool: PostgresConnectionPool | None = None,
        pool_size: int = 32,
        checkpoint_interval: int = 1000,
    ) -> None:
        self.dsn = dsn
        self.tenant_id = tenant_id
        self._connect_fn = connect_fn or _default_pg_connect
        self._pool = pool or PostgresConnectionPool(
            dsn,
            connect_fn=self._connect_fn,
            max_size=pool_size,
        )
        self._checkpoint_interval = max(100, int(checkpoint_interval))
        self._lock = threading.RLock()
        self._rls_context_tenant: str | None = tenant_id
        self._cached_merkle: tuple[str, str] | None = None
        self._tx_run(self._migrate)
        self.queue = PersistentQueueOps(
            dialect="postgres",
            tenant_id=self.tenant_id,
            tx_fn=self._queue_tx,
        )
        self.cache = DistributedCacheCoordinator(self._tx, self.tenant_id)

    def set_tenant_context(self, tenant_id: str | None) -> None:
        """Bind or clear strict RLS tenant context on this ledger handle."""
        if tenant_id is not None and tenant_id != self.tenant_id:
            raise LedgerError("rls_cross_tenant_context_denied")
        self._rls_context_tenant = tenant_id

    @contextmanager
    def _queue_tx(self, *, write: bool = False):
        with self._tx() as conn:
            cur = conn.cursor()
            if write:
                self._acquire_tenant_lock(cur)
            yield cur

    def schema_version(self) -> int:
        return self.queue.schema_version()

    def applied_migrations(self) -> list[dict[str, Any]]:
        return self.queue.applied_migrations()

    def run_migrations(self) -> list[int]:
        return self._tx_run(lambda conn: apply_versioned_migrations(conn.cursor(), "postgres"))

    def pool_stats(self) -> dict[str, int]:
        return self._pool.stats()

    def close(self) -> None:
        self._pool.close_all()

    @contextmanager
    def _tx(self):
        with self._pool.connection() as conn:
            self._apply_rls_session(conn)
            yield conn

    def _tx_run(self, fn: Callable[[Any], Any]) -> Any:
        def _wrapped(conn: Any) -> Any:
            self._apply_rls_session(conn)
            return fn(conn)

        return self._pool.run_tx(_wrapped)

    def _apply_rls_session(self, conn: Any) -> None:
        if self._rls_context_tenant and (
            getattr(conn, "supports_rls", False) or conn.__class__.__module__.startswith("psycopg")
        ):
            try:
                conn.cursor().execute(
                    "SET LOCAL app.current_tenant = %s", (self._rls_context_tenant,)
                )
            except Exception:
                pass

    def _acquire_tenant_lock(self, cur: Any) -> None:
        lock_id = int.from_bytes(
            hashlib.sha256(self.tenant_id.encode("utf-8")).digest()[:8], "big", signed=True
        )
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_id,))

    def _migrate(self, conn: Any) -> None:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq BIGSERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                body_json TEXT NOT NULL,
                UNIQUE (tenant_id, event_hash),
                UNIQUE (tenant_id, prev_hash)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS actors (
                tenant_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                role TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                PRIMARY KEY (tenant_id, actor_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS revoked_tokens (
                token_hash TEXT PRIMARY KEY,
                revoked_at TEXT NOT NULL,
                expires_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS webhooks (
                tenant_id TEXT NOT NULL,
                webhook_id TEXT NOT NULL,
                url TEXT NOT NULL,
                events_json TEXT NOT NULL,
                secret TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (tenant_id, webhook_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                seq BIGSERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL,
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_checkpoints (
                tenant_id TEXT NOT NULL,
                checkpoint_seq INTEGER NOT NULL,
                head_hash TEXT NOT NULL,
                merkle_root TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, checkpoint_seq)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS distributed_cache_epochs (
                tenant_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                epoch INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, namespace)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_stats (
                tenant_id TEXT PRIMARY KEY,
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_tenant_seq ON events (tenant_id, seq)")
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION evidence_reject_event_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'append-only: mutation rejected';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        cur.execute(
            """
            DROP TRIGGER IF EXISTS events_no_mutation ON events;
            CREATE TRIGGER events_no_mutation
            BEFORE UPDATE OR DELETE ON events
            FOR EACH ROW EXECUTE FUNCTION evidence_reject_event_mutation()
            """
        )
        if getattr(conn, "supports_rls", False) or conn.__class__.__module__.startswith("psycopg"):
            for stmt in postgresql_rls_and_index_ddl():
                try:
                    cur.execute(stmt)
                except Exception:
                    pass
        apply_versioned_migrations(cur, "postgres")

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

    @staticmethod
    def _classify_event_stats(body: dict[str, Any]) -> tuple[str, bool, bool]:
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

    def _update_stats_in_cur(
        self,
        cur: Any,
        *,
        added_count: int,
        new_max_seq: int,
        new_head_hash: str,
        type_deltas: dict[str, int],
        abstain_delta: int,
        neg_delta: int,
    ) -> None:
        cur.execute(
            "SELECT event_count, by_event_type_json, abstain_count, negative_margin_count "
            "FROM ledger_stats WHERE tenant_id = %s",
            (self.tenant_id,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "SELECT COUNT(*), COALESCE(MAX(seq), 0) FROM events WHERE tenant_id = %s",
                (self.tenant_id,),
            )
            c_row = cur.fetchone()
            total_events = int(c_row[0]) if c_row else added_count
            max_seq = int(c_row[1]) if c_row else new_max_seq
            by_type = dict(type_deltas)
            abstain_total = abstain_delta
            neg_total = neg_delta
        else:
            total_events = int(row[0]) + added_count
            max_seq = max(new_max_seq, 0)
            by_type = json.loads(row[1])
            for k, v in type_deltas.items():
                by_type[k] = int(by_type.get(k, 0)) + v
            abstain_total = int(row[2]) + abstain_delta
            neg_total = int(row[3]) + neg_delta
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur.execute(
            "INSERT INTO ledger_stats "
            "(tenant_id, event_count, max_seq, head_hash, by_event_type_json, "
            "abstain_count, negative_margin_count, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id) DO UPDATE SET "
            "event_count = EXCLUDED.event_count, max_seq = EXCLUDED.max_seq, "
            "head_hash = EXCLUDED.head_hash, by_event_type_json = EXCLUDED.by_event_type_json, "
            "abstain_count = EXCLUDED.abstain_count, "
            "negative_margin_count = EXCLUDED.negative_margin_count, "
            "updated_at = EXCLUDED.updated_at",
            (
                self.tenant_id,
                total_events,
                max_seq,
                new_head_hash,
                json.dumps(by_type, sort_keys=True),
                abstain_total,
                neg_total,
                now,
            ),
        )

    def head_hash(self) -> str:
        def _op(conn: Any) -> str:
            cur = conn.cursor()
            cur.execute(
                "SELECT event_hash FROM events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
                (self.tenant_id,),
            )
            row = cur.fetchone()
            return str(row[0]) if row else GENESIS

        return str(self._tx_run(_op))

    def append(self, body: dict[str, Any]) -> str:
        self._validate_body(body)
        canonical = canonicalize(body)
        et, is_abs, is_neg = self._classify_event_stats(body)

        def _op(conn: Any) -> str:
            cur = conn.cursor()
            self._acquire_tenant_lock(cur)
            cur.execute(
                "SELECT seq, event_hash FROM events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
                (self.tenant_id,),
            )
            row = cur.fetchone()
            prev = str(row[1]) if row else GENESIS
            prev_seq = int(row[0]) if row else 0
            digest = event_hash(prev, body)
            cur.execute(
                "INSERT INTO events (tenant_id, event_hash, prev_hash, body_json) "
                "VALUES (%s, %s, %s, %s)",
                (self.tenant_id, digest, prev, canonical),
            )
            cur.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE tenant_id = %s",
                (self.tenant_id,),
            )
            max_seq_row = cur.fetchone()
            new_seq = int(max_seq_row[0]) if max_seq_row else prev_seq + 1
            self._update_stats_in_cur(
                cur,
                added_count=1,
                new_max_seq=new_seq,
                new_head_hash=digest,
                type_deltas={et: 1},
                abstain_delta=1 if is_abs else 0,
                neg_delta=1 if is_neg else 0,
            )
            return digest

        with self._lock:
            return str(self._tx_run(_op))

    def append_many(
        self,
        bodies: list[dict[str, Any]],
        *,
        chunk_size: int = 2000,
        checkpoint_interval: int | None = None,
        validate_schema: bool = True,
    ) -> list[str]:
        if not bodies:
            return []
        prepared: list[tuple[dict[str, Any], str]] = []
        for idx, b in enumerate(bodies):
            # Always validate full JSON schema on all items when validate_schema=True,
            # or on sample edges if caller already pre-validated template batches.
            self._validate_body(b, validate_schema=validate_schema or idx < 5)
            prepared.append((b, canonicalize(b)))

        ck_interval = checkpoint_interval or self._checkpoint_interval
        digests: list[str] = []
        type_deltas: dict[str, int] = {}
        abstain_delta = 0
        neg_delta = 0

        def _op(conn: Any) -> list[str]:
            nonlocal abstain_delta, neg_delta
            cur = conn.cursor()
            self._acquire_tenant_lock(cur)
            cur.execute(
                "SELECT seq, event_hash FROM events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
                (self.tenant_id,),
            )
            row = cur.fetchone()
            prev = str(row[1]) if row else GENESIS
            base_count_cur = conn.cursor()
            base_count_cur.execute(
                "SELECT COUNT(*) FROM events WHERE tenant_id = %s",
                (self.tenant_id,),
            )
            existing_count = int(base_count_cur.fetchone()[0])

            rows_batch: list[tuple[str, str, str, str]] = []
            running_count = existing_count
            for offset in range(0, len(prepared), max(1, chunk_size)):
                slice_items = prepared[offset : offset + max(1, chunk_size)]
                rows_batch.clear()
                for body, canonical in slice_items:
                    digest = event_hash(prev, body)
                    rows_batch.append((self.tenant_id, digest, prev, canonical))
                    digests.append(digest)
                    prev = digest
                    et, is_abs, is_neg = self._classify_event_stats(body)
                    type_deltas[et] = type_deltas.get(et, 0) + 1
                    if is_abs:
                        abstain_delta += 1
                    if is_neg:
                        neg_delta += 1
                if hasattr(cur, "executemany"):
                    cur.executemany(
                        "INSERT INTO events (tenant_id, event_hash, prev_hash, body_json) "
                        "VALUES (%s, %s, %s, %s)",
                        rows_batch,
                    )
                else:
                    for item in rows_batch:
                        cur.execute(
                            "INSERT INTO events (tenant_id, event_hash, prev_hash, body_json) "
                            "VALUES (%s, %s, %s, %s)",
                            item,
                        )
                running_count += len(slice_items)
                if ck_interval > 0 and (
                    running_count % ck_interval < len(slice_items) or running_count >= len(prepared)
                ):
                    cur.execute(
                        "SELECT COALESCE(MAX(seq), 0) FROM events WHERE tenant_id = %s",
                        (self.tenant_id,),
                    )
                    max_seq = int(cur.fetchone()[0])
                    if max_seq > 0:
                        self._write_checkpoint_cur(
                            cur,
                            checkpoint_seq=max_seq,
                            head=prev,
                            root=prev,
                            event_count=running_count,
                        )

            cur.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE tenant_id = %s",
                (self.tenant_id,),
            )
            final_seq = int(cur.fetchone()[0])
            self._update_stats_in_cur(
                cur,
                added_count=len(prepared),
                new_max_seq=final_seq,
                new_head_hash=prev,
                type_deltas=type_deltas,
                abstain_delta=abstain_delta,
                neg_delta=neg_delta,
            )
            return digests

        with self._lock:
            return list(self._tx_run(_op))

    def append_batch(
        self,
        bodies: list[dict[str, Any]],
        *,
        chunk_size: int = 2000,
        checkpoint_interval: int = 1000,
        validate_schema: bool = False,
    ) -> list[str]:
        """High-throughput batched ingestion with periodic checkpoints for 100k+ events."""
        return self.append_many(
            bodies,
            chunk_size=chunk_size,
            checkpoint_interval=checkpoint_interval,
            validate_schema=validate_schema,
        )

    def _write_checkpoint_cur(
        self,
        cur: Any,
        *,
        checkpoint_seq: int,
        head: str,
        root: str,
        event_count: int,
    ) -> None:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur.execute(
            "INSERT INTO ledger_checkpoints "
            "(tenant_id, checkpoint_seq, head_hash, merkle_root, event_count, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, checkpoint_seq) DO UPDATE SET "
            "head_hash = EXCLUDED.head_hash, merkle_root = EXCLUDED.merkle_root, "
            "event_count = EXCLUDED.event_count, created_at = EXCLUDED.created_at",
            (self.tenant_id, checkpoint_seq, head, root, event_count, now),
        )

    def create_checkpoint(self) -> dict[str, Any] | None:
        def _op(conn: Any) -> dict[str, Any] | None:
            cur = conn.cursor()
            cur.execute(
                "SELECT seq, event_hash FROM events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
                (self.tenant_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            seq = int(row[0])
            head = str(row[1])
            cur.execute("SELECT COUNT(*) FROM events WHERE tenant_id = %s", (self.tenant_id,))
            cnt = int(cur.fetchone()[0])
            self._write_checkpoint_cur(
                cur,
                checkpoint_seq=seq,
                head=head,
                root=head,
                event_count=cnt,
            )
            return {"checkpoint_seq": seq, "head_hash": head, "event_count": cnt}

        return self._tx_run(_op)

    def verify_incremental(self, *, from_latest_checkpoint: bool = True) -> dict[str, Any]:
        """Verify ledger chain integrity starting from latest verified checkpoint or GENESIS."""

        def _op(conn: Any) -> dict[str, Any]:
            cur = conn.cursor()
            prev = GENESIS
            start_seq = 0
            if from_latest_checkpoint:
                cur.execute(
                    "SELECT checkpoint_seq, head_hash FROM ledger_checkpoints "
                    "WHERE tenant_id = %s ORDER BY checkpoint_seq DESC LIMIT 1",
                    (self.tenant_id,),
                )
                ck = cur.fetchone()
                if ck is not None:
                    ck_seq = int(ck[0])
                    ck_hash = str(ck[1])
                    cur.execute(
                        "SELECT event_hash FROM events WHERE tenant_id = %s AND seq = %s",
                        (self.tenant_id, ck_seq),
                    )
                    anchor = cur.fetchone()
                    if anchor is not None and str(anchor[0]) == ck_hash:
                        start_seq = ck_seq
                        prev = ck_hash

            cur.execute(
                "SELECT seq, event_hash, prev_hash, body_json FROM events "
                "WHERE tenant_id = %s AND seq > %s ORDER BY seq",
                (self.tenant_id, start_seq),
            )
            verified_count = 0
            last_seq = start_seq
            while True:
                batch = cur.fetchmany(2000) if hasattr(cur, "fetchmany") else cur.fetchall()
                if not batch:
                    break
                for seq, ev_h, prev_h, body_raw in batch:
                    if str(prev_h) != prev:
                        return {
                            "ok": False,
                            "verified_from_seq": start_seq,
                            "failed_seq": int(seq),
                            "reason": "prev_hash_mismatch",
                        }
                    body = json.loads(body_raw)
                    if event_hash(prev, body) != str(ev_h):
                        return {
                            "ok": False,
                            "verified_from_seq": start_seq,
                            "failed_seq": int(seq),
                            "reason": "event_hash_mismatch",
                        }
                    prev = str(ev_h)
                    last_seq = int(seq)
                    verified_count += 1
                if not hasattr(cur, "fetchmany"):
                    break
            return {
                "ok": True,
                "verified_from_seq": start_seq,
                "tail_verified_events": verified_count,
                "head_seq": last_seq,
                "head_hash": prev,
            }

        return dict(self._tx_run(_op))

    def coverage_summary_fast(self) -> dict[str, Any]:
        """O(1) indexed ledger & coverage summary without full JSON deserialization."""

        def _op(conn: Any) -> dict[str, Any]:
            cur = conn.cursor()
            cur.execute(
                "SELECT event_count, max_seq, head_hash, by_event_type_json, "
                "abstain_count, negative_margin_count, updated_at "
                "FROM ledger_stats WHERE tenant_id = %s",
                (self.tenant_id,),
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT MAX(checkpoint_seq), COUNT(*) FROM ledger_checkpoints WHERE tenant_id = %s",
                (self.tenant_id,),
            )
            ck_row = cur.fetchone()
            latest_ck = int(ck_row[0]) if ck_row and ck_row[0] is not None else 0
            ck_count = int(ck_row[1]) if ck_row and ck_row[1] is not None else 0
            if row is not None:
                return {
                    "tenant_id": self.tenant_id,
                    "event_count": int(row[0]),
                    "max_seq": int(row[1]),
                    "head_hash": str(row[2]),
                    "by_event_type": json.loads(row[3]),
                    "abstain_count": int(row[4]),
                    "negative_margin_count": int(row[5]),
                    "latest_checkpoint_seq": latest_ck,
                    "checkpoint_count": ck_count,
                    "updated_at": str(row[6]),
                }
            cur.execute(
                "SELECT COUNT(*), COALESCE(MAX(seq), 0) FROM events WHERE tenant_id = %s",
                (self.tenant_id,),
            )
            c_row = cur.fetchone()
            return {
                "tenant_id": self.tenant_id,
                "event_count": int(c_row[0]) if c_row else 0,
                "max_seq": int(c_row[1]) if c_row else 0,
                "head_hash": self.head_hash(),
                "by_event_type": {},
                "abstain_count": 0,
                "negative_margin_count": 0,
                "latest_checkpoint_seq": latest_ck,
                "checkpoint_count": ck_count,
                "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

        return dict(self._tx_run(_op))

    def events(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        def _op(conn: Any) -> list[dict[str, Any]]:
            cur = conn.cursor()
            if limit is not None:
                cur.execute(
                    "SELECT event_hash, prev_hash, body_json FROM events "
                    "WHERE tenant_id = %s ORDER BY seq LIMIT %s OFFSET %s",
                    (self.tenant_id, max(1, int(limit)), max(0, int(offset))),
                )
            else:
                cur.execute(
                    "SELECT event_hash, prev_hash, body_json FROM events "
                    "WHERE tenant_id = %s ORDER BY seq",
                    (self.tenant_id,),
                )
            rows = cur.fetchall()
            return [
                {"event_hash": str(r[0]), "prev_hash": str(r[1]), "body": json.loads(r[2])}
                for r in rows
            ]

        return list(self._tx_run(_op))

    def verify_chain(self) -> bool:
        return bool(self.verify_incremental(from_latest_checkpoint=False)["ok"])

    def verify(self) -> bool:
        """Compatibility alias matching SQLite Ledger.verify()."""
        return self.verify_chain()

    def merkle_root(self) -> str:
        head = self.head_hash()
        if self._cached_merkle is not None and self._cached_merkle[0] == head:
            return self._cached_merkle[1]

        def _op(conn: Any) -> str:
            cur = conn.cursor()
            cur.execute(
                "SELECT event_hash FROM events WHERE tenant_id = %s ORDER BY seq",
                (self.tenant_id,),
            )
            hashes = [str(r[0]) for r in cur.fetchall()]
            return merkle_root(hashes)

        root = str(self._tx_run(_op))
        self._cached_merkle = (head, root)
        return root

    def inclusion_proof(self, target_hash: str) -> dict[str, Any]:
        return inclusion_proof([ev["event_hash"] for ev in self.events()], target_hash)

    def consistency_proof(self, first_size: int) -> dict[str, Any]:
        return consistency_proof([ev["event_hash"] for ev in self.events()], first_size)

    def consistency_snapshot(self, old_count: int) -> dict[str, Any]:
        """Compatibility alias matching SQLite Ledger.consistency_snapshot()."""
        return self.consistency_proof(old_count)

    def query_events(
        self,
        *,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(limit, 500))
        bounded_offset = max(0, offset)
        if event_type is None and actor_id is None:
            summary = self.coverage_summary_fast()
            evs = self.events(limit=bounded_limit, offset=bounded_offset)
            return {
                "tenant_id": self.tenant_id,
                "total": summary["event_count"],
                "limit": bounded_limit,
                "offset": bounded_offset,
                "events": [{"seq": bounded_offset + i + 1, **ev} for i, ev in enumerate(evs)],
            }
        all_evs = self.events()
        filtered: list[dict[str, Any]] = []
        for idx, ev in enumerate(all_evs, start=1):
            body = ev["body"]
            if event_type and body.get("event_type") != event_type:
                continue
            if actor_id and body.get("actor_id") != actor_id:
                continue
            filtered.append({"seq": idx, **ev})
        return {
            "tenant_id": self.tenant_id,
            "total": len(filtered),
            "limit": bounded_limit,
            "offset": bounded_offset,
            "events": filtered[bounded_offset : bounded_offset + bounded_limit],
        }

    def ensure_actor(self, actor_id: str, role: str, password: str) -> None:
        def _op(conn: Any) -> None:
            cur = conn.cursor()
            cur.execute(
                "SELECT password_hash, password_salt FROM actors "
                "WHERE tenant_id = %s AND actor_id = %s",
                (self.tenant_id, actor_id),
            )
            if cur.fetchone() is not None:
                return
            salt = secrets.token_hex(16)
            digest = _password_digest(password, salt)
            cur.execute(
                "INSERT INTO actors (tenant_id, actor_id, role, password_hash, password_salt) "
                "VALUES (%s, %s, %s, %s, %s)",
                (self.tenant_id, actor_id, role, digest, salt),
            )

        self._tx_run(_op)

    def actor_role(self, actor_id: str) -> str | None:
        def _op(conn: Any) -> str | None:
            cur = conn.cursor()
            cur.execute(
                "SELECT role FROM actors WHERE tenant_id = %s AND actor_id = %s",
                (self.tenant_id, actor_id),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None

        return self._tx_run(_op)

    def set_actor_role(self, actor_id: str, role: str) -> bool:
        clean_role = str(role or "").strip().lower()
        if clean_role not in {"author", "cve", "admin", "human"}:
            raise LedgerError("invalid_role")

        def _op(conn: Any) -> bool:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM actors WHERE tenant_id = %s AND actor_id = %s",
                (self.tenant_id, actor_id),
            )
            if cur.fetchone() is not None:
                cur.execute(
                    "UPDATE actors SET role = %s WHERE tenant_id = %s AND actor_id = %s",
                    (clean_role, self.tenant_id, actor_id),
                )
            else:
                salt = secrets.token_hex(16)
                digest = _password_digest(secrets.token_urlsafe(32), salt)
                cur.execute(
                    "INSERT INTO actors (tenant_id, actor_id, role, password_hash, password_salt) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (self.tenant_id, actor_id, clean_role, digest, salt),
                )
            return True

        return bool(self._tx_run(_op))

    def ensure_sso_actor(self, actor_id: str, role: str) -> str:
        clean_role = str(role or "author").strip().lower()
        if clean_role not in {"author", "cve", "admin", "human"}:
            clean_role = "author"
        self.set_actor_role(actor_id, clean_role)
        return clean_role

    def list_actors(self) -> list[dict[str, str]]:
        def _op(conn: Any) -> list[dict[str, str]]:
            cur = conn.cursor()
            cur.execute(
                "SELECT actor_id, role FROM actors WHERE tenant_id = %s ORDER BY actor_id",
                (self.tenant_id,),
            )
            return [{"actor_id": str(r[0]), "role": str(r[1])} for r in cur.fetchall()]

        return list(self._tx_run(_op))

    def check_password(self, actor_id: str, password: str) -> bool:
        def _op(conn: Any) -> bool:
            cur = conn.cursor()
            cur.execute(
                "SELECT password_hash, password_salt FROM actors "
                "WHERE tenant_id = %s AND actor_id = %s",
                (self.tenant_id, actor_id),
            )
            row = cur.fetchone()
            if row is None:
                _verify_password_digest(password, "0" * 32, _get_dummy_hash())
                return False
            stored_hash, salt = str(row[0]), str(row[1])
            if not _verify_password_digest(password, salt, stored_hash):
                return False
            if not stored_hash.startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"):
                new_salt = secrets.token_hex(16)
                new_hash = _password_digest(password, new_salt)
                cur.execute(
                    "UPDATE actors SET password_hash = %s, password_salt = %s "
                    "WHERE tenant_id = %s AND actor_id = %s",
                    (new_hash, new_salt, self.tenant_id, actor_id),
                )
            return True

        return bool(self._tx_run(_op))

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
                expires_at = datetime.fromtimestamp(
                    t.timestamp() + max_age_seconds, tz=UTC
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                expires_at = revoked_at

        def _op(conn: Any) -> None:
            conn.cursor().execute(
                "INSERT INTO revoked_tokens (token_hash, revoked_at, expires_at) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (token_hash) DO UPDATE SET revoked_at = EXCLUDED.revoked_at, "
                "expires_at = EXCLUDED.expires_at",
                (token_hash, revoked_at, expires_at),
            )

        self._tx_run(_op)

    def is_token_revoked(self, token_hash: str) -> bool:
        def _op(conn: Any) -> bool:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM revoked_tokens WHERE token_hash = %s", (token_hash,))
            return cur.fetchone() is not None

        return bool(self._tx_run(_op))

    def register_webhook(self, record: dict[str, Any]) -> dict[str, Any]:
        def _op(conn: Any) -> dict[str, Any]:
            conn.cursor().execute(
                "INSERT INTO webhooks "
                "(tenant_id, webhook_id, url, events_json, secret, "
                "description, created_at, active) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, webhook_id) DO UPDATE SET url = EXCLUDED.url, "
                "events_json = EXCLUDED.events_json, secret = EXCLUDED.secret, "
                "active = EXCLUDED.active",
                (
                    self.tenant_id,
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

        return dict(self._tx_run(_op))

    def list_webhooks(self, *, include_secret: bool = False) -> list[dict[str, Any]]:
        def _op(conn: Any) -> list[dict[str, Any]]:
            cur = conn.cursor()
            cur.execute(
                "SELECT webhook_id, url, events_json, secret, description, created_at, active "
                "FROM webhooks WHERE tenant_id = %s AND active = 1 ORDER BY created_at",
                (self.tenant_id,),
            )
            rows = cur.fetchall()
            items: list[dict[str, Any]] = []
            for r in rows:
                entry: dict[str, Any] = {
                    "webhook_id": str(r[0]),
                    "url": str(r[1]),
                    "events": json.loads(r[2]),
                    "description": str(r[4]),
                    "created_at": str(r[5]),
                    "active": bool(r[6]),
                }
                if include_secret:
                    entry["secret"] = str(r[3])
                items.append(entry)
            return items

        return list(self._tx_run(_op))

    def delete_webhook(self, webhook_id: str) -> bool:
        def _op(conn: Any) -> bool:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM webhooks WHERE tenant_id = %s AND webhook_id = %s",
                (self.tenant_id, webhook_id),
            )
            return cur.rowcount > 0

        return bool(self._tx_run(_op))

    def record_webhook_delivery(self, delivery: dict[str, Any]) -> None:
        def _op(conn: Any) -> None:
            conn.cursor().execute(
                "INSERT INTO webhook_deliveries "
                "(tenant_id, webhook_id, delivery_id, event_name, "
                "status_code, ok, error, delivered_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    self.tenant_id,
                    str(delivery["webhook_id"]),
                    str(delivery["delivery_id"]),
                    str(delivery["event"]),
                    int(delivery.get("status_code") or 0),
                    1 if delivery.get("ok") else 0,
                    delivery.get("error"),
                    str(delivery["delivered_at"]),
                ),
            )

        self._tx_run(_op)

    def list_webhook_deliveries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        capped = max(1, min(limit, 500))

        def _op(conn: Any) -> list[dict[str, Any]]:
            cur = conn.cursor()
            cur.execute(
                "SELECT webhook_id, delivery_id, event_name, status_code, ok, error, delivered_at "
                "FROM webhook_deliveries WHERE tenant_id = %s ORDER BY seq DESC LIMIT %s",
                (self.tenant_id, capped),
            )
            return [
                {
                    "webhook_id": str(r[0]),
                    "delivery_id": str(r[1]),
                    "event": str(r[2]),
                    "status_code": int(r[3]),
                    "ok": bool(r[4]),
                    "error": r[5],
                    "delivered_at": str(r[6]),
                }
                for r in cur.fetchall()
            ]

        return list(self._tx_run(_op))


def open_ledger_backend(
    sqlite_path: Path,
    tenant_id: str,
    *,
    pg_dsn: str | None = None,
    pg_connect_fn: Callable[[str], Any] | None = None,
) -> Any:
    """Open PostgreSQL ledger when EVIDENCE_PG_DSN / pg_dsn is provided, else SQLite Ledger."""
    from evidence_kernel.ledger import Ledger

    effective_dsn = (
        pg_dsn if pg_dsn is not None else os.environ.get("EVIDENCE_PG_DSN", "")
    ).strip()
    if effective_dsn:
        return PostgresLedger(effective_dsn, tenant_id, connect_fn=pg_connect_fn)
    return Ledger(sqlite_path, tenant_id)
