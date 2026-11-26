"""Enterprise ops, blobs, webhooks, daemon jobs, overnight watch, threads & SBOM router."""

from __future__ import annotations

import base64
import hashlib
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evidence_coverage.adversarial import run_bench_attacker, run_envelope_critic
from evidence_coverage.collaboration_ecn import get_review_thread_store
from evidence_coverage.cross_artifact import audit_cross_artifact_consistency
from evidence_coverage.ma_readiness import evaluate_ma_technical_readiness
from evidence_coverage.overnight import (
    batch_human_signoff,
    build_morning_briefing,
    default_showcase_artifacts,
    run_overnight_cycle,
)
from evidence_coverage.qualification_aid import run_iq_oq_qualification_suite
from evidence_kernel.daemon import DaemonRunner, OvernightBudget
from evidence_kernel.hsm_eidas_scim import verify_sbom_and_dependencies
from evidence_kernel.ledger import SIGN_OFF_STATEMENT
from evidence_kernel.storage import BlobStoreError, open_blob_store
from evidence_kernel.telemetry import get_telemetry
from evidence_kernel.webhooks import WebhookError, new_webhook_record, replay_dead_letters
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse


def build_enterprise_ops_router(
    *,
    ok_fn: Callable[[str, Any, Any], dict[str, Any]],
    abstain_fn: Callable[[str, Any, str], dict[str, Any]],
    check_endpoint_access_fn: Callable[..., tuple[str | None, JSONResponse | None]],
    is_production_mode_fn: Callable[[], bool],
    actor_from_request_fn: Callable[..., str | None],
    session_actor_fn: Callable[..., str | None],
    validate_tenant_fn: Callable[[Any], str | None],
    open_ledger_fn: Callable[[str], Any],
    decode_body_bytes_fn: Callable[
        [dict[str, Any], str, str], tuple[bytes | None, JSONResponse | None]
    ],
    evidence_home_fn: Callable[[], Path],
    now_fn: Callable[[], str],
    repo_root_path: Path,
    demo_tenant: str = "demo",
) -> APIRouter:
    """Create APIRouter for blobs, webhooks, observability, daemons, overnight, reviews & SBOM."""
    router = APIRouter(tags=["enterprise-ops"])
    _briefing_cache: dict[tuple[str, str], dict[str, Any]] = {}
    _briefing_cache_lock = threading.RLock()

    @router.get("/blobs")
    def blobs_list(request: Request, tenant_id: str = demo_tenant) -> JSONResponse:
        checked_tenant = validate_tenant_fn(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                abstain_fn("blob_store@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        if (
            is_production_mode_fn()
            and actor_from_request_fn(request, tenant_id=checked_tenant) is None
        ):
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        store = open_blob_store(evidence_home_fn())
        return JSONResponse(
            ok_fn(
                "blob_store@1.0.0",
                {"backend": store.backend_name},
                {"backend": store.backend_name, "blobs": store.list_blobs()},
            )
        )

    @router.post("/blobs")
    def blobs_upload(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("blob_store@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = actor_from_request_fn(request, tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        filename = str(body.get("filename") or "artifact.bin")
        raw, err = decode_body_bytes_fn(body, "blob_store@1.0.0", filename)
        if err is not None or raw is None:
            return err or JSONResponse(
                abstain_fn("blob_store@1.0.0", {}, "missing_content"), status_code=400
            )
        ctype = str(body.get("content_type") or "application/octet-stream")
        meta = open_blob_store(evidence_home_fn()).put_blob(
            raw, content_type=ctype, filename=filename
        )
        return JSONResponse(ok_fn("blob_store@1.0.0", {"sha256": meta["sha256"]}, meta))

    @router.get("/blobs/{sha256_hex}")
    def blobs_download(sha256_hex: str, request: Request, tenant_id: str = demo_tenant) -> Response:
        checked_tenant = validate_tenant_fn(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                abstain_fn("blob_store@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        if (
            is_production_mode_fn()
            and actor_from_request_fn(request, tenant_id=checked_tenant) is None
        ):
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        store = open_blob_store(evidence_home_fn())
        try:
            data = store.get_blob(sha256_hex)
            meta = store.head_blob(sha256_hex) or {}
        except BlobStoreError as exc:
            return JSONResponse(abstain_fn("blob_store@1.0.0", {}, str(exc)), status_code=400)
        except FileNotFoundError:
            return JSONResponse(
                abstain_fn("blob_store@1.0.0", {}, "blob_not_found"), status_code=404
            )
        return Response(
            content=data,
            media_type=str(meta.get("content_type") or "application/octet-stream"),
        )

    @router.get("/webhooks")
    def webhooks_list(request: Request, tenant_id: str = demo_tenant) -> JSONResponse:
        checked_tenant = validate_tenant_fn(tenant_id)
        if checked_tenant is None:
            return JSONResponse(abstain_fn("webhooks@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = actor_from_request_fn(request, tenant_id=checked_tenant)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(checked_tenant)
        return JSONResponse(
            ok_fn(
                "webhooks@1.0.0",
                {"tenant_id": checked_tenant},
                {
                    "webhooks": ledger.list_webhooks(),
                    "deliveries": ledger.list_webhook_deliveries(),
                },
            )
        )

    @router.post("/webhooks")
    def webhooks_register(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(abstain_fn("webhooks@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = actor_from_request_fn(request, tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(tenant_id)
        if ledger.actor_role(actor) not in {"admin", "cve", "human"}:
            return JSONResponse(
                abstain_fn("webhooks@1.0.0", {}, "admin_or_cve_required"), status_code=403
            )
        allow_private = (not is_production_mode_fn()) and bool(body.get("allow_private_targets"))
        try:
            record_obj = new_webhook_record(
                url=str(body.get("url") or ""),
                events=body.get("events"),
                secret=body.get("secret"),
                description=str(body.get("description") or ""),
                allow_private_targets=allow_private,
            )
        except WebhookError as exc:
            return JSONResponse(abstain_fn("webhooks@1.0.0", {}, str(exc)), status_code=400)
        saved = ledger.register_webhook(record_obj)
        return JSONResponse(ok_fn("webhooks@1.0.0", {"webhook_id": saved["webhook_id"]}, saved))

    @router.delete("/webhooks/{webhook_id}")
    def webhooks_delete(
        webhook_id: str, request: Request, tenant_id: str = demo_tenant
    ) -> JSONResponse:
        checked_tenant = validate_tenant_fn(tenant_id)
        if checked_tenant is None:
            return JSONResponse(abstain_fn("webhooks@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = actor_from_request_fn(request, tenant_id=checked_tenant)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(checked_tenant)
        if not ledger.delete_webhook(webhook_id):
            return JSONResponse(
                abstain_fn("webhooks@1.0.0", {}, "webhook_not_found"), status_code=404
            )
        return JSONResponse(ok_fn("webhooks@1.0.0", {"webhook_id": webhook_id}, {"deleted": True}))

    @router.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(
            content=get_telemetry().render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @router.get("/metrics/observability")
    def observability_metrics() -> JSONResponse:
        return JSONResponse(ok_fn("observability@1.0.0", {}, get_telemetry().snapshot()))

    @router.get("/metrics/prometheus")
    def prometheus_metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(
            get_telemetry().render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @router.get("/telemetry/otlp")
    def telemetry_otlp(trace_id: str | None = None) -> JSONResponse:
        return JSONResponse(
            ok_fn("observability@1.0.0", {}, get_telemetry().export_otlp(trace_id=trace_id))
        )

    @router.get("/system/persistence")
    def system_persistence(tenant_id: str = demo_tenant) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(
                abstain_fn("persistence@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger_fn(checked)
        backend = getattr(ledger, "backend_name", "sqlite")
        return JSONResponse(
            ok_fn(
                "persistence@1.0.0",
                {"tenant_id": checked},
                {
                    "backend": backend,
                    "postgres_configured": bool(os.environ.get("EVIDENCE_PG_DSN", "").strip()),
                    "production_mode": is_production_mode_fn(),
                    "schema_version": ledger.schema_version()
                    if hasattr(ledger, "schema_version")
                    else 0,
                    "applied_migrations": ledger.applied_migrations()
                    if hasattr(ledger, "applied_migrations")
                    else [],
                },
            )
        )

    @router.post("/system/migrations/run")
    def system_run_migrations(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("migrations@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(tenant_id)
        newly = ledger.run_migrations() if hasattr(ledger, "run_migrations") else []
        return JSONResponse(
            ok_fn(
                "migrations@1.0.0",
                {"tenant_id": tenant_id},
                {
                    "backend": getattr(ledger, "backend_name", "sqlite"),
                    "newly_applied_versions": newly,
                    "schema_version": ledger.schema_version()
                    if hasattr(ledger, "schema_version")
                    else 0,
                    "applied_migrations": ledger.applied_migrations()
                    if hasattr(ledger, "applied_migrations")
                    else [],
                },
            )
        )

    @router.get("/webhooks/dlq")
    def list_webhooks_dlq(
        tenant_id: str = demo_tenant, status: str | None = "dead_letter"
    ) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(
                abstain_fn("webhook_dlq@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger_fn(checked)
        items = (
            ledger.queue.list_webhook_dlq(status=status or None, limit=200)
            if hasattr(ledger, "queue")
            else []
        )
        return JSONResponse(
            ok_fn(
                "webhook_dlq@1.0.0", {"tenant_id": checked}, {"count": len(items), "items": items}
            )
        )

    @router.post("/webhooks/dlq/replay")
    def replay_webhooks_dlq(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("webhook_dlq@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(tenant_id)
        dids = body.get("delivery_ids")
        results = replay_dead_letters(
            ledger,
            delivery_ids=[str(x) for x in dids] if isinstance(dids, list) else None,
        )
        return JSONResponse(
            ok_fn(
                "webhook_dlq@1.0.0",
                {"tenant_id": tenant_id},
                {"replayed_count": len(results), "results": results},
            )
        )

    @router.get("/daemon/status")
    def daemon_status(tenant_id: str = demo_tenant) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(abstain_fn("daemon@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger_fn(checked)
        jobs = ledger.queue.list_daemon_jobs(limit=100) if hasattr(ledger, "queue") else []
        budget = ledger.queue.get_budget_usage() if hasattr(ledger, "queue") else {}
        counts: dict[str, int] = {}
        for j in jobs:
            st = j["status"]
            counts[st] = counts.get(st, 0) + 1
        return JSONResponse(
            ok_fn(
                "daemon@1.0.0",
                {"tenant_id": checked},
                {"job_counts": counts, "budget_usage": budget, "recent_jobs": jobs[:25]},
            )
        )

    @router.get("/daemon/jobs")
    def daemon_jobs(tenant_id: str = demo_tenant, status: str | None = None) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(abstain_fn("daemon@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger_fn(checked)
        jobs = (
            ledger.queue.list_daemon_jobs(status=status, limit=200)
            if hasattr(ledger, "queue")
            else []
        )
        return JSONResponse(
            ok_fn("daemon@1.0.0", {"tenant_id": checked}, {"count": len(jobs), "jobs": jobs})
        )

    @router.post("/ingest/pdf/async")
    def ingest_pdf_async(body: dict[str, Any]) -> JSONResponse:
        checked = validate_tenant_fn(str(body.get("tenant_id", demo_tenant)))
        if checked is None:
            return JSONResponse(abstain_fn("ingest@1.0.0", {}, "invalid_tenant"), status_code=400)
        filename = str(body.get("filename") or "document.pdf")
        ledger = open_ledger_fn(checked)
        if not hasattr(ledger, "queue"):
            return JSONResponse(
                abstain_fn("ingest@1.0.0", {"tenant_id": checked}, "queue_unavailable"),
                status_code=503,
            )
        payload: dict[str, Any] = {
            "filename": filename,
            "max_workers": int(body.get("max_workers", 4)),
            "chunk_pages": int(body.get("chunk_pages", 25)),
        }
        if body.get("content_base64"):
            raw = base64.b64decode(str(body["content_base64"]))
            meta = open_blob_store(evidence_home_fn()).put_blob(
                raw, content_type="application/pdf", filename=filename
            )
            payload["pdf_sha256"] = meta["sha256"]
        elif body.get("file_path"):
            payload["file_path"] = str(body["file_path"])
        else:
            return JSONResponse(
                abstain_fn("ingest@1.0.0", {"tenant_id": checked}, "missing_pdf_source"),
                status_code=400,
            )
        job_id = str(
            body.get("job_id")
            or f"pdf-{hashlib.sha256(f'{checked}:{filename}:{payload}'.encode()).hexdigest()[:12]}"
        )
        enqueued = ledger.queue.enqueue_daemon_job(
            idempotency_key=job_id, job_type="ingest_heavy_pdf", payload=payload
        )
        return JSONResponse(
            ok_fn("ingest@1.0.0", {"tenant_id": checked, "job_id": job_id}, enqueued),
            status_code=202,
        )

    @router.post("/daemon/jobs/run")
    def daemon_jobs_run(body: dict[str, Any] | None = None) -> JSONResponse:
        from evidence_ingest.pdf import build_heavy_pdf_daemon_handler

        req = body or {}
        checked = validate_tenant_fn(str(req.get("tenant_id", demo_tenant)))
        if checked is None:
            return JSONResponse(abstain_fn("daemon@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger_fn(checked)
        store = open_blob_store(evidence_home_fn())
        runner = DaemonRunner(
            ledger, handlers={"ingest_heavy_pdf": build_heavy_pdf_daemon_handler(blob_store=store)}
        )
        return JSONResponse(ok_fn("daemon@1.0.0", {"tenant_id": checked}, runner.run_pending()))

    @router.post("/audit/cross-artifact")
    def audit_cross_artifact_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("cross_artifact@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(tenant_id)
        src = default_showcase_artifacts() if bool(body.get("use_showcase")) else body
        res = audit_cross_artifact_consistency(
            ledger,
            requirements=src.get("requirements") or body.get("requirements"),
            cad=src.get("cad") or body.get("cad"),
            fem=src.get("fem") or body.get("fem"),
            fem_f06=src.get("fem_f06") or body.get("fem_f06"),
            report=src.get("report") or body.get("report"),
            tolerances=body.get("tolerances"),
            invalidate_cells=bool(body.get("invalidate_cells", True)),
            actor_id=actor,
            created_at=str(body.get("created_at") or now_fn()),
        )
        return JSONResponse(ok_fn("cross_artifact@1.0.0", {"tenant_id": tenant_id}, res))

    @router.post("/adversarial/fuzz")
    def adversarial_fuzz_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("adversarial@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        method_ids = body.get("method_ids")
        include_smt = bool(body.get("include_smt_critic", True))
        quarantine_dir = evidence_home_fn() / "tenants" / tenant_id / "quarantine"
        attacker = run_bench_attacker(
            quarantine_dir=quarantine_dir,
            method_ids=[str(m) for m in method_ids] if isinstance(method_ids, list) else None,
            custom_inputs=body.get("custom_inputs")
            if isinstance(body.get("custom_inputs"), dict)
            else None,
        )
        critic = run_envelope_critic() if include_smt else None
        return JSONResponse(
            ok_fn(
                "adversarial@1.0.0",
                {"tenant_id": tenant_id},
                {"bench_attacker": attacker, "envelope_critic": critic},
            )
        )

    @router.get("/overnight/briefing")
    def get_overnight_briefing(tenant_id: str = demo_tenant) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(
                abstain_fn("overnight@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger_fn(checked)
        head = ledger.head_hash()
        cache_key = (checked, head)
        with _briefing_cache_lock:
            cached = _briefing_cache.get(cache_key)
            if cached is not None:
                return JSONResponse(ok_fn("overnight@1.0.0", {"tenant_id": checked}, cached))
        briefing = build_morning_briefing(ledger)
        with _briefing_cache_lock:
            if len(_briefing_cache) >= 128:
                _briefing_cache.pop(next(iter(_briefing_cache)), None)
            _briefing_cache[cache_key] = briefing
        return JSONResponse(ok_fn("overnight@1.0.0", {"tenant_id": checked}, briefing))

    @router.post("/overnight/run")
    def trigger_overnight_run(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("overnight@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(tenant_id)
        budget = OvernightBudget(
            max_tokens_per_night=int(body.get("max_tokens_per_night", 250_000)),
            max_cloud_tokens_per_night=int(body.get("max_cloud_tokens_per_night", 50_000)),
            max_jobs_per_run=int(body.get("max_jobs_per_run", 200)),
        )
        quarantine_dir = evidence_home_fn() / "tenants" / tenant_id / "quarantine"
        watch_dirs_safe: list[Path] = []
        base_home = evidence_home_fn().resolve()
        for raw_dir in body.get("watch_dirs") or []:
            cand = Path(str(raw_dir)).resolve()
            if base_home in cand.parents or cand == base_home:
                watch_dirs_safe.append(cand)
        ca_inputs = (
            body.get("cross_artifact") if isinstance(body.get("cross_artifact"), dict) else None
        )
        summary = run_overnight_cycle(
            ledger,
            watch_dirs=watch_dirs_safe or None,
            cross_artifact_inputs=ca_inputs,
            run_fuzzer=bool(body.get("run_fuzzer", True)),
            quarantine_dir=quarantine_dir,
            budget=budget,
            actor_id=actor,
            use_showcase_if_empty=bool(body.get("use_showcase", True)),
        )
        return JSONResponse(ok_fn("overnight@1.0.0", {"tenant_id": tenant_id}, summary))

    @router.post("/overnight/batch-signoff")
    def overnight_batch_signoff_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("overnight_signoff@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(tenant_id)
        role = ledger.actor_role(actor)
        if role == "author":
            return JSONResponse(
                abstain_fn("overnight_signoff@1.0.0", {"role": role}, "cve_role_required"),
                status_code=403,
            )
        fids = [str(x) for x in (body.get("finding_ids") or []) if str(x).strip()]
        if not fids:
            return JSONResponse(
                abstain_fn("overnight_signoff@1.0.0", {}, "missing_finding_ids"), status_code=400
            )
        result = batch_human_signoff(
            ledger,
            finding_ids=fids,
            actor_id=actor,
            actor_role=role,
            statement=str(body.get("statement") or SIGN_OFF_STATEMENT),
            created_at=str(body.get("created_at") or now_fn()),
            enforce_distinct_reviewer=is_production_mode_fn()
            or bool(body.get("enforce_distinct_reviewer", False)),
        )
        return JSONResponse(ok_fn("overnight_signoff@1.0.0", {"tenant_id": tenant_id}, result))

    @router.post("/reviews/threads")
    def create_review_thread(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("review_thread@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger_fn(tenant_id)
        target = str(body.get("target_event_hash") or ledger.head_hash())
        try:
            thr = get_review_thread_store().create_thread(
                tenant_id,
                target_event_hash=target,
                author_id=actor,
                body=str(body.get("body") or ""),
                anchor=body.get("anchor") if isinstance(body.get("anchor"), dict) else None,
                category=str(body.get("category") or "review_comment"),
                initial_status=str(body.get("initial_status") or "OPEN"),
            )
        except ValueError as exc:
            return JSONResponse(abstain_fn("review_thread@1.0.0", {}, str(exc)), status_code=400)
        return JSONResponse(ok_fn("review_thread@1.0.0", {"tenant_id": tenant_id}, thr))

    @router.post("/reviews/threads/{thread_id}/reply")
    def reply_review_thread(thread_id: str, body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("review_thread@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        try:
            thr = get_review_thread_store().reply_thread(
                tenant_id,
                thread_id,
                actor_id=actor,
                body=str(body.get("body") or ""),
                request_changes=bool(body.get("request_changes", False)),
            )
        except KeyError:
            return JSONResponse(
                abstain_fn("review_thread@1.0.0", {}, "thread_not_found"), status_code=404
            )
        except ValueError as exc:
            code = 409 if str(exc) == "thread_locked" else 400
            return JSONResponse(
                abstain_fn("review_thread@1.0.0", {"thread_id": thread_id}, str(exc)),
                status_code=code,
            )
        return JSONResponse(ok_fn("review_thread@1.0.0", {"thread_id": thread_id}, thr))

    @router.post("/reviews/threads/{thread_id}/resolve")
    def resolve_review_thread(
        thread_id: str, body: dict[str, Any], request: Request
    ) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("review_thread@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        role = open_ledger_fn(tenant_id).actor_role(actor)
        if role not in {"cve", "admin", "reviewer", "human"}:
            return JSONResponse(
                abstain_fn(
                    "review_thread@1.0.0",
                    {"thread_id": thread_id, "role": role},
                    "insufficient_role",
                ),
                status_code=403,
            )
        try:
            thr = get_review_thread_store().resolve_thread(
                tenant_id,
                thread_id,
                resolver_id=actor,
                resolution_note=str(body.get("resolution_note") or "Verified and resolved"),
            )
        except KeyError:
            return JSONResponse(
                abstain_fn("review_thread@1.0.0", {}, "thread_not_found"), status_code=404
            )
        except ValueError as exc:
            return JSONResponse(
                abstain_fn("review_thread@1.0.0", {"thread_id": thread_id}, str(exc)),
                status_code=409,
            )
        return JSONResponse(ok_fn("review_thread@1.0.0", {"thread_id": thread_id}, thr))

    @router.get("/reviews/threads")
    def list_review_threads(
        request: Request, tenant_id: str = demo_tenant, target_event_hash: str | None = None
    ) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(
                abstain_fn("review_thread@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = check_endpoint_access_fn(request, tenant_id=checked)
        if auth_err is not None:
            return auth_err
        threads = get_review_thread_store().list_threads(
            checked, target_event_hash=target_event_hash or None
        )
        return JSONResponse(
            ok_fn(
                "review_thread@1.0.0",
                {"tenant_id": checked},
                {"threads": threads, "count": len(threads)},
            )
        )

    @router.post("/qualification/iq-oq/run")
    def qualification_iq_oq_endpoint(
        request: Request, body: dict[str, Any] | None = None
    ) -> JSONResponse:
        req = body or {}
        tenant_id = validate_tenant_fn(req.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("qualification_aid@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = check_endpoint_access_fn(
            request,
            tenant_id=tenant_id,
            requested_actor=req.get("actor_id"),
            allowed_roles={"cve", "admin", "auditor", "reviewer", "human"},
        )
        if auth_err is not None:
            return auth_err
        root_override = req.get("repo_root")
        if is_production_mode_fn():
            if root_override:
                return JSONResponse(
                    abstain_fn("qualification_aid@1.0.0", {}, "repo_root_override_forbidden"),
                    status_code=403,
                )
            target_root = repo_root_path
        else:
            target_root = Path(str(root_override)) if root_override else repo_root_path
        return JSONResponse(
            ok_fn(
                "qualification_aid@1.0.0", {}, run_iq_oq_qualification_suite(repo_root=target_root)
            )
        )

    @router.get("/legal/ma-readiness")
    def legal_ma_readiness_endpoint(request: Request, tenant_id: str = demo_tenant) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(
                abstain_fn("ma_readiness@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = check_endpoint_access_fn(
            request,
            tenant_id=checked,
            allowed_roles={"cve", "admin", "auditor", "reviewer", "human"},
        )
        if auth_err is not None:
            return auth_err
        return JSONResponse(
            ok_fn("ma_readiness@1.0.0", {}, evaluate_ma_technical_readiness(repo_root_path))
        )

    @router.get("/security/sbom")
    def security_sbom_endpoint(request: Request, tenant_id: str = demo_tenant) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(abstain_fn("sbom@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(
            request,
            tenant_id=checked,
            allowed_roles={"cve", "admin", "auditor", "reviewer", "human"},
        )
        if auth_err is not None:
            return auth_err
        return JSONResponse(
            ok_fn(
                "sbom@1.0.0", {"tenant_id": checked}, verify_sbom_and_dependencies(repo_root_path)
            )
        )

    return router
