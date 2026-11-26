"""Quotations, batch stress dossier, NAFEMS SOL105/GPFORCE audit, FX hedging & EVM router."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method
from evidence_coverage.nafems_audit import (
    audit_abaqus_composite_layup_vs_report,
    audit_gpforce_freebody_equilibrium,
    audit_sol105_buckling_margins,
)
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
from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.fem_parsers import parse_nastran_f06
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse


def build_quotations_router(
    *,
    ok_fn: Callable[[str, Any, Any], dict[str, Any]],
    abstain_fn: Callable[[str, Any, str], dict[str, Any]],
    check_endpoint_access_fn: Callable[..., tuple[str | None, JSONResponse | None]],
    validate_tenant_fn: Callable[[Any], str | None],
    open_ledger_fn: Callable[[str], Any],
    attestation_keypair_fn: Callable[[], tuple[bytes, bytes]],
    now_fn: Callable[[], str],
) -> APIRouter:
    """Create APIRouter for quotation, calibration, CCN, portfolio, FX, EVM & batch stress."""
    router = APIRouter(tags=["quotations"])

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
            created_at=str(body.get("created_at") or now_fn()),
            rfq_id=str(body.get("rfq_id") or "RFQ-COMP-001"),
            customer_name=str(body.get("customer_name") or "Rotorcraft OEM / DOA Client"),
            currency=str(body.get("currency") or "EUR"),
        )

    @router.get("/quotations/catalog")
    def quotation_catalog_endpoint() -> JSONResponse:
        return JSONResponse(ok_fn("quotation_catalog@1.0.0", {}, get_quotation_catalog()))

    @router.post("/quotations/generate")
    def quotation_generate_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("quotation_multiagent@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = check_endpoint_access_fn(
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
            created_at=str(body.get("created_at") or now_fn()),
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
        ledger = open_ledger_fn(tenant_id)
        dossier = run_multiagent_quotation(ledger, spec)
        if dossier.confidence == "abstain":
            abstain_payload = abstain_fn(
                "quotation_multiagent@1.0.0",
                {"rfq_id": spec.rfq_id},
                dossier.abstain_reason or "abstain",
            )
            abstain_payload["decision_status"] = dossier.decision_status
            abstain_payload["event_hashes"] = dossier.event_hashes
            abstain_payload["merkle_root"] = dossier.merkle_root
            return JSONResponse(abstain_payload)
        return JSONResponse(
            ok_fn(
                "quotation_multiagent@1.0.0",
                {"rfq_id": dossier.rfq_id, "quotation_kind": dossier.quotation_kind},
                dossier.to_dict(),
            )
        )

    @router.post("/quotations/sensitivity")
    def quotation_sensitivity_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("quotation_sensitivity@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = check_endpoint_access_fn(
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
            created_at=str(body.get("created_at") or now_fn()),
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
        ledger = open_ledger_fn(tenant_id)
        result = run_whatif_sensitivity(ledger, spec, overrides)
        return JSONResponse(ok_fn("quotation_sensitivity@1.0.0", {"rfq_id": spec.rfq_id}, result))

    @router.get("/quotations/repos-benchmark")
    def quotation_repos_benchmark_endpoint() -> JSONResponse:
        result = QuotationIntelligenceScraper().run_full_harvest(live_network=False)
        return JSONResponse(ok_fn("quotation_scraper@1.0.0", {"mode": "catalog"}, result))

    @router.post("/quotations/scrape-repos")
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
            ok_fn(
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

    @router.get("/quotations/rotorcraft/catalog")
    def rotorcraft_quotation_catalog_endpoint() -> JSONResponse:
        return JSONResponse(ok_fn("rotorcraft_catalog@1.0.0", {}, get_rotorcraft_catalog()))

    @router.post("/quotations/rotorcraft/generate")
    def rotorcraft_quotation_generate_endpoint(
        body: dict[str, Any], request: Request
    ) -> JSONResponse:
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("rotorcraft_quotation@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = check_endpoint_access_fn(
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
            created_at=str(body.get("created_at") or now_fn()),
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
        ledger = open_ledger_fn(tenant_id)
        dossier = run_rotorcraft_department_quotation(ledger, spec)
        if dossier["confidence"] == "abstain":
            abstain_payload = abstain_fn(
                "rotorcraft_quotation@1.0.0",
                {},
                dossier.get("abstain_reason") or "abstain",
            )
            abstain_payload["decision_status"] = dossier["decision_status"]
            abstain_payload["event_hashes"] = dossier["event_hashes"]
            abstain_payload["merkle_root"] = dossier["merkle_root"]
            return JSONResponse(abstain_payload)
        return JSONResponse(
            ok_fn(
                "rotorcraft_quotation@1.0.0",
                {
                    "rfq_id": dossier["rfq_id"],
                    "archetype_id": dossier["archetype"]["archetype_id"],
                    "country_code": dossier["country_profile"]["country_code"],
                },
                dossier,
            )
        )

    @router.post("/quotations/rotorcraft/calibrate-historical")
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
                abstain_fn("rotorcraft_historical_calibration@1.0.0", {}, str(exc)),
                status_code=400,
            )
        return JSONResponse(
            ok_fn(
                "rotorcraft_historical_calibration@1.0.0",
                {"archetype_id": archetype_id, "country_code": country_code},
                payload,
            )
        )

    @router.post("/quotations/rotorcraft/composite-dag")
    def rotorcraft_composite_dag_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation

        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return JSONResponse(
                abstain_fn("composite_rotorcraft_quotation@1.0.0", {}, "invalid_tenant"),
                status_code=400,
            )
        actor_id, auth_err = check_endpoint_access_fn(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return auth_err
        spec = _build_composite_spec(body, tenant_id=tenant_id, actor_id=actor_id)
        ledger = open_ledger_fn(tenant_id)
        dossier = run_composite_rotorcraft_quotation(ledger, spec)
        if dossier["confidence"] == "abstain":
            abstain_payload = abstain_fn(
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
            ok_fn(
                "composite_rotorcraft_quotation@1.0.0",
                {
                    "rfq_id": dossier["rfq_id"],
                    "country_code": dossier["country_profile"]["country_code"],
                    "critical_path": dossier["composite_wbs_dag"]["critical_path_archetypes"],
                },
                dossier,
            )
        )

    @router.post("/quotations/rotorcraft/multiyear-cashflow")
    def rotorcraft_multiyear_cashflow_endpoint(body: dict[str, Any]) -> JSONResponse:
        inputs = dict(body.get("inputs") or body)
        try:
            ran = run_method(
                "aerospace_multiyear_cashflow_learning", inputs, include_intervals=True
            )
        except AbstainError as exc:
            return JSONResponse(
                abstain_fn("aerospace_multiyear_cashflow_learning@1.0.0", inputs, exc.reason),
                status_code=400,
            )
        return JSONResponse(ok_fn("aerospace_multiyear_cashflow_learning@1.0.0", inputs, ran))

    @router.post("/quotations/rotorcraft/idp-deep-inspect")
    def rotorcraft_idp_deep_inspect_endpoint(
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        from evidence_coverage.deep_idp_quotation_extractor import (
            extract_deep_idp_engineering_package,
        )

        req = body or {}
        res = extract_deep_idp_engineering_package(req.get("idp_attachments") or req)
        return JSONResponse(ok_fn("deep_idp_extractor@1.0.0", {}, res))

    @router.post("/quotations/rotorcraft/contract-audit")
    def rotorcraft_contract_audit_endpoint(body: dict[str, Any]) -> JSONResponse:
        from evidence_coverage.contract_clause_auditor import audit_rfq_contract_clauses

        pdf_bytes = base64.b64decode(str(body["pdf_base64"])) if body.get("pdf_base64") else None
        res = audit_rfq_contract_clauses(
            str(body.get("rfq_text") or ""),
            clauses=body.get("clauses") if isinstance(body.get("clauses"), list) else None,
            pdf_bytes=pdf_bytes,
            filename=str(body.get("filename") or "rfq.txt"),
        )
        return JSONResponse(ok_fn("contract_clause_auditor@1.0.0", {}, res))

    def _resolve_quotation_dossier(
        body: dict[str, Any], request: Request, method_tag: str
    ) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation

        if isinstance(body.get("dossier"), dict):
            return body["dossier"], None
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return None, JSONResponse(abstain_fn(method_tag, {}, "invalid_tenant"), status_code=400)
        actor_id, auth_err = check_endpoint_access_fn(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return None, auth_err
        spec = _build_composite_spec(body, tenant_id=tenant_id, actor_id=actor_id)
        dossier = run_composite_rotorcraft_quotation(open_ledger_fn(tenant_id), spec)
        if dossier.get("confidence") == "abstain":
            return (
                None,
                JSONResponse(
                    abstain_fn(method_tag, {}, dossier.get("abstain_reason") or "abstain"),
                    status_code=422,
                ),
            )
        return dossier, None

    @router.post("/quotations/rotorcraft/export-xlsx")
    def rotorcraft_export_xlsx_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.quotation_exporter import export_quotation_xlsx

        dossier, err = _resolve_quotation_dossier(body, request, "quotation_exporter_xlsx@1.0.0")
        if err is not None:
            return err
        assert dossier is not None
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

    @router.post("/quotations/rotorcraft/export-pdf")
    def rotorcraft_export_pdf_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.quotation_exporter import export_quotation_signed_pdf

        dossier, err = _resolve_quotation_dossier(body, request, "quotation_exporter_pdf@1.0.0")
        if err is not None:
            return err
        assert dossier is not None
        priv_pem, pub_pem = attestation_keypair_fn()
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

    @router.post("/quotations/rotorcraft/advanced-calibration")
    def rotorcraft_advanced_calibration_endpoint(
        body: dict[str, Any] | None = None,
    ) -> JSONResponse:
        from evidence_coverage.advanced_quotation_calibration import run_advanced_calibration_suite
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
        return JSONResponse(ok_fn("advanced_quotation_calibration@1.0.0", {}, payload))

    @router.get("/quotations/rotorcraft/erp-template")
    def rotorcraft_erp_template_endpoint(format: str = "xlsx") -> Response:
        from evidence_coverage.advanced_quotation_calibration import export_erp_sap_import_template

        try:
            res = export_erp_sap_import_template(fmt=format)
        except ValueError as exc:
            return JSONResponse(
                abstain_fn("erp_sap_template@1.0.0", {"format": format}, str(exc)),
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
            headers={"Content-Disposition": disposition, "X-AeroRegu-SHA256": res["sha256"]},
        )

    def _resolve_change_order(
        body: dict[str, Any], request: Request, method_tag: str, *, default_reason: str
    ) -> tuple[dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.quotation_change_order import compute_quotation_change_order

        if isinstance(body.get("ccn_dossier"), dict):
            return body["ccn_dossier"], None
        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return None, JSONResponse(abstain_fn(method_tag, {}, "invalid_tenant"), status_code=400)
        actor_id, auth_err = check_endpoint_access_fn(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return None, auth_err
        ledger = open_ledger_fn(tenant_id)
        if isinstance(body.get("baseline_dossier"), dict):
            baseline = body["baseline_dossier"]
        elif isinstance(body.get("baseline_spec"), dict):
            b_spec = _build_composite_spec(
                dict(body["baseline_spec"]), tenant_id=tenant_id, actor_id=actor_id
            )
            baseline = run_composite_rotorcraft_quotation(ledger, b_spec)
        else:
            return (
                None,
                JSONResponse(abstain_fn(method_tag, {}, "missing_baseline"), status_code=400),
            )
        rev_spec = _build_composite_spec(
            dict(body.get("revised_spec") or body), tenant_id=tenant_id, actor_id=actor_id
        )
        ccn = compute_quotation_change_order(
            ledger,
            baseline,
            rev_spec,
            cr_id=str(body.get("cr_id") or "CCN-001"),
            change_reason=str(body.get("change_reason") or default_reason),
            enforce_contract_gate=bool(body.get("enforce_contract_gate", True)),
        )
        return ccn, None

    @router.post("/quotations/rotorcraft/change-order")
    def rotorcraft_change_order_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        ccn, err = _resolve_change_order(
            body,
            request,
            "quotation_change_order@1.0.0",
            default_reason="Scope & schedule change request",
        )
        if err is not None:
            return err
        assert ccn is not None
        if ccn.get("confidence") == "abstain":
            abstain_payload = abstain_fn(
                "quotation_change_order@1.0.0",
                {"cr_id": ccn["cr_id"]},
                ccn.get("abstain_reason") or "abstain",
            )
            abstain_payload["decision_status"] = ccn["decision_status"]
            abstain_payload["contract_delta"] = ccn.get("contract_delta")
            abstain_payload["change_order_merkle_root"] = ccn.get("change_order_merkle_root")
            return JSONResponse(abstain_payload)
        return JSONResponse(
            ok_fn(
                "quotation_change_order@1.0.0",
                {"cr_id": ccn["cr_id"], "baseline_rfq_id": ccn["baseline_rfq_id"]},
                ccn,
            )
        )

    @router.post("/quotations/rotorcraft/change-order/export-xlsx")
    def rotorcraft_change_order_export_xlsx_endpoint(
        body: dict[str, Any], request: Request
    ) -> Response:
        from evidence_coverage.quotation_exporter import export_change_order_xlsx

        ccn, err = _resolve_change_order(
            body, request, "quotation_change_order_xlsx@1.0.0", default_reason="CCN Addendum"
        )
        if err is not None:
            return err
        assert ccn is not None
        if ccn.get("confidence") == "abstain":
            return JSONResponse(
                abstain_fn(
                    "quotation_change_order_xlsx@1.0.0", {}, ccn.get("abstain_reason") or "abstain"
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

    @router.post("/quotations/rotorcraft/change-order/export-pdf")
    def rotorcraft_change_order_export_pdf_endpoint(
        body: dict[str, Any], request: Request
    ) -> Response:
        from evidence_coverage.quotation_exporter import export_change_order_signed_pdf

        ccn, err = _resolve_change_order(
            body, request, "quotation_change_order_pdf@1.0.0", default_reason="CCN Addendum"
        )
        if err is not None:
            return err
        assert ccn is not None
        if ccn.get("confidence") == "abstain":
            return JSONResponse(
                abstain_fn(
                    "quotation_change_order_pdf@1.0.0", {}, ccn.get("abstain_reason") or "abstain"
                ),
                status_code=422,
            )
        priv_pem, pub_pem = attestation_keypair_fn()
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

    def _resolve_portfolio_and_nearshore(
        body: dict[str, Any], request: Request, version: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.portfolio_capacity_leveler import (
            level_portfolio_capacity,
            optimize_portfolio_nearshore_allocation,
        )

        dossiers = list(body.get("dossiers") or [])
        if not dossiers and isinstance(body.get("rfq_specs"), list):
            tenant_id = validate_tenant_fn(body.get("tenant_id"))
            if tenant_id is None:
                return (
                    None,
                    None,
                    JSONResponse(abstain_fn(version, {}, "invalid_tenant"), status_code=400),
                )
            actor_id, auth_err = check_endpoint_access_fn(
                request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
            )
            if auth_err is not None:
                return None, None, auth_err
            ledger = open_ledger_fn(tenant_id)
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
        port_res = level_portfolio_capacity(
            dossiers,
            team_headcount=headcount,
            max_utilization_pct=str(body.get("max_utilization_pct") or "85.000"),
            max_horizon_weeks=int(body.get("max_horizon_weeks") or 104),
        )
        ns_plan = None
        if body.get("optimize_nearshore", True) and dossiers:
            try:
                ns_plan = optimize_portfolio_nearshore_allocation(
                    port_res,
                    onshore_country=str(body.get("onshore_country") or "DE"),
                    nearshore_country=str(body.get("nearshore_country") or "ES"),
                    cve_onshore_only=bool(body.get("cve_onshore_only", True)),
                )
            except ValueError as exc:
                return None, None, JSONResponse(abstain_fn(version, {}, str(exc)), status_code=400)
        return port_res, ns_plan, None

    @router.post("/quotations/rotorcraft/portfolio-capacity")
    def rotorcraft_portfolio_capacity_endpoint(
        body: dict[str, Any], request: Request
    ) -> JSONResponse:
        port_res, ns_plan, err = _resolve_portfolio_and_nearshore(
            body, request, "portfolio_capacity_leveler@1.0.0"
        )
        if err is not None:
            return err
        assert port_res is not None
        payload = {**port_res}
        if ns_plan is not None:
            payload["nearshore_optimization"] = ns_plan
        return JSONResponse(ok_fn("portfolio_capacity_leveler@1.0.0", {}, payload))

    @router.post("/quotations/rotorcraft/portfolio-capacity/export-xlsx")
    def rotorcraft_portfolio_export_xlsx_endpoint(
        body: dict[str, Any], request: Request
    ) -> Response:
        from evidence_coverage.quotation_exporter import export_portfolio_capacity_xlsx

        port_res, ns_plan, err = _resolve_portfolio_and_nearshore(
            body, request, "portfolio_export_xlsx@1.0.0"
        )
        if err is not None:
            return err
        assert port_res is not None
        exported = export_portfolio_capacity_xlsx(port_res, nearshore_plan=ns_plan)
        return Response(
            content=exported["xlsx_bytes"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": 'attachment; filename="portfolio_rcpsp_plan.xlsx"',
                "X-AeroRegu-SHA256": exported["xlsx_sha256"],
                "X-AeroRegu-Formula-Count": str(exported["formula_count"]),
            },
        )

    @router.post("/quotations/rotorcraft/portfolio-capacity/export-pdf")
    def rotorcraft_portfolio_export_pdf_endpoint(
        body: dict[str, Any], request: Request
    ) -> Response:
        from evidence_coverage.quotation_exporter import export_portfolio_capacity_signed_pdf

        port_res, ns_plan, err = _resolve_portfolio_and_nearshore(
            body, request, "portfolio_export_pdf@1.0.0"
        )
        if err is not None:
            return err
        assert port_res is not None
        priv_pem, pub_pem = attestation_keypair_fn()
        exported = export_portfolio_capacity_signed_pdf(
            port_res,
            nearshore_plan=ns_plan,
            private_key_pem=priv_pem,
            public_key_pem=pub_pem,
        )
        return Response(
            content=exported["pdf_bytes"],
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="portfolio_rcpsp_signed.pdf"',
                "X-AeroRegu-SHA256": exported["pdf_sha256"],
                "X-AeroRegu-Merkle-Root": exported["merkle_root"],
            },
        )

    @router.post("/calc/batch-stress-dossier")
    def calc_batch_stress_dossier_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        from evidence_coverage.stress_dossier_packager import build_stress_summary_dossier

        checks = list(body.get("checks") or [])
        if not checks:
            return JSONResponse(
                abstain_fn("stress_dossier@1.0.0", {}, "empty_stress_checks"),
                status_code=400,
            )
        record_to_ledger = bool(body.get("record", False))
        ledger_obj = None
        tenant_id = "demo"
        actor_id = "stress-office"
        if record_to_ledger:
            checked_t = validate_tenant_fn(body.get("tenant_id"))
            if checked_t is None:
                return JSONResponse(
                    abstain_fn("stress_dossier@1.0.0", {}, "invalid_tenant"), status_code=400
                )
            resolved_actor, auth_err = check_endpoint_access_fn(
                request, tenant_id=checked_t, requested_actor=body.get("actor_id")
            )
            if auth_err is not None:
                return auth_err
            tenant_id = checked_t
            actor_id = resolved_actor or "author"
            ledger_obj = open_ledger_fn(tenant_id)
        try:
            res = build_stress_summary_dossier(
                str(body.get("dossier_id") or "STRESS-NOTE-001"),
                checks,
                ledger=ledger_obj,
                tenant_id=tenant_id,
                actor_id=actor_id,
                include_formal_proofs=bool(body.get("include_formal_proofs", True)),
            )
        except (AbstainError, ValueError, KeyError) as exc:
            reason = exc.reason if isinstance(exc, AbstainError) else str(exc)
            return JSONResponse(abstain_fn("stress_dossier@1.0.0", {}, reason), status_code=400)
        return JSONResponse(ok_fn("stress_dossier@1.0.0", {"dossier_id": res["dossier_id"]}, res))

    @router.post("/quotations/rotorcraft/fx-hedging")
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
                abstain_fn("quotation_fx_hedging@1.0.0", {}, str(exc)), status_code=400
            )
        return JSONResponse(ok_fn("quotation_fx_hedging@1.0.0", {}, res))

    def _resolve_evm_and_fx(
        body: dict[str, Any], request: Request, method_tag: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, JSONResponse | None]:
        from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
        from evidence_coverage.composite_dag_quotation import run_composite_rotorcraft_quotation
        from evidence_coverage.quotation_fx_hedging import evaluate_quotation_fx_hedging

        fx_rep = body.get("fx_report") if isinstance(body.get("fx_report"), dict) else None
        if isinstance(body.get("postmortem_report"), dict):
            return body["postmortem_report"], fx_rep, None

        tenant_id = validate_tenant_fn(body.get("tenant_id"))
        if tenant_id is None:
            return (
                None,
                None,
                JSONResponse(abstain_fn(method_tag, {}, "invalid_tenant"), status_code=400),
            )
        actor_id, auth_err = check_endpoint_access_fn(
            request, tenant_id=tenant_id, requested_actor=body.get("actor_id")
        )
        if auth_err is not None:
            return None, None, auth_err
        ledger = open_ledger_fn(tenant_id)
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
                return (
                    None,
                    None,
                    JSONResponse(
                        abstain_fn(
                            method_tag,
                            {},
                            str(baseline.get("abstain_reason") or "baseline_abstain"),
                        ),
                        status_code=400,
                    ),
                )
        try:
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
                created_at=body.get("created_at") or now_fn(),
            )
        except ValueError as exc:
            return None, None, JSONResponse(abstain_fn(method_tag, {}, str(exc)), status_code=400)
        if fx_rep is None and body.get("billing_currency"):
            evm_sum = pm.get("evm_summary") or {}
            fx_rep = evaluate_quotation_fx_hedging(
                quoted_price_eur=evm_sum.get("quoted_selling_price_eur") or "500000",
                cost_eur=evm_sum.get("bac_cost_eur") or "380000",
                billing_currency=str(body.get("billing_currency") or "USD"),
                hedge_ratio_pct=str(body.get("hedge_ratio_pct") or "85.000"),
            )
        return pm, fx_rep, None

    @router.post("/quotations/rotorcraft/evm-postmortem")
    def rotorcraft_evm_postmortem_endpoint(body: dict[str, Any], request: Request) -> JSONResponse:
        pm, _fx_rep, err = _resolve_evm_and_fx(body, request, "bid_actual_postmortem@1.0.0")
        if err is not None:
            return err
        assert pm is not None
        return JSONResponse(ok_fn("bid_actual_postmortem@1.0.0", {}, pm))

    @router.post("/quotations/rotorcraft/evm-postmortem/export-xlsx")
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

    @router.post("/quotations/rotorcraft/evm-postmortem/export-pdf")
    def rotorcraft_evm_export_pdf_endpoint(body: dict[str, Any], request: Request) -> Response:
        from evidence_coverage.quotation_exporter import export_evm_postmortem_signed_pdf

        pm, fx_rep, err = _resolve_evm_and_fx(body, request, "evm_export_pdf@1.0.0")
        if err is not None:
            return err
        assert pm is not None
        priv_pem, pub_pem = attestation_keypair_fn()
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

    @router.post("/nafems/audit-sol105-gpforce")
    def nafems_sol105_gpforce_audit_endpoint(body: dict[str, Any]) -> JSONResponse:
        from evidence_ingest.fem_parsers import parse_abaqus_inp

        f06_text = str(body.get("f06_text") or "")
        abq_text = str(body.get("abaqus_text") or "")
        if not f06_text.strip() and not abq_text.strip():
            return JSONResponse(
                abstain_fn("nafems_sol105_gpforce@1.0.0", {}, "missing_f06_or_abaqus_text"),
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
                    abstain_fn("nafems_sol105_gpforce@1.0.0", {}, exc.reason), status_code=422
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
                    abstain_fn("nafems_sol105_gpforce@1.0.0", {}, exc.reason), status_code=422
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
            ok_fn(
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

    return router
