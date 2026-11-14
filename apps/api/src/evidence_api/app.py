from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import tempfile
import threading
import time
import zipfile
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from evidence_calc.cad_bindings import bind_parameters_to_cards
from evidence_calc.diagnostics import classify_numeric_delta
from evidence_calc.errors import AbstainError
from evidence_calc.plugins import delete_plugin_card
from evidence_calc.registry import list_cards, load_card, register_custom_card, run_method
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
from evidence_coverage.pdf_report import build_signed_pdf_report, verify_signed_pdf_report
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
from evidence_ingest.router import ingest_bytes
from evidence_kernel.attestation import (
    build_pipeline_attestation,
    generate_ed25519_keypair,
    sign_attestation_dsse,
)
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
from evidence_kernel.webhooks import WebhookError, dispatch_webhook_event, new_webhook_record
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
        payload = JSONResponse(
            _ok(
                "auth@1.0.0",
                {"actor_id": actor_id, "tenant_id": tenant_id},
                {"actor_id": actor_id, "tenant_id": tenant_id},
            )
        )
        payload.set_cookie(
            "el_session",
            _token(actor_id, tenant_id),
            httponly=True,
            samesite="lax",
            secure=_cookie_secure(request),
        )
        return payload

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
    def auth_me(request: Request, tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor_id = _actor_from_request(request, tenant_id=checked_tenant)
        if actor_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        role = open_ledger(checked_tenant).actor_role(actor_id)
        return JSONResponse(
            _ok(
                "auth@1.0.0",
                {"tenant_id": checked_tenant},
                {"actor_id": actor_id, "tenant_id": checked_tenant, "role": role},
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

    @app.get("/ledger/verify")
    def ledger_verify(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("ledger@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked_tenant)
        events = ledger.events()
        return JSONResponse(
            _ok(
                "ledger@1.0.0",
                {"tenant_id": checked_tenant},
                {
                    "chain_verified": ledger.verify(),
                    "head_hash": ledger.head_hash(),
                    "merkle_root": ledger.merkle_root(),
                    "event_count": str(len(events)),
                },
            )
        )

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
    deliveries = dispatch_webhook_event(subs, event_name=event_name, payload=payload)
    for item in deliveries:
        ledger.record_webhook_delivery(item)
    return deliveries


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
