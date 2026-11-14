"""PostgreSQL distributed multi-tenant append-only ledger backend."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
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
    verify_chain_document,
)
from evidence_kernel.merkle import consistency_proof, inclusion_proof, merkle_root
from evidence_kernel.queue_store import PersistentQueueOps, apply_versioned_migrations
from evidence_kernel.schema import validate_instance


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


class PostgresLedger:
    """PostgreSQL tamper-evident multi-tenant append-only ledger with row locks & triggers."""

    backend_name: str = "postgresql"

    def __init__(
        self,
        dsn: str,
        tenant_id: str,
        *,
        connect_fn: Callable[[str], Any] | None = None,
    ) -> None:
        self.dsn = dsn
        self.tenant_id = tenant_id
        self._connect_fn = connect_fn or _default_pg_connect
        self._lock = threading.RLock()
        with self._tx() as conn:
            self._migrate(conn)
        self.queue = PersistentQueueOps(
            dialect="postgres",
            tenant_id=self.tenant_id,
            tx_fn=self._queue_tx,
        )

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
        with self._tx() as conn:
            return apply_versioned_migrations(conn.cursor(), "postgres")

    def close(self) -> None:
        return None

    @contextmanager
    def _tx(self):
        conn = self._connect_fn(self.dsn)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

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
        apply_versioned_migrations(cur, "postgres")

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
            import re

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

    def head_hash(self) -> str:
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT event_hash FROM events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
                (self.tenant_id,),
            )
            row = cur.fetchone()
        return str(row[0]) if row else GENESIS

    def append(self, body: dict[str, Any]) -> str:
        self._validate_body(body)
        canonical = canonicalize(body)
        with self._lock, self._tx() as conn:
            cur = conn.cursor()
            self._acquire_tenant_lock(cur)
            cur.execute(
                "SELECT event_hash FROM events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
                (self.tenant_id,),
            )
            row = cur.fetchone()
            prev = str(row[0]) if row else GENESIS
            digest = event_hash(prev, body)
            cur.execute(
                "INSERT INTO events (tenant_id, event_hash, prev_hash, body_json) "
                "VALUES (%s, %s, %s, %s)",
                (self.tenant_id, digest, prev, canonical),
            )
            return digest

    def append_many(self, bodies: list[dict[str, Any]]) -> list[str]:
        if not bodies:
            return []
        prepared = [(b, canonicalize(b)) for b in bodies]
        for b, _ in prepared:
            self._validate_body(b)
        digests: list[str] = []
        with self._lock, self._tx() as conn:
            cur = conn.cursor()
            self._acquire_tenant_lock(cur)
            cur.execute(
                "SELECT event_hash FROM events WHERE tenant_id = %s ORDER BY seq DESC LIMIT 1",
                (self.tenant_id,),
            )
            row = cur.fetchone()
            prev = str(row[0]) if row else GENESIS
            for body, canonical in prepared:
                digest = event_hash(prev, body)
                cur.execute(
                    "INSERT INTO events (tenant_id, event_hash, prev_hash, body_json) "
                    "VALUES (%s, %s, %s, %s)",
                    (self.tenant_id, digest, prev, canonical),
                )
                digests.append(digest)
                prev = digest
        return digests

    def events(self) -> list[dict[str, Any]]:
        with self._tx() as conn:
            cur = conn.cursor()
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

    def verify_chain(self) -> bool:
        return verify_chain_document(self.events())

    def merkle_root(self) -> str:
        return merkle_root([ev["event_hash"] for ev in self.events()])

    def inclusion_proof(self, target_hash: str) -> dict[str, Any]:
        return inclusion_proof([ev["event_hash"] for ev in self.events()], target_hash)

    def consistency_proof(self, first_size: int) -> dict[str, Any]:
        return consistency_proof([ev["event_hash"] for ev in self.events()], first_size)

    def query_events(
        self,
        *,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        all_evs = self.events()
        filtered: list[dict[str, Any]] = []
        for idx, ev in enumerate(all_evs, start=1):
            body = ev["body"]
            if event_type and body.get("event_type") != event_type:
                continue
            if actor_id and body.get("actor_id") != actor_id:
                continue
            filtered.append({"seq": idx, **ev})
        bounded_limit = max(1, min(limit, 500))
        bounded_offset = max(0, offset)
        return {
            "tenant_id": self.tenant_id,
            "total": len(filtered),
            "limit": bounded_limit,
            "offset": bounded_offset,
            "events": filtered[bounded_offset : bounded_offset + bounded_limit],
        }

    def ensure_actor(self, actor_id: str, role: str, password: str) -> None:
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT password_hash, password_salt FROM actors "
                "WHERE tenant_id = %s AND actor_id = %s",
                (self.tenant_id, actor_id),
            )
            row = cur.fetchone()
            if row is not None:
                return
            salt = secrets.token_hex(16)
            digest = _password_digest(password, salt)
            cur.execute(
                "INSERT INTO actors (tenant_id, actor_id, role, password_hash, password_salt) "
                "VALUES (%s, %s, %s, %s, %s)",
                (self.tenant_id, actor_id, role, digest, salt),
            )

    def actor_role(self, actor_id: str) -> str | None:
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT role FROM actors WHERE tenant_id = %s AND actor_id = %s",
                (self.tenant_id, actor_id),
            )
            row = cur.fetchone()
        return str(row[0]) if row else None

    def set_actor_role(self, actor_id: str, role: str) -> bool:
        clean_role = str(role or "").strip().lower()
        if clean_role not in {"author", "cve", "admin", "human"}:
            raise LedgerError("invalid_role")
        with self._tx() as conn:
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

    def ensure_sso_actor(self, actor_id: str, role: str) -> str:
        clean_role = str(role or "author").strip().lower()
        if clean_role not in {"author", "cve", "admin", "human"}:
            clean_role = "author"
        self.set_actor_role(actor_id, clean_role)
        return clean_role

    def list_actors(self) -> list[dict[str, str]]:
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT actor_id, role FROM actors WHERE tenant_id = %s ORDER BY actor_id",
                (self.tenant_id,),
            )
            rows = cur.fetchall()
        return [{"actor_id": str(r[0]), "role": str(r[1])} for r in rows]

    def check_password(self, actor_id: str, password: str) -> bool:
        with self._tx() as conn:
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
            with self._tx() as conn:
                conn.cursor().execute(
                    "UPDATE actors SET password_hash = %s, password_salt = %s "
                    "WHERE tenant_id = %s AND actor_id = %s",
                    (new_hash, new_salt, self.tenant_id, actor_id),
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
                expires_at = datetime.fromtimestamp(
                    t.timestamp() + max_age_seconds, tz=UTC
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                expires_at = revoked_at
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO revoked_tokens (token_hash, revoked_at, expires_at) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (token_hash) DO UPDATE SET revoked_at = EXCLUDED.revoked_at, "
                "expires_at = EXCLUDED.expires_at",
                (token_hash, revoked_at, expires_at),
            )

    def is_token_revoked(self, token_hash: str) -> bool:
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM revoked_tokens WHERE token_hash = %s",
                (token_hash,),
            )
            row = cur.fetchone()
        return row is not None

    def register_webhook(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._tx() as conn:
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

    def list_webhooks(self, *, include_secret: bool = False) -> list[dict[str, Any]]:
        with self._tx() as conn:
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

    def delete_webhook(self, webhook_id: str) -> bool:
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM webhooks WHERE tenant_id = %s AND webhook_id = %s",
                (self.tenant_id, webhook_id),
            )
            return cur.rowcount > 0

    def record_webhook_delivery(self, delivery: dict[str, Any]) -> None:
        with self._tx() as conn:
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

    def list_webhook_deliveries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        capped = max(1, min(limit, 500))
        with self._tx() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT webhook_id, delivery_id, event_name, status_code, ok, error, delivered_at "
                "FROM webhook_deliveries WHERE tenant_id = %s ORDER BY seq DESC LIMIT %s",
                (self.tenant_id, capped),
            )
            rows = cur.fetchall()
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
            for r in rows
        ]


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
