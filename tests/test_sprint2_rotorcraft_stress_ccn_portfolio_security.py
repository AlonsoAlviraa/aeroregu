"""Sprint 2 E2E Suite: Rotorcraft Stress Cards, Closed-Loop CCN, Portfolio RCPSP & Security."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.formal_methods import METHOD_DEFAULT_INPUTS, run_formal_proof_for_method
from evidence_api.mcp_server import handle_mcp_message
from evidence_calc.registry import list_cards, run_method
from evidence_coverage.composite_dag_quotation import (
    CompositeRotorcraftQuotationSpec,
    run_composite_rotorcraft_quotation,
)
from evidence_coverage.contract_clause_auditor import audit_rfq_contract_clauses
from evidence_coverage.portfolio_capacity_leveler import level_portfolio_capacity
from evidence_coverage.quotation_change_order import compute_quotation_change_order
from evidence_coverage.quotation_exporter import (
    export_change_order_signed_pdf,
    export_change_order_xlsx,
    export_quotation_xlsx,
    verify_quotation_signed_pdf,
)
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook
from typer.testing import CliRunner


# ==============================================================================
# 1. 5 Rotorcraft & Composite Stress Cards (Decimal + Arb Intervals + Z3 + Property Tests)
# ==============================================================================
def test_5_rotorcraft_stress_cards_physics_arb_and_z3_smt() -> None:
    cards = list_cards()
    assert len(cards) == 42

    expected_new = (
        "clt_laminate_abd_stiffness",
        "rotor_blade_centrifugal_bending",
        "ground_resonance_coleman_screen",
        "cs29_crashworthiness_561_562_load",
        "multirow_bolt_load_distribution",
    )
    for m_id in expected_new:
        res = run_method(
            m_id,
            METHOD_DEFAULT_INPUTS[m_id],
            normalize_units=True,
            include_intervals=True,
        )
        assert res["outputs"]
        assert len(res["exact_intervals"]) == len(res["outputs"])
        for iv in res["exact_intervals"].values():
            assert Decimal(iv["quantization_drift"]) < Decimal("0.001")
        smt = run_formal_proof_for_method(m_id)
        assert smt["proved"] is True
        assert smt["status"] in ("PROVED", "PROVED_UNSAT")

    # 1a. CLT: symmetric [0/45/45/0] -> zero B coupling; quasi-iso [0/45/-45/90] -> Ex == Ey
    sym_clt = run_method(
        "clt_laminate_abd_stiffness",
        {
            **METHOD_DEFAULT_INPUTS["clt_laminate_abd_stiffness"],
            "theta_3_deg": "45",
            "theta_4_deg": "0",
        },
        include_intervals=True,
    )["outputs"]
    assert Decimal(sym_clt["max_abs_b_coupling"]) == Decimal("0.0000")

    qi_clt = run_method(
        "clt_laminate_abd_stiffness",
        METHOD_DEFAULT_INPUTS["clt_laminate_abd_stiffness"],
    )["outputs"]
    assert abs(Decimal(qi_clt["ex_eff_mpa"]) - Decimal(qi_clt["ey_eff_mpa"])) < Decimal("1.0")
    assert Decimal(qi_clt["max_abs_b_coupling"]) > Decimal("0")

    clt_ce = run_formal_proof_for_method(
        "clt_laminate_abd_stiffness",
        {"nx_n_per_mm": "2000", "mx_n_mm_per_mm": "100"},
    )
    assert clt_ce["proved"] is False
    assert clt_ce["status"] == "COUNTEREXAMPLE_FOUND"

    # 1b. Rotor Blade CF + Bending + Goodman
    blade_out = run_method(
        "rotor_blade_centrifugal_bending",
        {
            "blade_mass_kg": "50",
            "rotor_omega_rad_s": "40",
            "cg_radius_m": "2.500",
            "root_area_mm2": "1000",
            "root_section_modulus_mm3": "20000",
            "flap_bending_moment_n_m": "1200",
            "lag_bending_moment_n_m": "900",
            "ultimate_tensile_mpa": "900",
            "endurance_limit_mpa": "300",
            "safety_factor": "1.500",
        },
    )["outputs"]
    # F_cf = 50 * 40^2 * 2.5 = 200000 N -> sigma_cf = 200 MPa; flap=60 MPa, lag=45 MPa -> alt=75 MPa
    assert Decimal(blade_out["centrifugal_force_n"]) == Decimal("200000.000")
    assert Decimal(blade_out["centrifugal_stress_mpa"]) == Decimal("200.000")
    assert Decimal(blade_out["alternating_stress_mpa"]) == Decimal("75.000")
    assert (
        run_formal_proof_for_method(
            "rotor_blade_centrifugal_bending", {"rotor_omega_rad_s": "110"}
        )["status"]
        == "COUNTEREXAMPLE_FOUND"
    )

    # 1c. Ground Resonance Coleman
    gr_out = run_method(
        "ground_resonance_coleman_screen",
        METHOD_DEFAULT_INPUTS["ground_resonance_coleman_screen"],
    )["outputs"]
    assert Decimal(gr_out["coalescence_rotor_speed_rad_s"]) == Decimal("29.0000")
    assert Decimal(gr_out["stability_margin_of_safety"]) > Decimal("0")
    assert (
        run_formal_proof_for_method(
            "ground_resonance_coleman_screen", {"blade_lag_damping_ratio": "0.005"}
        )["status"]
        == "COUNTEREXAMPLE_FOUND"
    )

    # 1d. CS 29.561 / 29.562 Crashworthiness
    crash_out = run_method(
        "cs29_crashworthiness_561_562_load",
        {
            "occupant_seat_mass_kg": "100",
            "delta_v_m_s": "9.100",
            "rise_time_s": "0.030",  # dv/tr = 303.3 m/s^2 = 30.93g > 20g -> dynamic dominates!
            "attachment_bolt_count": "4",
            "bolt_allowable_load_n": "12000",
            "floor_fitting_factor": "1.330",
        },
    )["outputs"]
    assert Decimal(crash_out["cs29_562_peak_g"]) > Decimal("30")
    assert Decimal(crash_out["governing_design_load_n"]) == Decimal(
        crash_out["dynamic_pulse_load_n"]
    )
    assert (
        run_formal_proof_for_method(
            "cs29_crashworthiness_561_562_load", {"bolt_allowable_load_n": "3000"}
        )["status"]
        == "COUNTEREXAMPLE_FOUND"
    )

    # 1e. Multirow 3-Row Bolt Splice (symmetry & equilibrium)
    mr_out = run_method(
        "multirow_bolt_load_distribution",
        METHOD_DEFAULT_INPUTS["multirow_bolt_load_distribution"],
    )["outputs"]
    p1 = Decimal(mr_out["row1_load_n"])
    p2 = Decimal(mr_out["row2_load_n"])
    p3 = Decimal(mr_out["row3_load_n"])
    assert abs((p1 + p2 + p3) - Decimal("12000")) < Decimal("0.001")
    assert abs(p1 - p3) < Decimal("0.001")
    assert p1 > p2
    assert (
        run_formal_proof_for_method(
            "multirow_bolt_load_distribution", {"total_applied_load_n": "90000"}
        )["status"]
        == "COUNTEREXAMPLE_FOUND"
    )


@settings(max_examples=20, deadline=None)
@given(
    total_load=st.integers(min_value=1000, max_value=40000),
    t1=st.decimals(min_value=Decimal("2.0"), max_value=Decimal("8.0"), places=1),
    t2=st.decimals(min_value=Decimal("2.0"), max_value=Decimal("8.0"), places=1),
)
def test_multirow_bolt_equilibrium_hypothesis(
    total_load: int,
    t1: Decimal,
    t2: Decimal,
) -> None:
    out = run_method(
        "multirow_bolt_load_distribution",
        {
            **METHOD_DEFAULT_INPUTS["multirow_bolt_load_distribution"],
            "total_applied_load_n": str(total_load),
            "plate1_thickness_mm": str(t1),
            "plate2_thickness_mm": str(t2),
        },
    )["outputs"]
    total = Decimal(out["row1_load_n"]) + Decimal(out["row2_load_n"]) + Decimal(out["row3_load_n"])
    assert abs(total - Decimal(total_load)) < Decimal("0.001")
    assert Decimal(out["row1_load_n"]) > Decimal("0")
    assert Decimal(out["row2_load_n"]) > Decimal("0")
    assert Decimal(out["row3_load_n"]) > Decimal("0")


# ==============================================================================
# 2. Closed-Loop Change-Order (CCN Rev A -> Rev B) & Signed CCN Exports
# ==============================================================================
def test_closed_loop_change_order_delta_pricer_and_exports(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ccn.sqlite3", tenant_id="demo")
    rev_a_spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-CCN-REV-A",
        rfq_text="CS-29 metallic detail fitting static dossier. AS9100, Net 60.",
        archetype_ids=("Q-DES-02", "Q-STR-03"),
        country_code="ES",
        unit_count=1,
        program_years=2,
    )
    baseline = run_composite_rotorcraft_quotation(ledger, rev_a_spec)
    assert baseline["decision_status"] == "APPROVED_FOR_HUMAN_REVIEW"

    rev_b_spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-CCN-REV-B",
        rfq_text=(
            "CS-29 metallic fitting + F&DT + HEMS STC + test rig correlation. AS9100, Net 60."
        ),
        archetype_ids=("Q-DES-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02", "Q-TST-01"),
        country_code="ES",
        unit_count=3,
        program_years=3,
    )
    ccn = compute_quotation_change_order(
        ledger,
        baseline,
        rev_b_spec,
        cr_id="CCN-HEMS-007",
        change_reason="OEM requested full F&DT + HEMS STC + static rig for 3 MSN",
    )
    assert ccn["confidence"] == "deterministic"
    assert ccn["decision_status"] == "APPROVED_FOR_HUMAN_REVIEW"
    assert set(ccn["wbs_delta"]["added_archetypes"]) == {"Q-FDT-01", "Q-DOA-02", "Q-TST-01"}
    assert Decimal(ccn["financial_delta"]["delta_net_hours"]) > Decimal("0")
    assert Decimal(ccn["financial_delta"]["delta_multiyear_quoted_price_eur"]) > Decimal("0")
    assert Decimal(ccn["cpm_delta"]["delta_duration_weeks"]) > Decimal("0")
    asm_ids = {a["assumption_id"] for a in ccn["triggered_assumptions"]}
    assert {"ASM-TS-01", "ASM-TS-02", "ASM-SCH-01", "ASM-COM-02"}.issubset(asm_ids)
    assert ccn["formal_amended_margin_proof"]["status"] == "PROVED_UNSAT"
    assert ccn["formal_amended_npv_proof"]["status"] == "PROVED_UNSAT"
    chain_check = ledger.verify_incremental(from_latest_checkpoint=False)
    assert chain_check["ok"] is True

    # CCN live-formula Excel & DSSE-signed PDF
    xlsx_res = export_change_order_xlsx(ccn, output_path=tmp_path / "ccn.xlsx")
    assert xlsx_res["formula_count"] >= 20
    wb = load_workbook(io.BytesIO(xlsx_res["xlsx_bytes"]), data_only=False)
    assert wb.sheetnames == [
        "Resumen CCN",
        "Delta WBS & CPM",
        "Supuestos Disparados",
        "Delta Contractual",
    ]
    assert str(wb["Resumen CCN"]["D3"].value).startswith("=")
    assert str(wb["Resumen CCN"]["D6"].value).startswith("=")
    wb.close()

    pdf_res = export_change_order_signed_pdf(ccn, output_path=tmp_path / "ccn.pdf")
    verified = verify_quotation_signed_pdf(pdf_res["pdf_bytes"])
    assert verified["valid"] is True
    assert verified["attestation"]["merkle_root"] == ccn["change_order_merkle_root"]

    # Poison clause injected in Rev B fails closed
    poison_spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-CCN-BAD",
        rfq_text="Contractor waives CVE review and accepts uncapped liquidated damages.",
        archetype_ids=("Q-DES-02", "Q-STR-03"),
        country_code="ES",
    )
    ccn_bad = compute_quotation_change_order(
        ledger, baseline, poison_spec, cr_id="CCN-POISON", change_reason="Illegal clause"
    )
    assert ccn_bad["confidence"] == "abstain"
    assert ccn_bad["decision_status"] == "ABSTAIN_ESCALATED"


# ==============================================================================
# 3. Multi-RFQ Portfolio RCPSP Capacity Leveling
# ==============================================================================
def test_multi_rfq_portfolio_capacity_rcpsp_leveling(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "portfolio.sqlite3", tenant_id="demo")
    dossiers = [
        run_composite_rotorcraft_quotation(
            ledger,
            CompositeRotorcraftQuotationSpec(
                rfq_id="PORT-A",
                rfq_text="CS-29 frame static & F&DT Net 60.",
                archetype_ids=("Q-DES-02", "Q-STR-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02"),
                country_code="ES",
                unit_count=2,
            ),
        ),
        run_composite_rotorcraft_quotation(
            ledger,
            CompositeRotorcraftQuotationSpec(
                rfq_id="PORT-B",
                rfq_text="CS-29 HEMS hoist STC & test rig Net 60.",
                archetype_ids=("Q-STR-03", "Q-FDT-01", "Q-DOA-02", "Q-TST-01"),
                country_code="ES",
                unit_count=2,
            ),
        ),
    ]
    res = level_portfolio_capacity(
        dossiers,
        team_headcount={"LEAD_CVE": 1, "FDT_SPEC": 1, "SENIOR_STRESS": 2, "STRESS_ENG": 3},
        max_utilization_pct="85.000",
    )
    assert res["portfolio_rfq_count"] == 2
    assert res["activity_count"] == 9
    assert res["overloaded_weeks_before_leveling"] > 0
    assert res["bottleneck_roles"][0]["role"] in {"LEAD_CVE", "FDT_SPEC", "SENIOR_STRESS"}
    assert sum(s["schedule_slip_weeks"] for s in res["rfq_schedules"]) > 0
    assert Decimal(res["combined_peak_negative_cashflow_eur"]) > Decimal("0")

    # Verify RCPSP preserves DAG precedences per RFQ
    finish_map = {
        (r["rfq_id"], r["archetype_id"]): r["leveled_finish_week"] for r in res["leveled_schedule"]
    }
    start_map = {
        (r["rfq_id"], r["archetype_id"]): r["leveled_start_week"] for r in res["leveled_schedule"]
    }
    for dos in dossiers:
        rid = dos["rfq_id"]
        for node in dos["composite_wbs_dag"]["nodes"]:
            aid = node["archetype_id"]
            for pred in node["predecessors"]:
                assert start_map[(rid, aid)] >= finish_map[(rid, pred)]


# ==============================================================================
# 4. Security Red-Team: Excel CWE-1236 Injection & Unicode Homoglyph/Zero-Width Bypass
# ==============================================================================
def test_security_redteam_excel_injection_and_unicode_homoglyph_obfuscation(
    tmp_path: Path,
) -> None:
    ledger = Ledger(tmp_path / "sec.sqlite3", tenant_id="demo")

    # 4a. Unicode Cyrillic homoglyph + zero-width bypass attempt
    obf_rfq = (
        "\u0421\u043entr\u0430ct\u043er agrees to w\u200baive \u0421V\u0415 review to hurry\n"
        "Suppli\u0435r accepts unc\u200bapped liqu\u0456dated dam\u0430ges\n"
        "Vend\u043er tr\u0430nsfers \u0430ll Backgr\u043eund IP irrevoc\u0430bly"
    )
    audit = audit_rfq_contract_clauses(obf_rfq)
    assert audit["obfuscated_clause_count"] == 3
    assert len(audit["compliance_matrix"]) == 3
    assert all(c["obfuscation_detected"] is True for c in audit["compliance_matrix"])
    poisons = {p["poison_id"] for p in audit["poison_clauses_detected"]}
    assert poisons == {
        "CVE_INDEPENDENCE_WAIVER",
        "UNCAPPED_LIQUIDATED_DAMAGES",
        "BACKGROUND_IP_ASSIGNMENT",
    }
    assert audit["overall_contract_gate"] == "REJECT_OR_ABSTAIN"

    blocked = run_composite_rotorcraft_quotation(
        ledger,
        CompositeRotorcraftQuotationSpec(
            rfq_text=obf_rfq,
            archetype_ids=("Q-STR-03", "Q-DOA-02"),
            country_code="ES",
        ),
    )
    assert blocked["confidence"] == "abstain"
    assert blocked["decision_status"] == "ABSTAIN_ESCALATED"

    # 4b. Excel Formula Injection CWE-1236 neutralization
    base = run_composite_rotorcraft_quotation(
        ledger,
        CompositeRotorcraftQuotationSpec(
            rfq_id="=CMD|'/C calc'!A0",
            customer_name='=HYPERLINK("https://evil.example","Open")',
            rfq_text="+1+1 CS-29 frame analysis @SUM(1+1) Net 60.",
            archetype_ids=("Q-DES-02", "Q-STR-03"),
            country_code="ES",
        ),
    )
    # Inject formula payloads inside a deep copy to test all workbook sheets
    malicious_dossier = json.loads(json.dumps(base))
    malicious_dossier["composite_wbs_dag"]["nodes"][0]["family"] = "@SUM(1+1)"
    malicious_dossier["contract_audit"]["compliance_matrix"][0]["text"] = '=IMPORTXML("http://x")'

    xlsx_res = export_quotation_xlsx(malicious_dossier, output_path=tmp_path / "safe.xlsx")
    wb = load_workbook(io.BytesIO(xlsx_res["xlsx_bytes"]), data_only=False)
    assert wb["Resumen Ejecutivo"]["B4"].value == "'=CMD|'/C calc'!A0"
    assert wb["Resumen Ejecutivo"]["B5"].value == '\'=HYPERLINK("https://evil.example","Open")'
    assert wb["WBS Multi-Arquetipo & CPM"]["B2"].value == "'@SUM(1+1)"
    assert wb["Matriz Contractual"]["E2"].value == '\'=IMPORTXML("http://x")'
    # Engine's own dashboard/CPM formulas MUST stay live
    assert str(wb["Resumen Ejecutivo"]["B8"].value).startswith("=")
    assert str(wb["WBS Multi-Arquetipo & CPM"]["E2"].value).startswith("=")
    wb.close()

    # Also test CWE-1236 on CCN workbook
    ccn = compute_quotation_change_order(
        ledger,
        base,
        CompositeRotorcraftQuotationSpec(
            rfq_id="-1+1",
            rfq_text="CS-29 frame analysis + F&DT Net 60.",
            archetype_ids=("Q-DES-02", "Q-STR-03", "Q-FDT-01"),
            country_code="ES",
        ),
        cr_id="=CCN_HACK",
        change_reason="+CMD|calc",
    )
    ccn_xlsx = export_change_order_xlsx(ccn, output_path=tmp_path / "safe_ccn.xlsx")
    cwb = load_workbook(io.BytesIO(ccn_xlsx["xlsx_bytes"]), data_only=False)
    assert cwb["Resumen CCN"]["B13"].value == "'=CCN_HACK"
    assert cwb["Resumen CCN"]["D13"].value == "'+CMD|calc"
    assert str(cwb["Resumen CCN"]["D3"].value).startswith("=")
    cwb.close()


# ==============================================================================
# 5. API, OpenAPI Sync, CLI, MCP & Cockpit v2 E2E
# ==============================================================================
def test_sprint2_api_cli_mcp_and_cockpit_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")

    # OpenAPI YAML contains all 4 new Sprint 2 paths
    repo_root = Path(__file__).resolve().parents[1]
    spec = yaml.safe_load((repo_root / "schemas" / "openapi.yaml").read_text(encoding="utf-8"))
    for p in (
        "/quotations/rotorcraft/change-order",
        "/quotations/rotorcraft/change-order/export-xlsx",
        "/quotations/rotorcraft/change-order/export-pdf",
        "/quotations/rotorcraft/portfolio-capacity",
    ):
        assert p in spec["paths"]

    # Cockpit v2 HTML + JS controls
    client = TestClient(create_app())
    html = client.get("/").text
    assert 'id="quote-op2-file"' in html
    assert 'id="quote-cf-svg-wrap"' in html
    assert 'id="quote-ccn-portfolio-details"' in html
    assert 'id="quote-ccn-run-btn"' in html
    assert 'id="quote-portfolio-btn"' in html
    js = client.get("/static/quotation_cockpit.js").text
    assert "renderCashflowSvg" in js
    assert "runChangeOrderDelta" in js
    assert "runPortfolioCapacity" in js

    # API Change-Order & Portfolio endpoints
    base_res = client.post(
        "/quotations/rotorcraft/composite-dag",
        json={
            "rfq_id": "API-BASE",
            "rfq_text": "CS-29 frame static Net 60.",
            "archetype_ids": ["Q-DES-02", "Q-STR-03"],
            "country_code": "ES",
        },
    )
    assert base_res.status_code == 200
    base_dos = base_res.json()["result"]

    ccn_res = client.post(
        "/quotations/rotorcraft/change-order",
        json={
            "baseline_dossier": base_dos,
            "rfq_id": "API-REV-B",
            "rfq_text": "CS-29 frame static + F&DT + STC Net 60.",
            "archetype_ids": ["Q-DES-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02"],
            "country_code": "ES",
            "unit_count": 2,
            "cr_id": "CCN-API-01",
            "change_reason": "Add F&DT + STC",
        },
    )
    assert ccn_res.status_code == 200
    ccn_dos = ccn_res.json()["result"]
    assert Decimal(ccn_dos["financial_delta"]["delta_multiyear_quoted_price_eur"]) > Decimal("0")

    ccn_xlsx_http = client.post(
        "/quotations/rotorcraft/change-order/export-xlsx", json={"ccn_dossier": ccn_dos}
    )
    assert ccn_xlsx_http.status_code == 200
    ccn_pdf_http = client.post(
        "/quotations/rotorcraft/change-order/export-pdf", json={"ccn_dossier": ccn_dos}
    )
    assert ccn_pdf_http.status_code == 200
    assert verify_quotation_signed_pdf(ccn_pdf_http.content)["valid"] is True

    port_res = client.post(
        "/quotations/rotorcraft/portfolio-capacity",
        json={"dossiers": [base_dos, ccn_dos["revised_dossier"]]},
    )
    assert port_res.status_code == 200
    assert port_res.json()["result"]["portfolio_rfq_count"] == 2

    # CLI quote change-order & portfolio-level
    runner = CliRunner()
    cli_ccn = runner.invoke(
        cli_app,
        [
            "quote",
            "change-order",
            "--baseline-text",
            "CS-29 frame static Net 60.",
            "--revised-text",
            "CS-29 frame static + F&DT + STC Net 60.",
            "--country",
            "ES",
            "--json",
        ],
    )
    assert cli_ccn.exit_code == 0
    assert Decimal(json.loads(cli_ccn.output)["financial_delta"]["delta_net_hours"]) > Decimal("0")

    cli_port = runner.invoke(
        cli_app,
        ["quote", "portfolio-level", "--rfq-count", "2", "--lead-cve", "1", "--json"],
    )
    assert cli_port.exit_code == 0
    assert json.loads(cli_port.output)["portfolio_rfq_count"] == 2

    # MCP tools == 43 and both new tools work end-to-end
    list_msg = handle_mcp_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert list_msg is not None
    assert len(list_msg["result"]["tools"]) == 43

    mcp_port = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "level_rotorcraft_portfolio_capacity", "arguments": {}},
        }
    )
    assert mcp_port is not None
    assert mcp_port["result"]["isError"] is False
    assert mcp_port["result"]["structuredContent"]["portfolio_rfq_count"] == 2
