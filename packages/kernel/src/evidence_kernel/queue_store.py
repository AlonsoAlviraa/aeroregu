"""Shared versioned migrations, dead-letter queue, and persistent worker store for SQLite/PG."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

MIGRATION_SPECS: tuple[tuple[int, str, str], ...] = (
    (1, "core_ledger_and_webhooks", "core_v1_events_actors_tokens_webhooks"),
    (2, "webhook_dead_letter_queue", "dlq_v2_webhook_retries_and_dead_letter"),
    (3, "persistent_daemon_queue_and_findings", "daemon_v3_jobs_checkpoints_budget_findings"),
)


def migration_checksum(version: int, name: str, tag: str) -> str:
    return hashlib.sha256(f"{version}:{name}:{tag}".encode()).hexdigest()[:16]


def _utc_now(offset_seconds: float = 0.0) -> str:
    dt = datetime.now(UTC) + timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ddl_statements_for_dialect(dialect: str) -> list[str]:
    """Return idempotent ANSI-compatible DDL statements for schema v2 and v3 tables."""
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if dialect == "sqlite" else "BIGSERIAL PRIMARY KEY"
    return [
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS webhook_dlq (
            seq {pk},
            tenant_id TEXT NOT NULL,
            delivery_id TEXT NOT NULL,
            webhook_id TEXT NOT NULL,
            event_name TEXT NOT NULL,
            url TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            next_retry_at TEXT NOT NULL,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, delivery_id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS daemon_jobs (
            seq {pk},
            tenant_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            job_type TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 50,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            checkpoint_json TEXT NOT NULL,
            result_json TEXT,
            attempt INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            backoff_seconds INTEGER NOT NULL DEFAULT 5,
            next_run_at TEXT NOT NULL,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, job_id),
            UNIQUE (tenant_id, idempotency_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS daemon_checkpoints (
            tenant_id TEXT NOT NULL,
            watcher_key TEXT NOT NULL,
            cursor_value TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, watcher_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS daemon_budget (
            tenant_id TEXT NOT NULL,
            budget_date TEXT NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            edge_tokens_used INTEGER NOT NULL DEFAULT 0,
            cloud_tokens_used INTEGER NOT NULL DEFAULT 0,
            jobs_executed INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, budget_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS overnight_findings (
            tenant_id TEXT NOT NULL,
            finding_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            risk_score INTEGER NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            target_event_hash TEXT,
            cell_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            signed_off_by TEXT,
            signed_off_at TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, finding_id)
        )
        """,
    ]


def apply_versioned_migrations(cur: Any, dialect: str) -> list[int]:
    """Execute DDL and record versioned schema_migrations entries idempotently."""
    for ddl in ddl_statements_for_dialect(dialect):
        cur.execute(ddl)

    cur.execute("SELECT version FROM schema_migrations ORDER BY version")
    existing = {int(row[0]) for row in cur.fetchall()}
    ph = "?" if dialect == "sqlite" else "%s"
    now = _utc_now()
    newly_applied: list[int] = []
    for version, name, tag in MIGRATION_SPECS:
        if version in existing:
            continue
        cur.execute(
            f"INSERT INTO schema_migrations (version, name, applied_at, checksum) "
            f"VALUES ({ph}, {ph}, {ph}, {ph})",
            (version, name, now, migration_checksum(version, name, tag)),
        )
        newly_applied.append(version)
    return newly_applied


class PersistentQueueOps:
    """Dialect-agnostic operations for migrations, webhook DLQ, daemon queue & briefing findings."""

    def __init__(self, *, dialect: str, tenant_id: str, tx_fn: Any) -> None:
        self.dialect = dialect
        self.tenant_id = tenant_id
        self._tx_fn = tx_fn
        self.ph = "?" if dialect == "sqlite" else "%s"

    def schema_version(self) -> int:
        with self._tx_fn(write=False) as cur:
            cur.execute("SELECT MAX(version) FROM schema_migrations")
            row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def applied_migrations(self) -> list[dict[str, Any]]:
        with self._tx_fn(write=False) as cur:
            cur.execute(
                "SELECT version, name, applied_at, checksum "
                "FROM schema_migrations ORDER BY version ASC"
            )
            rows = cur.fetchall()
        return [
            {
                "version": int(r[0]),
                "name": str(r[1]),
                "applied_at": str(r[2]),
                "checksum": str(r[3]),
            }
            for r in rows
        ]

    def upsert_webhook_dlq(
        self,
        *,
        delivery_id: str,
        webhook_id: str,
        event_name: str,
        url: str,
        payload: dict[str, Any],
        status: str,
        attempt_count: int,
        max_attempts: int,
        next_retry_at: str,
        last_error: str | None,
    ) -> dict[str, Any]:
        now = _utc_now()
        payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        p = self.ph
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"SELECT attempt_count FROM webhook_dlq "
                f"WHERE tenant_id = {p} AND delivery_id = {p}",
                (self.tenant_id, delivery_id),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO webhook_dlq "
                    "(tenant_id, delivery_id, webhook_id, event_name, url, payload_json, "
                    "status, attempt_count, max_attempts, next_retry_at, last_error, "
                    "created_at, updated_at) "
                    f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})",
                    (
                        self.tenant_id,
                        delivery_id,
                        webhook_id,
                        event_name,
                        url,
                        payload_str,
                        status,
                        attempt_count,
                        max_attempts,
                        next_retry_at,
                        last_error,
                        now,
                        now,
                    ),
                )
            else:
                cur.execute(
                    f"UPDATE webhook_dlq SET status = {p}, attempt_count = {p}, "
                    f"next_retry_at = {p}, last_error = {p}, updated_at = {p} "
                    f"WHERE tenant_id = {p} AND delivery_id = {p}",
                    (
                        status,
                        attempt_count,
                        next_retry_at,
                        last_error,
                        now,
                        self.tenant_id,
                        delivery_id,
                    ),
                )
        return {
            "delivery_id": delivery_id,
            "webhook_id": webhook_id,
            "event": event_name,
            "url": url,
            "status": status,
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "next_retry_at": next_retry_at,
            "last_error": last_error,
            "updated_at": now,
        }

    def list_webhook_dlq(
        self, *, status: str | None = "dead_letter", limit: int = 100
    ) -> list[dict[str, Any]]:
        capped = max(1, min(limit, 500))
        p = self.ph
        with self._tx_fn(write=False) as cur:
            if status:
                cur.execute(
                    f"SELECT delivery_id, webhook_id, event_name, url, payload_json, status, "
                    f"attempt_count, max_attempts, next_retry_at, last_error, "
                    f"created_at, updated_at "
                    f"FROM webhook_dlq WHERE tenant_id = {p} AND status = {p} "
                    f"ORDER BY seq DESC LIMIT {p}",
                    (self.tenant_id, status, capped),
                )
            else:
                cur.execute(
                    f"SELECT delivery_id, webhook_id, event_name, url, payload_json, status, "
                    f"attempt_count, max_attempts, next_retry_at, last_error, "
                    f"created_at, updated_at "
                    f"FROM webhook_dlq WHERE tenant_id = {p} ORDER BY seq DESC LIMIT {p}",
                    (self.tenant_id, capped),
                )
            rows = cur.fetchall()
        return [
            {
                "delivery_id": str(r[0]),
                "webhook_id": str(r[1]),
                "event": str(r[2]),
                "url": str(r[3]),
                "payload": json.loads(r[4]),
                "status": str(r[5]),
                "attempt_count": int(r[6]),
                "max_attempts": int(r[7]),
                "next_retry_at": str(r[8]),
                "last_error": r[9],
                "created_at": str(r[10]),
                "updated_at": str(r[11]),
            }
            for r in rows
        ]

    def enqueue_daemon_job(
        self,
        *,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        priority: int = 50,
        max_attempts: int = 3,
        backoff_seconds: int = 5,
    ) -> dict[str, Any]:
        now = _utc_now()
        p = self.ph
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"SELECT job_id, status, attempt FROM daemon_jobs "
                f"WHERE tenant_id = {p} AND idempotency_key = {p}",
                (self.tenant_id, idempotency_key),
            )
            existing = cur.fetchone()
            if existing is not None and str(existing[1]) in {
                "pending",
                "running",
                "retry_scheduled",
            }:
                return {
                    "job_id": str(existing[0]),
                    "idempotency_key": idempotency_key,
                    "job_type": job_type,
                    "status": str(existing[1]),
                    "deduplicated": True,
                }
            if existing is not None:
                job_id = str(existing[0])
                cur.execute(
                    f"UPDATE daemon_jobs SET status = {p}, payload_json = {p}, priority = {p}, "
                    f"next_run_at = {p}, updated_at = {p} WHERE tenant_id = {p} AND job_id = {p}",
                    (
                        "pending",
                        json.dumps(payload, sort_keys=True),
                        int(priority),
                        now,
                        now,
                        self.tenant_id,
                        job_id,
                    ),
                )
            else:
                job_id = f"job_{secrets.token_hex(8)}"
                phs = ", ".join([p] * 16)
                cur.execute(
                    "INSERT INTO daemon_jobs "
                    "(tenant_id, job_id, idempotency_key, job_type, priority, status, "
                    "payload_json, checkpoint_json, result_json, attempt, max_attempts, "
                    "backoff_seconds, next_run_at, last_error, created_at, updated_at) "
                    f"VALUES ({phs})",
                    (
                        self.tenant_id,
                        job_id,
                        idempotency_key,
                        job_type,
                        int(priority),
                        "pending",
                        json.dumps(payload, sort_keys=True),
                        "{}",
                        None,
                        0,
                        max(1, int(max_attempts)),
                        max(1, int(backoff_seconds)),
                        now,
                        None,
                        now,
                        now,
                    ),
                )
        return {
            "job_id": job_id,
            "idempotency_key": idempotency_key,
            "job_type": job_type,
            "status": "pending",
            "deduplicated": False,
        }

    def claim_next_daemon_job(self, *, now_iso: str | None = None) -> dict[str, Any] | None:
        now = now_iso or _utc_now()
        p = self.ph
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"SELECT job_id, idempotency_key, job_type, priority, status, payload_json, "
                f"checkpoint_json, attempt, max_attempts, backoff_seconds, created_at "
                f"FROM daemon_jobs WHERE tenant_id = {p} "
                f"AND status IN ('pending', 'retry_scheduled') AND next_run_at <= {p} "
                f"ORDER BY priority DESC, seq ASC LIMIT 1",
                (self.tenant_id, now),
            )
            row = cur.fetchone()
            if row is None:
                return None
            job_id = str(row[0])
            new_attempt = int(row[7]) + 1
            cur.execute(
                f"UPDATE daemon_jobs SET status = 'running', attempt = {p}, updated_at = {p} "
                f"WHERE tenant_id = {p} AND job_id = {p}",
                (new_attempt, now, self.tenant_id, job_id),
            )
        return {
            "job_id": job_id,
            "idempotency_key": str(row[1]),
            "job_type": str(row[2]),
            "priority": int(row[3]),
            "status": "running",
            "payload": json.loads(row[5]),
            "checkpoint": json.loads(row[6]),
            "attempt": new_attempt,
            "max_attempts": int(row[8]),
            "backoff_seconds": int(row[9]),
            "created_at": str(row[10]),
        }

    def checkpoint_daemon_job(self, job_id: str, checkpoint: dict[str, Any]) -> None:
        p = self.ph
        now = _utc_now()
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"UPDATE daemon_jobs SET checkpoint_json = {p}, updated_at = {p} "
                f"WHERE tenant_id = {p} AND job_id = {p}",
                (json.dumps(checkpoint, sort_keys=True), now, self.tenant_id, job_id),
            )

    def finish_daemon_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        next_run_at: str | None = None,
    ) -> None:
        p = self.ph
        now = _utc_now()
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"UPDATE daemon_jobs SET status = {p}, result_json = {p}, last_error = {p}, "
                f"next_run_at = {p}, updated_at = {p} WHERE tenant_id = {p} AND job_id = {p}",
                (
                    status,
                    json.dumps(result, sort_keys=True, default=str) if result is not None else None,
                    error,
                    next_run_at or now,
                    now,
                    self.tenant_id,
                    job_id,
                ),
            )

    def list_daemon_jobs(
        self, *, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        capped = max(1, min(limit, 500))
        p = self.ph
        with self._tx_fn(write=False) as cur:
            if status:
                cur.execute(
                    f"SELECT job_id, idempotency_key, job_type, priority, status, payload_json, "
                    f"checkpoint_json, result_json, attempt, max_attempts, backoff_seconds, "
                    f"next_run_at, last_error, created_at, updated_at "
                    f"FROM daemon_jobs WHERE tenant_id = {p} AND status = {p} "
                    f"ORDER BY seq DESC LIMIT {p}",
                    (self.tenant_id, status, capped),
                )
            else:
                cur.execute(
                    f"SELECT job_id, idempotency_key, job_type, priority, status, payload_json, "
                    f"checkpoint_json, result_json, attempt, max_attempts, backoff_seconds, "
                    f"next_run_at, last_error, created_at, updated_at "
                    f"FROM daemon_jobs WHERE tenant_id = {p} ORDER BY seq DESC LIMIT {p}",
                    (self.tenant_id, capped),
                )
            rows = cur.fetchall()
        return [
            {
                "job_id": str(r[0]),
                "idempotency_key": str(r[1]),
                "job_type": str(r[2]),
                "priority": int(r[3]),
                "status": str(r[4]),
                "payload": json.loads(r[5]),
                "checkpoint": json.loads(r[6]),
                "result": json.loads(r[7]) if r[7] else None,
                "attempt": int(r[8]),
                "max_attempts": int(r[9]),
                "backoff_seconds": int(r[10]),
                "next_run_at": str(r[11]),
                "last_error": r[12],
                "created_at": str(r[13]),
                "updated_at": str(r[14]),
            }
            for r in rows
        ]

    def get_watcher_checkpoint(self, watcher_key: str) -> dict[str, Any] | None:
        p = self.ph
        with self._tx_fn(write=False) as cur:
            cur.execute(
                f"SELECT cursor_value, metadata_json, updated_at FROM daemon_checkpoints "
                f"WHERE tenant_id = {p} AND watcher_key = {p}",
                (self.tenant_id, watcher_key),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "watcher_key": watcher_key,
            "cursor": str(row[0]),
            "metadata": json.loads(row[1]),
            "updated_at": str(row[2]),
        }

    def set_watcher_checkpoint(
        self, watcher_key: str, cursor_value: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        p = self.ph
        now = _utc_now()
        meta_str = json.dumps(metadata or {}, sort_keys=True)
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"SELECT watcher_key FROM daemon_checkpoints "
                f"WHERE tenant_id = {p} AND watcher_key = {p}",
                (self.tenant_id, watcher_key),
            )
            exists = cur.fetchone() is not None
            if exists:
                cur.execute(
                    f"UPDATE daemon_checkpoints SET cursor_value = {p}, metadata_json = {p}, "
                    f"updated_at = {p} WHERE tenant_id = {p} AND watcher_key = {p}",
                    (cursor_value, meta_str, now, self.tenant_id, watcher_key),
                )
            else:
                cur.execute(
                    f"INSERT INTO daemon_checkpoints "
                    f"(tenant_id, watcher_key, cursor_value, metadata_json, updated_at) "
                    f"VALUES ({p}, {p}, {p}, {p}, {p})",
                    (self.tenant_id, watcher_key, cursor_value, meta_str, now),
                )
        return {
            "watcher_key": watcher_key,
            "cursor": cursor_value,
            "metadata": metadata or {},
            "updated_at": now,
        }

    def get_budget_usage(self, budget_date: str | None = None) -> dict[str, Any]:
        day = budget_date or datetime.now(UTC).strftime("%Y-%m-%d")
        p = self.ph
        with self._tx_fn(write=False) as cur:
            cur.execute(
                f"SELECT tokens_used, edge_tokens_used, cloud_tokens_used, "
                f"jobs_executed, updated_at "
                f"FROM daemon_budget WHERE tenant_id = {p} AND budget_date = {p}",
                (self.tenant_id, day),
            )
            row = cur.fetchone()
        if row is None:
            return {
                "budget_date": day,
                "tokens_used": 0,
                "edge_tokens_used": 0,
                "cloud_tokens_used": 0,
                "jobs_executed": 0,
                "updated_at": _utc_now(),
            }
        return {
            "budget_date": day,
            "tokens_used": int(row[0]),
            "edge_tokens_used": int(row[1]),
            "cloud_tokens_used": int(row[2]),
            "jobs_executed": int(row[3]),
            "updated_at": str(row[4]),
        }

    def add_budget_usage(
        self,
        *,
        edge_tokens: int = 0,
        cloud_tokens: int = 0,
        jobs_delta: int = 0,
        budget_date: str | None = None,
    ) -> dict[str, Any]:
        day = budget_date or datetime.now(UTC).strftime("%Y-%m-%d")
        now = _utc_now()
        p = self.ph
        total_delta = max(0, int(edge_tokens)) + max(0, int(cloud_tokens))
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"SELECT tokens_used, edge_tokens_used, cloud_tokens_used, jobs_executed "
                f"FROM daemon_budget WHERE tenant_id = {p} AND budget_date = {p}",
                (self.tenant_id, day),
            )
            row = cur.fetchone()
            if row is None:
                tokens_used = total_delta
                edge_used = max(0, int(edge_tokens))
                cloud_used = max(0, int(cloud_tokens))
                jobs_exec = max(0, int(jobs_delta))
                cur.execute(
                    f"INSERT INTO daemon_budget "
                    f"(tenant_id, budget_date, tokens_used, edge_tokens_used, "
                    f"cloud_tokens_used, jobs_executed, updated_at) "
                    f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
                    (self.tenant_id, day, tokens_used, edge_used, cloud_used, jobs_exec, now),
                )
            else:
                tokens_used = int(row[0]) + total_delta
                edge_used = int(row[1]) + max(0, int(edge_tokens))
                cloud_used = int(row[2]) + max(0, int(cloud_tokens))
                jobs_exec = int(row[3]) + max(0, int(jobs_delta))
                cur.execute(
                    f"UPDATE daemon_budget SET tokens_used = {p}, edge_tokens_used = {p}, "
                    f"cloud_tokens_used = {p}, jobs_executed = {p}, updated_at = {p} "
                    f"WHERE tenant_id = {p} AND budget_date = {p}",
                    (tokens_used, edge_used, cloud_used, jobs_exec, now, self.tenant_id, day),
                )
        return {
            "budget_date": day,
            "tokens_used": tokens_used,
            "edge_tokens_used": edge_used,
            "cloud_tokens_used": cloud_used,
            "jobs_executed": jobs_exec,
            "updated_at": now,
        }

    def save_overnight_finding(self, finding: dict[str, Any]) -> dict[str, Any]:
        now = finding.get("created_at") or _utc_now()
        p = self.ph
        fid = str(finding["finding_id"])
        before_json = json.dumps(finding.get("before") or {}, sort_keys=True, default=str)
        after_json = json.dumps(finding.get("after") or {}, sort_keys=True, default=str)
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"SELECT finding_id FROM overnight_findings "
                f"WHERE tenant_id = {p} AND finding_id = {p}",
                (self.tenant_id, fid),
            )
            exists = cur.fetchone() is not None
            if exists:
                cur.execute(
                    f"UPDATE overnight_findings SET run_id = {p}, category = {p}, severity = {p}, "
                    f"risk_score = {p}, title = {p}, summary = {p}, before_json = {p}, "
                    f"after_json = {p}, target_event_hash = {p}, cell_id = {p}, status = {p}, "
                    f"signed_off_by = {p}, signed_off_at = {p} "
                    f"WHERE tenant_id = {p} AND finding_id = {p}",
                    (
                        str(finding["run_id"]),
                        str(finding["category"]),
                        str(finding["severity"]),
                        int(finding["risk_score"]),
                        str(finding["title"]),
                        str(finding["summary"]),
                        before_json,
                        after_json,
                        finding.get("target_event_hash"),
                        finding.get("cell_id"),
                        str(finding.get("status") or "open"),
                        finding.get("signed_off_by"),
                        finding.get("signed_off_at"),
                        self.tenant_id,
                        fid,
                    ),
                )
            else:
                phs = ", ".join([p] * 16)
                cur.execute(
                    "INSERT INTO overnight_findings "
                    "(tenant_id, finding_id, run_id, category, severity, risk_score, title, "
                    "summary, before_json, after_json, target_event_hash, cell_id, status, "
                    "signed_off_by, signed_off_at, created_at) "
                    f"VALUES ({phs})",
                    (
                        self.tenant_id,
                        fid,
                        str(finding["run_id"]),
                        str(finding["category"]),
                        str(finding["severity"]),
                        int(finding["risk_score"]),
                        str(finding["title"]),
                        str(finding["summary"]),
                        before_json,
                        after_json,
                        finding.get("target_event_hash"),
                        finding.get("cell_id"),
                        str(finding.get("status") or "open"),
                        finding.get("signed_off_by"),
                        finding.get("signed_off_at"),
                        now,
                    ),
                )
        return dict(finding)

    def list_overnight_findings(
        self, *, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        capped = max(1, min(limit, 500))
        p = self.ph
        with self._tx_fn(write=False) as cur:
            if status:
                cur.execute(
                    f"SELECT finding_id, run_id, category, severity, risk_score, title, summary, "
                    f"before_json, after_json, target_event_hash, cell_id, status, "
                    f"signed_off_by, signed_off_at, created_at "
                    f"FROM overnight_findings WHERE tenant_id = {p} AND status = {p} "
                    f"ORDER BY risk_score DESC, created_at DESC LIMIT {p}",
                    (self.tenant_id, status, capped),
                )
            else:
                cur.execute(
                    f"SELECT finding_id, run_id, category, severity, risk_score, title, summary, "
                    f"before_json, after_json, target_event_hash, cell_id, status, "
                    f"signed_off_by, signed_off_at, created_at "
                    f"FROM overnight_findings WHERE tenant_id = {p} "
                    f"ORDER BY risk_score DESC, created_at DESC LIMIT {p}",
                    (self.tenant_id, capped),
                )
            rows = cur.fetchall()
        return [
            {
                "finding_id": str(r[0]),
                "run_id": str(r[1]),
                "category": str(r[2]),
                "severity": str(r[3]),
                "risk_score": int(r[4]),
                "title": str(r[5]),
                "summary": str(r[6]),
                "before": json.loads(r[7]),
                "after": json.loads(r[8]),
                "target_event_hash": r[9],
                "cell_id": r[10],
                "status": str(r[11]),
                "signed_off_by": r[12],
                "signed_off_at": r[13],
                "created_at": str(r[14]),
            }
            for r in rows
        ]

    def resolve_overnight_finding(
        self, finding_id: str, *, signed_off_by: str, signed_off_at: str | None = None
    ) -> bool:
        p = self.ph
        when = signed_off_at or _utc_now()
        with self._tx_fn(write=True) as cur:
            cur.execute(
                f"UPDATE overnight_findings SET status = 'signed_off', "
                f"signed_off_by = {p}, signed_off_at = {p} "
                f"WHERE tenant_id = {p} AND finding_id = {p}",
                (signed_off_by, when, self.tenant_id, finding_id),
            )
            return getattr(cur, "rowcount", 0) > 0
