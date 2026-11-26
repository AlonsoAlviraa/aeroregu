"""Sprint 7 E2E Suite: 60 Stress Cards, Load Envelopes, Part 21J MoC, Risk & Cockpit v5."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
import yaml
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.formal_methods import (
    METHOD_DEFAULT_INPUTS,
    METHOD_FAMILIES,
    run_formal_proof_for_method,
)
from evidence_api.mcp_server import handle_mcp_message
from evidence_calc.errors import AbstainError
from evidence_calc.registry import list_method_ids, run_method
from evidence_coverage.certification_moc_matrix import (
    build_part21j_moc_matrix,
    export_moc_matrix_pdf,
    export_moc_matrix_xlsx,
)
from evidence_coverage.load_envelope_combiner import (
    combine_structural_load_envelopes,
    default_cs29_load_envelope_payload,
    export_load_envelope_pdf,
    export_load_envelope_xlsx,
)
from evidence_coverage.quotation_risk_frontier import (
    export_risk_frontier_pdf,
    export_risk_frontier_xlsx,
    run_quotation_risk_frontier,
)
from evidence_coverage.stress_dossier_packager import build_stress_summary_dossier
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from typer.testing import CliRunner


def _assert_xlsx_clean(xlsx_bytes: bytes, min_formulas: int) -> None:
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=False)
    formula_cnt = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            for val in row:
                if isinstance(val, str) and val.startswith("="):
                    formula_cnt += 1
                    # Never emit CWE-1236 risky formula starts
                    assert not val.startswith("=cmd")
    assert formula_cnt >= min_formulas


def _decode_first_qr(pdf_bytes: bytes) -> str:
    detector = cv2.QRCodeDetector()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for info in doc[0].get_images(full=True):
            raw = doc.extract_image(info[0])["image"]
            img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                cand, _, _ = detector.detectAndDecode(img)
                if cand:
                    return cand
    return ""


def test_sprint7_pillar1_60_cards_arb_intervals_z3_and_abstain() -> None:
    ids = list_method_ids(include_plugins=False)
    assert len(ids) == 60

    new_cards = (
        ("composite_bolted_joint_bearing_tension_shear", "governing_ms"),
        ("rotor_hub_elastomeric_bearing_strain", "margin_of_safety"),
        ("cs29_ditching_water_impact_panel", "margin_of_safety"),
        ("pressure_bulkhead_hoop_longitudinal_stress", "governing_ms"),
    )
    for mid, ms_key in new_cards:
        assert mid in ids
        assert mid in METHOD_FAMILIES
        defaults = dict(METHOD_DEFAULT_INPUTS[mid])
        res = run_method(mid, defaults, include_intervals=True)
        assert Decimal(res["outputs"][ms_key]) > Decimal("0")
        iv = res["exact_intervals"][ms_key]
        assert Decimal(iv["lower"]) <= Decimal(iv["mid"]) <= Decimal(iv["upper"])
        assert Decimal(iv["quantization_drift"]) < Decimal("0.001")

        # Z3 PROVED_UNSAT on nominal safe interval
        proof = run_formal_proof_for_method(mid, defaults)
        assert proof["status"] == "PROVED_UNSAT"
        assert proof["proved"] is True

        # Z3 COUNTEREXAMPLE_FOUND when safety_factor or demand exceeds limit
        bad = dict(defaults)
        if "applied_load_n" in bad:
            bad["applied_load_n"] = "25000"
        elif "axial_cf_load_n" in bad:
            bad["allowable_equiv_strain"] = "0.050"
        elif "vertical_sink_speed_m_s" in bad:
            bad["vertical_sink_speed_m_s"] = "12.0"
        else:
            bad["internal_delta_p_mpa"] = "0.800"
        cex = run_formal_proof_for_method(mid, bad)
        assert cex["status"] == "COUNTEREXAMPLE_FOUND"
        assert cex["proved"] is False

    # Abstain guards on unphysical geometry
    with pytest.raises(AbstainError, match="outside_validity"):
        bad_cbj = dict(METHOD_DEFAULT_INPUTS["composite_bolted_joint_bearing_tension_shear"])
        bad_cbj["strip_width_w_mm"] = bad_cbj["bolt_diameter_mm"]
        run_method("composite_bolted_joint_bearing_tension_shear", bad_cbj)

    with pytest.raises(AbstainError, match="outside_validity"):
        bad_ditch = dict(METHOD_DEFAULT_INPUTS["cs29_ditching_water_impact_panel"])
        bad_ditch["deadrise_angle_deg"] = "1.5"
        run_method("cs29_ditching_water_impact_panel", bad_ditch)


def test_sprint7_pillar2_load_envelope_combiner_arb_xlsx_pdf(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "env_ledger", "airbus-h")
    payload = default_cs29_load_envelope_payload()
    rep = combine_structural_load_envelopes(**payload, ledger=ledger, tenant_id="airbus-h")

    assert rep["component_count"] == 3
    assert rep["combination_count"] == 3
    assert rep["evaluated_pairs_count"] == 9
    assert rep["overall_status"] == "ALL_ENVELOPES_POSITIVE_MS"
    assert Decimal(rep["global_ms_min"]) > Decimal("0")
    assert rep.get("ledger_event_hash")
    assert ledger.verify() is True

    # Negative margin detection when extreme load is applied
    bad_payload = default_cs29_load_envelope_payload()
    bad_payload["basic_subcases"]["HARD_LAND"]["COMP-SKID-FWD"]["sx_mpa"] = "680.0"
    bad_rep = combine_structural_load_envelopes(**bad_payload)
    assert bad_rep["overall_status"] == "NEGATIVE_ENVELOPE_MARGIN_DETECTED"
    assert bad_rep["governing_component"] == "COMP-SKID-FWD"
    assert Decimal(bad_rep["global_ms_min"]) < Decimal("0")

    xr = export_load_envelope_xlsx(rep)
    assert xr["sheet_names"] == [
        "1_Envelope_Summary",
        "2_Load_Combinations",
        "3_Component_Envelopes",
        "4_Full_Matrix",
    ]
    _assert_xlsx_clean(xr["xlsx_bytes"], min_formulas=15)

    pr = export_load_envelope_pdf(rep)
    assert pr["pdf_bytes"].startswith(b"%PDF-")
    assert "aeroregu-env:" in _decode_first_qr(pr["pdf_bytes"])


def test_sprint7_pillar3_part21j_moc_matrix_gaps_signoff_xlsx_pdf(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "moc_ledger", "airbus-h")
    env = combine_structural_load_envelopes(**default_cs29_load_envelope_payload())
    dos = build_stress_summary_dossier(
        "STRESS-MOC-01",
        [
            {
                "check_id": "CHK-SKID",
                "component_name": "Skid Tube",
                "method_id": "cs29_skid_landing_gear_drop_energy",
                "inputs": dict(METHOD_DEFAULT_INPUTS["cs29_skid_landing_gear_drop_energy"]),
            },
            {
                "check_id": "CHK-DITCH",
                "component_name": "Hull Bottom",
                "method_id": "cs29_ditching_water_impact_panel",
                "inputs": dict(METHOD_DEFAULT_INPUTS["cs29_ditching_water_impact_panel"]),
            },
        ],
        include_formal_proofs=True,
    )

    custom_reqs = [
        {
            "cs_paragraph": "CS 29.303",
            "title": "Factor of Safety",
            "required_mocs": ["MOC-2"],
            "method_ids": ["load_envelope_combiner"],
            "revision": "REV-B",
        },
        {
            "cs_paragraph": "CS 29.725",
            "title": "Limit Drop Skid",
            "required_mocs": ["MOC-2", "MOC-4"],
            "provided_mocs": ["MOC-4"],
            "method_ids": ["cs29_skid_landing_gear_drop_energy"],
            "revision": "REV-A",  # stale relative to REV-B!
        },
        {
            "cs_paragraph": "CS 29.801",
            "title": "Ditching Panel",
            "required_mocs": ["MOC-2", "MOC-8"],
            "provided_mocs": ["MOC-8"],
            "method_ids": ["cs29_ditching_water_impact_panel"],
            "revision": "REV-B",
        },
    ]
    mat = build_part21j_moc_matrix(
        "PROG-H145-S7",
        requirements=custom_reqs,
        stress_dossier=dos,
        load_envelope=env,
        cve_signoffs={"CS 29.801": {"cve_id": "cve.martinez", "distinct_reviewer": True}},
        active_ecn_revision="REV-B",
        ledger=ledger,
        tenant_id="airbus-h",
    )
    assert mat["not_a_certification_determination"] is True
    assert mat["ready_count"] == 2
    assert mat["cve_signed_count"] == 1
    assert mat["open_gap_count"] == 1
    assert mat["open_gaps"][0]["status"] == "GAP_STALE_REVISION"
    assert mat["open_gaps"][0]["cs_paragraph"] == "CS 29.725"
    assert Decimal(mat["readiness_pct"]) == Decimal("66.67")
    assert ledger.verify() is True

    xr = export_moc_matrix_xlsx(mat)
    assert xr["sheet_names"] == ["1_Program_Readiness", "2_CS29_MoC_Matrix", "3_Open_Gaps"]
    _assert_xlsx_clean(xr["xlsx_bytes"], min_formulas=10)

    pr = export_moc_matrix_pdf(mat)
    assert pr["pdf_bytes"].startswith(b"%PDF-")
    assert "aeroregu-moc:" in _decode_first_qr(pr["pdf_bytes"])


def test_sprint7_pillar4_risk_frontier_determinism_z3_and_exports() -> None:
    r1 = run_quotation_risk_frontier(
        base_cost_eur="375000",
        base_quote_price_eur="480000",
        num_scenarios=300,
        seed=20261126,
    )
    r2 = run_quotation_risk_frontier(
        base_cost_eur="375000",
        base_quote_price_eur="480000",
        num_scenarios=300,
        seed=20261126,
    )
    assert r1["report_sha256"] == r2["report_sha256"]
    assert r1["label"] == "ESTIMATE"

    dist = r1["cost_distribution"]
    assert (
        Decimal(dist["cost_p10_eur"])
        <= Decimal(dist["cost_p50_eur"])
        <= Decimal(dist["cost_p80_eur"])
        <= Decimal(dist["cost_p90_eur"])
        <= Decimal(dist["cost_p95_eur"])
        <= Decimal(dist["cvar_95_cost_eur"])
    )
    assert len(r1["tornado_drivers"]) == 5
    assert Decimal(r1["tornado_drivers"][0]["swing_eur"]) >= Decimal(
        r1["tornado_drivers"][1]["swing_eur"]
    )
    pareto = r1["pareto_frontier"]
    assert len(pareto) == 11
    assert sum(1 for c in pareto if c["recommended_max_emv"]) == 1
    assert r1["formal_margin_floor_proof"]["status"] == "PROVED_UNSAT"

    xr = export_risk_frontier_xlsx(r1)
    assert xr["sheet_names"] == [
        "1_Executive_Risk_Brief",
        "2_Pareto_Bid_Frontier",
        "3_Tornado_Drivers",
        "4_Cost_Quantiles",
    ]
    _assert_xlsx_clean(xr["xlsx_bytes"], min_formulas=15)

    pr = export_risk_frontier_pdf(r1)
    assert pr["pdf_bytes"].startswith(b"%PDF-")
    assert "aeroregu-risk:" in _decode_first_qr(pr["pdf_bytes"])


def test_sprint7_pillar5_api_openapi_cli_mcp53_and_cockpit_v5(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")

    app = create_app()
    client = TestClient(app)

    # OpenAPI parity check for all 9 new routes
    schema_doc = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "schemas" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    expected_routes = {
        "/calc/load-envelope/combine",
        "/calc/load-envelope/export-xlsx",
        "/calc/load-envelope/export-pdf",
        "/certification/moc-matrix",
        "/certification/moc-matrix/export-xlsx",
        "/certification/moc-matrix/export-pdf",
        "/quotations/rotorcraft/risk-frontier",
        "/quotations/rotorcraft/risk-frontier/export-xlsx",
        "/quotations/rotorcraft/risk-frontier/export-pdf",
    }
    assert expected_routes.issubset(set(schema_doc["paths"].keys()))

    # Test API JSON + XLSX + PDF for all 3 modules
    r_env = client.post("/calc/load-envelope/combine", json={"envelope_id": "ENV-API-1"})
    assert r_env.status_code == 200
    assert Decimal(r_env.json()["result"]["global_ms_min"]) > Decimal("0")
    assert client.post("/calc/load-envelope/export-xlsx", json={}).status_code == 200
    assert client.post("/calc/load-envelope/export-pdf", json={}).content.startswith(b"%PDF-")

    r_moc = client.post(
        "/certification/moc-matrix",
        json={"program_id": "PROG-API-1", "load_envelope": r_env.json()["result"]},
    )
    assert r_moc.status_code == 200
    assert client.post("/certification/moc-matrix/export-xlsx", json={}).status_code == 200
    assert client.post("/certification/moc-matrix/export-pdf", json={}).content.startswith(b"%PDF-")

    r_rf = client.post(
        "/quotations/rotorcraft/risk-frontier",
        json={"base_cost_eur": "375000", "base_quote_price_eur": "480000", "num_scenarios": 200},
    )
    assert r_rf.status_code == 200
    assert r_rf.json()["result"]["formal_margin_floor_proof"]["status"] == "PROVED_UNSAT"
    assert (
        client.post("/quotations/rotorcraft/risk-frontier/export-xlsx", json={}).status_code == 200
    )
    assert client.post(
        "/quotations/rotorcraft/risk-frontier/export-pdf", json={}
    ).content.startswith(b"%PDF-")

    # Test 3 CLI commands
    runner = CliRunner()
    c_env = runner.invoke(cli_app, ["quote", "load-envelope", "--json"])
    assert c_env.exit_code == 0
    assert json.loads(c_env.output)["evaluated_pairs_count"] == 9

    c_moc = runner.invoke(cli_app, ["quote", "moc-matrix", "--json"])
    assert c_moc.exit_code == 0
    assert json.loads(c_moc.output)["requirement_count"] == 12

    c_rf = runner.invoke(cli_app, ["quote", "risk-frontier", "--scenarios", "150", "--json"])
    assert c_rf.exit_code == 0
    assert json.loads(c_rf.output)["num_scenarios"] == 150

    # Test MCP 53 tools & calls #51-#53
    tools_resp = handle_mcp_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(tools_resp["result"]["tools"]) == 53
    for t_name in (
        "combine_structural_load_envelopes",
        "build_part21j_moc_compliance_matrix",
        "optimize_quotation_risk_frontier",
    ):
        call_resp = handle_mcp_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": t_name, "arguments": {}},
            }
        )
        assert call_resp["result"]["isError"] is False

    # Test Cockpit v5 HTML + JS hooks & demo.html guard compliance
    html = client.get("/").text
    assert "quote-load-envelope-details" in html
    assert "quote-moc-matrix-details" in html
    assert "quote-risk-frontier-details" in html
    assert "Método (60)" in html
    assert "100" not in html
    assert "compliant" not in html.lower()

    js = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "api"
        / "src"
        / "evidence_api"
        / "static"
        / "quotation_cockpit.js"
    ).read_text(encoding="utf-8")
    for hook in ("quote-env-run-btn", "quote-moc-run-btn", "quote-risk-run-btn"):
        assert hook in js
