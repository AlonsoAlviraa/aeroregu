from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.registry import load_card, run_method
from evidence_coverage.grid import calc_inputs_for, generate_cells
from evidence_coverage.status import gap_report, set_cell_status
from evidence_domain.generate import build_aircraft, build_requirements
from evidence_eval.detect import assess
from evidence_eval.faults import clean_artifact, inject
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.gateway import gateway_from_env
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record
from evidence_kernel.supervisor import CaseSpec, run_case
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse

DEMO_TENANT = "demo"
ASSISTANCE = "This tool assists a human reviewer. It does not determine compliance."
VERIFY_TEXT = ASSISTANCE + "\nVerify with: uv run python -m evidence_kernel verify chain.json\n"


def create_app() -> FastAPI:
    app = FastAPI(title="aeroregu")

    @app.get("/health")
    def health() -> dict[str, Any]:
        gateway = "fixture" if not os.environ.get("MODEL_BASE_URL") else "openai_compatible"
        return _ok("health@1.0.0", {}, {"status": "ok", "gateway": gateway})

    @app.get("/requirements")
    def requirements() -> dict[str, Any]:
        document = build_requirements()
        return _ok("requirement_ids@1.0.0", {"count": str(len(document["requirements"]))}, document)

    @app.get("/aircraft")
    def aircraft() -> dict[str, Any]:
        document = build_aircraft()
        return _ok("synthetic_aircraft@0.1.0", {"aircraft_id": document["aircraft_id"]}, document)

    @app.post("/calc/run")
    def calc_run(body: dict[str, Any], request: Request) -> JSONResponse:
        created_at = str(body.get("created_at") or _now())
        records = body.get("example") == "first_cell" or bool(body.get("record"))
        actor_id = str(body.get("actor_id") or "author")
        if records:
            session_actor = _session_actor(request, body.get("actor_id"))
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
        try:
            ran = run_method(method_id, inputs)
        except AbstainError as exc:
            envelope = make_envelope(
                sources=_card_sources(method_id),
                method_version=_card_version(method_id),
                inputs=inputs,
                confidence="abstain",
                abstain_reason=exc.reason,
            )
            return JSONResponse(envelope)
        envelope = make_envelope(
            sources=ran["sources"],
            method_version=ran["method_version"],
            inputs=inputs,
            confidence="deterministic",
            result=ran["outputs"],
        )
        if records:
            ledger = open_ledger()
            event_hash = record(
                ledger,
                {
                    "event_type": "calc",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": created_at,
                    "payload": {
                        "method_id": method_id,
                        "inputs": inputs,
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

    @app.get("/coverage/gaps")
    def coverage_gaps() -> dict[str, Any]:
        report = gap_report(open_ledger().events())
        return _ok("coverage_grid@1.0.0", {"tenant_id": DEMO_TENANT}, report)

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

    @app.post("/supervisor/run")
    def supervisor_run(body: dict[str, Any], request: Request) -> JSONResponse:
        actor_id = _session_actor(request, body.get("actor_id"))
        if actor_id is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        text = str(body.get("text") or "Alpha item is listed in the source block.")
        created_at = str(body.get("created_at") or _now())
        case = CaseSpec(
            tenant_id=DEMO_TENANT,
            actor_id=actor_id,
            created_at=created_at,
            blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
            method_id=body.get("method_id", "rigid_body_point_mass"),
            calc_inputs=body.get("calc_inputs") or calc_inputs_for(generate_cells()[0]),
            reader_label=str(body.get("reader_label") or "NOT_VERIFIED"),
        )
        if body.get("omit_inputs"):
            case.calc_inputs = {}
        outcome = run_case(
            open_ledger(), gateway_from_env(str(body.get("scenario") or "happy")), case
        )
        return JSONResponse(outcome.envelope)

    @app.post("/auth/login")
    def login(body: dict[str, Any]) -> JSONResponse:
        ledger = open_ledger()
        actor_id = str(body.get("actor_id", ""))
        password = str(body.get("password", ""))
        if not ledger.check_password(actor_id, password):
            envelope = _abstain("auth@1.0.0", {"actor_id": actor_id}, "auth_failed")
            return JSONResponse(envelope, status_code=401)
        payload = JSONResponse(_ok("auth@1.0.0", {"actor_id": actor_id}, {"actor_id": actor_id}))
        payload.set_cookie("el_session", _token(actor_id), httponly=True, samesite="lax")
        return payload

    @app.post("/ledger/append")
    def ledger_append(body: dict[str, Any], request: Request) -> JSONResponse:
        actor = _actor_from_request(request)
        if actor is None or actor != body.get("actor_id"):
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger()
        digest = record(ledger, body)
        return JSONResponse(
            _ok("ledger@1.0.0", {"event_type": body["event_type"]}, {"event_hash": digest})
        )

    @app.post("/export/zip")
    def export_zip(request: Request) -> Response:
        if _actor_from_request(request) is None:
            return JSONResponse(_abstain("auth@1.0.0", {}, "auth_required"), status_code=401)
        ledger = open_ledger()
        blob = _zip_bytes(ledger.events())
        return Response(content=blob, media_type="application/zip")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "demo.html")

    return app


def open_ledger() -> Ledger:
    root = Path(os.environ.get("EVIDENCE_HOME", Path.cwd() / "data"))
    path = root / "tenants" / f"{DEMO_TENANT}.sqlite3"
    ledger = Ledger(path, DEMO_TENANT)
    ledger.ensure_actor("author", "human", "author-local")
    ledger.ensure_actor("reviewer", "human", "reviewer-local")
    return ledger


def _zip_bytes(events: list[dict[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("chain.json", json.dumps(events, indent=2))
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


def _token(actor_id: str) -> str:
    mac = hmac.new(_secret().encode(), actor_id.encode(), hashlib.sha256).hexdigest()
    return f"{actor_id}.{mac}"


def _session_actor(request: Request, requested: Any) -> str | None:
    actor = _actor_from_request(request)
    if actor is None:
        return None
    if requested is not None and str(requested) != actor:
        return None
    return actor


def _actor_from_request(request: Request) -> str | None:
    raw = request.cookies.get("el_session", "")
    if "." not in raw:
        return None
    actor_id, mac = raw.rsplit(".", 1)
    expected = hmac.new(_secret().encode(), actor_id.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    if open_ledger().actor_role(actor_id) is None:
        return None
    return actor_id


def _secret() -> str:
    return os.environ.get("EVIDENCE_SESSION_SECRET", "local-demo-session")


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
