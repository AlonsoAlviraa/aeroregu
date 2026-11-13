from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence_calc.diagnostics import classify_numeric_delta
from evidence_calc.errors import AbstainError
from evidence_calc.registry import load_card, run_method
from evidence_coverage.dossier import (
    active_calc_records,
    build_enterprise_dossier,
    export_oscal_sar,
    export_strictdoc,
)
from evidence_coverage.formal_bounds import prove_continuous_flight_envelope
from evidence_coverage.gate import evaluate_traceability_gate
from evidence_coverage.grid import calc_inputs_for, generate_cells
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
from evidence_kernel.attestation import build_pipeline_attestation
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
from evidence_kernel.supervisor import (
    CaseAbstain,
    CaseSpec,
    arun_case,
    astream_case,
    invoke_single_agent,
)
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

DEMO_TENANT = "demo"
TENANT_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
ASSISTANCE = "This tool assists a human reviewer. It does not determine compliance."
VERIFY_TEXT = ASSISTANCE + "\nVerify with: uv run python -m evidence_kernel verify chain.json\n"
_INITIALIZED_ACTOR_PATHS: set[Path] = set()


def create_app() -> FastAPI:
    app = FastAPI(title="aeroregu")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Evidence-Request-Hash"] = hashlib.sha256(
            f"{request.method}:{request.url.path}".encode()
        ).hexdigest()
        return response

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
            try:
                raw = base64.b64decode(str(body["content_base64"]), validate=True)
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
        try:
            parsed = ingest_bytes(raw, filename)
        except IngestAbstain as exc:
            return JSONResponse(
                _abstain("ingest@1.0.0", {"filename": filename}, exc.reason),
            )
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
            method_id = str(body["method_id"])
            inputs = body.get("inputs") or {}
            cell_id = body.get("cell_id")
        normalize_units = bool(body.get("normalize_units"))
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
        result_body = dict(ran["outputs"])
        if normalize_units and ran.get("unit_conversions"):
            result_body["unit_conversions"] = ran["unit_conversions"]
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
            if cell_id:
                cell = next(item for item in generate_cells() if item.cell_id == cell_id)
                set_cell_status(
                    ledger,
                    cell=cell,
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
        tenant_id: str = DEMO_TENANT,
    ) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(
                _abstain("traceability_gate@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        ledger = open_ledger(checked_tenant)
        gate = evaluate_traceability_gate(
            ledger.events(),
            chain_verified=ledger.verify(),
            require_head_signoff=require_signoff,
        )
        return JSONResponse(
            _ok(
                "traceability_gate@1.0.0",
                {"tenant_id": checked_tenant, "require_signoff": str(require_signoff).lower()},
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
        return JSONResponse(
            _ok(
                "coverage_grid@1.0.0",
                {"tenant_id": tenant_id, "shift": "+5%"},
                {
                    "invalidated_cells": [row["cell_id"] for row in records],
                    "invalidated_event_hashes": invalidated_hashes,
                    "delta_reverification_manifest": dossier["delta_reverification_manifest"],
                    "dossier_hash": dossier["dossier_hash"],
                },
            )
        )

    @app.get("/dossier/summary")
    def dossier_summary(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("dossier@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked_tenant)
        dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
        return JSONResponse(_ok("dossier@1.0.0", {"tenant_id": checked_tenant}, dossier))

    @app.get("/dossier/strictdoc")
    def dossier_strictdoc(tenant_id: str = DEMO_TENANT) -> Response:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("dossier@1.0.0", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked_tenant)
        dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
        content = export_strictdoc(dossier)
        return Response(content=content, media_type="text/plain; charset=utf-8")

    @app.get("/dossier/oscal")
    def dossier_oscal(tenant_id: str = DEMO_TENANT) -> JSONResponse:
        checked_tenant = _validate_tenant(tenant_id)
        if checked_tenant is None:
            return JSONResponse(_abstain("oscal_sar@1.1.2", {}, "invalid_tenant"), status_code=400)
        ledger = open_ledger(checked_tenant)
        dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
        sar = export_oscal_sar(dossier)
        return JSONResponse(_ok("oscal_sar@1.1.2", {"tenant_id": checked_tenant}, sar))

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
            artifact = body["artifact"]
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
    def agents_probe(body: dict[str, Any] | None = None) -> JSONResponse:
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
        records = bool(body.get("record"))
        actor_id = str(body.get("actor_id") or "author")
        if records:
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
            out["result"] = result
        elif out.get("confidence") == "deterministic" and isinstance(out.get("result"), dict):
            if agent_telemetry:
                out["result"] = {**out["result"], "agent_telemetry": agent_telemetry}
        return out

    @app.post("/supervisor/run")
    async def supervisor_run(body: dict[str, Any], request: Request) -> JSONResponse:
        err_resp, ctx = _prepare_supervisor_run(body, request)
        if err_resp is not None:
            return err_resp
        outcome = await arun_case(ctx["ledger"], ctx["gw"], ctx["case"])
        envelope = _decorate_supervisor_envelope(
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
                    decorated = _decorate_supervisor_envelope(
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
                    )
                    payload = {**payload, "envelope": decorated}
                yield f"event: {ev_type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.post("/auth/login")
    def login(body: dict[str, Any]) -> JSONResponse:
        if _secret() is None:
            envelope = _abstain("auth@1.0.0", {}, "session_secret_missing")
            return JSONResponse(envelope, status_code=401)
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "invalid_tenant"), status_code=400)
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
        )
        return payload

    @app.post("/ledger/append")
    def ledger_append(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = _validate_tenant(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(_abstain("ledger@1.0.0", {}, "invalid_tenant"), status_code=400)
        actor = _session_actor(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None or actor != body.get("actor_id"):
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger(tenant_id)
        event_body = {**body, "tenant_id": tenant_id}
        digest = record(ledger, event_body)
        return JSONResponse(
            _ok(
                "ledger@1.0.0",
                {"event_type": body["event_type"], "tenant_id": tenant_id},
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
        known_hashes = {str(event["event_hash"]) for event in ledger.events()}
        if target not in known_hashes:
            return JSONResponse(
                _abstain(
                    "human_signoff@1.0.0",
                    {"target_event_hash": target},
                    "target_event_not_found",
                ),
                status_code=404,
            )
        statement = str(body.get("statement") or SIGN_OFF_STATEMENT)
        created_at = str(body.get("created_at") or _now())
        signoff_inputs = {"target_event_hash": target, "statement": statement}
        envelope = make_envelope(
            sources=[
                project_source("human-review", "https://aeroregu.local/signoff", "ASSUMPTION")
            ],
            method_version="human_signoff@1.0.0",
            inputs=signoff_inputs,
            confidence="deterministic",
            result={"actor_id": actor_id, "target_event_hash": target, "statement": statement},
        )
        try:
            ev_hash = record(
                ledger,
                {
                    "event_type": "human_signoff",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": {
                        "actor_id": actor_id,
                        "target_event_hash": target,
                        "statement": statement,
                    },
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
                    "target_event_hash": target,
                    "statement": statement,
                    "merkle_root": ledger.merkle_root(),
                },
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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "demo.html")

    return app


def _validate_tenant(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return DEMO_TENANT
    candidate = str(value).strip()
    if TENANT_RE.fullmatch(candidate):
        return candidate
    return None


def open_ledger(tenant_id: str = DEMO_TENANT) -> Ledger:
    checked = _validate_tenant(tenant_id)
    if checked is None:
        raise ValueError(f"invalid tenant_id: {tenant_id!r}")
    root = Path(os.environ.get("EVIDENCE_HOME", Path.cwd() / "data"))
    path = (root / "tenants" / f"{checked}.sqlite3").resolve()
    existed = path.is_file()
    ledger = Ledger(path, checked)
    if not existed or path not in _INITIALIZED_ACTOR_PATHS:
        ledger.ensure_actor("author", "human", "author-local")
        ledger.ensure_actor("reviewer", "human", "reviewer-local")
        _INITIALIZED_ACTOR_PATHS.add(path)
    return ledger


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
    formal_proof_data = dossier.get("formal_envelope_proof") or {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("chain.json", json.dumps(events, indent=2))
        archive.writestr("dossier.json", json.dumps(dossier, indent=2))
        archive.writestr("traceability_gate.json", json.dumps(gate, indent=2))
        archive.writestr("dossier.sdoc", sdoc_content)
        archive.writestr("oscal_sar.json", json.dumps(oscal_content, indent=2))
        archive.writestr("attestation_bundle.json", json.dumps(attestation, indent=2))
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


def _token(actor_id: str, tenant_id: str = DEMO_TENANT) -> str:
    secret = _secret()
    if secret is None:
        raise RuntimeError("session secret is missing")
    subject = f"{tenant_id}:{actor_id}"
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
    if ":" in subject:
        token_tenant, actor_id = subject.split(":", 1)
    else:
        token_tenant, actor_id = DEMO_TENANT, subject
    if token_tenant != tenant_id:
        return None
    if open_ledger(tenant_id).actor_role(actor_id) is None:
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
