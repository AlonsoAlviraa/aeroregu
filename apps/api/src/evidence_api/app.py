from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import time
import zipfile
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    # Fall back to native Win32 IOCP wakeup if socketpair-based self-pipe is blocked
    # so restricted Windows loopback sandboxes do not block TestClient/AnyIO portals.
    import _overlapped
    import asyncio.proactor_events as _proactor_events

    if not getattr(_proactor_events.BaseProactorEventLoop, "_iocp_selfpipe_patched", False):
        _orig_make_self_pipe = _proactor_events.BaseProactorEventLoop._make_self_pipe
        _orig_close_self_pipe = _proactor_events.BaseProactorEventLoop._close_self_pipe
        _orig_loop_self_reading = _proactor_events.BaseProactorEventLoop._loop_self_reading
        _orig_write_to_self = _proactor_events.BaseProactorEventLoop._write_to_self

        def _iocp_make_self_pipe(self: Any) -> None:
            try:
                _orig_make_self_pipe(self)
            except OSError:
                self._ssock = None
                self._csock = None

        def _iocp_close_self_pipe(self: Any) -> None:
            if (
                getattr(self, "_ssock", None) is not None
                or getattr(self, "_csock", None) is not None
            ):
                _orig_close_self_pipe(self)
                return
            self._ssock = None
            self._csock = None

        def _iocp_loop_self_reading(self: Any, f: Any = None) -> None:
            if getattr(self, "_ssock", None) is not None:
                _orig_loop_self_reading(self, f)
            return None

        def _iocp_write_to_self(self: Any) -> None:
            if getattr(self, "_csock", None) is not None:
                _orig_write_to_self(self)
                return
            proactor = getattr(self, "_proactor", None)
            iocp = getattr(proactor, "_iocp", None) if proactor is not None else None
            if iocp is not None:
                _overlapped.PostQueuedCompletionStatus(iocp, 0, 0, 1)

        _proactor_events.BaseProactorEventLoop._make_self_pipe = _iocp_make_self_pipe  # type: ignore[method-assign]
        _proactor_events.BaseProactorEventLoop._close_self_pipe = _iocp_close_self_pipe  # type: ignore[method-assign]
        _proactor_events.BaseProactorEventLoop._loop_self_reading = _iocp_loop_self_reading  # type: ignore[method-assign]
        _proactor_events.BaseProactorEventLoop._write_to_self = _iocp_write_to_self  # type: ignore[method-assign]
        _proactor_events.BaseProactorEventLoop._iocp_selfpipe_patched = True  # type: ignore[attr-defined]

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from evidence_calc.allowables import (
    allowable_catalog_sha256,
    list_materials,
    lookup_allowable,
)
from evidence_calc.cad_bindings import bind_parameters_to_cards
from evidence_calc.diagnostics import classify_numeric_delta
from evidence_calc.errors import AbstainError
from evidence_calc.plugins import delete_plugin_card
from evidence_calc.registry import list_cards, load_card, register_custom_card, run_method
from evidence_coverage.adversarial import run_bench_attacker, run_envelope_critic
from evidence_coverage.collaboration_ecn import (
    CatiaInspectorBridge,
    ExcelStressSheetBridge,
    compute_ecn_revision_diff,
    get_review_thread_store,
)
from evidence_coverage.cross_artifact import audit_cross_artifact_consistency
from evidence_coverage.dossier import (
    active_calc_records,
    build_enterprise_dossier,
    export_oscal_sar,
    export_strictdoc,
)
from evidence_coverage.envelope_3d import build_vn_cg_envelope_3d
from evidence_coverage.formal_bounds import prove_continuous_flight_envelope
from evidence_coverage.gate import evaluate_traceability_gate
from evidence_coverage.grid import calc_inputs_for, generate_cells
from evidence_coverage.ma_readiness import evaluate_ma_technical_readiness
from evidence_coverage.nafems_audit import (
    audit_abaqus_composite_layup_vs_report,
    audit_gpforce_freebody_equilibrium,
    audit_sol105_buckling_margins,
    diff_bdf_revisions_and_invalidate,
    run_full_nafems_audit,
)
from evidence_coverage.overnight import (
    batch_human_signoff,
    build_morning_briefing,
    default_showcase_artifacts,
    run_overnight_cycle,
)
from evidence_coverage.pdf_report import build_signed_pdf_report, verify_signed_pdf_report
from evidence_coverage.qualification_aid import run_iq_oq_qualification_suite
from evidence_coverage.quotation_multiagent import (
    QuotationRequestSpec,
    get_quotation_catalog,
    run_multiagent_quotation,
    run_whatif_sensitivity,
)
from evidence_coverage.repo_web_scraper import QuotationIntelligenceScraper
from evidence_coverage.rotorcraft_quotation_catalog import (
    RotorcraftQuotationSpec,
    get_rotorcraft_catalog,
    run_rotorcraft_department_quotation,
)
from evidence_coverage.status import (
    gap_report,
    invalidate_mass_shift,
    list_cells_with_status,
    run_coverage_sweep,
    set_cell_status,
)
from evidence_domain.generate import build_aircraft, build_requirements
from evidence_eval.detect import assess
from evidence_eval.faults import clean_artifact, inject
from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.cad_brep import analyze_step_brep
from evidence_ingest.cae_binary import (
    ELEM_TYPE_CODES,
    parse_cae_h5_bytes,
    parse_cae_h5_file,
    parse_nastran_op2_bytes,
    parse_nastran_op2_file,
    run_sandboxed_cae_worker,
)
from evidence_ingest.fem_parsers import parse_nastran_bdf, parse_nastran_f06
from evidence_ingest.router import ingest_bytes
from evidence_kernel.attestation import (
    build_pipeline_attestation,
    generate_ed25519_keypair,
    sign_attestation_dsse,
)
from evidence_kernel.daemon import OvernightBudget
from evidence_kernel.edge import (
    EDGE_PRESETS,
    compact_blocks_for_edge,
    edge_deployment_recipe,
    get_edge_preset,
    preflight_edge_screening,
)
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.formal import SMTSolverProofEngine
from evidence_kernel.gateway import (
    describe_agent_runtime,
    gateway_from_env,
    probe_gateway_health,
    prompt_hash,
)
from evidence_kernel.hsm_eidas_scim import (
    EidasQESEnvelope,
    get_hsm_signer,
    get_qes_envelope_service,
    get_scim_directory,
    get_webauthn_verifier,
    verify_sbom_and_dependencies,
)
from evidence_kernel.ledger import (
    GENESIS,
    SIGN_OFF_STATEMENT,
    Ledger,
    LedgerError,
    verify_chain_document,
)
from evidence_kernel.numbers import collect_decimals
from evidence_kernel.orchestrator import record
from evidence_kernel.pg_ledger import open_ledger_backend
from evidence_kernel.sso import (
    OIDCConfig,
    OIDCVerifier,
    SAML2Verifier,
    SAMLConfig,
    SSOValidationError,
)
from evidence_kernel.storage import BlobStoreError, open_blob_store
from evidence_kernel.supervisor import (
    CaseAbstain,
    CaseSpec,
    arun_case,
    astream_case,
    invoke_single_agent,
)
from evidence_kernel.telemetry import get_telemetry
from evidence_kernel.webhooks import (
    WebhookError,
    dispatch_webhook_with_retry,
    new_webhook_record,
    replay_dead_letters,
)
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

DEMO_TENANT = "demo"
TENANT_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
MAX_INGEST_BYTES = int(os.environ.get("EVIDENCE_MAX_INGEST_BYTES", str(16 * 1024 * 1024)))
MAX_JSON_BODY_BYTES = int(os.environ.get("EVIDENCE_MAX_JSON_BODY_BYTES", str(24 * 1024 * 1024)))
DEFAULT_SESSION_TTL_SECONDS = int(os.environ.get("EVIDENCE_SESSION_TTL_SECONDS", "28800"))
ASSISTANCE = "This tool assists a human reviewer. It does not determine compliance."
VERIFY_TEXT = ASSISTANCE + "\nVerify with: uv run python -m evidence_kernel verify bundle.zip\n"
_INITIALIZED_ACTOR_PATHS: set[Path] = set()
_LEDGER_CACHE_LOCK = threading.RLock()
_LEDGER_CACHE: dict[Path, tuple[Ledger, tuple[int, int] | None]] = {}
_DOSSIER_CACHE_LOCK = threading.RLock()
_DOSSIER_CACHE: dict[tuple[str, str, tuple[tuple[int, int], ...] | None], dict[str, Any]] = {}
_MAX_DOSSIER_CACHE = 64
_GATE_CACHE_LOCK = threading.RLock()
_GATE_CACHE: dict[tuple[str, str, bool], dict[str, Any]] = {}
_FALLBACK_TEMP_LOCK = threading.Lock()
_FALLBACK_TEMP_DIR: Path | None = None


class _SlidingRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


_RATE_LIMITER = _SlidingRateLimiter()


def create_app() -> FastAPI:
    app = FastAPI(title="aeroregu")
    _ingested_docs: dict[tuple[str, str], dict[str, Any]] = {}

    def _check_endpoint_access(
        request: Request,
        *,
        tenant_id: str = DEMO_TENANT,
        requested_actor: Any = None,
        allowed_roles: set[str] | None = None,
        require_always: bool = False,
    ) -> tuple[str | None, JSONResponse | None]:
        has_bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
        has_cookie = bool(request.cookies.get("el_session"))
        if _is_production_mode() or require_always or has_bearer:
            actor = _session_actor(request, requested_actor, tenant_id=tenant_id)
            if actor is None:
                return None, JSONResponse(
                    _abstain("auth@1.0.0", {"tenant_id": tenant_id}, "auth_required"),
                    status_code=401,
                )
            if allowed_roles is not None:
                role = open_ledger(tenant_id).actor_role(actor)
                if role not in allowed_roles:
                    return None, JSONResponse(
                        _abstain(
                            "auth@1.0.0",
                            {"actor_id": actor, "role": role},
                            "insufficient_role",
                        ),
                        status_code=403,
                    )
            return actor, None
        if has_cookie:
            actor = _session_actor(request, requested_actor, tenant_id=tenant_id)
            if actor is not None:
                if allowed_roles is not None:
                    role = open_ledger(tenant_id).actor_role(actor)
                    if role not in allowed_roles:
                        return None, JSONResponse(
                            _abstain(
                                "auth@1.0.0",
                                {"actor_id": actor, "role": role},
                                "insufficient_role",
                            ),
                            status_code=403,
                        )
                return actor, None
        return str(requested_actor or "author"), None

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        cl = request.headers.get("content-length")
        if cl:
            try:
                if int(cl) > MAX_JSON_BODY_BYTES:
                    return JSONResponse(
                        _abstain("api@1.0.0", {}, "payload_too_large"),
                        status_code=413,
                    )
            except ValueError:
                pass
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        if _cookie_secure(request):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Evidence-Request-Hash"] = hashlib.sha256(
            f"{request.method}:{request.url.path}".encode()
        ).hexdigest()
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
            raise exc
        return JSONResponse(
            _abstain("api@1.0.0", {}, "internal_error"),
            status_code=500,
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        runtime = describe_agent_runtime()
        return _ok(
            "health@1.0.0",
            {},
            {
                "status": "ok",
                "gateway": runtime["active_mode"],
                "api_configured": runtime["api_backend"]["configured"],
                "edge_configured": runtime["edge_backend"]["configured"],
            },
        )

    @app.get("/requirements")
    def requirements() -> dict[str, Any]:
        document = build_requirements()
        return _ok("requirement_ids@1.0.0", {"count": str(len(document["requirements"]))}, document)

    @app.get("/aircraft")
    def aircraft() -> dict[str, Any]:
        document = build_aircraft()
        return _ok("synthetic_aircraft@0.1.0", {"aircraft_id": document["aircraft_id"]}, document)

    @app.post("/ingest/document")
    def ingest_document(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("ingest@1.0.0", {}, "invalid_tenant"), status_code=400)
        filename = str(body.get("filename") or "note.txt")
        records = bool(body.get("record"))
        actor_id = str(body.get("actor_id") or "author")
        if records:
            session_actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
            if session_actor is None:
                return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
            actor_id = session_actor
        if body.get("content_base64") is not None:
            encoded = str(body["content_base64"])
            if len(encoded) > (MAX_INGEST_BYTES * 4) // 3 + 16:
                return JSONResponse(
                    _abstain("ingest@1.0.0", {"filename": filename}, "payload_too_large"),
                    status_code=413,
                )
            try:
                raw = base64.b64decode(encoded, validate=True)
            except Exception:
                return JSONResponse(
                    _abstain("ingest@1.0.0", {"filename": filename}, "invalid_base64"),
                    status_code=400,
                )
        elif body.get("content_text") is not None:
            raw = str(body["content_text"]).encode("utf-8")
        else:
            return JSONResponse(
                _abstain("ingest@1.0.0", {"filename": filename}, "missing_document_content"),
                status_code=400,
            )
        if len(raw) > MAX_INGEST_BYTES:
            return JSONResponse(
                _abstain("ingest@1.0.0", {"filename": filename}, "payload_too_large"),
                status_code=413,
            )
        try:
            parsed = ingest_bytes(raw, filename)
        except IngestAbstain as exc:
            return JSONResponse(
                _abstain("ingest@1.0.0", {"filename": filename}, exc.reason),
            )
        if raw.startswith(b"%PDF"):
            try:
                open_blob_store(evidence_home()).put_blob(
                    raw, content_type="application/pdf", filename=filename
                )
            except Exception:
                pass
        recorded_hashes: list[str] = []
        if records and parsed["requirements"]:
            ledger = open_ledger(tenant_id)
            created_at = str(body.get("created_at") or _now())
            for req in parsed["requirements"]:
                req_env = make_envelope(
                    sources=[
                        project_source("ingest", "https://aeroregu.local/ingest", "ASSUMPTION")
                    ],
                    method_version="ingest_requirements@1.0.0",
                    inputs={
                        "id": req["id"],
                        "source_file_hash": req["source_file_hash"],
                        "span_start": req["span_start"],
                    },
                    confidence="quoted",
                    result={"id": req["id"], "title_label": req["title_label"]},
                )
                recorded_hashes.append(
                    record(
                        ledger,
                        {
                            "event_type": "requirement_recorded",
                            "tenant_id": ledger.tenant_id,
                            "actor_id": actor_id,
                            "created_at": created_at,
                            "payload": req,
                            "envelope": req_env,
                        },
                    )
                )
        result_payload = {**parsed, "recorded_event_hashes": recorded_hashes}
        doc_entry = {
            "tenant_id": tenant_id,
            "filename": parsed["filename"],
            "media_type": parsed["media_type"],
            "source_hash": parsed["source_hash"],
            "blocks": parsed["blocks"],
            "requirements": parsed["requirements"],
            "raw": raw if not raw.startswith(b"%PDF") else b"",
        }
        while len(_ingested_docs) > 256:
            _ingested_docs.pop(next(iter(_ingested_docs)))
        _ingested_docs[(tenant_id, parsed["source_hash"])] = doc_entry
        _ingested_docs[(tenant_id, parsed["filename"])] = doc_entry
        return JSONResponse(
            _ok(
                "ingest@1.0.0",
                {"filename": parsed["filename"], "source_hash": parsed["source_hash"]},
                result_payload,
            )
        )

    @app.post("/calc/run")
    def calc_run(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("calc@1.0.0", {}, "invalid_tenant"), status_code=400)
        created_at = str(body.get("created_at") or _now())
        records = body.get("example") == "first_cell" or bool(body.get("record"))
        actor_id = str(body.get("actor_id") or "author")
        if records:
            session_actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
            if session_actor is None:
                return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
            actor_id = session_actor
        if body.get("example") == "first_cell":
            cell = generate_cells()[0]
            method_id = "rigid_body_point_mass"
            inputs = calc_inputs_for(cell)
            cell_id = cell.cell_id
        else:
            raw_method = body.get("method_id")
            if not isinstance(raw_method, str) or not raw_method.strip():
                return JSONResponse(_abstain("calc@0", {}, "missing_method_id"), status_code=400)
            method_id = raw_method.strip()
            inputs = body.get("inputs") or {}
            cell_id = body.get("cell_id")
        target_cell = None
        if records and cell_id:
            target_cell = next((item for item in generate_cells() if item.cell_id == cell_id), None)
            if target_cell is None:
                return JSONResponse(
                    _abstain("calc@1.0.0", {"cell_id": str(cell_id)}, "unknown_cell"),
                    status_code=404,
                )
        normalize_units = bool(body.get("normalize_units"))
        include_intervals = bool(body.get("include_intervals", True))
        try:
            ran = run_method(
                method_id,
                inputs,
                normalize_units=normalize_units,
                include_intervals=include_intervals,
            )
        except AbstainError as exc:
            envelope = make_envelope(
                sources=_card_sources(method_id),
                method_version=_card_version(method_id),
                inputs=inputs,
                confidence="abstain",
                abstain_reason=exc.reason,
            )
            return JSONResponse(envelope)
        result_body = dict(ran["outputs"])
        if normalize_units and ran.get("unit_conversions"):
            result_body["unit_conversions"] = ran["unit_conversions"]
        if include_intervals and ran.get("exact_intervals"):
            result_body["exact_intervals"] = ran["exact_intervals"]
        if bool(body.get("formal_proof")) or body.get("formal_bounds") is not None:
            from evidence_api.formal_methods import run_formal_proof_for_method

            result_body["formal_proof"] = run_formal_proof_for_method(
                method_id,
                ran.get("normalized_inputs", inputs),
                formal_bounds=body.get("formal_bounds"),
            )
        envelope = make_envelope(
            sources=ran["sources"],
            method_version=ran["method_version"],
            inputs=ran.get("normalized_inputs", inputs),
            confidence="deterministic",
            result=result_body,
        )
        if records:
            ledger = open_ledger(tenant_id)
            event_hash = record(
                ledger,
                {
                    "event_type": "calc",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": {
                        "method_id": method_id,
                        "inputs": ran.get("normalized_inputs", inputs),
                        "outputs": ran["outputs"],
                    },
                    "envelope": envelope,
                },
            )
            if target_cell is not None:
                set_cell_status(
                    ledger,
                    cell=target_cell,
                    status="calc",
                    actor_id=actor_id,
                    actor_role="human",
                    created_at=created_at,
                    evidence_event_hash=event_hash,
                )
        return JSONResponse(envelope)

    @app.post("/calc/compare")
    def calc_compare(body: dict[str, Any]) -> JSONResponse:
        method_id = str(body.get("method_id") or "")
        inputs = body.get("inputs") or {}
        stated_outputs = body.get("stated_outputs")
        normalize_units = bool(body.get("normalize_units"))
        if not method_id:
            return JSONResponse(_abstain("calc@0", inputs, "unknown_method"), status_code=400)
        try:
            ran = run_method(method_id, inputs, normalize_units=normalize_units)
        except AbstainError as exc:
            envelope = make_envelope(
                sources=_card_sources(method_id),
                method_version=_card_version(method_id),
                inputs=inputs,
                confidence="abstain",
                abstain_reason=exc.reason,
            )
            return JSONResponse(envelope)
        effective_inputs = ran.get("normalized_inputs", inputs)
        fault_kind = (
            classify_numeric_delta(method_id, effective_inputs, stated_outputs, ran["outputs"])
            if isinstance(stated_outputs, dict)
            else "clean"
        )
        envelope = make_envelope(
            sources=ran["sources"],
            method_version=ran["method_version"],
            inputs=effective_inputs,
            confidence="deterministic",
            result={
                "fault_kind": fault_kind,
                "recomputed": ran["outputs"],
                "stated_outputs": stated_outputs,
                "unit_conversions": ran.get("unit_conversions", []),
            },
        )
        return JSONResponse(envelope)

    _summary_cache: dict[tuple[str, str, int], dict[str, Any]] = {}
    _summary_cache_lock = threading.RLock()

    @app.get("/coverage/summary")
    def coverage_summary(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("coverage_grid@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        with get_telemetry().start_span(
            "api.coverage_summary", stage="api", attributes={"tenant_id": checked_tenant}
        ):
            ledger = open_ledger(checked_tenant)
            cache_epoch = (
                ledger.cache.current_epoch("coverage_summary") if hasattr(ledger, "cache") else 0
            )
            head = ledger.head_hash()
            cache_key = (checked_tenant, head, cache_epoch)
            with _summary_cache_lock:
                cached = _summary_cache.get(cache_key)
                if cached is not None:
                    return JSONResponse(
                        _ok("coverage_grid@1.0.0", {"tenant_id": checked_tenant}, cached)
                    )
            stats = (
                ledger.coverage_summary_fast() if hasattr(ledger, "coverage_summary_fast") else None
            )
            if stats is not None and int(stats.get("event_count", 0)) > 5000:
                payload = {
                    **stats,
                    "cache_epoch": cache_epoch,
                    "indexed_fast_path": True,
                }
            elif stats is not None:
                report = gap_report(ledger.events())
                payload = {
                    **stats,
                    "cache_epoch": cache_epoch,
                    "indexed_fast_path": False,
                    "gap_summary": report,
                }
            else:
                evs = ledger.events()
                report = gap_report(evs)
                payload = {
                    "tenant_id": checked_tenant,
                    "event_count": len(evs),
                    "head_hash": head,
                    "cache_epoch": cache_epoch,
                    "indexed_fast_path": False,
                    "gap_summary": report,
                }
            with _summary_cache_lock:
                if len(_summary_cache) >= 128:
                    _summary_cache.pop(next(iter(_summary_cache)), None)
                _summary_cache[cache_key] = payload
            return JSONResponse(_ok("coverage_grid@1.0.0", {"tenant_id": checked_tenant}, payload))

    @app.get("/coverage/gaps")
    def coverage_gaps(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("coverage_grid@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        report = gap_report(open_ledger(checked_tenant).events())
        return JSONResponse(_ok("coverage_grid@1.0.0", {"tenant_id": checked_tenant}, report))

    @app.get("/coverage/cells")
    def coverage_cells(
        tenant_id: str = DEMO_TENANT,
        status: str | None = None,
        stale_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("coverage_grid@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        rows = list_cells_with_status(
            open_ledger(checked_tenant).events(),
            status_filter=status or None,
            stale_only=stale_only,
        )
        bounded_limit = max(1, min(int(limit), 200))
        bounded_offset = max(0, int(offset))
        return JSONResponse(
            _ok(
                "coverage_grid@1.0.0",
                {
                    "tenant_id": checked_tenant,
                    "status": status or "all",
                    "stale_only": str(stale_only).lower(),
                },
                {
                    "total": len(rows),
                    "limit": bounded_limit,
                    "offset": bounded_offset,
                    "cells": rows[bounded_offset : bounded_offset + bounded_limit],
                },
            )
        )

    @app.post("/coverage/sweep")
    def coverage_sweep(body: dict[str, Any] | None, request: Request) -> JSONResponse:
        payload_body = body or {}
        tenant_id = _validate_tenant(payload_body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("coverage_grid@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor_id = _session_actor(request, payload_body.get("actor_id"), tenant_id=tenant_id)
        if actor_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        created_at = str(payload_body.get("created_at") or _now())
        target_status = str(payload_body.get("target_status") or "gap")
        stale_only = bool(payload_body.get("stale_only"))
        limit = int(payload_body.get("limit") or 15)
        ledger = open_ledger(tenant_id)
        summary = run_coverage_sweep(
            ledger,
            actor_id=actor_id,
            created_at=created_at,
            target_status=target_status,
            stale_only=stale_only,
            limit=limit,
        )
        return JSONResponse(
            _ok(
                "coverage_grid@1.0.0",
                {"tenant_id": tenant_id, "target_status": target_status, "limit": str(limit)},
                {**summary, "merkle_root": ledger.merkle_root()},
            )
        )

    @app.get("/coverage/gate")
    def coverage_gate(
        require_signoff: bool = False,
        enforce_distinct: bool = False,
        tenant_id: str = DEMO_TENANT,
    ) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("traceability_gate@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger(checked_tenant)
        head = ledger.head_hash()
        cache_key = (checked_tenant, head, require_signoff, enforce_distinct)
        with _GATE_CACHE_LOCK:
            cached = _GATE_CACHE.get(cache_key)
            if cached is not None:
                return JSONResponse(
                    _ok(
                        "traceability_gate@1.0.0",
                        {
                            "tenant_id": checked_tenant,
                            "require_signoff": str(require_signoff).lower(),
                            "enforce_distinct": str(enforce_distinct).lower(),
                        },
                        cached,
                    )
                )
        gate = evaluate_traceability_gate(
            ledger.events(),
            chain_verified=ledger.verify(),
            require_head_signoff=require_signoff,
            enforce_distinct_reviewer=enforce_distinct,
        )
        with _GATE_CACHE_LOCK:
            if len(_GATE_CACHE) >= 64:
                _GATE_CACHE.pop(next(iter(_GATE_CACHE)), None)
            _GATE_CACHE[cache_key] = gate
        return JSONResponse(
            _ok(
                "traceability_gate@1.0.0",
                {
                    "tenant_id": checked_tenant,
                    "require_signoff": str(require_signoff).lower(),
                    "enforce_distinct": str(enforce_distinct).lower(),
                },
                gate,
            )
        )

    @app.post("/coverage/cell-status")
    def coverage_cell_status(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("coverage_grid@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor_id = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        cell_id = str(body.get("cell_id") or "")
        status = str(body.get("status") or "")
        if status not in {"not_in_envelope", "justified_not_critical", "gap"}:
            return JSONResponse(
                _abstain("coverage_grid@1.0.0", {"cell_id": cell_id}, "invalid_status"),
                status_code=400,
            )
        cell = next((item for item in generate_cells() if item.cell_id == cell_id), None)
        if cell is None:
            return JSONResponse(
                _abstain("coverage_grid@1.0.0", {"cell_id": cell_id}, "unknown_cell"),
                status_code=404,
            )
        created_at = str(body.get("created_at") or _now())
        evidence_hash = str(body.get("evidence_event_hash") or "")
        ledger = open_ledger(tenant_id)
        ev_hash = set_cell_status(
            ledger,
            cell=cell,
            status=status,
            actor_id=actor_id,
            actor_role="human",
            created_at=created_at,
            evidence_event_hash=evidence_hash,
        )
        return JSONResponse(
            _ok(
                "coverage_grid@1.0.0",
                {"cell_id": cell_id, "status": status},
                {"event_hash": ev_hash, "cell_id": cell_id, "status": status},
            )
        )

    @app.post("/coverage/mass-shift")
    def coverage_mass_shift(request: Request, body: dict[str, Any] | None = None) -> JSONResponse:
        payload_body = body or {}
        tenant_id = _validate_tenant(payload_body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("coverage_grid@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor_id = _session_actor(request, payload_body.get("actor_id"), tenant_id=tenant_id)
        if actor_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        created_at = str(payload_body.get("created_at") or _now())
        ledger = open_ledger(tenant_id)
        records = active_calc_records(ledger.events())
        invalidated_hashes = invalidate_mass_shift(
            ledger,
            records,
            actor_id=actor_id,
            created_at=created_at,
        )
        dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
        webhook_deliveries = _dispatch_registered_webhooks(
            ledger,
            event_name="envelope_invalidated",
            payload={
                "tenant_id": tenant_id,
                "reason": "mass_shift",
                "shift": "+5%",
                "actor_id": actor_id,
                "invalidated_cells": [row["cell_id"] for row in records],
                "invalidated_event_hashes": invalidated_hashes,
                "dossier_hash": dossier["dossier_hash"],
            },
        )
        return JSONResponse(
            _ok(
                "coverage_grid@1.0.0",
                {"tenant_id": tenant_id, "shift": "+5%"},
                {
                    "invalidated_cells": [row["cell_id"] for row in records],
                    "invalidated_event_hashes": invalidated_hashes,
                    "delta_reverification_manifest": dossier["delta_reverification_manifest"],
                    "dossier_hash": dossier["dossier_hash"],
                    "webhook_deliveries": webhook_deliveries,
                },
            )
        )

    @app.get("/dossier/summary")
    def dossier_summary(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("dossier@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked_tenant)
        bundle = _cached_dossier_bundle(ledger)
        return JSONResponse(_ok("dossier@1.0.0", {"tenant_id": checked_tenant}, bundle["dossier"]))

    @app.get("/dossier/strictdoc")
    def dossier_strictdoc(tenant_id: str = DEMO_TENANT) -> Response:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("dossier@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked_tenant)
        bundle = _cached_dossier_bundle(ledger)
        return Response(content=bundle["strictdoc"], media_type="text/plain; charset=utf-8")

    @app.get("/dossier/oscal")
    def dossier_oscal(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("oscal_sar@1.1.2", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked_tenant)
        bundle = _cached_dossier_bundle(ledger)
        return JSONResponse(_ok("oscal_sar@1.1.2", {"tenant_id": checked_tenant}, bundle["oscal"]))

    @app.post("/formal/prove")
    def formal_prove(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("formal_smt@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        kind = str(body.get("kind") or "flight_envelope")
        if kind == "structural_margin":
            engine = SMTSolverProofEngine()
            bounds = body.get("bounds") or {
                "area_mm2": ("100.000", "120.000"),
                "shear_force_n": ("1000.000", "2000.000"),
                "tensile_force_n": ("2000.000", "3000.000"),
            }
            allowables = body.get("allowables") or {
                "shear_allowable_mpa": "150.000",
                "tensile_allowable_mpa": "250.000",
            }
            sf = str(body.get("safety_factor") or "1.500")
            res = engine.prove_structural_margin(bounds, allowables, sf)
            return JSONResponse(_ok("formal_smt@1.0.0", body, res.to_dict()))
        if kind == "hover_power":
            engine = SMTSolverProofEngine()
            bounds = body.get("bounds") or {}
            t_range = tuple(bounds.get("thrust_n") or ("2000.000", "10500.000"))
            area = str(body.get("disk_area_m2") or "10.000")
            rho = str(body.get("air_density_kg_m3") or "1.225")
            fm = str(body.get("figure_of_merit") or "0.700")
            p_avail = str(body.get("max_power_available_kw") or "350.000")
            res = engine.prove_hover_power_envelope(t_range, area, rho, fm, p_avail)
            return JSONResponse(_ok("formal_smt@1.0.0", body, res.to_dict()))
        bounds = body.get("bounds") or {}
        m_range = bounds.get("mass_kg") or ("800.000", "1200.000")
        cg_range = bounds.get("cg_x_m") or ("-0.200", "0.200")
        lf_range = bounds.get("load_factor") or ("-1.000", "2.500")
        stations = body.get("stations_m")
        thrust = str(body.get("max_station_thrust_n") or "15000.000")
        res_dict = prove_continuous_flight_envelope(
            mass_range_kg=tuple(m_range),
            cg_range_m=tuple(cg_range),
            load_factor_range=tuple(lf_range),
            station_positions_m=stations,
            max_station_thrust_n=thrust,
        )
        return JSONResponse(_ok("formal_smt@1.0.0", body, res_dict))

    @app.post("/notes/check")
    def notes_check(body: dict[str, Any]) -> JSONResponse:
        example = body.get("example")
        if example == "unit_scale":
            artifact = inject("unit_scale", clean_artifact("bolt_screen", _bolt_inputs("3.000")), 0)
        elif example == "missing_input":
            artifact = inject(
                "missing_input",
                clean_artifact("bolt_screen", _bolt_inputs("3000.000")),
                0,
            )
            artifact["inputs"].pop("area_mm2", None)
        else:
            artifact = body.get("artifact")
            if not isinstance(artifact, dict):
                return JSONResponse(
                    _abstain("notes@1.0.0", {}, "missing_artifact"), status_code=400
                )
        return JSONResponse(assess(artifact)["envelope"])

    @app.get("/agents/runtime")
    def agents_runtime() -> JSONResponse:
        runtime = describe_agent_runtime()
        return JSONResponse(
            _ok(
                "agent_runtime@1.0.0",
                {},
                {
                    **runtime,
                    "edge_presets": EDGE_PRESETS,
                    "edge_recipes": {
                        "ollama": edge_deployment_recipe(runtime_kind="ollama"),
                        "llamacpp": edge_deployment_recipe(runtime_kind="llamacpp"),
                    },
                },
            )
        )

    @app.post("/agents/probe")
    def agents_probe(request: Request, body: dict[str, Any] | None = None) -> JSONResponse:
        tenant_id = _validate_tenant((body or {}).get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("agent_runtime@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        if _actor_from_request(request, tenant_id=tenant_id) is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        payload = body or {}
        target = str(payload.get("target") or "all")
        if target not in {"all", "api", "edge"}:
            return JSONResponse(
                _abstain("agent_runtime@1.0.0", {"target": target}, "invalid_probe_target"),
                status_code=400,
            )
        timeout_s = max(0.5, min(float(payload.get("timeout_s") or 3.0), 10.0))
        probed = probe_gateway_health(target=target, timeout_s=timeout_s)
        return JSONResponse(_ok("agent_runtime@1.0.0", {"target": target}, probed))

    @app.post("/agents/edge/preflight")
    def agents_edge_preflight(body: dict[str, Any]) -> JSONResponse:
        preset_id = str(body.get("edge_preset") or "laptop-cpu-16gb")
        raw_blocks = body.get("blocks")
        if isinstance(raw_blocks, list) and raw_blocks:
            blocks = list(raw_blocks)
        else:
            text = str(body.get("text") or "")
            if not text.strip():
                return JSONResponse(
                    _abstain("edge_preflight@1.0.0", {"edge_preset": preset_id}, "empty_document"),
                    status_code=400,
                )
            blocks = [
                {"text": line, "span_start": 0, "span_end": len(line)}
                for line in text.splitlines()
                if line.strip()
            ]
        report = preflight_edge_screening(blocks, preset_id=preset_id)
        return JSONResponse(_ok("edge_preflight@1.0.0", {"edge_preset": preset_id}, report))

    @app.post("/agents/invoke")
    def agents_invoke(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("agent_invoke@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        invoke_limit = int(os.environ.get("EVIDENCE_INVOKE_RATE_LIMIT", "60"))
        if not _RATE_LIMITER.allow(f"invoke:{_client_ip(request)}:{tenant_id}", invoke_limit, 60):
            return JSONResponse(
                _abstain("agent_invoke@1.0.0", {"tenant_id": tenant_id}, "rate_limited"),
                status_code=429,
            )
        records = bool(body.get("record"))
        actor_id = str(body.get("actor_id") or "author")
        if _is_production_mode():
            session_actor = _actor_from_request(request, tenant_id=tenant_id)
            if session_actor is None:
                return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
            actor_id = session_actor
        elif records:
            session_actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
            if session_actor is None:
                return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
            actor_id = session_actor

        agent_id = str(body.get("agent_id") or "")
        text = str(body.get("text") or "Alpha item is listed in the source block.")
        raw_blocks = body.get("blocks")
        blocks = (
            list(raw_blocks)
            if isinstance(raw_blocks, list) and raw_blocks
            else [{"text": text, "span_start": 0, "span_end": len(text)}]
        )
        compact_for_edge = bool(body.get("compact_for_edge"))
        edge_preset = body.get("edge_preset")
        if compact_for_edge:
            preset = get_edge_preset(str(edge_preset) if edge_preset else None)
            blocks = compact_blocks_for_edge(blocks, max_chars=int(preset["max_context_chars"]))

        source_text = "\n".join(str(b.get("text", "")) for b in blocks)
        allowed_list = [str(item) for item in (body.get("allowed_decimals") or [])]
        allowed_set = set(allowed_list) | collect_decimals(body.get("calc_inputs") or {})
        context = {
            "task": agent_id,
            "blocks": blocks,
            "quotation": str(blocks[0].get("text", "")),
            "span_start": str(blocks[0].get("span_start", 0)),
            "span_end": str(blocks[0].get("span_end", len(str(blocks[0].get("text", ""))))),
            "source_text": source_text,
            "reader_label": str(body.get("reader_label") or "NOT_VERIFIED"),
            "allowed_decimals": sorted(allowed_set),
        }
        gw = gateway_from_env(
            str(body.get("scenario") or "happy"),
            constrained=bool(body.get("constrained")),
            runtime_mode=str(body.get("runtime_mode") or "auto"),
            model=body.get("model"),
            edge_model=body.get("edge_model"),
            edge_preset=str(edge_preset) if edge_preset else None,
            max_schema_retries=(
                int(body["max_schema_retries"])
                if body.get("max_schema_retries") is not None
                else None
            ),
        )
        try:
            ran = invoke_single_agent(gw, agent_id, context, allowed_decimals=allowed_set)
        except CaseAbstain as exc:
            return JSONResponse(_abstain("agent_invoke@1.0.0", {"agent_id": agent_id}, exc.reason))

        recorded_hash = ""
        if records:
            ledger = open_ledger(tenant_id)
            created_at = str(body.get("created_at") or _now())
            turn_env = make_envelope(
                sources=[project_source("agent", "https://aeroregu.local/agent", "ASSUMPTION")],
                method_version=f"{agent_id}@1.0.0",
                inputs={"agent_id": agent_id, "prompt_hash": prompt_hash(agent_id)},
                confidence="quoted",
                result=ran["output"],
            )
            recorded_hash = record(
                ledger,
                {
                    "event_type": "agent_turn",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": {
                        "agent_id": agent_id,
                        "prompt_hash": prompt_hash(agent_id),
                        "temperature": "0",
                        "input_event_hashes": [],
                        "output": ran["output"],
                        "telemetry": ran["telemetry"],
                        "envelope": turn_env,
                    },
                    "envelope": turn_env,
                },
            )
        return JSONResponse(
            _ok(
                f"{agent_id}@1.0.0",
                {"agent_id": agent_id, "tenant_id": tenant_id},
                {
                    "agent_id": agent_id,
                    "output": ran["output"],
                    "telemetry": ran["telemetry"],
                    "recorded_event_hash": recorded_hash,
                },
            )
        )

    def _prepare_supervisor_run(
        body: dict[str, Any], request: Request
    ) -> tuple[JSONResponse | None, dict[str, Any]]:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return (
                JSONResponse(_abstain("supervisor@1.0.0", {}, "invalid_tenant"), status_code=400),
                {},
            )
        actor_id = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401), {}
        text = str(body.get("text") or "Alpha item is listed in the source block.")
        raw_blocks = body.get("blocks")
        blocks = (
            list(raw_blocks)
            if isinstance(raw_blocks, list) and raw_blocks
            else [{"text": text, "span_start": 0, "span_end": len(text)}]
        )
        created_at = str(body.get("created_at") or _now())
        cell_id = body.get("cell_id")
        if body.get("example") == "first_cell" and not cell_id:
            cell_id = generate_cells()[0].cell_id
        calc_inputs = body.get("calc_inputs")
        if calc_inputs is None:
            if cell_id:
                matched = next(
                    (item for item in generate_cells() if item.cell_id == cell_id),
                    generate_cells()[0],
                )
                calc_inputs = calc_inputs_for(matched)
            else:
                calc_inputs = calc_inputs_for(generate_cells()[0])
        use_gate = bool(body.get("use_decision_gate"))
        edge_preset = body.get("edge_preset")
        case = CaseSpec(
            tenant_id=tenant_id,
            actor_id=actor_id,
            created_at=created_at,
            blocks=blocks,
            method_id=body.get("method_id", "rigid_body_point_mass"),
            calc_inputs=calc_inputs,
            stated_outputs=body.get("stated_outputs"),
            reader_label=str(body.get("reader_label") or "NOT_VERIFIED"),
            use_decision_gate=use_gate,
            require_declared_units=bool(body.get("require_declared_units")),
            formal_verification=bool(body.get("formal_verification")),
            formal_bounds=body.get("formal_bounds"),
            record_requirements=bool(body.get("record_requirements")),
            compact_for_edge=bool(body.get("compact_for_edge")),
            edge_preset=str(edge_preset) if edge_preset else None,
        )
        if body.get("omit_inputs"):
            case.calc_inputs = {}
        ledger = open_ledger(tenant_id)
        gw = gateway_from_env(
            str(body.get("scenario") or "happy"),
            constrained=bool(body.get("constrained")),
            runtime_mode=str(body.get("runtime_mode") or "auto"),
            model=body.get("model"),
            edge_model=body.get("edge_model"),
            edge_preset=str(edge_preset) if edge_preset else None,
            max_schema_retries=(
                int(body["max_schema_retries"])
                if body.get("max_schema_retries") is not None
                else None
            ),
            max_turns=5 if use_gate else 4,
        )
        return None, {
            "ledger": ledger,
            "gw": gw,
            "case": case,
            "actor_id": actor_id,
            "created_at": created_at,
            "cell_id": cell_id,
            "stated_outputs": body.get("stated_outputs"),
        }

    def _decorate_supervisor_envelope(
        envelope: dict[str, Any],
        *,
        ledger: Ledger,
        actor_id: str,
        created_at: str,
        cell_id: Any,
        stated_outputs: Any,
        event_hashes: list[str],
        fault_kind: str | None,
        formal_proof: dict[str, Any] | None,
        agent_telemetry: list[dict[str, Any]],
        citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        out = dict(envelope)
        if formal_proof is not None:
            out["formal_proof"] = formal_proof
        if out.get("confidence") == "deterministic" and (
            cell_id is not None or stated_outputs is not None
        ):
            cell_updated = False
            if cell_id and fault_kind is None:
                cell = next(
                    (item for item in generate_cells() if item.cell_id == cell_id),
                    None,
                )
                if cell is not None:
                    set_cell_status(
                        ledger,
                        cell=cell,
                        status="calc",
                        actor_id=actor_id,
                        actor_role="human",
                        created_at=created_at,
                        evidence_event_hash=event_hashes[0] if event_hashes else "",
                    )
                    cell_updated = True
            result = dict(out.get("result") or {})
            result["cell_updated"] = cell_updated
            result["fault_kind"] = fault_kind or "clean"
            if cell_id:
                result["cell_id"] = str(cell_id)
            if agent_telemetry:
                result["agent_telemetry"] = agent_telemetry
            if citations:
                result["citations"] = citations
            out["result"] = result
        elif out.get("confidence") == "deterministic" and isinstance(out.get("result"), dict):
            extra: dict[str, Any] = {}
            if agent_telemetry:
                extra["agent_telemetry"] = agent_telemetry
            if citations:
                extra["citations"] = citations
            if extra:
                out["result"] = {**out["result"], **extra}
        return out

    @app.post("/supervisor/run")
    async def supervisor_run(body: dict[str, Any], request: Request) -> JSONResponse:
        err_resp, ctx = _prepare_supervisor_run(body, request)
        if err_resp is not None:
            return err_resp
        outcome = await arun_case(ctx["ledger"], ctx["gw"], ctx["case"])
        envelope = await run_in_threadpool(
            _decorate_supervisor_envelope,
            outcome.envelope,
            ledger=ctx["ledger"],
            actor_id=ctx["actor_id"],
            created_at=ctx["created_at"],
            cell_id=ctx["cell_id"],
            stated_outputs=ctx["stated_outputs"],
            event_hashes=outcome.event_hashes,
            fault_kind=outcome.fault_kind,
            formal_proof=outcome.formal_proof,
            agent_telemetry=outcome.agent_telemetry,
            citations=outcome.citations,
        )
        return JSONResponse(envelope)

    @app.post("/supervisor/stream")
    async def supervisor_stream(body: dict[str, Any], request: Request) -> Response:
        err_resp, ctx = _prepare_supervisor_run(body, request)
        if err_resp is not None:
            return err_resp

        async def event_generator():
            async for event in astream_case(ctx["ledger"], ctx["gw"], ctx["case"]):
                ev_type = event["event"]
                payload = event["data"]
                if ev_type == "done":
                    decorated = await run_in_threadpool(
                        _decorate_supervisor_envelope,
                        payload["envelope"],
                        ledger=ctx["ledger"],
                        actor_id=ctx["actor_id"],
                        created_at=ctx["created_at"],
                        cell_id=ctx["cell_id"],
                        stated_outputs=ctx["stated_outputs"],
                        event_hashes=payload.get("event_hashes", []),
                        fault_kind=payload.get("fault_kind"),
                        formal_proof=payload.get("formal_proof"),
                        agent_telemetry=payload.get("agent_telemetry", []),
                        citations=payload.get("citations"),
                    )
                    payload = {**payload, "envelope": decorated}
                yield f"event: {ev_type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.post("/auth/login")
    def login(body: dict[str, Any], request: Request) -> JSONResponse:
        if _secret() is None:
            envelope = _abstain("auth@1.0.0", {}, "session_secret_missing")
            return JSONResponse(envelope, status_code=401)
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "invalid_tenant"), status_code=400)
        login_limit = int(os.environ.get("EVIDENCE_LOGIN_RATE_LIMIT", "30"))
        client_id = _client_ip(request)
        if not _RATE_LIMITER.allow(f"login:{client_id}:{tenant_id}", login_limit, 60):
            return JSONResponse(
                _abstain("auth@1.0.0", {"tenant_id": tenant_id}, "rate_limited"),
                status_code=429,
            )
        ledger = open_ledger(tenant_id)
        actor_id = str(body.get("actor_id", ""))
        password = str(body.get("password", ""))
        if not ledger.check_password(actor_id, password):
            envelope = _abstain(
                "auth@1.0.0", {"actor_id": actor_id, "tenant_id": tenant_id}, "auth_failed"
            )
            return JSONResponse(envelope, status_code=401)
        if not get_scim_directory().is_actor_active(tenant_id, actor_id):
            envelope = _abstain(
                "auth@1.0.0", {"actor_id": actor_id, "tenant_id": tenant_id}, "scim_user_inactive"
            )
            return JSONResponse(envelope, status_code=403)
        session_tok = _token(actor_id, tenant_id)
        payload = JSONResponse(
            _ok(
                "auth@1.0.0",
                {"actor_id": actor_id, "tenant_id": tenant_id},
                {"actor_id": actor_id, "tenant_id": tenant_id, "session_token": session_tok},
            )
        )
        payload.set_cookie(
            "el_session",
            session_tok,
            httponly=True,
            samesite="lax",
            secure=_cookie_secure(request),
        )
        return payload

    @app.post("/auth/webauthn/challenge")
    def webauthn_challenge(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("webauthn@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        action = str(body.get("action") or "coverage_signoff")
        ttl_s = int(body.get("ttl_seconds") or 120)
        challenge = get_webauthn_verifier().issue_challenge(
            actor, tenant_id, action=action, ttl_seconds=ttl_s
        )
        return JSONResponse(
            _ok("webauthn@1.0.0", {"actor_id": actor, "tenant_id": tenant_id}, challenge)
        )

    @app.post("/auth/webauthn/verify")
    def webauthn_verify(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("webauthn@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        assertion = body.get("assertion") if isinstance(body.get("assertion"), dict) else body
        try:
            verified = get_webauthn_verifier().verify_assertion(
                assertion,
                expected_actor_id=actor,
                expected_tenant_id=tenant_id,
                expected_action=str(body.get("action") or "coverage_signoff"),
            )
        except ValueError as exc:
            return JSONResponse(
                _abstain("webauthn@1.0.0", {"actor_id": actor}, str(exc)),
                status_code=403,
            )
        return JSONResponse(
            _ok("webauthn@1.0.0", {"actor_id": actor, "tenant_id": tenant_id}, verified)
        )

    @app.post("/scim/v2/Users")
    def scim_create_user(
        body: dict[str, Any], request: Request, tenant_id: str = DEMO_TENANT
    ) -> JSONResponse:
        eff_tenant = _validate_tenant(body.get("tenant_id") or tenant_id)
        if eff_tenant is None:
            return JSONResponse({"detail": "invalid_tenant", "status": "400"}, status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=eff_tenant, allowed_roles={"admin", "cve", "human"}
        )
        if auth_err is not None:
            return auth_err
        try:
            user_doc = get_scim_directory().create_user(eff_tenant, body)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc), "status": "400"}, status_code=400)
        ledger = open_ledger(eff_tenant)
        roles = [str(r).lower() for r in user_doc.get("roles") or []]
        role = "cve" if "cve" in roles else ("admin" if "admin" in roles else "author")
        ledger.ensure_actor(str(user_doc["userName"]), role, secrets.token_hex(16))
        return JSONResponse(user_doc, status_code=201)

    @app.get("/scim/v2/Users/{user_id}")
    def scim_get_user(user_id: str, request: Request, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        eff_tenant = _validate_tenant(tenant_id)
        if eff_tenant is None:
            return JSONResponse({"detail": "invalid_tenant", "status": "400"}, status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=eff_tenant, allowed_roles={"admin", "cve", "human"}
        )
        if auth_err is not None:
            return auth_err
        user_doc = get_scim_directory().get_user(eff_tenant, user_id)
        if user_doc is None:
            return JSONResponse({"detail": "scim_user_not_found", "status": "404"}, status_code=404)
        return JSONResponse(user_doc)

    @app.patch("/scim/v2/Users/{user_id}")
    def scim_patch_user(
        user_id: str, body: dict[str, Any], request: Request, tenant_id: str = DEMO_TENANT
    ) -> JSONResponse:
        eff_tenant = _validate_tenant(body.get("tenant_id") or tenant_id)
        if eff_tenant is None:
            return JSONResponse({"detail": "invalid_tenant", "status": "400"}, status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=eff_tenant, allowed_roles={"admin", "cve", "human"}
        )
        if auth_err is not None:
            return auth_err
        try:
            user_doc = get_scim_directory().patch_user(eff_tenant, user_id, body)
        except KeyError:
            return JSONResponse({"detail": "scim_user_not_found", "status": "404"}, status_code=404)
        return JSONResponse(user_doc)

    @app.post("/auth/logout")
    def logout(request: Request, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "invalid_tenant"), status_code=400)
        raw = request.cookies.get("el_session", "")
        if raw:
            token_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            open_ledger(checked_tenant).revoke_token(token_digest, _now())
        resp = JSONResponse(_ok("auth@1.0.0", {"tenant_id": checked_tenant}, {"logged_out": True}))
        resp.delete_cookie("el_session", path="/")
        return resp

    @app.get("/auth/me")
    def auth_me(
        request: Request,
        tenant_id: str = DEMO_TENANT,
        optional: bool = False,
    ) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor_id = _actor_from_request(request, tenant_id=checked_tenant)
        if actor_id is None:
            if optional:
                return JSONResponse(
                    _ok(
                        "auth@1.0.0",
                        {"tenant_id": checked_tenant},
                        {"authenticated": False, "actor_id": None, "tenant_id": checked_tenant},
                    )
                )
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        role = open_ledger(checked_tenant).actor_role(actor_id)
        return JSONResponse(
            _ok(
                "auth@1.0.0",
                {"tenant_id": checked_tenant},
                {
                    "authenticated": True,
                    "actor_id": actor_id,
                    "tenant_id": checked_tenant,
                    "role": role,
                },
            )
        )

    @app.post("/ledger/append")
    def ledger_append(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("ledger@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None or actor != body.get("actor_id"):
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        event_type = body.get("event_type")
        if not isinstance(event_type, str) or not event_type.strip():
            return JSONResponse(_abstain("ledger@1.0.0", {}, "missing_event_type"), status_code=400)
        ledger = open_ledger(tenant_id)
        event_body = {**body, "tenant_id": tenant_id}
        try:
            digest = record(ledger, event_body)
        except Exception:
            return JSONResponse(
                _abstain("ledger@1.0.0", {"event_type": event_type}, "invalid_ledger_event"),
                status_code=400,
            )
        return JSONResponse(
            _ok(
                "ledger@1.0.0",
                {"event_type": event_type, "tenant_id": tenant_id},
                {"event_hash": digest},
            )
        )

    _verify_cache: dict[tuple[str, str], dict[str, Any]] = {}
    _verify_cache_lock = threading.RLock()

    @app.get("/ledger/verify")
    def ledger_verify(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("ledger@1.0.0", {}, "invalid_tenant"), status_code=400)
        with get_telemetry().start_span(
            "api.ledger_verify", stage="api", attributes={"tenant_id": checked_tenant}
        ):
            ledger = open_ledger(checked_tenant)
            head = ledger.head_hash()
            cache_key = (checked_tenant, head)
            with _verify_cache_lock:
                cached = _verify_cache.get(cache_key)
                if cached is not None:
                    return JSONResponse(_ok("ledger@1.0.0", {"tenant_id": checked_tenant}, cached))
            stats = (
                ledger.coverage_summary_fast() if hasattr(ledger, "coverage_summary_fast") else None
            )
            if hasattr(ledger, "verify_incremental"):
                inc = ledger.verify_incremental(from_latest_checkpoint=True)
                chain_ok = bool(inc["ok"])
                verified_from_seq = int(inc.get("verified_from_seq", 0))
            else:
                chain_ok = bool(ledger.verify())
                verified_from_seq = 0
            ev_count = int(stats["event_count"]) if stats is not None else len(ledger.events())
            payload = {
                "chain_verified": chain_ok,
                "head_hash": head,
                "merkle_root": ledger.merkle_root(),
                "event_count": str(ev_count),
                "verified_from_seq": verified_from_seq,
            }
            with _verify_cache_lock:
                if len(_verify_cache) >= 128:
                    _verify_cache.pop(next(iter(_verify_cache)), None)
                _verify_cache[cache_key] = payload
            return JSONResponse(_ok("ledger@1.0.0", {"tenant_id": checked_tenant}, payload))

    @app.get("/ledger/events")
    def ledger_events(
        tenant_id: str = DEMO_TENANT,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("ledger@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked_tenant)
        clamped_limit = max(1, min(limit, 200))
        clamped_offset = max(0, offset)
        query_result = ledger.query_events(
            event_type=event_type or None,
            actor_id=actor_id or None,
            limit=clamped_limit,
            offset=clamped_offset,
        )
        return JSONResponse(
            _ok(
                "ledger@1.0.0",
                {
                    "tenant_id": checked_tenant,
                    "event_type": event_type,
                    "actor_id": actor_id,
                    "limit": str(clamped_limit),
                    "offset": str(clamped_offset),
                },
                query_result,
            )
        )

    @app.get("/ledger/consistency")
    def ledger_consistency(old_count: int = 0, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("merkle_consistency@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger(checked_tenant)
        try:
            proof = ledger.consistency_snapshot(old_count)
        except ValueError:
            return JSONResponse(
                _abstain(
                    "merkle_consistency@1.0.0",
                    {"old_count": str(old_count), "tenant_id": checked_tenant},
                    "invalid_old_count",
                ),
                status_code=400,
            )
        return JSONResponse(
            _ok(
                "merkle_consistency@1.0.0",
                {"old_count": str(old_count), "tenant_id": checked_tenant},
                proof,
            )
        )

    @app.get("/ledger/proof/{event_hash}")
    def ledger_proof(event_hash: str, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("merkle_proof@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger(checked_tenant)
        try:
            proof = ledger.inclusion_proof(event_hash)
        except ValueError:
            return JSONResponse(
                _abstain("merkle_proof@1.0.0", {"event_hash": event_hash}, "event_not_found"),
                status_code=404,
            )
        return JSONResponse(_ok("merkle_proof@1.0.0", {"event_hash": event_hash}, proof))

    @app.post("/coverage/signoff")
    @app.post("/ledger/signoff")
    def ledger_signoff(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("human_signoff@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor_id = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        target = str(body.get("target_event_hash") or ledger.head_hash())
        if target == GENESIS:
            return JSONResponse(
                _abstain("human_signoff@1.0.0", {}, "empty_ledger"),
                status_code=400,
            )
        known_events = {str(event["event_hash"]): event for event in ledger.events()}
        if target not in known_events:
            return JSONResponse(
                _abstain(
                    "human_signoff@1.0.0",
                    {"target_event_hash": target},
                    "target_event_not_found",
                ),
                status_code=404,
            )
        target_ev = known_events[target]
        target_author = target_ev["body"].get("actor_id")
        actor_role = ledger.actor_role(actor_id)
        if actor_role == "author":
            return JSONResponse(
                _abstain(
                    "human_signoff@1.0.0",
                    {"target_event_hash": target, "role": actor_role},
                    "cve_role_required",
                ),
                status_code=403,
            )
        strict_distinct = _is_production_mode() or bool(body.get("enforce_distinct_reviewer"))
        if strict_distinct and target_author == actor_id:
            return JSONResponse(
                _abstain(
                    "human_signoff@1.0.0",
                    {"target_event_hash": target},
                    "self_signoff_prohibited",
                ),
                status_code=403,
            )
        require_webauthn = bool(body.get("require_webauthn")) or (
            os.environ.get("EVIDENCE_REQUIRE_WEBAUTHN", "").strip() == "1"
        )
        webauthn_verified = False
        if require_webauthn or body.get("webauthn_assertion") or body.get("webauthn_token"):
            verifier = get_webauthn_verifier()
            if isinstance(body.get("webauthn_assertion"), dict):
                try:
                    verifier.verify_assertion(
                        body["webauthn_assertion"],
                        expected_actor_id=actor_id,
                        expected_tenant_id=tenant_id,
                        expected_action="coverage_signoff",
                    )
                    webauthn_verified = True
                except ValueError as exc:
                    return JSONResponse(
                        _abstain(
                            "human_signoff@1.0.0",
                            {"target_event_hash": target},
                            str(exc),
                        ),
                        status_code=403,
                    )
            elif body.get("webauthn_token"):
                webauthn_verified = verifier.consume_step_up_token(
                    str(body["webauthn_token"]),
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    action="coverage_signoff",
                )
            if require_webauthn and not webauthn_verified:
                return JSONResponse(
                    _abstain(
                        "human_signoff@1.0.0",
                        {"target_event_hash": target},
                        "webauthn_step_up_required",
                    ),
                    status_code=403,
                )
        blocking_threads = get_review_thread_store().unresolved_blocking_threads(
            tenant_id, target_event_hash=target
        )
        if blocking_threads:
            return JSONResponse(
                _abstain(
                    "human_signoff@1.0.0",
                    {
                        "target_event_hash": target,
                        "blocking_threads": [t["thread_id"] for t in blocking_threads],
                    },
                    "unresolved_review_threads",
                ),
                status_code=409,
            )
        statement = str(body.get("statement") or SIGN_OFF_STATEMENT)
        created_at = str(body.get("created_at") or _now())
        review_duration_ms: int | None = None
        if body.get("review_duration_ms") is not None:
            try:
                review_duration_ms = int(body["review_duration_ms"])
            except (TypeError, ValueError):
                return JSONResponse(
                    _abstain(
                        "human_signoff@1.0.0", {"target_event_hash": target}, "invalid_duration"
                    ),
                    status_code=400,
                )
            if review_duration_ms < 0:
                return JSONResponse(
                    _abstain(
                        "human_signoff@1.0.0", {"target_event_hash": target}, "invalid_duration"
                    ),
                    status_code=400,
                )
        signoff_inputs = {"target_event_hash": target, "statement": statement}
        signoff_payload: dict[str, Any] = {
            "actor_id": actor_id,
            "target_event_hash": target,
            "statement": statement,
        }
        if review_duration_ms is not None:
            signoff_payload["review_duration_ms"] = review_duration_ms
        envelope = make_envelope(
            sources=[
                project_source("human-review", "https://aeroregu.local/signoff", "ASSUMPTION")
            ],
            method_version="human_signoff@1.0.0",
            inputs=signoff_inputs,
            confidence="deterministic",
            result=signoff_payload,
        )
        try:
            ev_hash = record(
                ledger,
                {
                    "event_type": "human_signoff",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": signoff_payload,
                    "envelope": envelope,
                },
            )
        except LedgerError:
            return JSONResponse(
                _abstain("human_signoff@1.0.0", signoff_inputs, "invalid_signoff"),
                status_code=400,
            )
        locked_threads = get_review_thread_store().lock_threads_on_signoff(
            tenant_id,
            target_event_hash=target,
            signoff_event_hash=ev_hash,
            signed_by=actor_id,
        )
        return JSONResponse(
            _ok(
                "human_signoff@1.0.0",
                signoff_inputs,
                {
                    "event_hash": ev_hash,
                    "actor_id": actor_id,
                    "role": actor_role,
                    "distinct_reviewer": bool(target_author and target_author != actor_id),
                    "target_event_hash": target,
                    "statement": statement,
                    "review_duration_ms": review_duration_ms,
                    "webauthn_verified": webauthn_verified,
                    "locked_review_threads": [t["thread_id"] for t in locked_threads],
                    "merkle_root": ledger.merkle_root(),
                },
            )
        )

    @app.get("/metrics/pilot")
    def pilot_metrics(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("pilot_metrics@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger(checked_tenant)
        events = ledger.events()
        signoffs = [ev for ev in events if ev["body"]["event_type"] == "human_signoff"]
        durations = [
            int(ev["body"]["payload"]["review_duration_ms"])
            for ev in signoffs
            if isinstance(ev["body"]["payload"].get("review_duration_ms"), (int, float))
        ]
        avg_ms = sum(durations) // len(durations) if durations else None
        sorted_d = sorted(durations)
        med_ms = sorted_d[len(sorted_d) // 2] if sorted_d else None
        return JSONResponse(
            _ok(
                "pilot_metrics@1.0.0",
                {"tenant_id": checked_tenant},
                {
                    "signed_reviews": len(signoffs),
                    "timed_reviews": len(durations),
                    "avg_review_duration_ms": avg_ms,
                    "median_review_duration_ms": med_ms,
                    "total_ledger_events": len(events),
                },
            )
        )

    @app.get("/attestation/public-key")
    def attestation_public_key() -> JSONResponse:
        _, pub_pem = _attestation_keypair()
        return JSONResponse(
            _ok(
                "attestation_key@1.0.0",
                {},
                {"alg": "ed25519", "public_key_pem": pub_pem.decode("utf-8")},
            )
        )

    @app.post("/export/zip")
    def export_zip(request: Request, tenant_id: str = DEMO_TENANT) -> Response:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("export@1.0.0", {}, "invalid_tenant"), status_code=400)
        if _actor_from_request(request, tenant_id=checked_tenant) is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(checked_tenant)
        blob = _zip_bytes(ledger.events())
        return Response(content=blob, media_type="application/zip")

    @app.post("/export/bundle/qes")
    def export_bundle_qes(request: Request, body: dict[str, Any] | None = None) -> JSONResponse:
        req = body or {}
        checked_tenant = _validate_tenant(str(req.get("tenant_id") or DEMO_TENANT))
        if checked_tenant is None:
            return JSONResponse(_abstain("export_qes@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _session_actor(request, req.get("actor_id"), tenant_id=checked_tenant)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        profile = str(req.get("profile") or "CAdES-B-LT")
        if profile not in {"CAdES-B-LT", "PAdES-B-LT"}:
            return JSONResponse(
                _abstain("export_qes@1.0.0", {"profile": profile}, "unsupported_qes_profile"),
                status_code=400,
            )
        ledger = open_ledger(checked_tenant)
        bundle_bytes = _zip_bytes(ledger.events())
        qes_svc = get_qes_envelope_service()
        envelope = qes_svc.build_envelope(
            bundle_bytes,
            signer_id=actor,
            profile=profile,
            key_uri=req.get("key_uri"),
        )
        verification = EidasQESEnvelope.verify_envelope(envelope, bundle_bytes)
        slot_info = get_hsm_signer().get_slot_info(req.get("key_uri"))
        return JSONResponse(
            _ok(
                "export_qes@1.0.0",
                {"tenant_id": checked_tenant, "profile": profile},
                {
                    "tenant_id": checked_tenant,
                    "signer_id": actor,
                    "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
                    "bundle_size_bytes": len(bundle_bytes),
                    "bundle_zip_b64": base64.b64encode(bundle_bytes).decode("ascii"),
                    "qes_envelope": envelope,
                    "verification": verification,
                    "hsm_slot": slot_info,
                },
            )
        )

    @app.post("/mcp")
    async def mcp_http_endpoint(request: Request, tenant_id: str = DEMO_TENANT) -> Response:
        from evidence_api.mcp_server import handle_mcp_message

        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32602, "message": "Invalid tenant"},
                },
                status_code=400,
            )
        mcp_limit = int(os.environ.get("EVIDENCE_MCP_RATE_LIMIT", "120"))
        if not _RATE_LIMITER.allow(f"mcp:{_client_ip(request)}:{checked_tenant}", mcp_limit, 60):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32005, "message": "Rate limit exceeded"},
                },
                status_code=429,
            )
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                },
                status_code=400,
            )
        is_auth = _actor_from_request(request, tenant_id=checked_tenant) is not None
        reply = await run_in_threadpool(
            handle_mcp_message,
            payload,
            require_auth_for_writes=_is_production_mode(),
            is_authenticated=is_auth,
        )
        if reply is None:
            return Response(status_code=204)
        return JSONResponse(reply)

    @app.get("/static/viewer3d.js")
    def viewer3d_script() -> FileResponse:
        return FileResponse(
            Path(__file__).parent / "static" / "viewer3d.js",
            media_type="application/javascript",
        )

    @app.get("/static/q4_ux_modules.js")
    def q4_ux_modules_script() -> FileResponse:
        return FileResponse(
            Path(__file__).parent / "static" / "q4_ux_modules.js",
            media_type="application/javascript",
        )

    @app.get("/static/quotation_cockpit.js")
    def quotation_cockpit_script() -> FileResponse:
        return FileResponse(
            Path(__file__).parent / "static" / "quotation_cockpit.js",
            media_type="application/javascript",
        )

    @app.post("/cad/ingest")
    def cad_ingest(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("cad_ingest@1.0.0", {}, "invalid_tenant"), status_code=400)
        filename = str(body.get("filename") or "model.stp")
        records = bool(body.get("record"))
        actor_id = str(body.get("actor_id") or "author")
        if records:
            session_actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
            if session_actor is None:
                return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
            actor_id = session_actor

        raw, err = _decode_body_bytes(body, "cad_ingest@1.0.0", filename)
        if err is not None or raw is None:
            return err or JSONResponse(
                _abstain("cad_ingest@1.0.0", {"filename": filename}, "missing_document_content"),
                status_code=400,
            )
        try:
            parsed = ingest_bytes(raw, filename)
        except IngestAbstain as exc:
            return JSONResponse(
                _abstain("cad_ingest@1.0.0", {"filename": filename}, exc.reason),
            )
        cad_cae = parsed.get("cad_cae")
        if not isinstance(cad_cae, dict):
            return JSONResponse(
                _abstain("cad_ingest@1.0.0", {"filename": filename}, "not_cad_cae_media"),
            )

        auto_run = bool(body.get("auto_run", True))
        bindings = bind_parameters_to_cards(
            list(cad_cae.get("parameters") or []),
            formulas=list(cad_cae.get("formulas") or []),
            auto_run=auto_run,
        )
        stated_by_method = body.get("stated_outputs")
        if isinstance(stated_by_method, dict):
            _attach_binding_deltas(bindings, stated_by_method)

        recorded_hash = ""
        if records:
            ledger = open_ledger(tenant_id)
            created_at = str(body.get("created_at") or _now())
            cad_env = make_envelope(
                sources=[project_source("cad-cae", "https://aeroregu.local/cad", "ASSUMPTION")],
                method_version="cad_ingest@1.0.0",
                inputs={"filename": parsed["filename"], "source_hash": parsed["source_hash"]},
                confidence="deterministic",
                result={
                    "format": cad_cae.get("format"),
                    "ready_methods": bindings.get("ready_methods", []),
                    "total_parameters_scanned": bindings.get("total_parameters_scanned", 0),
                },
            )
            recorded_hash = record(
                ledger,
                {
                    "event_type": "cad_cae_ingested",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": {
                        "filename": parsed["filename"],
                        "media_type": parsed["media_type"],
                        "source_hash": parsed["source_hash"],
                        "format": cad_cae.get("format"),
                        "ready_methods": bindings.get("ready_methods", []),
                    },
                    "envelope": cad_env,
                },
            )

        return JSONResponse(
            _ok(
                "cad_ingest@1.0.0",
                {"filename": parsed["filename"], "source_hash": parsed["source_hash"]},
                {
                    "filename": parsed["filename"],
                    "media_type": parsed["media_type"],
                    "source_hash": parsed["source_hash"],
                    "cad_cae": cad_cae,
                    "bindings": bindings,
                    "recorded_event_hash": recorded_hash,
                },
            )
        )

    @app.post("/cad/bind")
    def cad_bind(body: dict[str, Any]) -> JSONResponse:
        parameters = body.get("parameters")
        if not isinstance(parameters, list):
            return JSONResponse(
                _abstain("cad_bind@1.0.0", {}, "missing_parameters"), status_code=400
            )
        formulas = body.get("formulas") if isinstance(body.get("formulas"), list) else None
        auto_run = bool(body.get("auto_run", True))
        bindings = bind_parameters_to_cards(parameters, formulas=formulas, auto_run=auto_run)
        stated_by_method = body.get("stated_outputs")
        if isinstance(stated_by_method, dict):
            _attach_binding_deltas(bindings, stated_by_method)
        return JSONResponse(
            _ok(
                "cad_bind@1.0.0",
                {"parameter_count": str(len(parameters)), "auto_run": auto_run},
                bindings,
            )
        )

    @app.get("/coverage/envelope-3d")
    def coverage_envelope_3d_get(
        tenant_id: str = DEMO_TENANT,
        wing_area_m2: str = "12.000",
        v_c_mps: str = "65.000",
        v_d_mps: str = "82.000",
        nz_max: str = "2.500",
        nz_min: str = "-1.000",
    ) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("coverage_envelope_3d@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        try:
            for val in (wing_area_m2, v_c_mps, v_d_mps, nz_max, nz_min):
                Decimal(str(val))
        except (InvalidOperation, ValueError):
            return JSONResponse(
                _abstain("coverage_envelope_3d@1.0.0", {}, "invalid_numeric_input"), status_code=400
            )
        ledger = open_ledger(checked_tenant)
        payload = build_vn_cg_envelope_3d(
            ledger.events(),
            wing_area_m2=wing_area_m2,
            v_c_mps=v_c_mps,
            v_d_mps=v_d_mps,
            nz_max=nz_max,
            nz_min=nz_min,
        )
        return JSONResponse(
            _ok("coverage_envelope_3d@1.0.0", {"tenant_id": checked_tenant}, payload)
        )

    @app.post("/coverage/envelope-3d")
    def coverage_envelope_3d_post(body: dict[str, Any]) -> JSONResponse:
        checked_tenant = _validate_tenant(body.get("tenant_id"))
        if checked_tenant is None:
            return JSONResponse(
                _abstain("coverage_envelope_3d@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        wing_area_m2 = str(body.get("wing_area_m2") or "12.000")
        v_c_mps = str(body.get("v_c_mps") or "65.000")
        v_d_mps = str(body.get("v_d_mps") or "82.000")
        nz_max = str(body.get("nz_max") or "2.500")
        nz_min = str(body.get("nz_min") or "-1.000")
        mass_override = (
            str(body["mass_kg_override"]) if body.get("mass_kg_override") is not None else None
        )
        cad_cg_points = (
            list(body["cad_cg_points"]) if isinstance(body.get("cad_cg_points"), list) else None
        )
        cg_limits_m = (
            dict(body["cg_limits_m"]) if isinstance(body.get("cg_limits_m"), dict) else None
        )
        fem_overlay = (
            dict(body["fem_overlay"]) if isinstance(body.get("fem_overlay"), dict) else None
        )
        try:
            for val in (wing_area_m2, v_c_mps, v_d_mps, nz_max, nz_min):
                Decimal(val)
            if mass_override is not None:
                Decimal(mass_override)
            for pt in cad_cg_points or []:
                for k in ("x_cg_m", "y_cg_m", "z_cg_m", "x_m", "y_m", "z_m"):
                    if k in pt and pt[k] is not None:
                        Decimal(str(pt[k]))
        except (InvalidOperation, ValueError, TypeError):
            return JSONResponse(
                _abstain("coverage_envelope_3d@1.0.0", {}, "invalid_numeric_input"), status_code=400
            )
        ledger = open_ledger(checked_tenant)
        payload = build_vn_cg_envelope_3d(
            ledger.events(),
            cad_cg_points=cad_cg_points,
            mass_kg_override=mass_override,
            wing_area_m2=wing_area_m2,
            v_c_mps=v_c_mps,
            v_d_mps=v_d_mps,
            nz_max=nz_max,
            nz_min=nz_min,
            cg_limits_m=cg_limits_m,
            fem_overlay=fem_overlay,
        )
        return JSONResponse(
            _ok(
                "coverage_envelope_3d@1.0.0",
                {
                    "tenant_id": checked_tenant,
                    "cad_cg_count": str(len(cad_cg_points or [])),
                },
                payload,
            )
        )

    @app.get("/calc/cards")
    def calc_cards_list() -> JSONResponse:
        cards = list_cards()
        return JSONResponse(_ok("calc_catalog@1.0.0", {}, {"methods": cards, "count": len(cards)}))

    @app.post("/calc/cards")
    def calc_cards_register(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("calc_catalog@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        if _is_production_mode():
            actor = _actor_from_request(request, tenant_id=tenant_id)
            if actor is None:
                return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
            if open_ledger(tenant_id).actor_role(actor) not in {"admin", "cve", "human"}:
                return JSONResponse(
                    _abstain("auth@1.0.0", {}, "admin_or_cve_required"), status_code=403
                )
        card_payload = body.get("card") if isinstance(body.get("card"), dict) else body
        try:
            saved = register_custom_card(card_payload)
        except AbstainError as exc:
            return JSONResponse(_abstain("calc_catalog@1.0.0", {}, exc.reason), status_code=400)
        return JSONResponse(
            _ok("calc_catalog@1.0.0", {"method_id": saved["method_id"]}, {"card": saved})
        )

    @app.delete("/calc/cards/{method_id}")
    def calc_cards_delete(
        method_id: str, request: Request, tenant_id: str = DEMO_TENANT
    ) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("calc_catalog@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        if _is_production_mode() and _actor_from_request(request, tenant_id=checked_tenant) is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        removed = delete_plugin_card(method_id)
        if not removed:
            return JSONResponse(
                _abstain(
                    "calc_catalog@1.0.0", {"method_id": method_id}, "plugin_not_found_or_builtin"
                ),
                status_code=404,
            )
        return JSONResponse(_ok("calc_catalog@1.0.0", {"method_id": method_id}, {"deleted": True}))

    @app.post("/sso/oidc/callback")
    def sso_oidc_callback(body: dict[str, Any], request: Request) -> JSONResponse:
        if _secret() is None:
            return JSONResponse(
                _abstain("sso_oidc@1.0.0", {}, "session_secret_missing"), status_code=401
            )
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("sso_oidc@1.0.0", {}, "invalid_tenant"), status_code=400)
        id_token = str(body.get("id_token") or "")
        if not id_token:
            return JSONResponse(_abstain("sso_oidc@1.0.0", {}, "missing_id_token"), status_code=400)

        env_jwks_raw = os.environ.get("EVIDENCE_OIDC_JWKS_JSON", "").strip()
        env_jwks = json.loads(env_jwks_raw) if env_jwks_raw else None
        req_jwks = (
            body.get("jwks")
            if (not _is_production_mode() and isinstance(body.get("jwks"), dict))
            else None
        )
        jwks_obj = env_jwks or req_jwks
        issuer = os.environ.get("EVIDENCE_OIDC_ISSUER", "").strip() or (
            str(body.get("issuer") or "") if not _is_production_mode() else ""
        )
        audience = os.environ.get("EVIDENCE_OIDC_AUDIENCE", "").strip() or (
            str(body.get("audience") or "") if not _is_production_mode() else ""
        )
        jwks_uri = os.environ.get("EVIDENCE_OIDC_JWKS_URI", "").strip() or None
        if not issuer or not audience or (jwks_obj is None and not jwks_uri):
            return JSONResponse(
                _abstain("sso_oidc@1.0.0", {}, "oidc_provider_not_configured"), status_code=400
            )

        verifier = OIDCVerifier(
            OIDCConfig(
                provider_name=str(
                    body.get("provider") or os.environ.get("EVIDENCE_OIDC_PROVIDER", "entra_id")
                ),
                issuer=issuer,
                audience=audience,
                jwks=jwks_obj,
                jwks_uri=jwks_uri,
            )
        )
        try:
            identity = verifier.verify_id_token(id_token, expected_nonce=body.get("nonce"))
        except SSOValidationError as exc:
            return JSONResponse(_abstain("sso_oidc@1.0.0", {}, str(exc)), status_code=401)

        ledger = open_ledger(tenant_id)
        role = ledger.ensure_sso_actor(identity["actor_id"], identity["role"])
        resp = JSONResponse(
            _ok(
                "sso_oidc@1.0.0",
                {"tenant_id": tenant_id, "provider": identity["provider"]},
                {
                    "actor_id": identity["actor_id"],
                    "role": role,
                    "provider": identity["provider"],
                    "tenant_id": tenant_id,
                },
            )
        )
        resp.set_cookie(
            "el_session",
            _token(identity["actor_id"], tenant_id),
            httponly=True,
            samesite="lax",
            secure=_cookie_secure(request),
        )
        return resp

    @app.post("/sso/saml/acs")
    def sso_saml_acs(body: dict[str, Any], request: Request) -> JSONResponse:
        if _secret() is None:
            return JSONResponse(
                _abstain("sso_saml@1.0.0", {}, "session_secret_missing"), status_code=401
            )
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("sso_saml@1.0.0", {}, "invalid_tenant"), status_code=400)
        saml_b64 = str(body.get("saml_response") or "")
        if not saml_b64:
            return JSONResponse(
                _abstain("sso_saml@1.0.0", {}, "missing_saml_response"), status_code=400
            )

        idp_entity = os.environ.get("EVIDENCE_SAML_IDP_ENTITY_ID", "").strip() or (
            str(body.get("idp_entity_id") or "") if not _is_production_mode() else ""
        )
        sp_entity = os.environ.get("EVIDENCE_SAML_SP_ENTITY_ID", "").strip() or (
            str(body.get("sp_entity_id") or "") if not _is_production_mode() else ""
        )
        cert_pem = os.environ.get("EVIDENCE_SAML_CERT_PEM", "").replace("\\n", "\n").strip() or (
            str(body.get("idp_certificate_pem") or "") if not _is_production_mode() else ""
        )
        if not idp_entity or not sp_entity or not cert_pem:
            return JSONResponse(
                _abstain("sso_saml@1.0.0", {}, "saml_provider_not_configured"), status_code=400
            )

        try:
            verifier = SAML2Verifier(
                SAMLConfig(
                    provider_name=str(body.get("provider") or "okta_saml"),
                    idp_entity_id=idp_entity,
                    sp_entity_id=sp_entity,
                    idp_certificate_pem=cert_pem,
                )
            )
            identity = verifier.verify_saml_response(saml_b64)
        except (SSOValidationError, ValueError) as exc:
            return JSONResponse(_abstain("sso_saml@1.0.0", {}, str(exc)), status_code=401)

        ledger = open_ledger(tenant_id)
        role = ledger.ensure_sso_actor(identity["actor_id"], identity["role"])
        resp = JSONResponse(
            _ok(
                "sso_saml@1.0.0",
                {"tenant_id": tenant_id, "provider": identity["provider"]},
                {
                    "actor_id": identity["actor_id"],
                    "role": role,
                    "provider": identity["provider"],
                    "tenant_id": tenant_id,
                },
            )
        )
        resp.set_cookie(
            "el_session",
            _token(identity["actor_id"], tenant_id),
            httponly=True,
            samesite="lax",
            secure=_cookie_secure(request),
        )
        return resp

    @app.get("/admin/roles")
    def admin_roles_list(request: Request, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("rbac@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _actor_from_request(request, tenant_id=checked_tenant)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(checked_tenant)
        if ledger.actor_role(actor) not in {"admin", "human"}:
            return JSONResponse(_abstain("rbac@1.0.0", {}, "admin_role_required"), status_code=403)
        return JSONResponse(
            _ok("rbac@1.0.0", {"tenant_id": checked_tenant}, {"actors": ledger.list_actors()})
        )

    @app.post("/admin/roles")
    def admin_roles_set(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("rbac@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _actor_from_request(request, tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        if ledger.actor_role(actor) != "admin":
            return JSONResponse(_abstain("rbac@1.0.0", {}, "admin_role_required"), status_code=403)
        target_actor = str(body.get("target_actor_id") or "").strip()
        target_role = str(body.get("role") or "").strip().lower()
        if not target_actor:
            return JSONResponse(
                _abstain("rbac@1.0.0", {}, "missing_target_actor_id"), status_code=400
            )
        try:
            ledger.set_actor_role(target_actor, target_role)
        except LedgerError as exc:
            return JSONResponse(_abstain("rbac@1.0.0", {}, str(exc)), status_code=400)
        return JSONResponse(
            _ok(
                "rbac@1.0.0",
                {"tenant_id": tenant_id, "target_actor_id": target_actor},
                {"actor_id": target_actor, "role": target_role},
            )
        )

    @app.get("/blobs")
    def blobs_list(request: Request, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("blob_store@1.0.0", {}, "invalid_tenant"), status_code=400)
        if _is_production_mode() and _actor_from_request(request, tenant_id=checked_tenant) is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        store = open_blob_store(evidence_home())
        return JSONResponse(
            _ok(
                "blob_store@1.0.0",
                {"backend": store.backend_name},
                {"backend": store.backend_name, "blobs": store.list_blobs()},
            )
        )

    @app.post("/blobs")
    def blobs_upload(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("blob_store@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _actor_from_request(request, tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        filename = str(body.get("filename") or "artifact.bin")
        raw, err = _decode_body_bytes(body, "blob_store@1.0.0", filename)
        if err is not None or raw is None:
            return err or JSONResponse(
                _abstain("blob_store@1.0.0", {}, "missing_content"), status_code=400
            )
        ctype = str(body.get("content_type") or "application/octet-stream")
        meta = open_blob_store(evidence_home()).put_blob(raw, content_type=ctype, filename=filename)
        return JSONResponse(_ok("blob_store@1.0.0", {"sha256": meta["sha256"]}, meta))

    @app.get("/blobs/{sha256_hex}")
    def blobs_download(sha256_hex: str, request: Request, tenant_id: str = DEMO_TENANT) -> Response:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("blob_store@1.0.0", {}, "invalid_tenant"), status_code=400)
        if _is_production_mode() and _actor_from_request(request, tenant_id=checked_tenant) is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        store = open_blob_store(evidence_home())
        try:
            data = store.get_blob(sha256_hex)
            meta = store.head_blob(sha256_hex) or {}
        except BlobStoreError as exc:
            return JSONResponse(_abstain("blob_store@1.0.0", {}, str(exc)), status_code=400)
        except FileNotFoundError:
            return JSONResponse(_abstain("blob_store@1.0.0", {}, "blob_not_found"), status_code=404)
        return Response(
            content=data,
            media_type=str(meta.get("content_type") or "application/octet-stream"),
        )

    @app.get("/webhooks")
    def webhooks_list(request: Request, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("webhooks@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _actor_from_request(request, tenant_id=checked_tenant)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(checked_tenant)
        return JSONResponse(
            _ok(
                "webhooks@1.0.0",
                {"tenant_id": checked_tenant},
                {
                    "webhooks": ledger.list_webhooks(),
                    "deliveries": ledger.list_webhook_deliveries(),
                },
            )
        )

    @app.post("/webhooks")
    def webhooks_register(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("webhooks@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _actor_from_request(request, tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        if ledger.actor_role(actor) not in {"admin", "cve", "human"}:
            return JSONResponse(
                _abstain("webhooks@1.0.0", {}, "admin_or_cve_required"), status_code=403
            )
        allow_private = (not _is_production_mode()) and bool(body.get("allow_private_targets"))
        try:
            record_obj = new_webhook_record(
                url=str(body.get("url") or ""),
                events=body.get("events"),
                secret=body.get("secret"),
                description=str(body.get("description") or ""),
                allow_private_targets=allow_private,
            )
        except WebhookError as exc:
            return JSONResponse(_abstain("webhooks@1.0.0", {}, str(exc)), status_code=400)
        saved = ledger.register_webhook(record_obj)
        return JSONResponse(_ok("webhooks@1.0.0", {"webhook_id": saved["webhook_id"]}, saved))

    @app.delete("/webhooks/{webhook_id}")
    def webhooks_delete(
        webhook_id: str, request: Request, tenant_id: str = DEMO_TENANT
    ) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("webhooks@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _actor_from_request(request, tenant_id=checked_tenant)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(checked_tenant)
        if not ledger.delete_webhook(webhook_id):
            return JSONResponse(
                _abstain("webhooks@1.0.0", {}, "webhook_not_found"), status_code=404
            )
        return JSONResponse(_ok("webhooks@1.0.0", {"webhook_id": webhook_id}, {"deleted": True}))

    @app.get("/dossier/pdf")
    def dossier_pdf_download(
        tenant_id: str = DEMO_TENANT,
        enforce_distinct: bool = False,
        require_signoff: bool = False,
    ) -> Response:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("dossier_pdf@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger(checked_tenant)
        events = ledger.events()
        priv_pem, pub_pem = _attestation_keypair()

        # Gather any source PDFs stored in the object store matching hashes referenced in events
        pdf_sources: dict[str, bytes] = {}
        store = open_blob_store(evidence_home())
        for ev in events:
            payload = (ev.get("body") or {}).get("payload") or {}
            hashes: set[str] = set()
            if payload.get("source_hash"):
                hashes.add(str(payload["source_hash"]))
            if payload.get("source_file_hash"):
                hashes.add(str(payload["source_file_hash"]))
            for req in payload.get("requirements") or []:
                if isinstance(req, dict) and (
                    req.get("source_hash") or req.get("source_file_hash")
                ):
                    hashes.add(str(req.get("source_hash") or req.get("source_file_hash")))
            for src in ((ev.get("body") or {}).get("envelope") or {}).get("sources") or []:
                if isinstance(src, dict) and src.get("content_hash"):
                    hashes.add(str(src["content_hash"]))
            for h in hashes:
                if h in pdf_sources or len(h) != 64:
                    continue
                try:
                    blob = store.get_blob(h)
                    if blob.startswith(b"%PDF"):
                        pdf_sources[h] = blob
                except Exception:
                    continue

        report = build_signed_pdf_report(
            events,
            tenant_id=checked_tenant,
            chain_verified=ledger.verify(),
            private_key_pem=priv_pem,
            public_key_pem=pub_pem,
            pdf_sources=pdf_sources or None,
            enforce_distinct_reviewer=enforce_distinct,
            require_head_signoff=require_signoff,
        )
        headers = {
            "Content-Disposition": f'attachment; filename="aeroregu-dossier-{checked_tenant}.pdf"',
            "X-Evidence-Merkle-Root": report["merkle_root"],
            "X-Evidence-PDF-SHA256": report["pdf_sha256"],
        }
        return Response(content=report["pdf_bytes"], media_type="application/pdf", headers=headers)

    @app.post("/dossier/pdf/verify")
    def dossier_pdf_verify(body: dict[str, Any]) -> JSONResponse:
        raw, err = _decode_body_bytes(body, "dossier_pdf_verify@1.0.0", "dossier.pdf")
        if err is not None or raw is None:
            return err or JSONResponse(
                _abstain("dossier_pdf_verify@1.0.0", {}, "missing_pdf"), status_code=400
            )
        _, pub_pem = _attestation_keypair()
        expected_pub = (
            str(body["public_key_pem"]).encode("utf-8") if body.get("public_key_pem") else pub_pem
        )
        verdict = verify_signed_pdf_report(raw, expected_public_key_pem=expected_pub)
        return JSONResponse(_ok("dossier_pdf_verify@1.0.0", {}, verdict))

    @app.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(
            content=get_telemetry().render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/metrics/observability")
    def observability_metrics() -> JSONResponse:
        return JSONResponse(_ok("observability@1.0.0", {}, get_telemetry().snapshot()))

    @app.get("/metrics/prometheus")
    def prometheus_metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(
            get_telemetry().render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    @app.get("/telemetry/otlp")
    def telemetry_otlp(trace_id: str | None = None) -> JSONResponse:
        return JSONResponse(
            _ok("observability@1.0.0", {}, get_telemetry().export_otlp(trace_id=trace_id))
        )

    _cae_meshes: dict[str, dict[str, Any]] = {}
    _cae_element_index: dict[tuple[str, int], dict[str, Any]] = {}

    @app.post("/cae/mesh/{model_id}")
    def register_cae_mesh(model_id: str, body: dict[str, Any], request: Request) -> JSONResponse:
        checked = _validate_tenant(str(body.get("tenant_id", DEMO_TENANT)))
        if checked is None:
            return JSONResponse(_abstain("cae@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        elements = list(body.get("elements") or [])
        _cae_meshes[f"{checked}:{model_id}"] = {
            "model_id": model_id,
            "tenant_id": checked,
            "node_count": int(body.get("node_count", len(body.get("nodeCoords", {})))),
            "element_count": len(elements),
            "nodeCoords": body.get("nodeCoords") or {},
            "elements": elements,
            "pid_summary": body.get("pid_summary") or {},
            "pdf_citations": body.get("pdf_citations") or {},
        }
        citations = body.get("pdf_citations") or {}
        for el in elements:
            eid = int(el["element_id"])
            pid = int(el.get("pid", 0))
            _cae_element_index[(checked, eid)] = {
                "model_id": model_id,
                "element_id": eid,
                "pid": pid,
                "element_type": el.get("element_type", "CQUAD4"),
                "subcase_id": int(el.get("subcase_id", 1)),
                "ms_min": str(el.get("ms_min", "0.250")),
                "von_mises_mpa": str(el.get("von_mises_mpa", "120.0")),
                "calc_event_hash": str(el.get("calc_event_hash") or f"calc-{pid}-{eid}"),
                "pdf_citation": citations.get(str(pid))
                or el.get("pdf_citation")
                or {
                    "doc_id": "stress_report.pdf",
                    "page_no": 1,
                    "bbox": [48.0, 120.0, 420.0, 148.0],
                },
            }
        return JSONResponse(
            _ok(
                "cae@1.0.0",
                {"tenant_id": checked, "model_id": model_id},
                {"model_id": model_id, "element_count": len(elements)},
            )
        )

    @app.get("/cae/mesh/{model_id}")
    def get_cae_mesh(
        model_id: str, request: Request, tenant_id: str = DEMO_TENANT, pid: int | None = None
    ) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(_abstain("cae@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(request, tenant_id=checked)
        if auth_err is not None:
            return auth_err
        mesh = _cae_meshes.get(f"{checked}:{model_id}")
        if mesh is None:
            return JSONResponse(
                _abstain("cae@1.0.0", {"model_id": model_id}, "cae_mesh_not_found"),
                status_code=404,
            )
        if pid is not None:
            filtered = [e for e in mesh["elements"] if int(e.get("pid", 0)) == pid]
            out = {**mesh, "elements": filtered, "element_count": len(filtered), "pid_filter": pid}
        else:
            out = mesh
        return JSONResponse(_ok("cae@1.0.0", {"tenant_id": checked, "model_id": model_id}, out))

    @app.get("/cae/element/{element_id}/evidence")
    def get_cae_element_evidence(
        element_id: int, request: Request, tenant_id: str = DEMO_TENANT
    ) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(_abstain("cae@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(request, tenant_id=checked)
        if auth_err is not None:
            return auth_err
        rec = _cae_element_index.get((checked, int(element_id)))
        if rec is None:
            return JSONResponse(
                _abstain("cae@1.0.0", {"element_id": element_id}, "element_not_indexed"),
                status_code=404,
            )
        return JSONResponse(_ok("cae@1.0.0", {"tenant_id": checked, "element_id": element_id}, rec))

    @app.post("/plm/webhook/ecn")
    def plm_webhook_ecn(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_ingest.plm_connectors import apply_ecn_selective_invalidation_to_ledger

        checked = _validate_tenant(str(body.get("tenant_id", DEMO_TENANT)))
        if checked is None:
            return JSONResponse(_abstain("plm@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        ledger = open_ledger(checked)
        plan = apply_ecn_selective_invalidation_to_ledger(
            ledger,
            ecn_diff=dict(body.get("ecn_diff") or {}),
            all_cells=list(body.get("cells") or []),
        )
        return JSONResponse(_ok("plm@1.0.0", {"tenant_id": checked}, plan))

    @app.post("/plm/sync")
    def plm_sync(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_ingest.plm_connectors import (
            MockPLMServerTransport,
            PLMConnectorError,
            build_plm_connector,
        )

        checked = _validate_tenant(str(body.get("tenant_id", DEMO_TENANT)))
        if checked is None:
            return JSONResponse(_abstain("plm@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        system = str(body.get("system", "3dexperience")).lower()
        if system not in {"3dexperience", "teamcenter", "windchill"}:
            return JSONResponse(
                _abstain("plm@1.0.0", {}, "unsupported_plm_system"), status_code=400
            )
        transport = MockPLMServerTransport() if body.get("use_mock_plm") else None
        conn = build_plm_connector(
            system,  # type: ignore[arg-type]
            base_url=str(body.get("base_url") or "https://plm.aeroregu.local"),
            token_url=str(body.get("token_url") or "https://plm.aeroregu.local/oauth/token"),
            client_id=str(body.get("client_id") or "aeroregu-svc"),
            client_secret=str(body.get("client_secret") or "svc-secret"),
            transport=transport,
        )
        try:
            bom = conn.fetch_ebom(
                str(body.get("item_id") or "WING-SPAR-ASM-01"),
                revision=str(body.get("revision") or "Rev A"),
                msn=int(body.get("msn", 1)),
            )
            return JSONResponse(_ok("plm@1.0.0", {"tenant_id": checked}, bom))
        except PLMConnectorError as exc:
            return JSONResponse(
                _abstain("plm@1.0.0", {"system": system}, str(exc)), status_code=503
            )
        finally:
            conn.close()

    @app.post("/plm/writeback")
    def plm_writeback(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_ingest.plm_connectors import (
            MockPLMServerTransport,
            PLMConnectorError,
            build_plm_connector,
        )

        checked = _validate_tenant(str(body.get("tenant_id", DEMO_TENANT)))
        if checked is None:
            return JSONResponse(_abstain("plm@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        ledger = open_ledger(checked)
        system = str(body.get("system", "3dexperience")).lower()
        if system not in {"3dexperience", "teamcenter", "windchill"}:
            return JSONResponse(
                _abstain("plm@1.0.0", {}, "unsupported_plm_system"), status_code=400
            )
        transport = MockPLMServerTransport() if body.get("use_mock_plm") else None
        conn = build_plm_connector(
            system,  # type: ignore[arg-type]
            base_url=str(body.get("base_url") or "https://plm.aeroregu.local"),
            token_url=str(body.get("token_url") or "https://plm.aeroregu.local/oauth/token"),
            client_id=str(body.get("client_id") or "aeroregu-svc"),
            client_secret=str(body.get("client_secret") or "svc-secret"),
            transport=transport,
        )
        try:
            wb = conn.writeback_merkle_attestation(
                change_action_id=str(body.get("change_action_id") or "ECN-2026-001"),
                merkle_root=str(body.get("merkle_root") or ledger.merkle_root()),
                head_hash=str(body.get("head_hash") or ledger.head_hash()),
                chain_verified=bool(body.get("chain_verified", True)),
                revision=str(body.get("revision") or "Rev B"),
                msn=int(body.get("msn", 16)),
            )
            return JSONResponse(_ok("plm@1.0.0", {"tenant_id": checked}, wb))
        except PLMConnectorError as exc:
            return JSONResponse(
                _abstain("plm@1.0.0", {"system": system}, str(exc)), status_code=503
            )
        finally:
            conn.close()

    @app.get("/system/persistence")
    def system_persistence(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(
                _abstain("persistence@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger(checked)
        backend = getattr(ledger, "backend_name", "sqlite")
        return JSONResponse(
            _ok(
                "persistence@1.0.0",
                {"tenant_id": checked},
                {
                    "backend": backend,
                    "postgres_configured": bool(os.environ.get("EVIDENCE_PG_DSN", "").strip()),
                    "production_mode": _is_production_mode(),
                    "schema_version": ledger.schema_version()
                    if hasattr(ledger, "schema_version")
                    else 0,
                    "applied_migrations": ledger.applied_migrations()
                    if hasattr(ledger, "applied_migrations")
                    else [],
                },
            )
        )

    @app.post("/system/migrations/run")
    def system_run_migrations(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("migrations@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        newly = ledger.run_migrations() if hasattr(ledger, "run_migrations") else []
        return JSONResponse(
            _ok(
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

    @app.get("/webhooks/dlq")
    def list_webhooks_dlq(
        tenant_id: str = DEMO_TENANT, status: str | None = "dead_letter"
    ) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(
                _abstain("webhook_dlq@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger(checked)
        items = (
            ledger.queue.list_webhook_dlq(status=status or None, limit=200)
            if hasattr(ledger, "queue")
            else []
        )
        return JSONResponse(
            _ok(
                "webhook_dlq@1.0.0",
                {"tenant_id": checked},
                {"count": len(items), "items": items},
            )
        )

    @app.post("/webhooks/dlq/replay")
    def replay_webhooks_dlq(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("webhook_dlq@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        dids = body.get("delivery_ids")
        results = replay_dead_letters(
            ledger,
            delivery_ids=[str(x) for x in dids] if isinstance(dids, list) else None,
        )
        return JSONResponse(
            _ok(
                "webhook_dlq@1.0.0",
                {"tenant_id": tenant_id},
                {"replayed_count": len(results), "results": results},
            )
        )

    @app.get("/daemon/status")
    def daemon_status(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(_abstain("daemon@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked)
        jobs = ledger.queue.list_daemon_jobs(limit=100) if hasattr(ledger, "queue") else []
        budget = ledger.queue.get_budget_usage() if hasattr(ledger, "queue") else {}
        counts: dict[str, int] = {}
        for j in jobs:
            st = j["status"]
            counts[st] = counts.get(st, 0) + 1
        return JSONResponse(
            _ok(
                "daemon@1.0.0",
                {"tenant_id": checked},
                {"job_counts": counts, "budget_usage": budget, "recent_jobs": jobs[:25]},
            )
        )

    @app.get("/daemon/jobs")
    def daemon_jobs(tenant_id: str = DEMO_TENANT, status: str | None = None) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(_abstain("daemon@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked)
        jobs = (
            ledger.queue.list_daemon_jobs(status=status, limit=200)
            if hasattr(ledger, "queue")
            else []
        )
        return JSONResponse(
            _ok("daemon@1.0.0", {"tenant_id": checked}, {"count": len(jobs), "jobs": jobs})
        )

    @app.post("/ingest/pdf/async")
    def ingest_pdf_async(body: dict[str, Any]) -> JSONResponse:
        import base64

        checked = _validate_tenant(str(body.get("tenant_id", DEMO_TENANT)))
        if checked is None:
            return JSONResponse(_abstain("ingest@1.0.0", {}, "invalid_tenant"), status_code=400)
        filename = str(body.get("filename") or "document.pdf")
        ledger = open_ledger(checked)
        if not hasattr(ledger, "queue"):
            return JSONResponse(
                _abstain("ingest@1.0.0", {"tenant_id": checked}, "queue_unavailable"),
                status_code=503,
            )
        payload: dict[str, Any] = {
            "filename": filename,
            "max_workers": int(body.get("max_workers", 4)),
            "chunk_pages": int(body.get("chunk_pages", 25)),
        }
        if body.get("content_base64"):
            raw = base64.b64decode(str(body["content_base64"]))
            meta = open_blob_store(evidence_home()).put_blob(
                raw, content_type="application/pdf", filename=filename
            )
            payload["pdf_sha256"] = meta["sha256"]
        elif body.get("file_path"):
            payload["file_path"] = str(body["file_path"])
        else:
            return JSONResponse(
                _abstain("ingest@1.0.0", {"tenant_id": checked}, "missing_pdf_source"),
                status_code=400,
            )
        job_id = str(
            body.get("job_id")
            or f"pdf-{hashlib.sha256(f'{checked}:{filename}:{payload}'.encode()).hexdigest()[:12]}"
        )
        enqueued = ledger.queue.enqueue_daemon_job(
            idempotency_key=job_id,
            job_type="ingest_heavy_pdf",
            payload=payload,
        )
        return JSONResponse(
            _ok("ingest@1.0.0", {"tenant_id": checked, "job_id": job_id}, enqueued),
            status_code=202,
        )

    @app.post("/daemon/jobs/run")
    def daemon_jobs_run(body: dict[str, Any] | None = None) -> JSONResponse:
        from evidence_ingest.pdf import build_heavy_pdf_daemon_handler
        from evidence_kernel.daemon import DaemonRunner

        req = body or {}
        checked = _validate_tenant(str(req.get("tenant_id", DEMO_TENANT)))
        if checked is None:
            return JSONResponse(_abstain("daemon@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked)
        store = open_blob_store(evidence_home())
        runner = DaemonRunner(
            ledger,
            handlers={"ingest_heavy_pdf": build_heavy_pdf_daemon_handler(blob_store=store)},
        )
        result = runner.run_pending()
        return JSONResponse(_ok("daemon@1.0.0", {"tenant_id": checked}, result))

    @app.post("/audit/cross-artifact")
    def audit_cross_artifact_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("cross_artifact@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        use_showcase = bool(body.get("use_showcase"))
        src = default_showcase_artifacts() if use_showcase else body
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
            created_at=str(body.get("created_at") or _now()),
        )
        return JSONResponse(_ok("cross_artifact@1.0.0", {"tenant_id": tenant_id}, res))

    @app.post("/nafems/audit")
    def nafems_audit_endpoint(body: dict[str, Any]) -> JSONResponse:
        bdf_text = str(body.get("bdf_text") or "")
        if not bdf_text.strip():
            return JSONResponse(
                _abstain("nafems_audit@1.0.0", {}, "missing_bdf_text"), status_code=400
            )
        bdf_bytes = bdf_text.encode("utf-8")
        bdf_hash = hashlib.sha256(bdf_bytes).hexdigest()
        try:
            bdf_parsed = parse_nastran_bdf(bdf_bytes, bdf_hash, unit_system=body.get("unit_system"))
        except IngestAbstain as exc:
            return JSONResponse(_abstain("nafems_audit@1.0.0", {}, exc.reason), status_code=422)

        f06_parsed: dict[str, Any] | None = None
        f06_hash = ""
        f06_text = str(body.get("f06_text") or "")
        if f06_text.strip():
            f06_bytes = f06_text.encode("utf-8")
            f06_hash = hashlib.sha256(f06_bytes).hexdigest()
            try:
                f06_parsed = parse_nastran_f06(f06_bytes, f06_hash)
            except IngestAbstain as exc:
                return JSONResponse(_abstain("nafems_audit@1.0.0", {}, exc.reason), status_code=422)

        res = run_full_nafems_audit(
            bdf_parsed=bdf_parsed,
            bdf_hash=bdf_hash,
            f06_parsed=f06_parsed,
            f06_hash=f06_hash,
            report_blocks=body.get("report_blocks"),
            report_claims=body.get("report_claims"),
            report_hash=body.get("report_hash"),
            required_load_families=body.get("required_load_families"),
            rotor_rpm=body.get("rotor_rpm"),
            blade_count=int(body.get("blade_count", 4)),
            guard_band_pct=str(body.get("guard_band_pct", "10.0")),
            min_effective_mass_frac=str(body.get("min_effective_mass_frac", "0")),
            require_unit_system=bool(body.get("require_unit_system", False)),
        )
        if res["abstain"]:
            return JSONResponse(
                _abstain(
                    "nafems_audit@1.0.0",
                    {"bdf_sha256": bdf_hash},
                    str(res["abstain_reason"]),
                ),
                status_code=422,
            )
        return JSONResponse(_ok("nafems_audit@1.0.0", {"bdf_sha256": bdf_hash}, res))

    @app.post("/nafems/bdf-diff")
    def nafems_bdf_diff_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("nafems_diff@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        rev_a_text = str(body.get("rev_a_bdf_text") or "")
        rev_b_text = str(body.get("rev_b_bdf_text") or "")
        if not rev_a_text.strip() or not rev_b_text.strip():
            return JSONResponse(
                _abstain("nafems_diff@1.0.0", {}, "missing_bdf_text"), status_code=400
            )
        try:
            a_bytes = rev_a_text.encode("utf-8")
            b_bytes = rev_b_text.encode("utf-8")
            bdf_a = parse_nastran_bdf(a_bytes, hashlib.sha256(a_bytes).hexdigest())
            bdf_b = parse_nastran_bdf(b_bytes, hashlib.sha256(b_bytes).hexdigest())
        except IngestAbstain as exc:
            return JSONResponse(_abstain("nafems_diff@1.0.0", {}, exc.reason), status_code=422)

        invalidate = bool(body.get("invalidate_cells", True))
        ledger = open_ledger(tenant_id) if invalidate else None
        res = diff_bdf_revisions_and_invalidate(
            rev_a_bdf=bdf_a,
            rev_b_bdf=bdf_b,
            ledger=ledger,
            actor_id=actor,
            created_at=str(body.get("created_at") or _now()),
        )
        return JSONResponse(_ok("nafems_diff@1.0.0", {"tenant_id": tenant_id}, res))

    @app.post("/adversarial/fuzz")
    def adversarial_fuzz_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("adversarial@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        method_ids = body.get("method_ids")
        include_smt = bool(body.get("include_smt_critic", True))
        quarantine_dir = evidence_home() / "tenants" / tenant_id / "quarantine"
        attacker = run_bench_attacker(
            quarantine_dir=quarantine_dir,
            method_ids=[str(m) for m in method_ids] if isinstance(method_ids, list) else None,
            custom_inputs=body.get("custom_inputs")
            if isinstance(body.get("custom_inputs"), dict)
            else None,
        )
        critic = run_envelope_critic() if include_smt else None
        return JSONResponse(
            _ok(
                "adversarial@1.0.0",
                {"tenant_id": tenant_id},
                {"bench_attacker": attacker, "envelope_critic": critic},
            )
        )

    _briefing_cache: dict[tuple[str, str], dict[str, Any]] = {}
    _briefing_cache_lock = threading.RLock()

    @app.get("/overnight/briefing")
    def get_overnight_briefing(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(_abstain("overnight@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked)
        head = ledger.head_hash()
        cache_key = (checked, head)
        with _briefing_cache_lock:
            cached = _briefing_cache.get(cache_key)
            if cached is not None:
                return JSONResponse(_ok("overnight@1.0.0", {"tenant_id": checked}, cached))
        briefing = build_morning_briefing(ledger)
        with _briefing_cache_lock:
            if len(_briefing_cache) >= 128:
                _briefing_cache.pop(next(iter(_briefing_cache)), None)
            _briefing_cache[cache_key] = briefing
        return JSONResponse(_ok("overnight@1.0.0", {"tenant_id": checked}, briefing))

    @app.post("/overnight/run")
    def trigger_overnight_run(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("overnight@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        budget = OvernightBudget(
            max_tokens_per_night=int(body.get("max_tokens_per_night", 250_000)),
            max_cloud_tokens_per_night=int(body.get("max_cloud_tokens_per_night", 50_000)),
            max_jobs_per_run=int(body.get("max_jobs_per_run", 200)),
        )
        quarantine_dir = evidence_home() / "tenants" / tenant_id / "quarantine"
        watch_dirs_safe: list[Path] = []
        base_home = evidence_home().resolve()
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
        return JSONResponse(_ok("overnight@1.0.0", {"tenant_id": tenant_id}, summary))

    @app.post("/overnight/batch-signoff")
    def overnight_batch_signoff_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("overnight_signoff@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        role = ledger.actor_role(actor)
        if role == "author":
            return JSONResponse(
                _abstain("overnight_signoff@1.0.0", {"role": role}, "cve_role_required"),
                status_code=403,
            )
        fids = [str(x) for x in (body.get("finding_ids") or []) if str(x).strip()]
        if not fids:
            return JSONResponse(
                _abstain("overnight_signoff@1.0.0", {}, "missing_finding_ids"),
                status_code=400,
            )
        result = batch_human_signoff(
            ledger,
            finding_ids=fids,
            actor_id=actor,
            actor_role=role,
            statement=str(body.get("statement") or SIGN_OFF_STATEMENT),
            created_at=str(body.get("created_at") or _now()),
            enforce_distinct_reviewer=_is_production_mode()
            or bool(body.get("enforce_distinct_reviewer", False)),
        )
        return JSONResponse(_ok("overnight_signoff@1.0.0", {"tenant_id": tenant_id}, result))

    @app.post("/ecn/diff")
    def ecn_diff_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("ecn_diff@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        rev_a = body.get("rev_a")
        rev_b = body.get("rev_b")
        if not isinstance(rev_a, dict) or not isinstance(rev_b, dict):
            return JSONResponse(
                _abstain("ecn_diff@1.0.0", {}, "missing_ecn_revisions"), status_code=400
            )
        ecn_id = str(body.get("ecn_id") or "ECN-2026-001")
        diff_res = compute_ecn_revision_diff(rev_a, rev_b, ecn_id=ecn_id)
        return JSONResponse(_ok("ecn_diff@1.0.0", {"ecn_id": ecn_id}, diff_res))

    @app.post("/reviews/threads")
    def create_review_thread(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("review_thread@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
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
            return JSONResponse(_abstain("review_thread@1.0.0", {}, str(exc)), status_code=400)
        return JSONResponse(_ok("review_thread@1.0.0", {"tenant_id": tenant_id}, thr))

    @app.post("/reviews/threads/{thread_id}/reply")
    def reply_review_thread(thread_id: str, body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("review_thread@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
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
                _abstain("review_thread@1.0.0", {}, "thread_not_found"), status_code=404
            )
        except ValueError as exc:
            code = 409 if str(exc) == "thread_locked" else 400
            return JSONResponse(
                _abstain("review_thread@1.0.0", {"thread_id": thread_id}, str(exc)),
                status_code=code,
            )
        return JSONResponse(_ok("review_thread@1.0.0", {"thread_id": thread_id}, thr))

    @app.post("/reviews/threads/{thread_id}/resolve")
    def resolve_review_thread(
        thread_id: str, body: dict[str, Any], request: Request
    ) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("review_thread@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        role = open_ledger(tenant_id).actor_role(actor)
        if role not in {"cve", "admin", "reviewer", "human"}:
            return JSONResponse(
                _abstain(
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
                _abstain("review_thread@1.0.0", {}, "thread_not_found"), status_code=404
            )
        except ValueError as exc:
            return JSONResponse(
                _abstain("review_thread@1.0.0", {"thread_id": thread_id}, str(exc)), status_code=409
            )
        return JSONResponse(_ok("review_thread@1.0.0", {"thread_id": thread_id}, thr))

    @app.get("/reviews/threads")
    def list_review_threads(
        request: Request, tenant_id: str = DEMO_TENANT, target_event_hash: str | None = None
    ) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(
                _abstain("review_thread@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = _check_endpoint_access(request, tenant_id=checked)
        if auth_err is not None:
            return auth_err
        threads = get_review_thread_store().list_threads(
            checked, target_event_hash=target_event_hash or None
        )
        return JSONResponse(
            _ok(
                "review_thread@1.0.0",
                {"tenant_id": checked},
                {"threads": threads, "count": len(threads)},
            )
        )

    @app.post("/integrations/excel/sync")
    def excel_bridge_sync(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("excel_sync@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        imported = ExcelStressSheetBridge.import_named_ranges(body)
        try:
            calc_out = run_method(
                imported["method_id"],
                imported["inputs"],
                include_intervals=True,
                normalize_units=True,
            )
        except AbstainError as exc:
            return JSONResponse(
                _abstain("excel_sync@1.0.0", {"method_id": imported["method_id"]}, exc.reason),
                status_code=400,
            )
        ledger = open_ledger(tenant_id)
        stamp = ExcelStressSheetBridge.export_verification_stamp(
            body,
            calc_result=calc_out,
            merkle_root=ledger.merkle_root(),
            event_hash=ledger.head_hash(),
        )
        return JSONResponse(
            _ok(
                "excel_sync@1.0.0",
                {"workbook_id": imported["workbook_id"], "method_id": imported["method_id"]},
                {"imported": imported, "calculation": calc_out, "stamp": stamp},
            )
        )

    @app.post("/integrations/catia/selection")
    def catia_selection_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("catia_inspector@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = _check_endpoint_access(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        ctx = CatiaInspectorBridge.resolve_selection_context(
            body,
            cad_result=body.get("cad_result") if isinstance(body.get("cad_result"), dict) else None,
            margins_by_part=(
                body.get("margins_by_part")
                if isinstance(body.get("margins_by_part"), dict)
                else None
            ),
        )
        return JSONResponse(_ok("catia_inspector@1.0.0", {"part_number": ctx["part_number"]}, ctx))

    @app.post("/qualification/iq-oq/run")
    def qualification_iq_oq_endpoint(
        request: Request, body: dict[str, Any] | None = None
    ) -> JSONResponse:
        req = body or {}
        tenant_id = _validate_tenant(req.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("qualification_aid@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = _check_endpoint_access(
            request,
            tenant_id=tenant_id,
            requested_actor=req.get("actor_id"),
            allowed_roles={"cve", "admin", "auditor", "reviewer", "human"},
        )
        if auth_err is not None:
            return auth_err
        default_root = Path(__file__).resolve().parents[4]
        root_override = req.get("repo_root")
        if _is_production_mode():
            if root_override:
                return JSONResponse(
                    _abstain("qualification_aid@1.0.0", {}, "repo_root_override_forbidden"),
                    status_code=403,
                )
            repo_root = default_root
        else:
            repo_root = Path(str(root_override)) if root_override else default_root
        report = run_iq_oq_qualification_suite(repo_root=repo_root)
        return JSONResponse(_ok("qualification_aid@1.0.0", {}, report))

    @app.get("/legal/ma-readiness")
    def legal_ma_readiness_endpoint(request: Request, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(
                _abstain("ma_readiness@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = _check_endpoint_access(
            request,
            tenant_id=checked,
            allowed_roles={"cve", "admin", "auditor", "reviewer", "human"},
        )
        if auth_err is not None:
            return auth_err
        repo_root = Path(__file__).resolve().parents[4]
        report = evaluate_ma_technical_readiness(repo_root)
        return JSONResponse(_ok("ma_readiness@1.0.0", {}, report))

    @app.get("/calc/materials")
    def calc_materials_endpoint() -> JSONResponse:
        mats = list_materials()
        cat_hash = allowable_catalog_sha256()
        return JSONResponse(
            _ok(
                "allowables@1.0.0",
                {"catalog_sha256": cat_hash},
                {"materials": mats, "catalog_sha256": cat_hash},
            )
        )

    @app.post("/calc/allowables")
    def calc_allowables_endpoint(body: dict[str, Any]) -> JSONResponse:
        mat_id = str(body.get("material_id") or "").strip()
        if not mat_id:
            return JSONResponse(
                _abstain("allowables@1.0.0", {}, "missing_material_id"), status_code=400
            )
        try:
            res = lookup_allowable(
                mat_id,
                basis=str(body.get("basis") or "A"),
                property_name=str(body.get("property_name") or "fty_mpa"),
                thickness_mm=str(body.get("thickness_mm") or "10"),
                temp_c=str(body.get("temp_c") or "23"),
                environment=str(body.get("environment") or "RTD"),
            )
        except (AbstainError, InvalidOperation, ValueError) as exc:
            reason = exc.reason if isinstance(exc, AbstainError) else "invalid_allowable_input"
            return JSONResponse(
                _abstain("allowables@1.0.0", {"material_id": mat_id}, reason),
                status_code=400,
            )
        return JSONResponse(
            _ok(
                "allowables@1.0.0",
                {"material_id": res["material_id"], "basis": res["basis"]},
                res,
            )
        )

    @app.post("/cad/brep/analyze")
    def cad_brep_analyze_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        checked = _validate_tenant(body.get("tenant_id"))
        if checked is None:
            return JSONResponse(_abstain("cad_brep@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        filename = str(body.get("filename") or "assembly.step")
        raw, err = _decode_body_bytes(body, "cad_brep@1.0.0", filename)
        if err is not None or raw is None:
            return err or JSONResponse(
                _abstain("cad_brep@1.0.0", {"filename": filename}, "missing_step_content"),
                status_code=400,
            )
        source_hash = hashlib.sha256(raw).hexdigest()
        try:
            density = float(body.get("default_density_kg_m3") or 2810.0)
        except (TypeError, ValueError):
            return JSONResponse(
                _abstain("cad_brep@1.0.0", {"filename": filename}, "invalid_density"),
                status_code=400,
            )
        try:
            res = analyze_step_brep(raw, source_hash, default_density_kg_m3=density)
        except IngestAbstain as exc:
            return JSONResponse(
                _abstain("cad_brep@1.0.0", {"filename": filename}, exc.reason),
                status_code=400,
            )
        return JSONResponse(
            _ok(
                "cad_brep@1.0.0",
                {"filename": filename, "source_hash": source_hash},
                {"source_hash": source_hash, **res},
            )
        )

    @app.post("/cae/binary/parse")
    def cae_binary_parse_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        checked = _validate_tenant(body.get("tenant_id"))
        if checked is None:
            return JSONResponse(_abstain("cae_binary@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err

        raw_path = body.get("file_path")
        filename = str(body.get("filename") or "results.op2")
        source_hash = str(body.get("source_hash") or "").strip() or None
        use_sandbox = bool(body.get("sandbox", False))
        raw: bytes | None = None

        try:
            if raw_path is not None:
                candidate = Path(str(raw_path)).resolve()
                allowed_roots = (
                    evidence_home().resolve(),
                    Path(tempfile.gettempdir()).resolve(),
                )
                if not any(candidate.is_relative_to(root) for root in allowed_roots):
                    return JSONResponse(
                        _abstain(
                            "cae_binary@1.0.0",
                            {"file_path": str(raw_path)},
                            "path_outside_allowed_roots",
                        ),
                        status_code=403,
                    )
                if not candidate.is_file():
                    return JSONResponse(
                        _abstain(
                            "cae_binary@1.0.0",
                            {"file_path": str(raw_path)},
                            "file_not_found",
                        ),
                        status_code=404,
                    )
                suffix = candidate.suffix.lower() or Path(filename).suffix.lower()
                if use_sandbox or suffix in {".odb", ".rst"}:
                    raw = candidate.read_bytes()
                    digest = source_hash or hashlib.sha256(raw).hexdigest()
                    parsed = run_sandboxed_cae_worker(raw, digest, suffix or ".odb")
                elif suffix == ".h5":
                    parsed = parse_cae_h5_file(candidate, source_hash=source_hash)
                else:
                    parsed = parse_nastran_op2_file(candidate, source_hash=source_hash)
            else:
                raw, err = _decode_body_bytes(body, "cae_binary@1.0.0", filename)
                if err is not None or raw is None:
                    return err or JSONResponse(
                        _abstain("cae_binary@1.0.0", {"filename": filename}, "missing_cae_content"),
                        status_code=400,
                    )
                digest = source_hash or hashlib.sha256(raw).hexdigest()
                suffix = Path(filename).suffix.lower() or ".op2"
                if use_sandbox or suffix in {".odb", ".rst"}:
                    parsed = run_sandboxed_cae_worker(raw, digest, suffix)
                elif suffix == ".h5":
                    parsed = parse_cae_h5_bytes(raw, digest)
                else:
                    parsed = parse_nastran_op2_bytes(raw, digest)
        except IngestAbstain as exc:
            return JSONResponse(
                _abstain("cae_binary@1.0.0", {"filename": filename}, exc.reason),
                status_code=400,
            )

        blocks_out = [
            b.as_dict() if hasattr(b, "as_dict") else b for b in (parsed.get("blocks") or [])
        ]
        parsed_clean = {**parsed, "blocks": blocks_out}
        model_id = str(
            body.get("model_id") or f"cae-{str(parsed_clean.get('source_hash', 'model'))[:8]}"
        )
        vmesh = parsed_clean.get("viewer_mesh") or {}
        nodes_raw = list(vmesh.get("nodes") or [])
        elems_raw = list(vmesh.get("elements") or [])
        elem_ms_map = {int(k): v for k, v in (vmesh.get("element_ms") or {}).items()}
        elem_vm_map = {int(k): v for k, v in (vmesh.get("element_vm_mpa") or {}).items()}
        elem_sub_map = {int(k): v for k, v in (vmesh.get("element_subcase") or {}).items()}
        node_coords: dict[str, list[float]] = {}
        for n in nodes_raw:
            if isinstance(n, dict):
                nid = str(n.get("id", n.get("nid", "")))
                node_coords[nid] = [float(n["x"]), float(n["y"]), float(n["z"])]
            elif isinstance(n, (list, tuple)) and len(n) >= 4:
                node_coords[str(int(n[0]))] = [float(n[1]), float(n[2]), float(n[3])]
        indexed_elements: list[dict[str, Any]] = []
        for e in elems_raw:
            if isinstance(e, dict):
                eid = int(e.get("element_id", e.get("eid", 0)))
                pid = int(e.get("pid", 0))
                et = str(e.get("element_type", "CQUAD4"))
                nids = list(e.get("nodes") or [])
            elif isinstance(e, (list, tuple)) and len(e) >= 7:
                eid = int(e[0])
                pid = int(e[1])
                et = ELEM_TYPE_CODES.get(int(e[2]), "CQUAD4")
                nids = [int(n) for n in e[3:7] if int(n) > 0]
            else:
                continue
            ms_val = str(round(float(elem_ms_map.get(eid, 0.25)), 4))
            vm_val = str(round(float(elem_vm_map.get(eid, 120.0)), 3))
            sub_val = int(elem_sub_map.get(eid, 1))
            el_rec = {
                "element_id": eid,
                "pid": pid,
                "element_type": et,
                "nodes": nids,
                "subcase_id": sub_val,
                "ms_min": ms_val,
                "von_mises_mpa": vm_val,
                "calc_event_hash": f"cae-{model_id}-{pid}-{eid}",
                "pdf_citation": {
                    "doc_id": filename,
                    "page_no": 1,
                    "bbox": [48.0, 120.0, 420.0, 148.0],
                },
            }
            indexed_elements.append(el_rec)
            _cae_element_index[(checked, eid)] = {"model_id": model_id, **el_rec}
        _cae_meshes[f"{checked}:{model_id}"] = {
            "model_id": model_id,
            "tenant_id": checked,
            "node_count": int(parsed_clean.get("node_count", len(node_coords))),
            "element_count": int(parsed_clean.get("element_count", len(indexed_elements))),
            "nodeCoords": node_coords,
            "elements": indexed_elements,
            "pid_summary": parsed_clean.get("pid_ms_summary") or {},
            "pdf_citations": {},
        }
        parsed_clean["model_id"] = model_id
        return JSONResponse(
            _ok(
                "cae_binary@1.0.0",
                {"tenant_id": checked, "model_id": model_id, "filename": filename},
                parsed_clean,
            )
        )

    @app.get("/security/sbom")
    def security_sbom_endpoint(request: Request, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(_abstain("sbom@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(
            request,
            tenant_id=checked,
            allowed_roles={"cve", "admin", "auditor", "reviewer", "human"},
        )
        if auth_err is not None:
            return auth_err
        repo_root = Path(__file__).resolve().parents[4]
        report = verify_sbom_and_dependencies(repo_root)
        return JSONResponse(_ok("sbom@1.0.0", {"tenant_id": checked}, report))

    @app.get("/ingest/document/{doc_id}/page/{page_no}")
    def get_ingested_document_page(
        doc_id: str, page_no: int, request: Request, tenant_id: str = DEMO_TENANT
    ) -> JSONResponse:
        checked = _validate_tenant(tenant_id)
        if checked is None:
            return JSONResponse(_abstain("ingest@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = _check_endpoint_access(request, tenant_id=checked)
        if auth_err is not None:
            return auth_err
        if page_no < 1:
            return JSONResponse(
                _abstain("ingest@1.0.0", {"page_no": page_no}, "invalid_page_number"),
                status_code=400,
            )

        doc_entry = _ingested_docs.get((checked, doc_id))
        source_hash = doc_entry["source_hash"] if doc_entry else doc_id
        raw_pdf: bytes | None = None
        if re.fullmatch(r"[0-9a-f]{64}", source_hash):
            try:
                candidate = open_blob_store(evidence_home()).get_blob(source_hash)
                if candidate.startswith(b"%PDF"):
                    raw_pdf = candidate
            except Exception:
                raw_pdf = None

        if doc_entry is None and raw_pdf is None:
            return JSONResponse(
                _abstain("ingest@1.0.0", {"doc_id": doc_id}, "document_not_found"),
                status_code=404,
            )

        all_blocks = list(doc_entry["blocks"]) if doc_entry else []
        page_blocks = [
            b
            for b in all_blocks
            if b.get("page_no") == page_no or (b.get("page_no") is None and page_no == 1)
        ]
        highlight_bboxes = [b["bbox"] for b in page_blocks if b.get("bbox")]
        width_pt = 612.0
        height_pt = 792.0
        image_base64 = ""
        mime_type = "image/svg+xml"

        if raw_pdf is not None:
            try:
                import pymupdf as fitz  # type: ignore[import-not-found]

                with fitz.open(stream=raw_pdf, filetype="pdf") as pdf_doc:
                    if page_no > len(pdf_doc):
                        return JSONResponse(
                            _abstain(
                                "ingest@1.0.0",
                                {"doc_id": doc_id, "page_no": page_no},
                                "page_out_of_range",
                            ),
                            status_code=404,
                        )
                    page = pdf_doc[page_no - 1]
                    width_pt = float(page.rect.width)
                    height_pt = float(page.rect.height)
                    pix = page.get_pixmap(dpi=120)
                    image_base64 = base64.b64encode(pix.tobytes("png")).decode("ascii")
                    mime_type = "image/png"
            except Exception:
                image_base64 = ""

        svg_boxes: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {int(width_pt)} {int(height_pt)}">',
            f'<rect width="{int(width_pt)}" height="{int(height_pt)}" fill="#0f172a"/>',
            f'<text x="24" y="34" fill="#94a3b8" font-size="14" font-family="monospace">'
            f"Doc: {doc_id[:36]} | Page {page_no}</text>",
        ]
        for idx, blk in enumerate(page_blocks):
            bbox = blk.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
                bw = max(8.0, x1 - x0)
                bh = max(12.0, y1 - y0)
            else:
                x0, y0, bw, bh = (28.0, 56.0 + idx * 34.0, width_pt - 56.0, 26.0)
            snippet = (
                str(blk.get("text", ""))[:88]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            svg_boxes.append(
                f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                f'fill="rgba(56,189,248,0.12)" stroke="#38bdf8" stroke-width="1.5"/>'
            )
            svg_boxes.append(
                f'<text x="{x0 + 4:.1f}" y="{y0 + 16:.1f}" fill="#e2e8f0" '
                f'font-size="11" font-family="monospace">{snippet}</text>'
            )
        svg_boxes.append("</svg>")
        svg_markup = "\n".join(svg_boxes)
        if not image_base64:
            image_base64 = base64.b64encode(svg_markup.encode("utf-8")).decode("ascii")

        return JSONResponse(
            _ok(
                "ingest@1.0.0",
                {"doc_id": doc_id, "page_no": page_no},
                {
                    "doc_id": doc_id,
                    "source_hash": source_hash,
                    "page_no": page_no,
                    "width_pt": width_pt,
                    "height_pt": height_pt,
                    "mime_type": mime_type,
                    "image_base64": image_base64,
                    "svg": svg_markup,
                    "blocks": page_blocks,
                    "highlight_bboxes": highlight_bboxes,
                },
            )
        )

    @app.get("/quotations/catalog")
    def quotation_catalog_endpoint() -> JSONResponse:
        return JSONResponse(_ok("quotation_catalog@1.0.0", {}, get_quotation_catalog()))

    @app.post("/quotations/generate")
    def quotation_generate_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("quotation_multiagent@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = _check_endpoint_access(
            request,
            tenant_id=tenant_id,
            requested_actor=body.get("actor_id"),
        )
        if auth_err is not None:
            return auth_err
        spec = QuotationRequestSpec(
            rfq_text=str(body.get("rfq_text") or ""),
            quotation_kind=str(body.get("quotation_kind") or "hybrid_turnkey"),  # type: ignore[arg-type]
            tenant_id=tenant_id,
            actor_id=actor_id or str(body.get("actor_id") or "author"),
            created_at=str(body.get("created_at") or _now()),
            currency=str(body.get("currency") or "EUR"),
            target_margin_pct=str(body.get("target_margin_pct") or "22.000"),
            min_acceptable_margin_pct=str(body.get("min_acceptable_margin_pct") or "10.000"),
            explicit_params=dict(body.get("explicit_params") or {}),
            bom_items=list(body.get("bom_items") or []),
            assumption_overrides=dict(body.get("assumption_overrides") or {}),
            enable_formal_smt=bool(body.get("enable_formal_smt", True)),
            export_control_restricted=bool(body.get("export_control_restricted", False)),
            customer_name=str(body.get("customer_name") or "Aerospace Client"),
            rfq_id=str(body.get("rfq_id") or "RFQ-AUTO-001"),
        )
        ledger = open_ledger(tenant_id)
        dossier = run_multiagent_quotation(ledger, spec)
        if dossier.confidence == "abstain":
            abstain_payload = _abstain(
                "quotation_multiagent@1.0.0",
                {"rfq_id": spec.rfq_id},
                dossier.abstain_reason or "abstain",
            )
            abstain_payload["decision_status"] = dossier.decision_status
            abstain_payload["event_hashes"] = dossier.event_hashes
            abstain_payload["merkle_root"] = dossier.merkle_root
            return JSONResponse(abstain_payload)
        return JSONResponse(
            _ok(
                "quotation_multiagent@1.0.0",
                {"rfq_id": dossier.rfq_id, "quotation_kind": dossier.quotation_kind},
                dossier.to_dict(),
            )
        )

    @app.post("/quotations/sensitivity")
    def quotation_sensitivity_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("quotation_sensitivity@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = _check_endpoint_access(
            request,
            tenant_id=tenant_id,
            requested_actor=body.get("actor_id"),
        )
        if auth_err is not None:
            return auth_err
        spec = QuotationRequestSpec(
            rfq_text=str(body.get("rfq_text") or ""),
            quotation_kind=str(body.get("quotation_kind") or "hybrid_turnkey"),  # type: ignore[arg-type]
            tenant_id=tenant_id,
            actor_id=actor_id or str(body.get("actor_id") or "author"),
            created_at=str(body.get("created_at") or _now()),
            currency=str(body.get("currency") or "EUR"),
            target_margin_pct=str(body.get("target_margin_pct") or "22.000"),
            min_acceptable_margin_pct=str(body.get("min_acceptable_margin_pct") or "10.000"),
            explicit_params=dict(body.get("explicit_params") or {}),
            bom_items=list(body.get("bom_items") or []),
            assumption_overrides=dict(body.get("assumption_overrides") or {}),
            enable_formal_smt=bool(body.get("enable_formal_smt", True)),
            export_control_restricted=bool(body.get("export_control_restricted", False)),
            customer_name=str(body.get("customer_name") or "Aerospace Client"),
            rfq_id=str(body.get("rfq_id") or "RFQ-AUTO-001"),
        )
        overrides = dict(body.get("overrides") or {})
        ledger = open_ledger(tenant_id)
        result = run_whatif_sensitivity(ledger, spec, overrides)
        return JSONResponse(_ok("quotation_sensitivity@1.0.0", {"rfq_id": spec.rfq_id}, result))

    @app.get("/quotations/repos-benchmark")
    def quotation_repos_benchmark_endpoint() -> JSONResponse:
        result = QuotationIntelligenceScraper().run_full_harvest(live_network=False)
        return JSONResponse(_ok("quotation_scraper@1.0.0", {"mode": "catalog"}, result))

    @app.post("/quotations/scrape-repos")
    def quotation_scrape_repos_endpoint(body: dict[str, Any] | None = None) -> JSONResponse:
        req = body or {}
        live = bool(req.get("live_network", False))
        queries = req.get("queries")
        scraper = QuotationIntelligenceScraper()
        gh = scraper.scrape_github_repositories(
            queries=[str(q) for q in queries] if isinstance(queries, list) else None,
            live_network=live,
        )
        web = scraper.scrape_web_platforms(live_network=live)
        cmp = scraper.compare_against_aeroregu()
        report = scraper.export_intelligence_report_markdown(
            github_res=gh, web_res=web, comparison=cmp
        )
        return JSONResponse(
            _ok(
                "quotation_scraper@1.0.0",
                {"live_network": live},
                {
                    "github": gh,
                    "web_platforms": web,
                    "comparison": cmp,
                    "markdown_report": report,
                },
            )
        )

    @app.get("/quotations/rotorcraft/catalog")
    def rotorcraft_quotation_catalog_endpoint() -> JSONResponse:
        return JSONResponse(_ok("rotorcraft_catalog@1.0.0", {}, get_rotorcraft_catalog()))

    @app.post("/quotations/rotorcraft/generate")
    def rotorcraft_quotation_generate_endpoint(
        body: dict[str, Any], request: Request
    ) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("rotorcraft_quotation@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = _check_endpoint_access(
            request,
            tenant_id=tenant_id,
            requested_actor=body.get("actor_id"),
        )
        if auth_err is not None:
            return auth_err
        spec = RotorcraftQuotationSpec(
            rfq_text=str(body.get("rfq_text") or ""),
            country_code=str(body.get("country_code") or "EU_DEFAULT"),
            archetype_id=(str(body["archetype_id"]) if body.get("archetype_id") else None),
            cert_basis=str(body.get("cert_basis") or "CS-29"),
            material_family=str(body.get("material_family") or "HYBRID_AL_CFRP"),
            cosysmo_complexity=str(body.get("cosysmo_complexity") or "NOMINAL"),
            idp_maturity=str(body.get("idp_maturity") or "COMPLETE"),
            target_margin_pct=str(body.get("target_margin_pct") or "22.000"),
            min_acceptable_margin_pct=str(body.get("min_acceptable_margin_pct") or "10.000"),
            nearshore_country=str(body.get("nearshore_country") or "ES"),
            enable_formal_smt=bool(body.get("enable_formal_smt", True)),
            export_control_restricted=bool(body.get("export_control_restricted", False)),
            tenant_id=tenant_id,
            actor_id=actor_id or str(body.get("actor_id") or "author"),
            created_at=str(body.get("created_at") or _now()),
            rfq_id=str(body.get("rfq_id") or "RFQ-ROTOR-001"),
            customer_name=str(body.get("customer_name") or "Rotorcraft OEM / DOA Client"),
            currency=str(body.get("currency") or "EUR"),
            extra_travel_hardware_eur=(
                str(body["extra_travel_hardware_eur"])
                if body.get("extra_travel_hardware_eur") is not None
                else None
            ),
            cve_min_ratio_pct=(
                str(body["cve_min_ratio_pct"])
                if body.get("cve_min_ratio_pct") is not None
                else None
            ),
            assumption_overrides=dict(body.get("assumption_overrides") or {}),
            idp_attachments=dict(body.get("idp_attachments") or {}),
            use_historical_calibration=bool(body.get("use_historical_calibration", True)),
            historical_corpus_path=(
                str(body["historical_corpus_path"]) if body.get("historical_corpus_path") else None
            ),
            historical_top_k=int(body.get("historical_top_k") or 3),
        )
        ledger = open_ledger(tenant_id)
        dossier = run_rotorcraft_department_quotation(ledger, spec)
        if dossier["confidence"] == "abstain":
            abstain_payload = _abstain(
                "rotorcraft_quotation@1.0.0",
                {},
                dossier.get("abstain_reason") or "abstain",
            )
            abstain_payload["decision_status"] = dossier["decision_status"]
            abstain_payload["event_hashes"] = dossier["event_hashes"]
            abstain_payload["merkle_root"] = dossier["merkle_root"]
            return JSONResponse(abstain_payload)
        return JSONResponse(
            _ok(
                "rotorcraft_quotation@1.0.0",
                {
                    "rfq_id": dossier["rfq_id"],
                    "archetype_id": dossier["archetype"]["archetype_id"],
                    "country_code": dossier["country_profile"]["country_code"],
                },
                dossier,
            )
        )

    @app.post("/quotations/rotorcraft/calibrate-historical")
    def rotorcraft_calibrate_historical_endpoint(
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        from evidence_coverage.historical_quotation_calibrator import (
            run_historical_calibration_and_matching,
        )

        req = body or {}
        archetype_id = str(req.get("archetype_id") or "Q-STR-03")
        country_code = str(req.get("country_code") or "EU_DEFAULT")
        try:
            payload = run_historical_calibration_and_matching(
                archetype_id=archetype_id,
                country_code=country_code,
                cert_basis=str(req.get("cert_basis") or "CS-29"),
                material_family=str(req.get("material_family") or "HYBRID_AL_CFRP"),
                corpus_path=(str(req["corpus_path"]) if req.get("corpus_path") else None),
                records=(req["records"] if isinstance(req.get("records"), list) else None),
                synthetic_count=int(req.get("synthetic_count") or 2160),
                idp_attachments=req.get("idp_attachments"),
                top_k=int(req.get("top_k") or 3),
            )
        except ValueError as exc:
            return JSONResponse(
                _abstain("rotorcraft_historical_calibration@1.0.0", {}, str(exc)),
                status_code=400,
            )
        return JSONResponse(
            _ok(
                "rotorcraft_historical_calibration@1.0.0",
                {"archetype_id": archetype_id, "country_code": country_code},
                payload,
            )
        )

    def _build_composite_spec(body: dict[str, Any], *, tenant_id: str, actor_id: str | None) -> Any:
        from evidence_coverage.composite_dag_quotation import CompositeRotorcraftQuotationSpec

        raw_archs = body.get("archetype_ids") or ()
        arch_tuple = tuple(str(a).strip() for a in raw_archs if str(a).strip())
        raw_edges = body.get("custom_edges") or ()
        edges_tuple = tuple(
            (str(e[0]), str(e[1]), str(e[2]) if len(e) > 2 else "CAD_DMU")
            for e in raw_edges
            if isinstance(e, (list, tuple)) and len(e) >= 2
        )
        return CompositeRotorcraftQuotationSpec(
            rfq_text=str(body.get("rfq_text") or ""),
            archetype_ids=arch_tuple,
            custom_edges=edges_tuple,
            country_code=str(body.get("country_code") or "EU_DEFAULT"),
            nearshore_country=str(body.get("nearshore_country") or "ES"),
            cert_basis=str(body.get("cert_basis") or "CS-29"),
            material_family=str(body.get("material_family") or "HYBRID_AL_CFRP"),
            cosysmo_complexity=str(body.get("cosysmo_complexity") or "NOMINAL"),
            idp_maturity=str(body.get("idp_maturity") or "COMPLETE"),
            target_margin_pct=str(body.get("target_margin_pct") or "22.000"),
            min_acceptable_margin_pct=str(body.get("min_acceptable_margin_pct") or "10.000"),
            min_npv_eur=str(body.get("min_npv_eur") or "0.000"),
            unit_count=int(body.get("unit_count") or 1),
            learning_rate_pct=str(body.get("learning_rate_pct") or "85.000"),
            crawford_weight_pct=str(body.get("crawford_weight_pct") or "50.000"),
            program_years=int(body.get("program_years") or 3),
            annual_inflation_pct=(
                str(body["annual_inflation_pct"])
                if body.get("annual_inflation_pct") is not None
                else None
            ),
            wacc_annual_pct=(
                str(body["wacc_annual_pct"]) if body.get("wacc_annual_pct") is not None else None
            ),
            payment_terms_days=(
                int(body["payment_terms_days"])
                if body.get("payment_terms_days") is not None
                else None
            ),
            milestone_ko_pct=str(body.get("milestone_ko_pct") or "25.000"),
            milestone_pdr_pct=str(body.get("milestone_pdr_pct") or "20.000"),
            milestone_cdr_pct=str(body.get("milestone_cdr_pct") or "25.000"),
            milestone_test_pct=str(body.get("milestone_test_pct") or "15.000"),
            milestone_cve_pct=str(body.get("milestone_cve_pct") or "15.000"),
            cve_min_ratio_pct=(
                str(body["cve_min_ratio_pct"])
                if body.get("cve_min_ratio_pct") is not None
                else None
            ),
            enable_formal_smt=bool(body.get("enable_formal_smt", True)),
            export_control_restricted=bool(body.get("export_control_restricted", False)),
            enforce_contract_gate=bool(body.get("enforce_contract_gate", True)),
            contract_clauses=(
                list(body["contract_clauses"])
                if isinstance(body.get("contract_clauses"), list)
                else None
            ),
            idp_attachments=dict(body.get("idp_attachments") or {}),
            use_historical_calibration=bool(body.get("use_historical_calibration", True)),
            historical_corpus_path=(
                str(body["historical_corpus_path"]) if body.get("historical_corpus_path") else None
            ),
            historical_top_k=int(body.get("historical_top_k") or 3),
            assumption_overrides=dict(body.get("assumption_overrides") or {}),
            tenant_id=tenant_id,
            actor_id=actor_id or str(body.get("actor_id") or "author"),
            created_at=str(body.get("created_at") or _now()),
            rfq_id=str(body.get("rfq_id") or "RFQ-COMP-001"),
            customer_name=str(body.get("customer_name") or "Rotorcraft OEM / DOA Client"),
            currency=str(body.get("currency") or "EUR"),
        )

    @app.post("/quotations/rotorcraft/composite-dag")
    def rotorcraft_composite_dag_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation

        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("composite_rotorcraft_quotation@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = _check_endpoint_access(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        spec = _build_composite_spec(body, tenant_id=tenant_id, actor_id=actor_id)
        ledger = open_ledger(tenant_id)
        dossier = run_composite_rotorcraft_quotation(ledger, spec)
        if dossier["confidence"] == "abstain":
            abstain_payload = _abstain(
                "composite_rotorcraft_quotation@1.0.0",
                {"rfq_id": spec.rfq_id},
                dossier.get("abstain_reason") or "abstain",
            )
            abstain_payload["decision_status"] = dossier["decision_status"]
            abstain_payload["contract_audit"] = dossier.get("contract_audit")
            abstain_payload["event_hashes"] = dossier["event_hashes"]
            abstain_payload["merkle_root"] = dossier["merkle_root"]
            return JSONResponse(abstain_payload)
        return JSONResponse(
            _ok(
                "composite_rotorcraft_quotation@1.0.0",
                {
                    "rfq_id": dossier["rfq_id"],
                    "country_code": dossier["country_profile"]["country_code"],
                    "critical_path": dossier["composite_wbs_dag"]["critical_path_archetypes"],
                },
                dossier,
            )
        )

    @app.post("/quotations/rotorcraft/multiyear-cashflow")
    def rotorcraft_multiyear_cashflow_endpoint(body: dict[str, Any]) -> JSONResponse:
        inputs = dict(body.get("inputs") or body)
        try:
            ran = run_method(
                "aerospace_multiyear_cashflow_learning", inputs, include_intervals=True
            )
        except AbstainError as exc:
            return JSONResponse(
                _abstain("aerospace_multiyear_cashflow_learning@1.0.0", inputs, exc.reason),
                status_code=400,
            )
        return JSONResponse(_ok("aerospace_multiyear_cashflow_learning@1.0.0", inputs, ran))

    @app.post("/quotations/rotorcraft/idp-deep-inspect")
    def rotorcraft_idp_deep_inspect_endpoint(
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        from evidence_coverage.deep_idp_quotation_extractor import (
            extract_deep_idp_engineering_package,
        )

        req = body or {}
        res = extract_deep_idp_engineering_package(req.get("idp_attachments") or req)
        return JSONResponse(_ok("deep_idp_extractor@1.0.0", {}, res))

    @app.post("/quotations/rotorcraft/contract-audit")
    def rotorcraft_contract_audit_endpoint(body: dict[str, Any]) -> JSONResponse:
        from evidence_coverage.contract_clause_auditor import audit_rfq_contract_clauses

        pdf_bytes = base64.b64decode(str(body["pdf_base64"])) if body.get("pdf_base64") else None
        res = audit_rfq_contract_clauses(
            str(body.get("rfq_text") or ""),
            clauses=body.get("clauses") if isinstance(body.get("clauses"), list) else None,
            pdf_bytes=pdf_bytes,
            filename=str(body.get("filename") or "rfq.txt"),
        )
        return JSONResponse(_ok("contract_clause_auditor@1.0.0", {}, res))

    @app.post("/quotations/rotorcraft/export-xlsx")
    def rotorcraft_export_xlsx_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.quotation_exporter import export_quotation_xlsx

        if isinstance(body.get("dossier"), dict):
            dossier = body["dossier"]
        else:
            tenant_id = _validate_tenant(body.get("tenant_id"))
            if tenant_id is None:
                return JSONResponse(
                    _abstain("quotation_exporter_xlsx@1.0.0", {}, "invalid_tenant"),
                    status_code=400,
                )
            actor_id, auth_err = _check_endpoint_access(
                request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
            )
            if auth_err is not None:
                return auth_err
            spec = _build_composite_spec(body, tenant_id=tenant_id, actor_id=actor_id)
            dossier = run_composite_rotorcraft_quotation(open_ledger(tenant_id), spec)
            if dossier.get("confidence") == "abstain":
                return JSONResponse(
                    _abstain(
                        "quotation_exporter_xlsx@1.0.0",
                        {},
                        dossier.get("abstain_reason") or "abstain",
                    ),
                    status_code=422,
                )

        exported = export_quotation_xlsx(dossier)
        rfq_id = str(dossier.get("rfq_id") or "quotation").replace('"', "")
        return Response(
            content=exported["xlsx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{rfq_id}_quotation.xlsx"',
                "X-AeroRegu-SHA256": exported["xlsx_sha256"],
                "X-AeroRegu-Formula-Count": str(exported["formula_count"]),
            },
        )

    @app.post("/quotations/rotorcraft/export-pdf")
    def rotorcraft_export_pdf_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.quotation_exporter import export_quotation_signed_pdf

        if isinstance(body.get("dossier"), dict):
            dossier = body["dossier"]
        else:
            tenant_id = _validate_tenant(body.get("tenant_id"))
            if tenant_id is None:
                return JSONResponse(
                    _abstain("quotation_exporter_pdf@1.0.0", {}, "invalid_tenant"),
                    status_code=400,
                )
            actor_id, auth_err = _check_endpoint_access(
                request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
            )
            if auth_err is not None:
                return auth_err
            spec = _build_composite_spec(body, tenant_id=tenant_id, actor_id=actor_id)
            dossier = run_composite_rotorcraft_quotation(open_ledger(tenant_id), spec)
            if dossier.get("confidence") == "abstain":
                return JSONResponse(
                    _abstain(
                        "quotation_exporter_pdf@1.0.0",
                        {},
                        dossier.get("abstain_reason") or "abstain",
                    ),
                    status_code=422,
                )

        priv_pem, pub_pem = _attestation_keypair()
        exported = export_quotation_signed_pdf(
            dossier, private_key_pem=priv_pem, public_key_pem=pub_pem
        )
        rfq_id = str(dossier.get("rfq_id") or "quotation").replace('"', "")
        return Response(
            content=exported["pdf_bytes"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{rfq_id}_signed_quote.pdf"',
                "X-AeroRegu-SHA256": exported["pdf_sha256"],
                "X-AeroRegu-Merkle-Root": exported["merkle_root"],
            },
        )

    @app.post("/quotations/rotorcraft/advanced-calibration")
    def rotorcraft_advanced_calibration_endpoint(
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        from evidence_coverage.advanced_quotation_calibration import (
            run_advanced_calibration_suite,
        )
        from evidence_coverage.historical_quotation_calibrator import (
            generate_reference_historical_corpus,
            ingest_historical_quotations,
        )

        req = body or {}
        if req.get("corpus_path"):
            corpus = ingest_historical_quotations(str(req["corpus_path"]))["records"]
        elif isinstance(req.get("records"), list):
            corpus = ingest_historical_quotations(list(req["records"]))["records"]
        else:
            corpus = generate_reference_historical_corpus(int(req.get("synthetic_count") or 2160))

        payload = run_advanced_calibration_suite(
            corpus=corpus,
            archetype_id=str(req.get("archetype_id") or "Q-STR-03"),
            country_code=str(req.get("country_code") or "EU_DEFAULT"),
            k_folds=int(req.get("k_folds") or 5),
            exclude_outliers=bool(req.get("exclude_outliers", True)),
            target_margin_pct=str(req.get("target_margin_pct") or "22.000"),
            min_acceptable_margin_pct=str(req.get("min_acceptable_margin_pct") or "10.000"),
        )
        return JSONResponse(_ok("advanced_quotation_calibration@1.0.0", {}, payload))

    @app.get("/quotations/rotorcraft/erp-template")
    def rotorcraft_erp_template_endpoint(format: str = "xlsx") -> Response:
        from evidence_coverage.advanced_quotation_calibration import export_erp_sap_import_template

        try:
            res = export_erp_sap_import_template(fmt=format)
        except ValueError as exc:
            return JSONResponse(
                _abstain("erp_sap_template@1.0.0", {"format": format}, str(exc)),
                status_code=400,
            )
        media = (
            "text/csv"
            if res["format"] == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        disposition = f'attachment; filename="aeroregu_erp_sap_bids_template.{res["format"]}"'
        return Response(
            content=res["content_bytes"],
            media_type=media,
            headers={
                "Content-Disposition": disposition,
                "X-AeroRegu-SHA256": res["sha256"],
            },
        )

    @app.post("/quotations/rotorcraft/change-order")
    def rotorcraft_change_order_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.quotation_change_order import compute_quotation_change_order

        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("quotation_change_order@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = _check_endpoint_access(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        ledger = open_ledger(tenant_id)

        if isinstance(body.get("baseline_dossier"), dict):
            baseline = body["baseline_dossier"]
        elif isinstance(body.get("baseline_spec"), dict):
            b_spec = _build_composite_spec(
                dict(body["baseline_spec"]), tenant_id=tenant_id, actor_id=actor_id
            )
            baseline = run_composite_rotorcraft_quotation(ledger, b_spec)
        else:
            return JSONResponse(
                _abstain("quotation_change_order@1.0.0", {}, "missing_baseline_dossier"),
                status_code=400,
            )

        rev_raw = dict(body.get("revised_spec") or body)
        rev_spec = _build_composite_spec(rev_raw, tenant_id=tenant_id, actor_id=actor_id)
        ccn = compute_quotation_change_order(
            ledger,
            baseline,
            rev_spec,
            cr_id=str(body.get("cr_id") or "CCN-001"),
            change_reason=str(body.get("change_reason") or "Scope & schedule change request"),
            enforce_contract_gate=bool(body.get("enforce_contract_gate", True)),
        )
        if ccn.get("confidence") == "abstain":
            abstain_payload = _abstain(
                "quotation_change_order@1.0.0",
                {"cr_id": ccn["cr_id"]},
                ccn.get("abstain_reason") or "abstain",
            )
            abstain_payload["decision_status"] = ccn["decision_status"]
            abstain_payload["contract_delta"] = ccn.get("contract_delta")
            abstain_payload["change_order_merkle_root"] = ccn.get("change_order_merkle_root")
            return JSONResponse(abstain_payload)
        return JSONResponse(
            _ok(
                "quotation_change_order@1.0.0",
                {"cr_id": ccn["cr_id"], "baseline_rfq_id": ccn["baseline_rfq_id"]},
                ccn,
            )
        )

    @app.post("/quotations/rotorcraft/change-order/export-xlsx")
    def rotorcraft_change_order_export_xlsx_endpoint(
        body: dict[str, Any], request: Request
    ) -> Response:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.quotation_change_order import compute_quotation_change_order
        from evidence_coverage.quotation_exporter import export_change_order_xlsx

        if isinstance(body.get("ccn_dossier"), dict):
            ccn = body["ccn_dossier"]
        else:
            tenant_id = _validate_tenant(body.get("tenant_id"))
            if tenant_id is None:
                return JSONResponse(
                    _abstain("quotation_change_order_xlsx@1.0.0", {}, "invalid_tenant"),
                    status_code=400,
                )
            actor_id, auth_err = _check_endpoint_access(
                request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
            )
            if auth_err is not None:
                return auth_err
            ledger = open_ledger(tenant_id)
            if isinstance(body.get("baseline_dossier"), dict):
                baseline = body["baseline_dossier"]
            elif isinstance(body.get("baseline_spec"), dict):
                b_spec = _build_composite_spec(
                    dict(body["baseline_spec"]), tenant_id=tenant_id, actor_id=actor_id
                )
                baseline = run_composite_rotorcraft_quotation(ledger, b_spec)
            else:
                return JSONResponse(
                    _abstain("quotation_change_order_xlsx@1.0.0", {}, "missing_baseline"),
                    status_code=400,
                )
            rev_spec = _build_composite_spec(
                dict(body.get("revised_spec") or body), tenant_id=tenant_id, actor_id=actor_id
            )
            ccn = compute_quotation_change_order(
                ledger,
                baseline,
                rev_spec,
                cr_id=str(body.get("cr_id") or "CCN-001"),
                change_reason=str(body.get("change_reason") or "CCN Addendum"),
            )
            if ccn.get("confidence") == "abstain":
                return JSONResponse(
                    _abstain(
                        "quotation_change_order_xlsx@1.0.0",
                        {},
                        ccn.get("abstain_reason") or "abstain",
                    ),
                    status_code=422,
                )
        exported = export_change_order_xlsx(ccn)
        cr_id = str(ccn.get("cr_id") or "CCN-001").replace('"', "")
        return Response(
            content=exported["xlsx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{cr_id}_change_order.xlsx"',
                "X-AeroRegu-SHA256": exported["xlsx_sha256"],
                "X-AeroRegu-Formula-Count": str(exported["formula_count"]),
            },
        )

    @app.post("/quotations/rotorcraft/change-order/export-pdf")
    def rotorcraft_change_order_export_pdf_endpoint(
        body: dict[str, Any], request: Request
    ) -> Response:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.quotation_change_order import compute_quotation_change_order
        from evidence_coverage.quotation_exporter import export_change_order_signed_pdf

        if isinstance(body.get("ccn_dossier"), dict):
            ccn = body["ccn_dossier"]
        else:
            tenant_id = _validate_tenant(body.get("tenant_id"))
            if tenant_id is None:
                return JSONResponse(
                    _abstain("quotation_change_order_pdf@1.0.0", {}, "invalid_tenant"),
                    status_code=400,
                )
            actor_id, auth_err = _check_endpoint_access(
                request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
            )
            if auth_err is not None:
                return auth_err
            ledger = open_ledger(tenant_id)
            if isinstance(body.get("baseline_dossier"), dict):
                baseline = body["baseline_dossier"]
            elif isinstance(body.get("baseline_spec"), dict):
                b_spec = _build_composite_spec(
                    dict(body["baseline_spec"]), tenant_id=tenant_id, actor_id=actor_id
                )
                baseline = run_composite_rotorcraft_quotation(ledger, b_spec)
            else:
                return JSONResponse(
                    _abstain("quotation_change_order_pdf@1.0.0", {}, "missing_baseline"),
                    status_code=400,
                )
            rev_spec = _build_composite_spec(
                dict(body.get("revised_spec") or body), tenant_id=tenant_id, actor_id=actor_id
            )
            ccn = compute_quotation_change_order(
                ledger,
                baseline,
                rev_spec,
                cr_id=str(body.get("cr_id") or "CCN-001"),
                change_reason=str(body.get("change_reason") or "CCN Addendum"),
            )
            if ccn.get("confidence") == "abstain":
                return JSONResponse(
                    _abstain(
                        "quotation_change_order_pdf@1.0.0",
                        {},
                        ccn.get("abstain_reason") or "abstain",
                    ),
                    status_code=422,
                )
        priv_pem, pub_pem = _attestation_keypair()
        exported = export_change_order_signed_pdf(
            ccn, private_key_pem=priv_pem, public_key_pem=pub_pem
        )
        cr_id = str(ccn.get("cr_id") or "CCN-001").replace('"', "")
        return Response(
            content=exported["pdf_bytes"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{cr_id}_signed_ccn.pdf"',
                "X-AeroRegu-SHA256": exported["pdf_sha256"],
                "X-AeroRegu-Merkle-Root": exported["merkle_root"],
            },
        )

    @app.post("/quotations/rotorcraft/portfolio-capacity")
    def rotorcraft_portfolio_capacity_endpoint(
        body: dict[str, Any], request: Request
    ) -> JSONResponse:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.portfolio_capacity_leveler import level_portfolio_capacity

        dossiers = list(body.get("dossiers") or [])
        if not dossiers and isinstance(body.get("rfq_specs"), list):
            tenant_id = _validate_tenant(body.get("tenant_id"))
            if tenant_id is None:
                return JSONResponse(
                    _abstain("portfolio_capacity_leveler@1.0.0", {}, "invalid_tenant"),
                    status_code=400,
                )
            actor_id, auth_err = _check_endpoint_access(
                request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
            )
            if auth_err is not None:
                return auth_err
            ledger = open_ledger(tenant_id)
            for idx, raw_s in enumerate(body["rfq_specs"]):
                spec = _build_composite_spec(
                    {"rfq_id": f"RFQ-{idx + 1:03d}", **dict(raw_s)},
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                )
                d = run_composite_rotorcraft_quotation(ledger, spec)
                if d.get("confidence") != "abstain":
                    dossiers.append(d)

        headcount = (
            {str(k): int(v) for k, v in body["team_headcount"].items()}
            if isinstance(body.get("team_headcount"), dict)
            else None
        )
        res = level_portfolio_capacity(
            dossiers,
            team_headcount=headcount,
            max_utilization_pct=str(body.get("max_utilization_pct") or "85.000"),
            max_horizon_weeks=int(body.get("max_horizon_weeks") or 104),
        )
        return JSONResponse(_ok("portfolio_capacity_leveler@1.0.0", {}, res))

    @app.post("/quotations/rotorcraft/fx-hedging")
    def rotorcraft_fx_hedging_endpoint(body: dict[str, Any]) -> JSONResponse:
        from evidence_coverage.quotation_fx_hedging import evaluate_quotation_fx_hedging

        try:
            res = evaluate_quotation_fx_hedging(
                quoted_price_eur=body.get("quoted_price_eur") or "500000",
                cost_eur=body.get("cost_eur") or "380000",
                billing_currency=str(body.get("billing_currency") or "USD"),
                cost_currency=str(body.get("cost_currency") or "EUR"),
                hedge_ratio_pct=str(body.get("hedge_ratio_pct") or "80.000"),
                forward_carry_bps_per_year=str(body.get("forward_carry_bps_per_year") or "85.000"),
                program_years=int(body.get("program_years") or 3),
                fx_shock_band_pct=str(body.get("fx_shock_band_pct") or "10.000"),
                cost_drift_band_pct=str(body.get("cost_drift_band_pct") or "5.000"),
                min_acceptable_margin_pct=str(body.get("min_acceptable_margin_pct") or "10.000"),
            )
        except ValueError as exc:
            return JSONResponse(
                _abstain("quotation_fx_hedging@1.0.0", {}, str(exc)),
                status_code=400,
            )
        return JSONResponse(_ok("quotation_fx_hedging@1.0.0", {}, res))

    @app.post("/quotations/rotorcraft/evm-postmortem")
    def rotorcraft_evm_postmortem_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation

        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                _abstain("bid_actual_postmortem@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = _check_endpoint_access(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        ledger = open_ledger(tenant_id)

        baseline = body.get("baseline_dossier")
        if not isinstance(baseline, dict) or not baseline.get("composite_wbs_dag"):
            b_spec = dict(body.get("baseline_spec") or {})
            if not b_spec:
                b_spec = {
                    "rfq_id": body.get("rfq_id") or "RFQ-BASE-001",
                    "rfq_text": str(body.get("baseline_rfq_text") or "CS-29 frame static Net 60."),
                    "archetype_ids": body.get("baseline_archetypes")
                    or ["Q-DES-02", "Q-STR-03", "Q-DOA-02"],
                    "country_code": str(body.get("country_code") or "EU_DEFAULT"),
                }
            spec = _build_composite_spec(
                b_spec,
                tenant_id=tenant_id,
                actor_id=actor_id or str(body.get("actor_id") or "stress-office-controller"),
            )
            baseline = run_composite_rotorcraft_quotation(ledger, spec)
            if baseline.get("confidence") == "abstain":
                return JSONResponse(
                    _abstain(
                        "bid_actual_postmortem@1.0.0",
                        {},
                        str(baseline.get("abstain_reason") or "baseline_abstain"),
                    ),
                    status_code=400,
                )

        try:
            res = run_bid_actual_evm_postmortem(
                ledger,
                baseline,
                body.get("actuals"),
                actuals_csv=body.get("actuals_csv"),
                project_id=body.get("project_id"),
                actual_ecn_iterations=int(body.get("actual_ecn_iterations") or 0),
                idp_rework_hours=str(body.get("idp_rework_hours") or "0"),
                unbilled_scope_hours=str(body.get("unbilled_scope_hours") or "0"),
                cve_rework_hours=str(body.get("cve_rework_hours") or "0"),
                actor_id=actor_id or str(body.get("actor_id") or "stress-office-controller"),
                created_at=body.get("created_at") or _now(),
            )
        except ValueError as exc:
            return JSONResponse(
                _abstain("bid_actual_postmortem@1.0.0", {}, str(exc)),
                status_code=400,
            )
        return JSONResponse(_ok("bid_actual_postmortem@1.0.0", {}, res))

    def _resolve_evm_and_fx(
        body: dict[str, Any], request: Request, method_tag: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.quotation_fx_hedging import evaluate_quotation_fx_hedging

        fx_rep = body.get("fx_report") if isinstance(body.get("fx_report"), dict) else None
        if isinstance(body.get("postmortem_report"), dict):
            return body["postmortem_report"], fx_rep, None

        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return (
                None,
                None,
                JSONResponse(_abstain(method_tag, {}, "invalid_tenant"), status_code=400),
            )
        actor_id, auth_err = _check_endpoint_access(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return None, None, auth_err
        ledger = open_ledger(tenant_id)
        baseline = body.get("baseline_dossier")
        if not isinstance(baseline, dict) or not baseline.get("composite_wbs_dag"):
            b_spec = dict(body.get("baseline_spec") or {})
            if not b_spec:
                b_spec = {
                    "rfq_id": body.get("rfq_id") or "RFQ-BASE-001",
                    "rfq_text": str(body.get("baseline_rfq_text") or "CS-29 frame static Net 60."),
                    "archetype_ids": body.get("baseline_archetypes")
                    or ["Q-DES-02", "Q-STR-03", "Q-DOA-02"],
                    "country_code": str(body.get("country_code") or "EU_DEFAULT"),
                }
            spec = _build_composite_spec(
                b_spec,
                tenant_id=tenant_id,
                actor_id=actor_id or str(body.get("actor_id") or "stress-office-controller"),
            )
            baseline = run_composite_rotorcraft_quotation(ledger, spec)
        pm = run_bid_actual_evm_postmortem(
            ledger,
            baseline,
            body.get("actuals"),
            actuals_csv=body.get("actuals_csv"),
            project_id=body.get("project_id"),
            actual_ecn_iterations=int(body.get("actual_ecn_iterations") or 0),
            idp_rework_hours=str(body.get("idp_rework_hours") or "0"),
            unbilled_scope_hours=str(body.get("unbilled_scope_hours") or "0"),
            cve_rework_hours=str(body.get("cve_rework_hours") or "0"),
            actor_id=actor_id or str(body.get("actor_id") or "stress-office-controller"),
            created_at=body.get("created_at") or _now(),
        )
        if fx_rep is None and body.get("billing_currency"):
            evm_sum = pm.get("evm_summary") or {}
            fx_rep = evaluate_quotation_fx_hedging(
                quoted_price_eur=evm_sum.get("quoted_selling_price_eur") or "500000",
                cost_eur=evm_sum.get("bac_cost_eur") or "380000",
                billing_currency=str(body.get("billing_currency") or "USD"),
                hedge_ratio_pct=str(body.get("hedge_ratio_pct") or "85.000"),
            )
        return pm, fx_rep, None

    @app.post("/quotations/rotorcraft/evm-postmortem/export-xlsx")
    def rotorcraft_evm_export_xlsx_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.quotation_exporter import export_evm_postmortem_xlsx

        pm, fx_rep, err = _resolve_evm_and_fx(body, request, "evm_export_xlsx@1.0.0")
        if err is not None:
            return err
        assert pm is not None
        exported = export_evm_postmortem_xlsx(pm, fx_report=fx_rep)
        pid = str(pm.get("project_id") or "POST-001").replace('"', "")
        return Response(
            content=exported["xlsx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{pid}_evm_postmortem.xlsx"',
                "X-AeroRegu-SHA256": exported["xlsx_sha256"],
                "X-AeroRegu-Formula-Count": str(exported["formula_count"]),
            },
        )

    @app.post("/quotations/rotorcraft/evm-postmortem/export-pdf")
    def rotorcraft_evm_export_pdf_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.quotation_exporter import export_evm_postmortem_signed_pdf

        pm, fx_rep, err = _resolve_evm_and_fx(body, request, "evm_export_pdf@1.0.0")
        if err is not None:
            return err
        assert pm is not None
        priv_pem, pub_pem = _attestation_keypair()
        exported = export_evm_postmortem_signed_pdf(
            pm, fx_report=fx_rep, private_key_pem=priv_pem, public_key_pem=pub_pem
        )
        pid = str(pm.get("project_id") or "POST-001").replace('"', "")
        return Response(
            content=exported["pdf_bytes"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{pid}_signed_evm.pdf"',
                "X-AeroRegu-SHA256": exported["pdf_sha256"],
                "X-AeroRegu-Merkle-Root": exported["merkle_root"],
            },
        )

    @app.post("/nafems/audit-sol105-gpforce")
    def nafems_sol105_gpforce_audit_endpoint(body: dict[str, Any]) -> JSONResponse:
        from evidence_ingest.fem_parsers import parse_abaqus_inp

        f06_text = str(body.get("f06_text") or "")
        abq_text = str(body.get("abaqus_text") or "")
        if not f06_text.strip() and not abq_text.strip():
            return JSONResponse(
                _abstain("nafems_sol105_gpforce@1.0.0", {}, "missing_f06_or_abaqus_text"),
                status_code=400,
            )

        sol105_res = None
        gpforce_res = None
        if f06_text.strip():
            f06_bytes = f06_text.encode("utf-8")
            f06_hash = hashlib.sha256(f06_bytes).hexdigest()
            try:
                f06_parsed = parse_nastran_f06(f06_bytes, f06_hash)
            except IngestAbstain as exc:
                return JSONResponse(
                    _abstain("nafems_sol105_gpforce@1.0.0", {}, exc.reason), status_code=422
                )
            sol105_res = audit_sol105_buckling_margins(
                f06_parsed,
                min_buckling_factor=str(body.get("min_buckling_factor") or "1.000"),
            )
            gpforce_res = audit_gpforce_freebody_equilibrium(
                f06_parsed,
                max_nodal_residual_n=str(body.get("max_nodal_residual_n") or "0.010"),
            )

        abaqus_res = None
        if abq_text.strip():
            abq_bytes = abq_text.encode("utf-8")
            abq_hash = hashlib.sha256(abq_bytes).hexdigest()
            try:
                abq_parsed = parse_abaqus_inp(abq_bytes, abq_hash)
            except IngestAbstain as exc:
                return JSONResponse(
                    _abstain("nafems_sol105_gpforce@1.0.0", {}, exc.reason), status_code=422
                )
            abaqus_res = audit_abaqus_composite_layup_vs_report(
                abq_parsed,
                report_claims=body.get("abaqus_report_claims"),
            )

        f06_has_data = (sol105_res is not None and not sol105_res["abstain"]) or (
            gpforce_res is not None and not gpforce_res["abstain"]
        )
        overall = (
            (not f06_text.strip() or f06_has_data)
            and (sol105_res is None or sol105_res["abstain"] or sol105_res["clear"])
            and (gpforce_res is None or gpforce_res["abstain"] or gpforce_res["balanced"])
            and (abaqus_res is None or abaqus_res["consistent"])
        )
        return JSONResponse(
            _ok(
                "nafems_sol105_gpforce@1.0.0",
                {},
                {
                    "overall_pass": overall,
                    "sol105_buckling": sol105_res,
                    "gpforce_equilibrium": gpforce_res,
                    "abaqus_composite_drift": abaqus_res,
                },
            )
        )

    @app.get("/mcp/catalog")
    def get_mcp_catalog_endpoint() -> JSONResponse:
        from evidence_api.mcp_server import get_mcp_catalog

        return JSONResponse(_ok("mcp@1.0.0", {}, get_mcp_catalog()))

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "demo.html")

    return app


def _decode_body_bytes(
    body: dict[str, Any], method_version: str, filename: str
) -> tuple[bytes | None, JSONResponse | None]:
    if body.get("content_base64") is not None:
        encoded = str(body["content_base64"])
        if len(encoded) > (MAX_INGEST_BYTES * 4) // 3 + 16:
            return None, JSONResponse(
                _abstain(method_version, {"filename": filename}, "payload_too_large"),
                status_code=413,
            )
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception:
            return None, JSONResponse(
                _abstain(method_version, {"filename": filename}, "invalid_base64"),
                status_code=400,
            )
    elif body.get("content_text") is not None:
        raw = str(body["content_text"]).encode("utf-8")
    else:
        return None, JSONResponse(
            _abstain(method_version, {"filename": filename}, "missing_document_content"),
            status_code=400,
        )
    if len(raw) > MAX_INGEST_BYTES:
        return None, JSONResponse(
            _abstain(method_version, {"filename": filename}, "payload_too_large"),
            status_code=413,
        )
    return raw, None


def _attach_binding_deltas(bindings: dict[str, Any], stated_by_method: dict[str, Any]) -> None:
    cards = bindings.get("cards") or {}
    for method_id, card_info in cards.items():
        execution = card_info.get("execution")
        stated = stated_by_method.get(method_id)
        if (
            isinstance(execution, dict)
            and execution.get("confidence") == "deterministic"
            and isinstance(stated, dict)
        ):
            delta = classify_numeric_delta(
                method_id,
                dict(card_info.get("matched_inputs") or {}),
                {str(k): str(v) for k, v in stated.items()},
                dict(execution.get("outputs") or {}),
            )
            execution["delta_classification"] = delta


def _validate_tenant(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return DEMO_TENANT
    candidate = str(value).strip()
    if TENANT_RE.fullmatch(candidate):
        return candidate
    return None


def _is_production_mode() -> bool:
    return os.environ.get("EVIDENCE_PRODUCTION", "").strip().lower() in {"1", "true", "yes"} or (
        os.environ.get("EVIDENCE_DISABLE_DEMO_ACTORS", "").strip().lower() in {"1", "true", "yes"}
    )


def evidence_home() -> Path:
    configured = os.environ.get("EVIDENCE_HOME", "").strip()
    if configured:
        return Path(configured).resolve()
    candidate = (Path.home() / ".aeroregu").resolve()
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        global _FALLBACK_TEMP_DIR
        with _FALLBACK_TEMP_LOCK:
            if _FALLBACK_TEMP_DIR is None:
                td = tempfile.mkdtemp(prefix="aeroregu-")
                try:
                    os.chmod(td, 0o700)
                except OSError:
                    pass
                _FALLBACK_TEMP_DIR = Path(td).resolve()
            return _FALLBACK_TEMP_DIR


def _sqlite_fingerprint(path: Path | None) -> tuple[tuple[int, int], ...] | None:
    if path is None:
        return None
    try:
        parts: list[tuple[int, int]] = []
        for candidate in (path, Path(f"{path}-wal")):
            if candidate.exists():
                st = candidate.stat()
                parts.append((int(st.st_mtime_ns), int(st.st_size)))
        return tuple(parts) if parts else None
    except OSError:
        return None


def _cached_dossier_bundle(ledger: Any) -> dict[str, Any]:
    head = ledger.head_hash()
    l_path = getattr(ledger, "path", None)
    fp = _sqlite_fingerprint(l_path)
    key = (str(l_path or f"pg:{ledger.tenant_id}"), head, fp)
    with _DOSSIER_CACHE_LOCK:
        cached = _DOSSIER_CACHE.get(key)
        if cached is not None:
            return cached
    chain_ok = ledger.verify()
    dossier = build_enterprise_dossier(ledger.events(), chain_verified=chain_ok)
    strictdoc = export_strictdoc(dossier)
    oscal = export_oscal_sar(dossier)
    bundle = {"dossier": dossier, "strictdoc": strictdoc, "oscal": oscal}
    if chain_ok:
        with _DOSSIER_CACHE_LOCK:
            if len(_DOSSIER_CACHE) >= _MAX_DOSSIER_CACHE:
                oldest = next(iter(_DOSSIER_CACHE))
                _DOSSIER_CACHE.pop(oldest, None)
            _DOSSIER_CACHE[key] = bundle
    return bundle


def _dispatch_registered_webhooks(
    ledger: Any,
    *,
    event_name: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    subs = ledger.list_webhooks(include_secret=True)
    if not subs:
        return []
    return dispatch_webhook_with_retry(
        subs,
        event_name=event_name,
        payload=payload,
        ledger=ledger,
        max_attempts=3,
        backoff_base_seconds=0.0,
    )


def _ensure_default_actors(ledger: Any) -> None:
    author_pw = os.environ.get("EVIDENCE_AUTHOR_PASSWORD")
    reviewer_pw = os.environ.get("EVIDENCE_REVIEWER_PASSWORD")
    admin_pw = os.environ.get("EVIDENCE_ADMIN_PASSWORD")
    if _is_production_mode():
        if author_pw:
            ledger.ensure_actor("author", "author", author_pw)
        if reviewer_pw:
            ledger.ensure_actor("reviewer", "cve", reviewer_pw)
        if admin_pw:
            ledger.ensure_actor("admin", "admin", admin_pw)
    else:
        ledger.ensure_actor("author", "author", author_pw or "author-local")
        ledger.ensure_actor("reviewer", "cve", reviewer_pw or "reviewer-local")
        ledger.ensure_actor("admin", "admin", admin_pw or "admin-local")


def open_ledger(tenant_id: str = DEMO_TENANT) -> Any:
    checked = _validate_tenant(tenant_id)
    if checked is None:
        raise ValueError(f"invalid tenant_id: {tenant_id!r}")
    root = evidence_home()
    path = (root / "tenants" / f"{checked}.sqlite3").resolve()
    alt_path = (root / "tenants" / checked / "ledger.sqlite3").resolve()
    if not path.is_file() and alt_path.is_file():
        path = alt_path
    pg_dsn = os.environ.get("EVIDENCE_PG_DSN", "").strip()
    if pg_dsn:
        ledger = open_ledger_backend(path, checked, pg_dsn=pg_dsn)
        _ensure_default_actors(ledger)
        return ledger
    with _LEDGER_CACHE_LOCK:
        try:
            st = path.stat()
            disk_id: tuple[int, int] | None = (int(st.st_dev), int(st.st_ino))
        except OSError:
            disk_id = None
        cached = _LEDGER_CACHE.get(path)
        if cached is not None and disk_id is not None and cached[1] == disk_id:
            return cached[0]
        existed = disk_id is not None
        ledger = open_ledger_backend(path, checked)
        if not existed or path not in _INITIALIZED_ACTOR_PATHS:
            _ensure_default_actors(ledger)
            _INITIALIZED_ACTOR_PATHS.add(path)
        try:
            st_after = path.stat()
            stored_id: tuple[int, int] | None = (int(st_after.st_dev), int(st_after.st_ino))
        except OSError:
            stored_id = None
        _LEDGER_CACHE[path] = (ledger, stored_id)
        return ledger


def _attestation_keypair() -> tuple[bytes, bytes]:
    """Load or provision the Ed25519 keypair used to DSSE-sign every ZIP export."""
    env_pem = os.environ.get("EVIDENCE_DSSE_PRIVATE_KEY_PEM", "").strip()
    if env_pem:
        priv_pem = env_pem.replace("\\n", "\n").encode("utf-8")
        priv = serialization.load_pem_private_key(priv_pem, password=None)
        if not isinstance(priv, Ed25519PrivateKey):
            raise TypeError("EVIDENCE_DSSE_PRIVATE_KEY_PEM must be an Ed25519 private key")
        pub_pem = priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return priv_pem, pub_pem

    root = evidence_home()
    key_path = Path(
        os.environ.get(
            "EVIDENCE_DSSE_PRIVATE_KEY_PATH",
            str(root / ".keys" / "attestation_ed25519.pem"),
        )
    )
    if key_path.is_file():
        priv_pem = key_path.read_bytes()
        priv = serialization.load_pem_private_key(priv_pem, password=None)
        if not isinstance(priv, Ed25519PrivateKey):
            raise TypeError("DSSE key path must hold an Ed25519 private key")
        pub_pem = priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return priv_pem, pub_pem

    priv_pem, pub_pem = generate_ed25519_keypair()
    try:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(priv_pem)
        key_path.with_suffix(".pub.pem").write_bytes(pub_pem)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    return priv_pem, pub_pem


def _zip_bytes(events: list[dict[str, Any]]) -> bytes:
    chain_ok = verify_chain_document(events)
    dossier = build_enterprise_dossier(events, chain_verified=chain_ok)
    gate = evaluate_traceability_gate(
        events,
        chain_verified=chain_ok,
        dossier=dossier,
    )
    sdoc_content = export_strictdoc(dossier)
    oscal_content = export_oscal_sar(dossier)
    attestation = build_pipeline_attestation(events)
    priv_pem, pub_pem = _attestation_keypair()
    dsse_envelope = sign_attestation_dsse(attestation, priv_pem)
    m_root = str(attestation["subject"][0]["digest"]["merkle_root"])
    formal_proof_data = dossier.get("formal_envelope_proof") or {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("chain.json", json.dumps(events, indent=2))
        archive.writestr("merkle_root.txt", m_root + "\n")
        archive.writestr("dossier.json", json.dumps(dossier, indent=2))
        archive.writestr("traceability_gate.json", json.dumps(gate, indent=2))
        archive.writestr("dossier.sdoc", sdoc_content)
        archive.writestr("oscal_sar.json", json.dumps(oscal_content, indent=2))
        archive.writestr("attestation_bundle.json", json.dumps(attestation, indent=2))
        archive.writestr("attestation_bundle.dsse.json", json.dumps(dsse_envelope, indent=2))
        archive.writestr("attestation_public_key.pem", pub_pem)
        archive.writestr("formal_proof.json", json.dumps(formal_proof_data, indent=2))
        archive.writestr("README.txt", VERIFY_TEXT)
    return buffer.getvalue()


def _ok(method_version: str, inputs: Any, result: Any) -> dict[str, Any]:
    return make_envelope(
        sources=[project_source("aeroregu", "https://aeroregu.local/api", "ASSUMPTION")],
        method_version=method_version,
        inputs=inputs,
        confidence="deterministic",
        result=result,
    )


def _abstain(method_version: str, inputs: Any, reason: str) -> dict[str, Any]:
    return make_envelope(
        sources=[project_source("aeroregu", "https://aeroregu.local/api", "ASSUMPTION")],
        method_version=method_version,
        inputs=inputs,
        confidence="abstain",
        abstain_reason=reason,
    )


def _card_sources(method_id: str) -> list[dict[str, Any]]:
    try:
        return load_card(method_id)["sources"]
    except AbstainError:
        return [project_source("calc", "https://aeroregu.local/calc", "ASSUMPTION")]


def _card_version(method_id: str) -> str:
    try:
        return str(load_card(method_id)["method_version"])
    except AbstainError:
        return "calc@0"


def _token(actor_id: str, tenant_id: str = DEMO_TENANT, *, ttl_seconds: int | None = None) -> str:
    secret = _secret()
    if secret is None:
        raise RuntimeError("session secret is missing")
    ttl = DEFAULT_SESSION_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
    exp_epoch = int(time.time()) + ttl
    subject = f"{tenant_id}:{actor_id}:{exp_epoch}"
    mac = hmac.new(secret.encode(), subject.encode(), hashlib.sha256).hexdigest()
    return f"{subject}.{mac}"


def _session_actor(
    request: Request,
    requested: Any,
    *,
    tenant_id: str = DEMO_TENANT,
) -> str | None:
    actor = _actor_from_request(request, tenant_id=tenant_id)
    if actor is None:
        return None
    if requested is not None and str(requested) != actor:
        return None
    return actor


def _client_ip(request: Request) -> str:
    peer_ip = request.client.host if request.client else "unknown"
    trust_proxy = os.environ.get("EVIDENCE_TRUST_PROXY", "").strip().lower() in {
        "1",
        "true",
        "yes",
    } or peer_ip in {"127.0.0.1", "::1", "localhost", "testclient"}
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return peer_ip


def _cookie_secure(request: Request) -> bool:
    explicit = os.environ.get("EVIDENCE_COOKIE_SECURE", "").strip().lower()
    if explicit in {"1", "true", "yes"}:
        return True
    if explicit in {"0", "false", "no"}:
        return False
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if request.url.scheme == "https" or proto == "https":
        return True
    return _is_production_mode() and (request.url.hostname or "") != "testserver"


def _actor_from_request(request: Request, *, tenant_id: str = DEMO_TENANT) -> str | None:
    secret = _secret()
    if secret is None:
        return None
    raw = request.cookies.get("el_session", "")
    if not raw:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw = auth_header[7:].strip()
    if "." not in raw:
        return None
    subject, mac = raw.rsplit(".", 1)
    expected = hmac.new(secret.encode(), subject.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    parts = subject.split(":")
    if len(parts) != 3:
        return None
    token_tenant, actor_id, exp_str = parts
    try:
        if int(exp_str) < int(time.time()):
            return None
    except ValueError:
        return None
    if token_tenant != tenant_id:
        return None
    ledger = open_ledger(tenant_id)
    if ledger.actor_role(actor_id) is None:
        return None
    token_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if ledger.is_token_revoked(token_digest):
        return None
    if not get_scim_directory().is_actor_active(tenant_id, actor_id):
        return None
    return actor_id


def _secret() -> str | None:
    secret = os.environ.get("EVIDENCE_SESSION_SECRET", "")
    if len(secret) < 24 or secret == "local-demo-session":
        return None
    return secret


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bolt_inputs(shear: str) -> dict[str, Any]:
    return {
        "shear_force_n": shear,
        "tensile_force_n": "4000.000",
        "area_mm2": "80.000",
        "shear_allowable_mpa": "250.000",
        "tensile_allowable_mpa": "250.000",
        "thickness_mm": "5.000",
    }


app = create_app()
