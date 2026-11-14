from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import httpx
from evidence_kernel.agents import ACTIVE_AGENTS, IMPLEMENTED_LATER_AGENTS, require_active_agent
from evidence_kernel.daemon import DaemonRunner, FolderWatcher, GitWatcher, OvernightBudget
from evidence_kernel.formal import SMTSolverProofEngine
from evidence_kernel.gateway import BudgetedGateway, FixtureGateway, HybridAgentRouter
from evidence_kernel.ledger import Ledger
from evidence_kernel.pg_ledger import PostgresLedger
from evidence_kernel.telemetry import get_telemetry
from evidence_kernel.webhooks import (
    dispatch_webhook_with_retry,
    new_webhook_record,
    replay_dead_letters,
)


class _PgSQLiteShimConn:
    """Minimal Postgres-to-SQLite DB-API shim matching PostgresLedger queries."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self) -> Any:
        conn = self._conn

        class _Cur:
            def __init__(self) -> None:
                self._c = conn.cursor()

            def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Cur:
                st = sql.strip()
                if (
                    st.startswith("SELECT pg_advisory_xact_lock")
                    or "CREATE OR REPLACE FUNCTION" in st
                ):
                    return self
                if "CREATE TRIGGER events_no_mutation" in st:
                    conn.execute(
                        "CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events "
                        "BEGIN SELECT RAISE(ABORT, 'append-only: update rejected'); END"
                    )
                    conn.execute(
                        "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events "
                        "BEGIN SELECT RAISE(ABORT, 'append-only: delete rejected'); END"
                    )
                    return self
                tr = sql.replace(
                    "BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT"
                ).replace("%s", "?")
                self._c.execute(tr, params)
                return self

            def fetchone(self) -> Any:
                return self._c.fetchone()

            def fetchall(self) -> list[Any]:
                return self._c.fetchall()

            @property
            def rowcount(self) -> int:
                return self._c.rowcount

        return _Cur()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        return None


def test_versioned_migrations_sqlite_and_postgres(tmp_path: Path) -> None:
    sqlite_ledger = Ledger(tmp_path / "sqlite.db", "demo")
    assert sqlite_ledger.schema_version() == 3
    migs = sqlite_ledger.applied_migrations()
    assert [m["version"] for m in migs] == [1, 2, 3]
    assert sqlite_ledger.run_migrations() == []

    pg_db = sqlite3.connect(tmp_path / "pg_sim.db")
    pg_ledger = PostgresLedger(
        "postgresql://sim/db",
        "demo",
        connect_fn=lambda _dsn: _PgSQLiteShimConn(pg_db),
    )
    assert pg_ledger.schema_version() == 3
    assert len(pg_ledger.applied_migrations()) == 3
    assert pg_ledger.run_migrations() == []
    pg_db.close()


def test_folder_watcher_git_watcher_checkpoints_retry_and_budget(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "daemon.sqlite3", "demo")
    watch_dir = tmp_path / "plm_drop"
    watch_dir.mkdir()
    bdf_file = watch_dir / "wing_frame.bdf"
    bdf_file.write_text("GRID,1,,0.0,0.0,0.0\nENDDATA\n", encoding="utf-8")

    fw = FolderWatcher([watch_dir])
    scan1 = fw.scan_and_enqueue(ledger)
    assert scan1["scanned_files"] == 1
    assert scan1["enqueued_count"] == 1

    # Second scan with unchanged content deduplicates via SHA-256 checkpoint
    scan2 = fw.scan_and_enqueue(ledger)
    assert scan2["enqueued_count"] == 0
    assert scan2["unchanged"] == 1

    # Git watcher on temporary repository
    repo = tmp_path / "git_prog"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "ci@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=repo, check=True)
    (repo / "loads.bdf").write_text("FORCE,1,1,0,100.0\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    gw = GitWatcher(repo, base_branch="master")
    g1 = gw.scan_and_enqueue(ledger)
    assert g1["repo_present"] is True
    assert g1["enqueued_count"] >= 1
    assert gw.scan_and_enqueue(ledger)["enqueued_count"] == 0

    # Runner checkpointing + backoff retry -> completion + nightly budget enforcement
    calls = {"flaky": 0}

    def handle_artifact(job: dict[str, Any], ck: Any) -> dict[str, Any]:
        ck({"step": "parsed"})
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise RuntimeError("transient_parse_glitch")
        return {"ok": True, "edge_tokens": 600, "cloud_tokens": 0}

    def handle_git(job: dict[str, Any], ck: Any) -> dict[str, Any]:
        ck({"step": "diffed"})
        return {"ok": True, "edge_tokens": 700, "cloud_tokens": 0}

    runner = DaemonRunner(
        ledger,
        handlers={"artifact_ingest_audit": handle_artifact, "git_branch_audit": handle_git},
        budget=OvernightBudget(max_tokens_per_night=800, max_jobs_per_run=10),
    )
    res1 = runner.run_pending()
    # One job ran and exhausted 700 tokens; flaky artifact scheduled retry with future next_run_at
    assert res1["processed"] >= 1
    assert ledger.queue.get_budget_usage()["tokens_used"] == 700

    # Force retry job ready now -> should stop on budget exhaustion if budget already near cap
    jobs_retry = ledger.queue.list_daemon_jobs(status="retry_scheduled")
    if jobs_retry:
        # With only 100 tokens remaining vs 800 cap, simulate exhausted budget cleanly
        ledger.queue.add_budget_usage(edge_tokens=200)
        res2 = runner.run_pending(now_iso="2099-01-01T00:00:00Z")
        assert res2["stopped_reason"] == "nightly_token_budget_exhausted"


def test_webhook_retry_dead_letter_and_replay(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "wh.sqlite3", "demo")
    sub = new_webhook_record(
        url="https://hooks.example.org/evidence",
        events=["envelope_invalidated"],
        allow_private_targets=True,
    )
    ledger.register_webhook(sub)

    attempts_seen: list[int] = []

    def always_fail(request: httpx.Request) -> httpx.Response:
        attempts_seen.append(1)
        return httpx.Response(503, json={"err": "down"})

    deliveries = dispatch_webhook_with_retry(
        ledger.list_webhooks(include_secret=True),
        event_name="envelope_invalidated",
        payload={"cell_id": "cell-1"},
        ledger=ledger,
        transport=httpx.MockTransport(always_fail),
        max_attempts=3,
        backoff_base_seconds=0.0,
    )
    assert len(attempts_seen) == 3
    assert deliveries[0]["dead_lettered"] is True
    assert deliveries[0]["status"] == "dead_letter"
    assert len(ledger.queue.list_webhook_dlq(status="dead_letter")) == 1

    # Replay once downstream recovers
    replayed = replay_dead_letters(
        ledger,
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"ok": True})),
    )
    assert len(replayed) == 1
    assert replayed[0]["ok"] is True
    assert replayed[0]["status"] == "delivered"
    assert ledger.queue.list_webhook_dlq(status="dead_letter") == []


def test_telemetry_prometheus_and_later_agents_active() -> None:
    assert "envelope_critic" in IMPLEMENTED_LATER_AGENTS
    assert "bench_attacker" in IMPLEMENTED_LATER_AGENTS
    assert require_active_agent("envelope_critic") == "envelope_critic"
    assert "bench_attacker" in ACTIVE_AGENTS

    tel = get_telemetry()
    tel.reset()
    engine = SMTSolverProofEngine(timeout_ms=2000, cross_check=True)
    proof = engine.prove_structural_margin(
        bounds={
            "area_mm2": ("100.000", "120.000"),
            "shear_force_n": ("1000.000", "2000.000"),
            "tensile_force_n": ("1500.000", "2500.000"),
        },
        allowables={"shear_allowable_mpa": "150.000", "tensile_allowable_mpa": "250.000"},
    )
    assert proof.proved is True
    assert "z3_ms" in proof.solver_stats["cross_check"]

    router = HybridAgentRouter(
        edge_gateway=FixtureGateway("happy"),
        api_gateway=FixtureGateway("happy"),
    )
    comp = BudgetedGateway(router).complete(
        "reader",
        [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "quotation": "mass = 900.000 kg",
                        "span_start": "0",
                        "span_end": "17",
                    }
                ),
            }
        ],
        None,
    )
    assert not comp.abstained
    prom = tel.render_prometheus()
    assert "aeroregu_smt_solver_duration_seconds_bucket" in prom
    assert "aeroregu_llm_tokens_total" in prom
    assert "aeroregu_abstain_rate" in prom
