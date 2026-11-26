"""Sprint 7 engineering router: Stress Dossier, Heavy PDF, Load Envelopes, MoC & Risk."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_ingest.blocks import IngestAbstain
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse


def build_sprint7_engineering_router(
    *,
    ok_fn: Callable[[str, Any, Any], dict[str, Any]],
    abstain_fn: Callable[[str, Any, str], dict[str, Any]],
    check_endpoint_access_fn: Callable[..., tuple[str | None, JSONResponse | None]],
    is_production_mode_fn: Callable[[], bool],
    session_actor_fn: Callable[..., str | None],
    validate_tenant_fn: Callable[[Any], str | None],
    open_ledger_fn: Callable[[str], Any],
    attestation_keypair_fn: Callable[[], tuple[bytes, bytes]],
    decode_body_bytes_fn: Callable[
        [dict[str, Any], str, str], tuple[bytes | None, JSONResponse | None]
    ],
    demo_tenant: str = "demo",
) -> APIRouter:
    """Create APIRouter for Sprint 7 aerospace engineering & commercial frontier endpoints."""
    router = APIRouter(tags=["sprint7-engineering"])

    def _resolve_stress_dossier(
        body: dict[str, Any], request: Request, version: str
    ) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.stress_dossier_packager import build_stress_summary_dossier

        from evidence_api.formal_methods import METHOD_DEFAULT_INPUTS

        if isinstance(body.get("dossier"), dict) and body["dossier"].get("checks_results"):
            return dict(body["dossier"]), None

        checks = list(body.get("checks") or [])
        if not checks:
            checks = [
                {
                    "check_id": "SKID-01",
                    "component_name": "Skid Cross-Tube Aft",
                    "method_id": "cs29_skid_landing_gear_drop_energy",
                    "inputs": dict(METHOD_DEFAULT_INPUTS["cs29_skid_landing_gear_drop_energy"]),
                },
                {
                    "check_id": "TRDS-02",
                    "component_name": "Tail Rotor Drive Shaft",
                    "method_id": "shaft_whirl_critical_speed_screen",
                    "inputs": dict(METHOD_DEFAULT_INPUTS["shaft_whirl_critical_speed_screen"]),
                },
                {
                    "check_id": "FIRE-03",
                    "component_name": "CS 29.1191 Firewall",
                    "method_id": "firewall_thermal_buckling_screen",
                    "inputs": dict(METHOD_DEFAULT_INPUTS["firewall_thermal_buckling_screen"]),
                },
            ]
        ledger_obj = None
        tenant_id = demo_tenant
        actor_id = "stress-office"
        if bool(body.get("record", False)):
            checked_t = validate_tenant_fn(body.get("tenant_id"))
            if checked_t is None:
                return None, JSONResponse(
                    abstain_fn(version, {}, "invalid_tenant"), status_code=400
                )
            resolved_actor, auth_err = check_endpoint_access_fn(
                request, tenant_id=checked_t, requested_actor=body.get("actor_id")
            )
            if auth_err is not None:
                return None, auth_err
            tenant_id = checked_t
            actor_id = str(resolved_actor or "author")
            ledger_obj = open_ledger_fn(tenant_id)
        try:
            dos = build_stress_summary_dossier(
                str(body.get("dossier_id") or "STRESS-NOTE-001"),
                checks,
                ledger=ledger_obj,
                tenant_id=tenant_id,
                actor_id=actor_id,
                include_formal_proofs=bool(body.get("include_formal_proofs", True)),
            )
        except (AbstainError, ValueError, KeyError) as exc:
            reason = exc.reason if isinstance(exc, AbstainError) else str(exc)
            return None, JSONResponse(abstain_fn(version, {}, reason), status_code=400)
        return dos, None

    @router.post("/calc/batch-stress-dossier/export-xlsx")
    def calc_batch_stress_export_xlsx_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.stress_dossier_packager import export_stress_dossier_xlsx

        dos, err = _resolve_stress_dossier(body, request, "stress_dossier_xlsx@1.0.0")
        if err is not None:
            return err
        assert dos is not None
        exported = export_stress_dossier_xlsx(dos)
        did = str(dos.get("dossier_id") or "STRESS-NOTE-001").replace('"', "")
        return Response(
            content=exported["xlsx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{did}_stress_dossier.xlsx"',
                "X-AeroRegu-SHA256": exported["xlsx_sha256"],
                "X-AeroRegu-Formula-Count": str(exported["formula_count"]),
            },
        )

    @router.post("/calc/batch-stress-dossier/export-pdf")
    def calc_batch_stress_export_pdf_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.stress_dossier_packager import export_stress_dossier_signed_pdf

        dos, err = _resolve_stress_dossier(body, request, "stress_dossier_pdf@1.0.0")
        if err is not None:
            return err
        assert dos is not None
        priv_pem, pub_pem = attestation_keypair_fn()
        exported = export_stress_dossier_signed_pdf(
            dos, private_key_pem=priv_pem, public_key_pem=pub_pem
        )
        did = str(dos.get("dossier_id") or "STRESS-NOTE-001").replace('"', "")
        return Response(
            content=exported["pdf_bytes"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{did}_signed_stress_dossier.pdf"',
                "X-AeroRegu-SHA256": exported["pdf_sha256"],
                "X-AeroRegu-Merkle-Root": exported["merkle_root"],
            },
        )

    @router.post("/ingest/heavy-pdf")
    def ingest_heavy_pdf_endpoint(body: dict[str, Any]) -> JSONResponse:
        from evidence_ingest.pdf import ingest_pdf_parallel

        fname = str(body.get("filename") or "heavy_spec.pdf").strip() or "heavy_spec.pdf"
        raw, err = decode_body_bytes_fn(body, "heavy_pdf@1.0.0", fname)
        if err is not None:
            return err
        assert raw is not None
        try:
            res = ingest_pdf_parallel(
                raw,
                source_uri=fname,
                max_workers=int(body.get("max_workers") or 4),
                chunk_pages=int(body.get("chunk_pages") or 20),
            )
        except IngestAbstain as exc:
            return JSONResponse(
                abstain_fn("heavy_pdf@1.0.0", {"filename": fname}, exc.reason),
                status_code=422,
            )
        return JSONResponse(
            ok_fn(
                "heavy_pdf@1.0.0",
                {"filename": fname, "source_hash": res["source_hash"]},
                {
                    "source_uri": res["source_uri"],
                    "source_hash": res["source_hash"],
                    "total_pages": res["total_pages"],
                    "worker_count": res["worker_count"],
                    "pages_per_second": res["pages_per_second"],
                    "heavy_pdf_async": res["heavy_pdf_async"],
                    "verified_pages": res["verified_pages"],
                    "abstained_pages": res["abstained_pages"],
                    "modalities": res["modalities"],
                    "block_count": len(res["blocks"]),
                },
            )
        )

    def _resolve_load_envelope(
        body: dict[str, Any], request: Request, version: str
    ) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.load_envelope_combiner import (
            combine_structural_load_envelopes,
            default_cs29_load_envelope_payload,
        )

        if isinstance(body.get("envelope_report"), dict):
            return body["envelope_report"], None
        defaults = default_cs29_load_envelope_payload()
        env_id = str(body.get("envelope_id") or defaults["envelope_id"])
        subcases = body.get("basic_subcases") or defaults["basic_subcases"]
        combos = body.get("combinations") or defaults["combinations"]
        allowables = body.get("component_allowables") or defaults["component_allowables"]
        record_flag = bool(body.get("record", False))
        ledger_obj = None
        tenant_id = validate_tenant_fn(str(body.get("tenant_id") or demo_tenant)) or demo_tenant
        actor_id = "stress-office"
        if record_flag:
            actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
            if actor is None and is_production_mode_fn():
                return None, JSONResponse(abstain_fn(version, {}, "auth_required"), status_code=401)
            ledger_obj = open_ledger_fn(tenant_id)
            actor_id = actor or "author"
        try:
            rep = combine_structural_load_envelopes(
                env_id,
                subcases,
                combos,
                allowables,
                ledger=ledger_obj,
                tenant_id=tenant_id,
                actor_id=actor_id,
            )
        except (AbstainError, ValueError, KeyError) as exc:
            reason = exc.reason if isinstance(exc, AbstainError) else str(exc)
            return None, JSONResponse(abstain_fn(version, {}, reason), status_code=400)
        return rep, None

    @router.post("/calc/load-envelope/combine")
    def calc_load_envelope_combine_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        rep, err = _resolve_load_envelope(body, request, "load_envelope@1.0.0")
        if err is not None:
            return err
        assert rep is not None
        return JSONResponse(ok_fn("load_envelope@1.0.0", {"envelope_id": rep["envelope_id"]}, rep))

    @router.post("/calc/load-envelope/export-xlsx")
    def calc_load_envelope_xlsx_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.load_envelope_combiner import export_load_envelope_xlsx

        rep, err = _resolve_load_envelope(body, request, "load_envelope_xlsx@1.0.0")
        if err is not None:
            return err
        assert rep is not None
        exported = export_load_envelope_xlsx(rep)
        eid = str(rep.get("envelope_id") or "ENV-CS29").replace('"', "")
        return Response(
            content=exported["xlsx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{eid}_load_envelope.xlsx"',
                "X-AeroRegu-SHA256": exported["xlsx_sha256"],
                "X-AeroRegu-Formula-Count": str(exported["formula_count"]),
            },
        )

    @router.post("/calc/load-envelope/export-pdf")
    def calc_load_envelope_pdf_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.load_envelope_combiner import export_load_envelope_pdf

        rep, err = _resolve_load_envelope(body, request, "load_envelope_pdf@1.0.0")
        if err is not None:
            return err
        assert rep is not None
        priv_pem, pub_pem = attestation_keypair_fn()
        exported = export_load_envelope_pdf(rep, private_key_pem=priv_pem, public_key_pem=pub_pem)
        eid = str(rep.get("envelope_id") or "ENV-CS29").replace('"', "")
        return Response(
            content=exported["pdf_bytes"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{eid}_signed_load_envelope.pdf"',
                "X-AeroRegu-SHA256": exported["pdf_sha256"],
                "X-AeroRegu-Merkle-Root": exported["merkle_root"],
            },
        )

    def _resolve_moc_matrix(
        body: dict[str, Any], request: Request, version: str
    ) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.certification_moc_matrix import build_part21j_moc_matrix

        if isinstance(body.get("moc_matrix"), dict):
            return body["moc_matrix"], None
        program_id = str(body.get("program_id") or "PROG-H145-MOD")
        record_flag = bool(body.get("record", False))
        ledger_obj = None
        tenant_id = validate_tenant_fn(str(body.get("tenant_id") or demo_tenant)) or demo_tenant
        actor_id = "cve-office"
        if record_flag:
            actor = session_actor_fn(request, body.get("actor_id"), tenant_id=tenant_id)
            if actor is None and is_production_mode_fn():
                return None, JSONResponse(abstain_fn(version, {}, "auth_required"), status_code=401)
            ledger_obj = open_ledger_fn(tenant_id)
            actor_id = actor or "author"
        try:
            mat = build_part21j_moc_matrix(
                program_id,
                requirements=body.get("requirements"),
                stress_dossier=body.get("stress_dossier"),
                load_envelope=body.get("load_envelope"),
                fem_audit=body.get("fem_audit"),
                ledger_event_hashes=body.get("ledger_event_hashes"),
                cve_signoffs=body.get("cve_signoffs"),
                active_ecn_revision=str(body.get("active_ecn_revision") or "REV-A"),
                ledger=ledger_obj,
                tenant_id=tenant_id,
                actor_id=actor_id,
            )
        except (AbstainError, ValueError, KeyError) as exc:
            reason = exc.reason if isinstance(exc, AbstainError) else str(exc)
            return None, JSONResponse(abstain_fn(version, {}, reason), status_code=400)
        return mat, None

    @router.post("/certification/moc-matrix")
    def certification_moc_matrix_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        mat, err = _resolve_moc_matrix(body, request, "part21j_moc_matrix@1.0.0")
        if err is not None:
            return err
        assert mat is not None
        return JSONResponse(
            ok_fn("part21j_moc_matrix@1.0.0", {"program_id": mat["program_id"]}, mat)
        )

    @router.post("/certification/moc-matrix/export-xlsx")
    def certification_moc_matrix_xlsx_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.certification_moc_matrix import export_moc_matrix_xlsx

        mat, err = _resolve_moc_matrix(body, request, "part21j_moc_xlsx@1.0.0")
        if err is not None:
            return err
        assert mat is not None
        exported = export_moc_matrix_xlsx(mat)
        pid = str(mat.get("program_id") or "PROG-CS29").replace('"', "")
        return Response(
            content=exported["xlsx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{pid}_moc_matrix.xlsx"',
                "X-AeroRegu-SHA256": exported["xlsx_sha256"],
                "X-AeroRegu-Formula-Count": str(exported["formula_count"]),
            },
        )

    @router.post("/certification/moc-matrix/export-pdf")
    def certification_moc_matrix_pdf_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.certification_moc_matrix import export_moc_matrix_pdf

        mat, err = _resolve_moc_matrix(body, request, "part21j_moc_pdf@1.0.0")
        if err is not None:
            return err
        assert mat is not None
        priv_pem, pub_pem = attestation_keypair_fn()
        exported = export_moc_matrix_pdf(mat, private_key_pem=priv_pem, public_key_pem=pub_pem)
        pid = str(mat.get("program_id") or "PROG-CS29").replace('"', "")
        return Response(
            content=exported["pdf_bytes"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{pid}_signed_moc_matrix.pdf"',
                "X-AeroRegu-SHA256": exported["pdf_sha256"],
                "X-AeroRegu-Merkle-Root": exported["merkle_root"],
            },
        )

    def _resolve_risk_frontier(
        body: dict[str, Any], version: str
    ) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.quotation_risk_frontier import run_quotation_risk_frontier

        if isinstance(body.get("risk_report"), dict):
            return body["risk_report"], None
        try:
            rep = run_quotation_risk_frontier(
                base_cost_eur=body.get("base_cost_eur", "375000"),
                base_quote_price_eur=body.get("base_quote_price_eur", "480000"),
                bid_prep_cost_eur=body.get("bid_prep_cost_eur", "25000"),
                min_margin_floor_pct=body.get("min_margin_floor_pct", "12.00"),
                num_scenarios=int(body.get("num_scenarios", 500)),
                seed=int(body.get("seed", 20261126)),
                risk_drivers=body.get("risk_drivers"),
                market_price_reference_eur=body.get("market_price_reference_eur"),
                price_elasticity=body.get("price_elasticity", "10.0"),
                baseline_dossier=body.get("baseline_dossier"),
            )
        except (AbstainError, ValueError, KeyError) as exc:
            reason = exc.reason if isinstance(exc, AbstainError) else str(exc)
            return None, JSONResponse(abstain_fn(version, {}, reason), status_code=400)
        return rep, None

    @router.post("/quotations/rotorcraft/risk-frontier")
    def quotation_risk_frontier_endpoint(body: dict[str, Any]) -> JSONResponse:
        rep, err = _resolve_risk_frontier(body, "quotation_risk_frontier@1.0.0")
        if err is not None:
            return err
        assert rep is not None
        return JSONResponse(ok_fn("quotation_risk_frontier@1.0.0", {"seed": rep["seed"]}, rep))

    @router.post("/quotations/rotorcraft/risk-frontier/export-xlsx")
    def quotation_risk_frontier_xlsx_endpoint(body: dict[str, Any]) -> Response:
        from evidence_coverage.quotation_risk_frontier import export_risk_frontier_xlsx

        rep, err = _resolve_risk_frontier(body, "quotation_risk_xlsx@1.0.0")
        if err is not None:
            return err
        assert rep is not None
        exported = export_risk_frontier_xlsx(rep)
        return Response(
            content=exported["xlsx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="aeroregu_risk_frontier.xlsx"',
                "X-AeroRegu-SHA256": exported["xlsx_sha256"],
                "X-AeroRegu-Formula-Count": str(exported["formula_count"]),
            },
        )

    @router.post("/quotations/rotorcraft/risk-frontier/export-pdf")
    def quotation_risk_frontier_pdf_endpoint(body: dict[str, Any]) -> Response:
        from evidence_coverage.quotation_risk_frontier import export_risk_frontier_pdf

        rep, err = _resolve_risk_frontier(body, "quotation_risk_pdf@1.0.0")
        if err is not None:
            return err
        assert rep is not None
        priv_pem, pub_pem = attestation_keypair_fn()
        exported = export_risk_frontier_pdf(rep, private_key_pem=priv_pem, public_key_pem=pub_pem)
        return Response(
            content=exported["pdf_bytes"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="aeroregu_signed_risk_frontier.pdf"',
                "X-AeroRegu-SHA256": exported["pdf_sha256"],
                "X-AeroRegu-Merkle-Root": exported["merkle_root"],
            },
        )

    return router
