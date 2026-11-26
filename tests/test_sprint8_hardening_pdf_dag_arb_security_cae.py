"""Sprint 8 verifiable hardening tests across PDF layout, Part 21J DAG, Arb intervals,
metallic ETW physics, EMV interior optimum, Cockpit UI, prod auth gate, real OP2/NURBS scanners,
extracted routers, and compact MCP profile.
"""

from __future__ import annotations

import struct
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from evidence_api.app import MAX_INGEST_BYTES, _token, create_app
from evidence_api.mcp_server import MCP_COMPACT_TOOLS, handle_mcp_message
from evidence_calc.allowables import lookup_allowable
from evidence_calc.registry import CARD_CONSOLIDATION_MAP, list_cards, run_method
from evidence_coverage.certification_moc_matrix import (
    build_part21j_moc_matrix,
    export_moc_matrix_pdf,
)
from evidence_coverage.composite_dag_quotation import (
    CompositeRotorcraftQuotationSpec,
    run_composite_rotorcraft_quotation,
)
from evidence_coverage.enterprise_kms_airgap import (
    AWSKMSAdapter,
    PKCS11HSMBridge,
    WebAuthnStepUpManager,
)
from evidence_coverage.load_envelope_combiner import (
    combine_structural_load_envelopes,
    default_cs29_load_envelope_payload,
    export_load_envelope_pdf,
)
from evidence_coverage.quotation_exporter import export_quotation_signed_pdf
from evidence_coverage.quotation_risk_frontier import (
    export_risk_frontier_pdf,
    run_quotation_risk_frontier,
)
from evidence_coverage.stress_dossier_packager import (
    build_stress_summary_dossier,
    export_stress_dossier_signed_pdf,
)
from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.cad_brep import analyze_step_with_ocp_or_polyhedral
from evidence_ingest.cae_binary import (
    detect_cae_binary_format,
    inspect_nastran_op2_fortran_blocks,
    parse_nastran_op2_file,
)
from evidence_kernel.ledger import Ledger
from evidence_kernel.paths import repo_root
from fastapi.testclient import TestClient


def _test_keypair() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _assert_corporate_pdf_clean(pdf_bytes: bytes) -> None:
    import pymupdf

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    assert doc.page_count >= 1
    assert doc.embfile_count() >= 1
    for p_idx in range(doc.page_count):
        page = doc[p_idx]
        text = page.get_text("text")
        assert text.strip(), f"empty text on page {p_idx + 1}"
        # Ensure QR / signature images never overlap body text blocks
        blocks = page.get_text("blocks")
        for img in page.get_image_info(xrefs=True):
            ix0, iy0, ix1, iy1 = img["bbox"]
            for blk in blocks:
                bx0, by0, bx1, by1, btext, *_ = blk
                if not str(btext).strip():
                    continue
                inter_x = max(0.0, min(ix1, bx1) - max(ix0, bx0))
                inter_y = max(0.0, min(iy1, by1) - max(iy0, by0))
                assert inter_x * inter_y < 120.0, (
                    f"image overlaps text block on page {p_idx + 1}: {btext!r}"
                )
    doc.close()


def test_phase1a_corporate_pdf_exporters_layout_and_dsse(tmp_path: Path) -> None:
    priv_pem, pub_pem = _test_keypair()
    ledger = Ledger(tmp_path / "pdf.db", tenant_id="sprint8")
    spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-SPRINT8-PDF",
        rfq_text="CS-29 HEMS rescue hoist STC",
        archetype_ids=(
            "Q-DES-02",
            "Q-DES-04",
            "Q-STR-01",
            "Q-STR-02",
            "Q-STR-03",
            "Q-FDT-01",
            "Q-TST-01",
            "Q-DOA-02",
        ),
        country_code="ES",
        unit_count=3,
    )
    dossier = run_composite_rotorcraft_quotation(ledger, spec)
    pdf1 = export_quotation_signed_pdf(dossier, private_key_pem=priv_pem, public_key_pem=pub_pem)
    _assert_corporate_pdf_clean(pdf1["pdf_bytes"])

    stress = build_stress_summary_dossier(
        "STRESS-SPRINT8",
        [
            {
                "check_id": "SKID-01",
                "component_name": "Skid Aft Cross-Tube",
                "method_id": "cs29_skid_landing_gear_drop_energy",
                "inputs": {
                    "gross_weight_kg": "2800",
                    "drop_height_m": "0.330",
                    "rotor_lift_fraction": "0.667",
                    "vertical_stroke_m": "0.220",
                    "gear_efficiency_eta": "0.750",
                    "cross_tube_od_mm": "76.0",
                    "cross_tube_wall_mm": "6.0",
                    "cantilever_arm_mm": "420.0",
                    "yield_allowable_mpa": "441.0",
                    "safety_factor": "1.000",
                },
                "material_lookup": {
                    "target_field": "yield_allowable_mpa",
                    "material_id": "AL-7075-T651",
                    "basis": "A",
                    "temp_c": "50",
                    "temp_uncertainty_c": "5",
                },
            }
        ],
    )
    pdf2 = export_stress_dossier_signed_pdf(
        stress, private_key_pem=priv_pem, public_key_pem=pub_pem
    )
    _assert_corporate_pdf_clean(pdf2["pdf_bytes"])

    env_payload = default_cs29_load_envelope_payload()
    env_rep = combine_structural_load_envelopes(
        "ENV-SPRINT8",
        env_payload["basic_subcases"],
        env_payload["combinations"],
        env_payload["component_allowables"],
    )
    pdf3 = export_load_envelope_pdf(env_rep, private_key_pem=priv_pem, public_key_pem=pub_pem)
    _assert_corporate_pdf_clean(pdf3["pdf_bytes"])

    moc = build_part21j_moc_matrix("PROG-SPRINT8", stress_dossier=stress, load_envelope=env_rep)
    pdf4 = export_moc_matrix_pdf(moc, private_key_pem=priv_pem, public_key_pem=pub_pem)
    _assert_corporate_pdf_clean(pdf4["pdf_bytes"])

    risk = run_quotation_risk_frontier()
    pdf5 = export_risk_frontier_pdf(risk, private_key_pem=priv_pem, public_key_pem=pub_pem)
    _assert_corporate_pdf_clean(pdf5["pdf_bytes"])


def test_phase1b_dag_part21j_precedence_and_parallelism(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "dag.db", tenant_id="sprint8-dag")
    spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-DAG-8",
        rfq_text="CS-29 HEMS modification",
        archetype_ids=(
            "Q-DES-02",
            "Q-DES-04",
            "Q-STR-01",
            "Q-STR-02",
            "Q-STR-03",
            "Q-FDT-01",
            "Q-TST-01",
            "Q-DOA-02",
        ),
    )
    dossier = run_composite_rotorcraft_quotation(ledger, spec)
    dag = dossier["composite_wbs_dag"]
    edges = {(e["from"], e["to"]) for e in dag["edges"]}
    assert ("Q-TST-01", "Q-DOA-02") in edges
    assert ("Q-DOA-02", "Q-TST-01") not in edges
    assert ("Q-DES-04", "Q-STR-01") not in edges
    assert ("Q-STR-03", "Q-TST-01") in edges
    assert dag["critical_path_archetypes"][-1] == "Q-DOA-02"
    by_id = {n["archetype_id"]: n for n in dag["nodes"]}
    assert Decimal(by_id["Q-FDT-01"]["early_start_week"]) < Decimal(
        by_id["Q-DOA-02"]["early_finish_week"]
    )
    assert ("Q-FDT-01", "Q-DOA-02") in edges
    # After Phase 1B fix, Q-FDT-01 and Q-TST-01 start in parallel after Q-STR-03 and feed Q-DOA-02
    assert Decimal(by_id["Q-FDT-01"]["early_start_week"]) == Decimal(
        by_id["Q-TST-01"]["early_start_week"]
    )


def test_phase1c_arb_interval_propagation_from_material_lookup() -> None:
    base_inputs = {
        "gross_weight_kg": "2800",
        "drop_height_m": "0.330",
        "rotor_lift_fraction": "0.667",
        "vertical_stroke_m": "0.220",
        "gear_efficiency_eta": "0.750",
        "cross_tube_od_mm": "76.0",
        "cross_tube_wall_mm": "6.0",
        "cantilever_arm_mm": "420.0",
        "yield_allowable_mpa": "441.0",
        "safety_factor": "1.000",
    }
    tight = run_method(
        "cs29_skid_landing_gear_drop_energy",
        {
            **base_inputs,
            "material_lookup": {
                "target_field": "yield_allowable_mpa",
                "material_id": "AL-7075-T651",
                "basis": "A",
                "temp_c": "85",
                "temp_uncertainty_c": "0",
            },
        },
        include_intervals=True,
    )
    wide = run_method(
        "cs29_skid_landing_gear_drop_energy",
        {
            **base_inputs,
            "material_lookup": {
                "target_field": "yield_allowable_mpa",
                "material_id": "AL-7075-T651",
                "basis": "A",
                "temp_c": "85",
                "temp_uncertainty_c": "15",
            },
        },
        include_intervals=True,
    )
    ms_wide = wide["exact_intervals"]["margin_of_safety"]
    ms_tight = tight["exact_intervals"]["margin_of_safety"]
    assert ms_wide["propagated_input_uncertainty"] is True
    assert "yield_allowable_mpa" in ms_wide["input_uncertainty_sources"]
    wide_span = Decimal(ms_wide["upper"]) - Decimal(ms_wide["lower"])
    tight_span = Decimal(ms_tight["upper"]) - Decimal(ms_tight["lower"])
    assert wide_span > tight_span


def test_phase1d_metallic_etw_physics_and_provenance_notice() -> None:
    al_etw = lookup_allowable("AL-7075-T651", temp_c="24", environment="ETW")
    al_rtd = lookup_allowable("AL-7075-T651", temp_c="24", environment="RTD")
    assert al_etw["moisture_applicable"] is False
    assert Decimal(al_etw["knockdown_factor"]) == Decimal("1")
    assert al_etw["allowable_value_mpa"] == al_rtd["allowable_value_mpa"]
    assert al_etw["data_provenance_notice"] == "SCREENING_TEXTBOOK_REFERENCE_NOT_LICENSED_MMPDS_DB"

    cfrp_etw = lookup_allowable("IM7-8552-UD", temp_c="24", environment="ETW")
    cfrp_rtd = lookup_allowable("IM7-8552-UD", temp_c="24", environment="RTD")
    assert cfrp_etw["moisture_applicable"] is True
    assert Decimal(cfrp_etw["allowable_value_mpa"]) < Decimal(cfrp_rtd["allowable_value_mpa"])


def test_phase1e_emv_interior_optimum() -> None:
    rep = run_quotation_risk_frontier()
    rec = rep["recommended_bid"]
    assert rec["optimum_location"] == "INTERIOR_MAXIMUM"
    assert rep["formal_margin_floor_proof"]["status"] == "PROVED_UNSAT"
    frontier = rep["pareto_frontier"]
    rec_indices = [idx for idx, row in enumerate(frontier) if row["recommended_max_emv"]]
    assert len(rec_indices) == 1
    assert 0 < rec_indices[0] < len(frontier) - 1


def test_phase1f_cockpit_ui_and_sync_contracts() -> None:
    root = repo_root()
    demo_html = (root / "apps" / "api" / "src" / "evidence_api" / "static" / "demo.html").read_text(
        encoding="utf-8"
    )
    cockpit_js = (
        root / "apps" / "api" / "src" / "evidence_api" / "static" / "quotation_cockpit.js"
    ).read_text(encoding="utf-8")

    assert "Session: anonymous" not in demo_html
    assert "Sesión local (Demo)" in demo_html
    assert "grid-template-columns: minmax(0, 1fr);" in demo_html
    assert 'id="quote-stress-checks-json"' in demo_html
    assert 'id="quote-env-payload-json"' in demo_html
    assert 'id="quote-moc-reqs-json"' in demo_html
    assert "function syncInspectorDock" in demo_html
    assert "window.syncInspectorDock" in cockpit_js


def test_phase2_prod_auth_default_deny_and_honest_adapters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "prod_home"))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_PRODUCTION", "1")
    monkeypatch.setenv("EVIDENCE_AUTHOR_PASSWORD", "ProdAuthor!Pass123")
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    assert (
        client.post(
            "/ingest/document",
            json={"filename": "huge.txt", "content_text": "x" * (MAX_INGEST_BYTES + 8)},
        ).status_code
        == 413
    )

    for path in (
        "/calc/batch-stress-dossier",
        "/calc/load-envelope/combine",
        "/certification/moc-matrix",
        "/quotations/rotorcraft/risk-frontier",
        "/security/sbom-airgap-audit",
    ):
        resp = client.post(path, json={})
        assert resp.status_code == 401, f"expected 401 on {path}, got {resp.status_code}"

    # Authenticated request succeeds
    tok = _token("author", "demo", ttl_seconds=600)
    auth_resp = client.post(
        "/quotations/rotorcraft/risk-frontier",
        headers={"Authorization": f"Bearer {tok}"},
        json={},
    )
    assert auth_resp.status_code == 200
    assert auth_resp.json()["result"]["recommended_bid"]["optimum_location"] == "INTERIOR_MAXIMUM"

    # Honest emulator labels
    hsm = PKCS11HSMBridge()
    assert hsm.backend_mode == "software_hsm_emulator"
    assert hsm.sign_dsse({"ok": True})["backend_mode"] == "software_hsm_emulator"

    kms = AWSKMSAdapter("arn:aws:kms:eu-central-1:123456789012:key/demo")
    assert kms.backend_mode == "software_kms_emulator"

    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    mgr = WebAuthnStepUpManager()
    assert mgr.verification_mode == "in_memory_ed25519_stepup_emulator"
    mgr.register_user_credential(user_id="cve-1", credential_id="cred-1", public_key_pem=pub_pem)
    opts = mgr.generate_reauth_options(user_id="cve-1")
    import base64

    sig = base64.b64encode(priv.sign(opts["challenge"].encode("utf-8"))).decode("ascii")
    ver = mgr.verify_reauth_assertion(
        active_user_id="cve-1",
        credential_id="cred-1",
        challenge=opts["challenge"],
        signature_b64=sig,
    )
    assert ver["verified"] is True
    assert ver["verification_mode"] == "in_memory_ed25519_stepup_emulator"


def _fortran_rec(payload: bytes) -> bytes:
    marker = struct.pack("<I", len(payload))
    return marker + payload + marker


def test_phase3_real_op2_fortran_header_and_nurbs_fail_closed(tmp_path: Path) -> None:
    # Real-style Fortran OP2 header tables without internal AEROH5/GRID records
    op2_bytes = (
        _fortran_rec(b"ID NASTRAN OP2")
        + _fortran_rec(b"GEOM1   " + b"\x00" * 16)
        + _fortran_rec(b"OUG1    " + b"\x00" * 16)
    )
    op2_path = tmp_path / "external_msc.op2"
    op2_path.write_bytes(op2_bytes)

    scanned = inspect_nastran_op2_fortran_blocks(op2_path)
    assert scanned["valid_fortran_records"] is True
    assert scanned["endianness"] == "<"
    assert {"GEOM1", "OUG1"}.issubset(set(scanned["detected_tables"]))

    fmt = detect_cae_binary_format(op2_path)
    assert fmt["format"] == "nastran_op2_fortran"
    assert fmt["pynastran_available"] is False

    with pytest.raises(IngestAbstain) as exc_info:
        parse_nastran_op2_file(op2_path)
    assert exc_info.value.reason == "pynastran_required_for_full_op2_extraction"

    nurbs_step = (
        b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"
        b"#10=B_SPLINE_SURFACE_WITH_KNOTS('S',3,3,((#1,#2)),.UNSPECIFIED.,.F.,.F.,.F.,(4,4),(0.0,1.0),.UNSPECIFIED.);\n"
        b"ENDSEC;\nEND-ISO-10303-21;\n"
    )
    nurbs_res = analyze_step_with_ocp_or_polyhedral(nurbs_step)
    assert nurbs_res["status"] == "ABSTAIN"
    assert nurbs_res["abstain_reason"] == "ocp_required_for_nurbs_brep"
    assert nurbs_res["nurbs_entity_count"] >= 1


def test_phase4_routers_compact_mcp_and_card_consolidation() -> None:
    import yaml

    app_instance = create_app()
    spec_path = repo_root() / "schemas" / "openapi.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    live_paths = {
        r.path
        for r in app_instance.routes
        if getattr(r, "methods", None)
        and r.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }
    assert live_paths == set(spec["paths"].keys())

    assert len(CARD_CONSOLIDATION_MAP) >= 8
    cards = list_cards()
    assert all("canonical_card_id" in c for c in cards)

    assert len(MCP_COMPACT_TOOLS) <= 12
    compact_list = handle_mcp_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        profile="compact",
    )
    assert isinstance(compact_list, dict)
    assert len(compact_list["result"]["tools"]) == len(MCP_COMPACT_TOOLS)

    compact_call = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "aeroregu_calc_dispatch",
                "arguments": {
                    "action": "allowables_lookup",
                    "payload": {"material_id": "AL-7075-T651", "environment": "ETW"},
                },
            },
        },
        profile="compact",
    )
    assert isinstance(compact_call, dict)
    assert compact_call["result"]["isError"] is False
    assert compact_call["result"]["structuredContent"]["moisture_applicable"] is False
