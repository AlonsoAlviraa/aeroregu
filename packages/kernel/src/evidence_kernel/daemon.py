"""Persistent continuous-verification worker queue, checkpoints, budget guard, and watchers."""

from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from evidence_kernel.telemetry import get_telemetry

DEFAULT_WATCH_EXTENSIONS = frozenset(
    {
        ".bdf",
        ".dat",
        ".nas",
        ".inp",
        ".f06",
        ".stp",
        ".step",
        ".p21",
        ".igs",
        ".iges",
        ".xml",
        ".catxml",
        ".pdf",
        ".docx",
        ".xlsx",
    }
)


def _utc_iso(offset_seconds: float = 0.0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class OvernightBudget:
    """Per-night token, job count, and wall-time budget for unsupervised daemon runs."""

    max_tokens_per_night: int = 250_000
    max_cloud_tokens_per_night: int = 50_000
    max_jobs_per_run: int = 200
    max_wall_seconds: float = 3600.0
    _started_monotonic: float = field(default_factory=time.monotonic, init=False, repr=False)
    _jobs_in_run: int = field(default=0, init=False, repr=False)

    def reset_run_window(self) -> None:
        self._started_monotonic = time.monotonic()
        self._jobs_in_run = 0

    def can_consume(
        self,
        ledger: Any,
        *,
        planned_edge_tokens: int = 0,
        planned_cloud_tokens: int = 0,
    ) -> tuple[bool, str | None]:
        elapsed = time.monotonic() - self._started_monotonic
        if elapsed > self.max_wall_seconds:
            return False, "nightly_wall_clock_exhausted"
        if self._jobs_in_run >= self.max_jobs_per_run:
            return False, "nightly_job_cap_reached"
        if hasattr(ledger, "queue"):
            usage = ledger.queue.get_budget_usage()
            if usage["tokens_used"] + planned_edge_tokens + planned_cloud_tokens > (
                self.max_tokens_per_night
            ):
                return False, "nightly_token_budget_exhausted"
            if usage["cloud_tokens_used"] + planned_cloud_tokens > self.max_cloud_tokens_per_night:
                return False, "nightly_cloud_token_budget_exhausted"
        return True, None

    def record_execution(
        self,
        ledger: Any,
        *,
        edge_tokens: int = 0,
        cloud_tokens: int = 0,
    ) -> dict[str, Any]:
        self._jobs_in_run += 1
        if hasattr(ledger, "queue"):
            return ledger.queue.add_budget_usage(
                edge_tokens=edge_tokens,
                cloud_tokens=cloud_tokens,
                jobs_delta=1,
            )
        return {
            "tokens_used": edge_tokens + cloud_tokens,
            "edge_tokens_used": edge_tokens,
            "cloud_tokens_used": cloud_tokens,
            "jobs_executed": self._jobs_in_run,
        }


class FolderWatcher:
    """Watches shared/PLM folders for new or modified artifacts using incremental checkpoints."""

    def __init__(
        self,
        directories: list[Path | str],
        *,
        extensions: frozenset[str] = DEFAULT_WATCH_EXTENSIONS,
        recursive: bool = True,
    ) -> None:
        self.directories = [Path(d).expanduser().resolve() for d in directories]
        self.extensions = {ext.lower() for ext in extensions}
        self.recursive = recursive

    @staticmethod
    def _file_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def scan_and_enqueue(self, ledger: Any, *, priority: int = 75) -> dict[str, Any]:
        if not hasattr(ledger, "queue"):
            return {"scanned_files": 0, "enqueued": [], "unchanged": 0}
        enqueued: list[dict[str, Any]] = []
        unchanged = 0
        scanned = 0

        for base_dir in self.directories:
            if not base_dir.is_dir():
                continue
            iterator = base_dir.rglob("*") if self.recursive else base_dir.iterdir()
            for file_path in sorted(iterator):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in self.extensions:
                    continue
                scanned += 1
                digest = self._file_sha256(file_path)
                ck_key = f"folder:{file_path.resolve()}"
                prev = ledger.queue.get_watcher_checkpoint(ck_key)
                if prev is not None and prev["cursor"] == digest:
                    unchanged += 1
                    continue
                job = ledger.queue.enqueue_daemon_job(
                    job_type="artifact_ingest_audit",
                    payload={
                        "file_path": str(file_path.resolve()),
                        "filename": file_path.name,
                        "suffix": file_path.suffix.lower(),
                        "sha256": digest,
                        "previous_sha256": prev["cursor"] if prev else None,
                    },
                    idempotency_key=f"file:{file_path.resolve()}:{digest}",
                    priority=priority,
                )
                ledger.queue.set_watcher_checkpoint(
                    ck_key,
                    digest,
                    {"filename": file_path.name, "size_bytes": file_path.stat().st_size},
                )
                enqueued.append(job)

        return {
            "scanned_files": scanned,
            "enqueued_count": len(enqueued),
            "unchanged": unchanged,
            "enqueued": enqueued,
        }


class GitWatcher:
    """Watches local Git branches / PR diffs and enqueues changed artifact verification jobs."""

    def __init__(self, repo_path: Path | str, *, base_branch: str = "master") -> None:
        self.repo_path = Path(repo_path).expanduser().resolve()
        self.base_branch = base_branch

    def _run_git(self, args: list[str]) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.repo_path), *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"git exited {proc.returncode}")
        return proc.stdout.strip()

    def scan_and_enqueue(self, ledger: Any, *, priority: int = 85) -> dict[str, Any]:
        if not hasattr(ledger, "queue") or not (self.repo_path / ".git").exists():
            return {"repo_present": False, "branches_checked": 0, "enqueued": []}

        refs_raw = self._run_git(
            ["for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads"]
        )
        branches: list[tuple[str, str]] = []
        for line in refs_raw.splitlines():
            parts = line.strip().split()
            if len(parts) == 2:
                branches.append((parts[0], parts[1]))

        enqueued: list[dict[str, Any]] = []
        for branch_name, commit_sha in branches:
            ck_key = f"git:{self.repo_path}:{branch_name}"
            prev = ledger.queue.get_watcher_checkpoint(ck_key)
            if prev is not None and prev["cursor"] == commit_sha:
                continue

            changed_files: list[str] = []
            compare_ref = prev["cursor"] if prev is not None else self.base_branch
            try:
                if compare_ref and compare_ref != commit_sha:
                    diff_out = self._run_git(
                        ["diff", "--name-only", f"{compare_ref}..{commit_sha}"]
                    )
                    changed_files = [ln.strip() for ln in diff_out.splitlines() if ln.strip()]
            except RuntimeError:
                changed_files = []

            job = ledger.queue.enqueue_daemon_job(
                job_type="git_branch_audit",
                payload={
                    "repo_path": str(self.repo_path),
                    "branch": branch_name,
                    "commit_sha": commit_sha,
                    "base_ref": compare_ref,
                    "changed_files": changed_files,
                },
                idempotency_key=f"git:{branch_name}:{commit_sha}",
                priority=priority,
            )
            ledger.queue.set_watcher_checkpoint(
                ck_key,
                commit_sha,
                {"branch": branch_name, "changed_files": len(changed_files)},
            )
            enqueued.append(job)

        return {
            "repo_present": True,
            "branches_checked": len(branches),
            "enqueued_count": len(enqueued),
            "enqueued": enqueued,
        }


JobHandler = Callable[[dict[str, Any], Callable[[dict[str, Any]], None]], dict[str, Any]]


class DaemonRunner:
    """Executes persistent background verification jobs with checkpoints, retries & budget."""

    def __init__(
        self,
        ledger: Any,
        *,
        handlers: dict[str, JobHandler] | None = None,
        budget: OvernightBudget | None = None,
        backoff_multiplier: float = 2.0,
    ) -> None:
        self.ledger = ledger
        self.handlers: dict[str, JobHandler] = dict(handlers or {})
        self.budget = budget or OvernightBudget()
        self.backoff_multiplier = backoff_multiplier

    def register_handler(self, job_type: str, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    def run_pending(self, *, now_iso: str | None = None) -> dict[str, Any]:
        """Drain ready queued jobs until empty or budget cap reached."""
        if not hasattr(self.ledger, "queue"):
            return {"processed": 0, "abstained": True, "reason": "queue_unsupported", "jobs": []}
        self.budget.reset_run_window()
        tel = get_telemetry()
        processed_jobs: list[dict[str, Any]] = []
        stopped_reason: str | None = None

        while True:
            ok_budget, budget_reason = self.budget.can_consume(self.ledger)
            if not ok_budget:
                stopped_reason = budget_reason
                tel.record_verification(
                    stage="daemon_budget", abstained=True, reason=stopped_reason or ""
                )
                break

            job = self.ledger.queue.claim_next_daemon_job(now_iso=now_iso)
            if job is None:
                break

            job_id = job["job_id"]
            job_type = job["job_type"]
            handler = self.handlers.get(job_type)
            if handler is None:
                self.ledger.queue.finish_daemon_job(
                    job_id,
                    status="failed",
                    error=f"unregistered_job_type:{job_type}",
                )
                tel.record_daemon_job(job_type, "failed")
                processed_jobs.append({"job_id": job_id, "job_type": job_type, "status": "failed"})
                continue

            def _save_checkpoint(state: dict[str, Any], _jid: str = job_id) -> None:
                merged = {**job["checkpoint"], **state}
                job["checkpoint"] = merged
                self.ledger.queue.checkpoint_daemon_job(_jid, merged)

            try:
                result = handler(job, _save_checkpoint)
                edge_tok = int(result.get("edge_tokens", 0))
                cloud_tok = int(result.get("cloud_tokens", 0))
                self.ledger.queue.finish_daemon_job(job_id, status="completed", result=result)
                self.budget.record_execution(
                    self.ledger,
                    edge_tokens=edge_tok,
                    cloud_tokens=cloud_tok,
                )
                tel.record_daemon_job(job_type, "completed")
                tel.record_verification(stage="daemon_job", abstained=False)
                processed_jobs.append(
                    {
                        "job_id": job_id,
                        "job_type": job_type,
                        "status": "completed",
                        "result": result,
                    }
                )
            except Exception as exc:
                attempt = int(job["attempt"])
                max_attempts = int(job["max_attempts"])
                base_backoff = int(job["backoff_seconds"])
                if attempt >= max_attempts:
                    self.ledger.queue.finish_daemon_job(
                        job_id,
                        status="dead_letter",
                        error=str(exc),
                    )
                    tel.record_daemon_job(job_type, "dead_letter")
                    processed_jobs.append(
                        {
                            "job_id": job_id,
                            "job_type": job_type,
                            "status": "dead_letter",
                            "error": str(exc),
                        }
                    )
                else:
                    delay_s = max(1, int(base_backoff * (self.backoff_multiplier ** (attempt - 1))))
                    next_at = _utc_iso(offset_seconds=delay_s)
                    self.ledger.queue.finish_daemon_job(
                        job_id,
                        status="retry_scheduled",
                        error=str(exc),
                        next_run_at=next_at,
                    )
                    tel.record_daemon_job(job_type, "retry_scheduled")
                    processed_jobs.append(
                        {
                            "job_id": job_id,
                            "job_type": job_type,
                            "status": "retry_scheduled",
                            "next_run_at": next_at,
                            "error": str(exc),
                        }
                    )

        usage = self.ledger.queue.get_budget_usage()
        return {
            "processed": len(processed_jobs),
            "stopped_reason": stopped_reason,
            "budget_usage": usage,
            "jobs": processed_jobs,
        }
