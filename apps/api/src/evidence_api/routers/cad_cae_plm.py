"""CAD B-Rep, CAE binary/OP2/H5, PLM, NAFEMS BDF diff, allowables & page highlights router."""

from __future__ import annotations

import base64
import hashlib
import re
import tempfile
from collections.abc import Callable
from decimal import InvalidOperation
from pathlib import Path
from typing import Any

from evidence_calc.allowables import (
    allowable_catalog_sha256,
    list_materials,
    lookup_allowable,
)
from evidence_calc.cad_bindings import bind_parameters_to_cards
from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method
from evidence_coverage.collaboration_ecn import (
    CatiaInspectorBridge,
    ExcelStressSheetBridge,
    compute_ecn_revision_diff,
)
from evidence_coverage.nafems_audit import (
    diff_bdf_revisions_and_invalidate,
    run_full_nafems_audit,
)
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
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.orchestrator import record
from evidence_kernel.storage import open_blob_store
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


def build_cad_cae_plm_router(
    *,
    ok_fn: Callable[[str, Any, Any], dict[str, Any]],
    abstain_fn: Callable[[str, Any, str], dict[str, Any]],
    check_endpoint_access_fn: Callable[..., tuple[str | None, JSONResponse | None]],
    session_actor_fn: Callable[..., str | None],
    validate_tenant_fn: Callable[[Any], str | None],
    open_ledger_fn: Callable[[str], Any],
    decode_body_bytes_fn: Callable[
        [dict[str, Any], str, str], tuple[bytes | None, JSONResponse | None]
    ],
    attach_binding_deltas_fn: Callable[[dict[str, Any], dict[str, Any]], None],
    evidence_home_fn: Callable[[], Path],
    now_fn: Callable[[], str],
    ingested_docs_ref: dict[tuple[str, str], dict[str, Any]],
    demo_tenant: str = "demo",
) -> APIRouter:
    """Create APIRouter for CAD/CAE/PLM, NAFEMS audits, integrations & document page views."""
    router = APIRouter(tags=["cad-cae-plm"])
    _cae_meshes: dict[str, dict[str, Any]] = {}
    _cae_element_index: dict[tuple[str, int], dict[str, Any]] = {}

    @router.post("/cad/ingest")
    def cad_ingest(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("cad_ingest@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        filename = str(body.get("filename") or "model.stp")
        records = bool(body.get("record"))
        actor_id = str(body.get("actor_id") or "author")
        if records:
            session_actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
            if session_actor is None:
                return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
            actor_id = session_actor

        raw, err = decode_body_bytes_fn(body, "cad_ingest@1.0.0", filename)
        if err is not None or raw is None:
            return err or JSONResponse(
                abstain_fn("cad_ingest@1.0.0", {"filename": filename}, "missing_document_content"),
                status_code=400,
            )
        try:
            parsed = ingest_bytes(raw, filename)
        except IngestAbstain as exc:
            return JSONResponse(abstain_fn("cad_ingest@1.0.0", {"filename": filename}, exc.reason))
        cad_cae = parsed.get("cad_cae")
        if not isinstance(cad_cae, dict):
            return JSONResponse(
                abstain_fn("cad_ingest@1.0.0", {"filename": filename}, "not_cad_cae_media")
            )

        auto_run = bool(body.get("auto_run", True))
        bindings = bind_parameters_to_cards(
            list(cad_cae.get("parameters") or []),
            formulas=list(cad_cae.get("formulas") or []),
            auto_run=auto_run,
        )
        stated_by_method = body.get("stated_outputs")
        if isinstance(stated_by_method, dict):
            attach_binding_deltas_fn(bindings, stated_by_method)

        recorded_hash = ""
        if records:
            ledger = open_ledger_fn(tenant_id)
            created_at = str(body.get("created_at") or now_fn())
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
            ok_fn(
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

    @router.post("/cad/bind")
    def cad_bind(body: dict[str, Any]) -> JSONResponse:
        parameters = body.get("parameters")
        if not isinstance(parameters, list):
            return JSONResponse(
                abstain_fn("cad_bind@1.0.0", {}, "missing_parameters"), status_code=400
            )
        formulas = body.get("formulas") if isinstance(body.get("formulas"), list) else None
        auto_run = bool(body.get("auto_run", True))
        bindings = bind_parameters_to_cards(parameters, formulas=formulas, auto_run=auto_run)
        stated_by_method = body.get("stated_outputs")
        if isinstance(stated_by_method, dict):
            attach_binding_deltas_fn(bindings, stated_by_method)
        return JSONResponse(
            ok_fn(
                "cad_bind@1.0.0",
                {"parameter_count": str(len(parameters)), "auto_run": auto_run},
                bindings,
            )
        )

    @router.post("/cae/mesh/{model_id}")
    def register_cae_mesh(model_id: str, body: dict[str, Any], request: Request) -> JSONResponse:
        checked = validate_tenant_fn(str(body.get("tenant_id", demo_tenant)))
        if checked is None:
            return JSONResponse(abstain_fn("cae@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(
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
            ok_fn(
                "cae@1.0.0",
                {"tenant_id": checked, "model_id": model_id},
                {"model_id": model_id, "element_count": len(elements)},
            )
        )

    @router.get("/cae/mesh/{model_id}")
    def get_cae_mesh(
        model_id: str, request: Request, tenant_id: str = demo_tenant, pid: int | None = None
    ) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(abstain_fn("cae@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(request, tenant_id=checked)
        if auth_err is not None:
            return auth_err
        mesh = _cae_meshes.get(f"{checked}:{model_id}")
        if mesh is None:
            return JSONResponse(
                abstain_fn("cae@1.0.0", {"model_id": model_id}, "cae_mesh_not_found"),
                status_code=404,
            )
        if pid is not None:
            filtered = [e for e in mesh["elements"] if int(e.get("pid", 0)) == pid]
            out = {**mesh, "elements": filtered, "element_count": len(filtered), "pid_filter": pid}
        else:
            out = mesh
        return JSONResponse(ok_fn("cae@1.0.0", {"tenant_id": checked, "model_id": model_id}, out))

    @router.get("/cae/element/{element_id}/evidence")
    def get_cae_element_evidence(
        element_id: int, request: Request, tenant_id: str = demo_tenant
    ) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(abstain_fn("cae@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(request, tenant_id=checked)
        if auth_err is not None:
            return auth_err
        rec = _cae_element_index.get((checked, int(element_id)))
        if rec is None:
            return JSONResponse(
                abstain_fn("cae@1.0.0", {"element_id": element_id}, "element_not_indexed"),
                status_code=404,
            )
        return JSONResponse(
            ok_fn("cae@1.0.0", {"tenant_id": checked, "element_id": element_id}, rec)
        )

    @router.post("/plm/webhook/ecn")
    def plm_webhook_ecn(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_ingest.plm_connectors import apply_ecn_selective_invalidation_to_ledger

        checked = validate_tenant_fn(str(body.get("tenant_id", demo_tenant)))
        if checked is None:
            return JSONResponse(abstain_fn("plm@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        ledger = open_ledger_fn(checked)
        plan = apply_ecn_selective_invalidation_to_ledger(
            ledger,
            ecn_diff=dict(body.get("ecn_diff") or {}),
            all_cells=list(body.get("cells") or []),
        )
        return JSONResponse(ok_fn("plm@1.0.0", {"tenant_id": checked}, plan))

    @router.post("/plm/sync")
    def plm_sync(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_ingest.plm_connectors import (
            MockPLMServerTransport,
            PLMConnectorError,
            build_plm_connector,
        )

        checked = validate_tenant_fn(str(body.get("tenant_id", demo_tenant)))
        if checked is None:
            return JSONResponse(abstain_fn("plm@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        system = str(body.get("system", "3dexperience")).lower()
        if system not in {"3dexperience", "teamcenter", "windchill"}:
            return JSONResponse(
                abstain_fn("plm@1.0.0", {}, "unsupported_plm_system"), status_code=400
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
            return JSONResponse(ok_fn("plm@1.0.0", {"tenant_id": checked}, bom))
        except PLMConnectorError as exc:
            return JSONResponse(
                abstain_fn("plm@1.0.0", {"system": system}, str(exc)), status_code=503
            )
        finally:
            conn.close()

    @router.post("/plm/writeback")
    def plm_writeback(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_ingest.plm_connectors import (
            MockPLMServerTransport,
            PLMConnectorError,
            build_plm_connector,
        )

        checked = validate_tenant_fn(str(body.get("tenant_id", demo_tenant)))
        if checked is None:
            return JSONResponse(abstain_fn("plm@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        ledger = open_ledger_fn(checked)
        system = str(body.get("system", "3dexperience")).lower()
        if system not in {"3dexperience", "teamcenter", "windchill"}:
            return JSONResponse(
                abstain_fn("plm@1.0.0", {}, "unsupported_plm_system"), status_code=400
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
            return JSONResponse(ok_fn("plm@1.0.0", {"tenant_id": checked}, wb))
        except PLMConnectorError as exc:
            return JSONResponse(
                abstain_fn("plm@1.0.0", {"system": system}, str(exc)), status_code=503
            )
        finally:
            conn.close()

    @router.post("/nafems/audit")
    def nafems_audit_endpoint(body: dict[str, Any]) -> JSONResponse:
        bdf_text = str(body.get("bdf_text") or "")
        if not bdf_text.strip():
            return JSONResponse(
                abstain_fn("nafems_audit@1.0.0", {}, "missing_bdf_text"), status_code=400
            )
        bdf_bytes = bdf_text.encode("utf-8")
        bdf_hash = hashlib.sha256(bdf_bytes).hexdigest()
        try:
            bdf_parsed = parse_nastran_bdf(bdf_bytes, bdf_hash, unit_system=body.get("unit_system"))
        except IngestAbstain as exc:
            return JSONResponse(abstain_fn("nafems_audit@1.0.0", {}, exc.reason), status_code=422)

        f06_parsed: dict[str, Any] | None = None
        f06_hash = ""
        f06_text = str(body.get("f06_text") or "")
        if f06_text.strip():
            f06_bytes = f06_text.encode("utf-8")
            f06_hash = hashlib.sha256(f06_bytes).hexdigest()
            try:
                f06_parsed = parse_nastran_f06(f06_bytes, f06_hash)
            except IngestAbstain as exc:
                return JSONResponse(
                    abstain_fn("nafems_audit@1.0.0", {}, exc.reason), status_code=422
                )

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
                abstain_fn(
                    "nafems_audit@1.0.0", {"bdf_sha256": bdf_hash}, str(res["abstain_reason"])
                ),
                status_code=422,
            )
        return JSONResponse(ok_fn("nafems_audit@1.0.0", {"bdf_sha256": bdf_hash}, res))

    @router.post("/nafems/bdf-diff")
    def nafems_bdf_diff_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("nafems_diff@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
        if actor is None:
            return JSONResponse(abstain_fn("auth@1.0.0", {}, "auth_required"), status_code=401)
        rev_a_text = str(body.get("rev_a_bdf_text") or "")
        rev_b_text = str(body.get("rev_b_bdf_text") or "")
        if not rev_a_text.strip() or not rev_b_text.strip():
            return JSONResponse(
                abstain_fn("nafems_diff@1.0.0", {}, "missing_bdf_text"), status_code=400
            )
        try:
            a_bytes = rev_a_text.encode("utf-8")
            b_bytes = rev_b_text.encode("utf-8")
            bdf_a = parse_nastran_bdf(a_bytes, hashlib.sha256(a_bytes).hexdigest())
            bdf_b = parse_nastran_bdf(b_bytes, hashlib.sha256(b_bytes).hexdigest())
        except IngestAbstain as exc:
            return JSONResponse(abstain_fn("nafems_diff@1.0.0", {}, exc.reason), status_code=422)

        invalidate = bool(body.get("invalidate_cells", True))
        ledger = open_ledger_fn(tenant_id) if invalidate else None
        res = diff_bdf_revisions_and_invalidate(
            rev_a_bdf=bdf_a,
            rev_b_bdf=bdf_b,
            ledger=ledger,
            actor_id=actor,
            created_at=str(body.get("created_at") or now_fn()),
        )
        return JSONResponse(ok_fn("nafems_diff@1.0.0", {"tenant_id": tenant_id}, res))

    @router.post("/ecn/diff")
    def ecn_diff_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(abstain_fn("ecn_diff@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        rev_a = body.get("rev_a")
        rev_b = body.get("rev_b")
        if not isinstance(rev_a, dict) or not isinstance(rev_b, dict):
            return JSONResponse(
                abstain_fn("ecn_diff@1.0.0", {}, "missing_ecn_revisions"), status_code=400
            )
        ecn_id = str(body.get("ecn_id") or "ECN-2026-001")
        diff_res = compute_ecn_revision_diff(rev_a, rev_b, ecn_id=ecn_id)
        return JSONResponse(ok_fn("ecn_diff@1.0.0", {"ecn_id": ecn_id}, diff_res))

    @router.post("/integrations/excel/sync")
    def excel_bridge_sync(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("excel_sync@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = check_endpoint_access_fn(
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
                abstain_fn("excel_sync@1.0.0", {"method_id": imported["method_id"]}, exc.reason),
                status_code=400,
            )
        ledger = open_ledger_fn(tenant_id)
        stamp = ExcelStressSheetBridge.export_verification_stamp(
            body,
            calc_result=calc_out,
            merkle_root=ledger.merkle_root(),
            event_hash=ledger.head_hash(),
        )
        return JSONResponse(
            ok_fn(
                "excel_sync@1.0.0",
                {"workbook_id": imported["workbook_id"], "method_id": imported["method_id"]},
                {"imported": imported, "calculation": calc_out, "stamp": stamp},
            )
        )

    @router.post("/integrations/catia/selection")
    def catia_selection_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("catia_inspector@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = check_endpoint_access_fn(
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
        return JSONResponse(
            ok_fn("catia_inspector@1.0.0", {"part_number": ctx["part_number"]}, ctx)
        )

    @router.get("/calc/materials")
    def calc_materials_endpoint() -> JSONResponse:
        mats = list_materials()
        cat_hash = allowable_catalog_sha256()
        return JSONResponse(
            ok_fn(
                "allowables@1.0.0",
                {"catalog_sha256": cat_hash},
                {"materials": mats, "catalog_sha256": cat_hash},
            )
        )

    @router.post("/calc/allowables")
    def calc_allowables_endpoint(body: dict[str, Any]) -> JSONResponse:
        mat_id = str(body.get("material_id") or "").strip()
        if not mat_id:
            return JSONResponse(
                abstain_fn("allowables@1.0.0", {}, "missing_material_id"), status_code=400
            )
        try:
            res = lookup_allowable(
                mat_id,
                basis=str(body.get("basis") or "A"),
                property_name=str(body.get("property_name") or "fty_mpa"),
                thickness_mm=str(body.get("thickness_mm") or "10"),
                temp_c=str(body.get("temp_c") or "23"),
                environment=str(body.get("environment") or "RTD"),
                include_intervals=bool(body.get("include_intervals", False)),
                temp_uncertainty_c=str(body.get("temp_uncertainty_c") or "0"),
                thickness_uncertainty_mm=str(body.get("thickness_uncertainty_mm") or "0"),
            )
        except (AbstainError, InvalidOperation, ValueError) as exc:
            reason = exc.reason if isinstance(exc, AbstainError) else "invalid_allowable_input"
            return JSONResponse(
                abstain_fn("allowables@1.0.0", {"material_id": mat_id}, reason),
                status_code=400,
            )
        return JSONResponse(
            ok_fn(
                "allowables@1.0.0", {"material_id": res["material_id"], "basis": res["basis"]}, res
            )
        )

    @router.post("/cad/brep/analyze")
    def cad_brep_analyze_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        checked = validate_tenant_fn(body.get("tenant_id"))
        if checked is None:
            return JSONResponse(abstain_fn("cad_brep@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        filename = str(body.get("filename") or "assembly.step")
        raw, err = decode_body_bytes_fn(body, "cad_brep@1.0.0", filename)
        if err is not None or raw is None:
            return err or JSONResponse(
                abstain_fn("cad_brep@1.0.0", {"filename": filename}, "missing_step_content"),
                status_code=400,
            )
        source_hash = hashlib.sha256(raw).hexdigest()
        try:
            density = float(body.get("default_density_kg_m3") or 2810.0)
        except (TypeError, ValueError):
            return JSONResponse(
                abstain_fn("cad_brep@1.0.0", {"filename": filename}, "invalid_density"),
                status_code=400,
            )
        try:
            res = analyze_step_brep(raw, source_hash, default_density_kg_m3=density)
        except IngestAbstain as exc:
            return JSONResponse(
                abstain_fn("cad_brep@1.0.0", {"filename": filename}, exc.reason),
                status_code=400,
            )
        return JSONResponse(
            ok_fn(
                "cad_brep@1.0.0",
                {"filename": filename, "source_hash": source_hash},
                {"source_hash": source_hash, **res},
            )
        )

    @router.post("/cae/binary/parse")
    def cae_binary_parse_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        checked = validate_tenant_fn(body.get("tenant_id"))
        if checked is None:
            return JSONResponse(
                abstain_fn("cae_binary@1.0.0", {}, "invalid_tenant"), status_code=400
            )
        _, auth_err = check_endpoint_access_fn(
            request, tenant_id=checked, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err

        raw_path = body.get("file_path")
        filename = str(body.get("filename") or "results.op2")
        source_hash = str(body.get("source_hash") or "").strip() or None
        use_sandbox = bool(body.get("sandbox", False))
        try:
            if raw_path is not None:
                candidate = Path(str(raw_path)).resolve()
                allowed_roots = (
                    evidence_home_fn().resolve(),
                    Path(tempfile.gettempdir()).resolve(),
                )
                if not any(candidate.is_relative_to(root) for root in allowed_roots):
                    return JSONResponse(
                        abstain_fn(
                            "cae_binary@1.0.0",
                            {"file_path": str(raw_path)},
                            "path_outside_allowed_roots",
                        ),
                        status_code=403,
                    )
                if not candidate.is_file():
                    return JSONResponse(
                        abstain_fn(
                            "cae_binary@1.0.0", {"file_path": str(raw_path)}, "file_not_found"
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
                raw, err = decode_body_bytes_fn(body, "cae_binary@1.0.0", filename)
                if err is not None or raw is None:
                    return err or JSONResponse(
                        abstain_fn(
                            "cae_binary@1.0.0", {"filename": filename}, "missing_cae_content"
                        ),
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
                abstain_fn("cae_binary@1.0.0", {"filename": filename}, exc.reason), status_code=400
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
            el_rec = {
                "element_id": eid,
                "pid": pid,
                "element_type": et,
                "nodes": nids,
                "subcase_id": int(elem_sub_map.get(eid, 1)),
                "ms_min": str(round(float(elem_ms_map.get(eid, 0.25)), 4)),
                "von_mises_mpa": str(round(float(elem_vm_map.get(eid, 120.0)), 3)),
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
            ok_fn(
                "cae_binary@1.0.0",
                {"tenant_id": checked, "model_id": model_id, "filename": filename},
                parsed_clean,
            )
        )

    @router.get("/ingest/document/{doc_id}/page/{page_no}")
    def get_ingested_document_page(
        doc_id: str, page_no: int, request: Request, tenant_id: str = demo_tenant
    ) -> JSONResponse:
        checked = validate_tenant_fn(tenant_id)
        if checked is None:
            return JSONResponse(abstain_fn("ingest@1.0.0", {}, "invalid_tenant"), status_code=400)
        _, auth_err = check_endpoint_access_fn(request, tenant_id=checked)
        if auth_err is not None:
            return auth_err
        if page_no < 1:
            return JSONResponse(
                abstain_fn("ingest@1.0.0", {"page_no": page_no}, "invalid_page_number"),
                status_code=400,
            )

        doc_entry = ingested_docs_ref.get((checked, doc_id))
        source_hash = doc_entry["source_hash"] if doc_entry else doc_id
        raw_pdf: bytes | None = None
        if re.fullmatch(r"[0-9a-f]{64}", source_hash):
            try:
                candidate = open_blob_store(evidence_home_fn()).get_blob(source_hash)
                if candidate.startswith(b"%PDF"):
                    raw_pdf = candidate
            except Exception:
                raw_pdf = None

        if doc_entry is None and raw_pdf is None:
            return JSONResponse(
                abstain_fn("ingest@1.0.0", {"doc_id": doc_id}, "document_not_found"),
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
                            abstain_fn(
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
            ok_fn(
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

    return router
