"""Sprint 5 E2E Verification Suite:
1. 50-digit FLINT/Arb interval-bounded MMPDS-16 / CMH-17 allowables + STEP B-Rep density sync.
2. 4 Rotorcraft Systems, Propulsion & Landing-Gear Stress Cards (52 -> 56 catalog), Arb, Z3 SMT
   (PROVED_UNSAT + COUNTEREXAMPLE_FOUND), plugin-shadowing guard, and Hypothesis checks.
3. Multi-Site Nearshore RCPSP Portfolio Optimizer (Part 21.A.239 CVE onshore) + OEM .xlsx/.pdf.
4. Automated Batch Stress-Note Dossier Packager + Ledger Sealing + IQ/OQ v2 + FastAPI/CLI/MCP (49).
"""

from __future__ import annotations

import base64
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
from evidence_calc.allowables import allowable_catalog_sha256, lookup_allowable
from evidence_calc.errors import AbstainError
from evidence_calc.plugins import card_sha256, register_plugin_card
from evidence_calc.registry import list_method_ids, run_method
from evidence_coverage.composite_dag_quotation import (
    CompositeRotorcraftQuotationSpec,
    run_composite_rotorcraft_quotation,
)
from evidence_coverage.pdf_report import _DSSE_ATTACHMENT_NAME
from evidence_coverage.portfolio_capacity_leveler import (
    level_portfolio_capacity,
    optimize_portfolio_nearshore_allocation,
)
from evidence_coverage.qualification_aid import run_iq_oq_qualification_suite
from evidence_coverage.quotation_exporter import (
    export_portfolio_capacity_signed_pdf,
    export_portfolio_capacity_xlsx,
    verify_quotation_signed_pdf,
)
from evidence_coverage.stress_dossier_packager import (
    build_stress_summary_dossier,
    export_stress_dossier_signed_pdf,
    export_stress_dossier_xlsx,
)
from evidence_ingest.cad_brep import _AEROSPACE_DENSITIES_KG_M3
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook
from typer.testing import CliRunner

try:
    import pymupdf
except Exception:  # pragma: no cover
    pymupdf = None


def test_sprint5_1_arb_interval_allowables_and_brep_density_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "ehome"))

    # STEP B-Rep densities synchronized with Sprint 3 allowables catalog
    assert _AEROSPACE_DENSITIES_KG_M3["AL-LI-2198-T8"] == 2690.0
    assert _AEROSPACE_DENSITIES_KG_M3["AS4-8552-PW"] == 1570.0
    assert _AEROSPACE_DENSITIES_KG_M3["T800-M21-UD"] == 1580.0

    # 50-digit FLINT/Arb interval-bounded temperature & thickness interpolation
    res = lookup_allowable(
        "AL-7075-T651",
        basis="A",
        property_name="fty_mpa",
        thickness_mm="42.0",
        temp_c="95.0",
        environment="RTD",
        include_intervals=True,
        temp_uncertainty_c="8.0",
        thickness_uncertainty_mm="3.0",
    )
    assert res["catalog_sha256"] == allowable_catalog_sha256()
    iv = res["exact_intervals"]["allowable_value_mpa"]
    nom = Decimal(res["allowable_value_mpa"])
    assert Decimal(iv["lower"]) < nom < Decimal(iv["upper"])
    assert Decimal(res["certified_lower_bound_mpa"]) == Decimal(iv["lower"])
    assert res["uncertainty_envelope"]["ball_dps"] == 50

    # Fail-closed when uncertainty interval crosses catalog envelope
    with pytest.raises(AbstainError, match="allowable_outside_temp_range"):
        lookup_allowable(
            "AL-7075-T651",
            temp_c="148.0",
            include_intervals=True,
            temp_uncertainty_c="5.0",
        )

    # HTTP /calc/allowables forwards include_intervals & uncertainty bounds
    client = TestClient(create_app())
    resp = client.post(
        "/calc/allowables",
        json={
            "material_id": "TI-6AL-4V",
            "basis": "A",
            "property_name": "fty_mpa",
            "thickness_mm": "30",
            "temp_c": "140",
            "environment": "ETW",
            "include_intervals": True,
            "temp_uncertainty_c": "10",
            "thickness_uncertainty_mm": "2",
        },
    )
    assert resp.status_code == 200
    body_res = resp.json()["result"]
    assert "exact_intervals" in body_res
    b_iv = body_res["exact_intervals"]["allowable_value_mpa"]
    assert (
        Decimal(b_iv["lower"]) <= Decimal(body_res["allowable_value_mpa"]) <= Decimal(b_iv["upper"])
    )


@settings(max_examples=20, deadline=None)
@given(
    temp_c=st.decimals(min_value="26", max_value="135", places=1),
    temp_unc=st.decimals(min_value="0.5", max_value="10", places=1),
    thk_mm=st.decimals(min_value="12", max_value="65", places=1),
    thk_unc=st.decimals(min_value="0.2", max_value="5", places=1),
)
def test_sprint5_2_hypothesis_allowables_arb_sound_enclosure(
    temp_c: Decimal, temp_unc: Decimal, thk_mm: Decimal, thk_unc: Decimal
) -> None:
    res = lookup_allowable(
        "AL-7075-T651",
        basis="B",
        property_name="fcy_mpa",
        thickness_mm=str(thk_mm),
        temp_c=str(temp_c),
        environment="RTD",
        include_intervals=True,
        temp_uncertainty_c=str(temp_unc),
        thickness_uncertainty_mm=str(thk_unc),
    )
    iv = res["exact_intervals"]["allowable_value_mpa"]
    lo, nom, hi = Decimal(iv["lower"]), Decimal(res["allowable_value_mpa"]), Decimal(iv["upper"])
    assert lo <= nom <= hi
    assert (hi - lo) >= Decimal("0")


def test_sprint5_3_four_new_cards_56_catalog_arb_z3_and_shadow_guard(
    tmp_path: Path,
) -> None:
    ids = list_method_ids(include_plugins=False)
    assert len(ids) == 56

    new_cards = (
        "cs29_skid_landing_gear_drop_energy",
        "shaft_whirl_critical_speed_screen",
        "firewall_thermal_buckling_screen",
        "hertzian_bearing_contact_stress",
    )
    for mid in new_cards:
        assert mid in ids
        defaults = dict(METHOD_DEFAULT_INPUTS[mid])
        res = run_method(mid, defaults, include_intervals=True)
        ms_key = "governing_ms" if mid == "firewall_thermal_buckling_screen" else "margin_of_safety"
        assert Decimal(res["outputs"][ms_key]) > Decimal("0")
        iv = res["exact_intervals"][ms_key]
        assert Decimal(iv["quantization_drift"]) < Decimal("0.001")
        assert Decimal(iv["lower"]) <= Decimal(iv["upper"])

        proved = run_formal_proof_for_method(mid, defaults)
        assert proved["proved"] is True
        assert proved["status"] == "PROVED_UNSAT"

        # Built-in shadowing protection
        with pytest.raises(AbstainError, match="builtin_method_protected"):
            register_plugin_card(
                {
                    "method_id": mid,
                    "method_version": f"{mid}@9.9.9",
                    "title": "Shadow attempt",
                    "input_units": {"x": "newton"},
                    "required": ["x"],
                    "limits": {"x": {"min": "0", "max": "10"}},
                    "formulas": {"y": "x"},
                    "plugin": True,
                },
                plugins_dir=tmp_path / "plugins",
            )

    # Verify Z3 SMT finds explicit counterexamples on overloaded/undersized bounds
    bad_skid = {
        **METHOD_DEFAULT_INPUTS["cs29_skid_landing_gear_drop_energy"],
        "drop_height_m": "0.950",
    }
    assert run_formal_proof_for_method("cs29_skid_landing_gear_drop_energy", bad_skid)[
        "status"
    ] == ("COUNTEREXAMPLE_FOUND")
    bad_whirl = {
        **METHOD_DEFAULT_INPUTS["shaft_whirl_critical_speed_screen"],
        "shaft_length_mm": "2400",
    }
    assert run_formal_proof_for_method("shaft_whirl_critical_speed_screen", bad_whirl)[
        "status"
    ] == ("COUNTEREXAMPLE_FOUND")
    bad_fw = {**METHOD_DEFAULT_INPUTS["firewall_thermal_buckling_screen"], "delta_temp_c": "450"}
    assert run_formal_proof_for_method("firewall_thermal_buckling_screen", bad_fw)["status"] == (
        "COUNTEREXAMPLE_FOUND"
    )
    bad_hz = {**METHOD_DEFAULT_INPUTS["hertzian_bearing_contact_stress"], "normal_load_n": "65000"}
    assert run_formal_proof_for_method("hertzian_bearing_contact_stress", bad_hz)["status"] == (
        "COUNTEREXAMPLE_FOUND"
    )
    assert card_sha256({"a": 1})


@settings(max_examples=15, deadline=None)
@given(
    p_lo=st.integers(min_value=8000, max_value=20000),
    delta_p=st.integers(min_value=2000, max_value=15000),
)
def test_sprint5_4_hypothesis_hertzian_contact_monotonicity(p_lo: int, delta_p: int) -> None:
    base = dict(METHOD_DEFAULT_INPUTS["hertzian_bearing_contact_stress"])
    r1 = run_method("hertzian_bearing_contact_stress", {**base, "normal_load_n": str(p_lo)})
    r2 = run_method(
        "hertzian_bearing_contact_stress", {**base, "normal_load_n": str(p_lo + delta_p)}
    )
    assert Decimal(r2["outputs"]["peak_contact_pressure_mpa"]) > Decimal(
        r1["outputs"]["peak_contact_pressure_mpa"]
    )
    assert Decimal(r2["outputs"]["margin_of_safety"]) < Decimal(r1["outputs"]["margin_of_safety"])


def test_sprint5_5_portfolio_nearshore_optimizer_and_oem_exports(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "port_ledger.db", tenant_id="airbus")
    dossiers = []
    for idx, archs in enumerate(
        [
            ("Q-DES-02", "Q-STR-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02"),
            ("Q-DES-03", "Q-STR-01", "Q-STR-03", "Q-FDT-01", "Q-TST-01"),
            ("Q-DES-02", "Q-STR-03", "Q-DOA-02", "Q-DOA-03"),
        ],
        start=1,
    ):
        d = run_composite_rotorcraft_quotation(
            ledger,
            CompositeRotorcraftQuotationSpec(
                rfq_id=f"RFQ-S5-{idx:02d}",
                rfq_text="CS-29 frame & hoist F&DT Net 60.",
                archetype_ids=archs,
                country_code="DE",
                tenant_id="airbus",
                created_at="2026-11-25T18:00:00Z",
            ),
        )
        dossiers.append(d)

    # Constrain team so overflow occurs cleanly across LEAD_CVE + Stress engineers
    port_res = level_portfolio_capacity(
        dossiers,
        team_headcount={"LEAD_CVE": 1, "SENIOR_STRESS": 1, "STRESS_ENG": 2, "CAD_ENG": 2},
        max_utilization_pct="70.000",
        max_horizon_weeks=26,
    )
    assert "overflow_hours_by_role" in port_res
    assert Decimal(port_res["recommended_nearshore_overflow_hours"]) > Decimal("0")

    ns_plan = optimize_portfolio_nearshore_allocation(
        port_res, onshore_country="DE", nearshore_country="ES", cve_onshore_only=True
    )
    assert ns_plan["cve_governance_preserved"] is True
    assert Decimal(ns_plan["total_offloaded_hours"]) > Decimal("0")
    assert Decimal(ns_plan["net_savings_eur"]) > Decimal("0")
    cve_row = next(r for r in ns_plan["per_role_allocation"] if r["role"] == "LEAD_CVE")
    assert Decimal(cve_row["offloaded_nearshore_hours"]) == Decimal("0.000")
    assert cve_row["allocation_policy"] == "ONSHORE_ONLY_PART21_CVE"

    # CWE-1236 injection probe on RFQ ID
    injected_port = json.loads(json.dumps(port_res))
    injected_port["rfq_schedules"][0]["rfq_id"] = '=HYPERLINK("http://evil", "Click")'
    x_res = export_portfolio_capacity_xlsx(
        injected_port, nearshore_plan=ns_plan, output_path=tmp_path / "portfolio.xlsx"
    )
    assert x_res["formula_count"] >= 20
    wb = load_workbook(io.BytesIO(x_res["xlsx_bytes"]), data_only=False)
    assert wb.sheetnames == [
        "1_Portfolio_Summary",
        "2_Role_Bottlenecks",
        "3_RFQ_Schedule_Slip",
        "4_Nearshore_Optimization",
    ]
    assert str(wb["3_RFQ_Schedule_Slip"]["A2"].value).startswith("'=")

    p_res = export_portfolio_capacity_signed_pdf(
        port_res, nearshore_plan=ns_plan, output_path=tmp_path / "portfolio.pdf"
    )
    ver_ok = verify_quotation_signed_pdf(
        p_res["pdf_bytes"], expected_public_key_pem=p_res["public_key_pem"].encode("ascii")
    )
    assert ver_ok["valid"] is True

    # Tamper DSSE payload & confirm rejection
    assert pymupdf is not None
    doc = pymupdf.open(stream=p_res["pdf_bytes"], filetype="pdf")
    dsse_obj = json.loads(doc.embfile_get(_DSSE_ATTACHMENT_NAME).decode("utf-8"))
    dec_payload = json.loads(base64.b64decode(dsse_obj["payload"]).decode("utf-8"))
    dec_payload["nearshore_savings_eur"] = "9999999.99"
    dsse_obj["payload"] = base64.b64encode(json.dumps(dec_payload).encode("utf-8")).decode("ascii")
    doc.embfile_del(_DSSE_ATTACHMENT_NAME)
    doc.embfile_add(
        _DSSE_ATTACHMENT_NAME,
        json.dumps(dsse_obj).encode("utf-8"),
        filename=_DSSE_ATTACHMENT_NAME,
    )
    tampered_bytes = doc.tobytes()
    doc.close()
    assert verify_quotation_signed_pdf(tampered_bytes)["valid"] is False


def test_sprint5_6_stress_dossier_iq_oq_api_openapi_cli_and_mcp49(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "ehome"))
    ledger = Ledger(tmp_path / "stress_ledger.db", tenant_id="airbus")

    checks = [
        {
            "check_id": "SKID-01",
            "component_name": "=CMD|SkidTube!A0",
            "method_id": "cs29_skid_landing_gear_drop_energy",
            "inputs": dict(METHOD_DEFAULT_INPUTS["cs29_skid_landing_gear_drop_energy"]),
            "material_lookup": {
                "target_field": "yield_allowable_mpa",
                "material_id": "AL-7075-T651",
                "basis": "A",
                "temp_c": "50",
                "temp_uncertainty_c": "5",
            },
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
        {
            "check_id": "HERTZ-04",
            "component_name": "Swashplate Bearing",
            "method_id": "hertzian_bearing_contact_stress",
            "inputs": dict(METHOD_DEFAULT_INPUTS["hertzian_bearing_contact_stress"]),
        },
    ]

    dossier = build_stress_summary_dossier(
        "STRESS-H145-S5", checks, ledger=ledger, tenant_id="airbus", include_formal_proofs=True
    )
    assert dossier["check_count"] == 4
    assert dossier["passed_margin_count"] == 4
    assert dossier["formal_proved_count"] == 4
    assert dossier["overall_status"] == "ALL_MARGINS_POSITIVE"
    assert Decimal(dossier["global_ms_min"]) > Decimal("0")
    assert ledger.verify() is True

    sx = export_stress_dossier_xlsx(dossier, output_path=tmp_path / "stress.xlsx")
    assert sx["formula_count"] >= 15
    wb = load_workbook(io.BytesIO(sx["xlsx_bytes"]), data_only=False)
    assert str(wb["2_Component_Checks"]["B2"].value).startswith("'=")

    sp = export_stress_dossier_signed_pdf(dossier, output_path=tmp_path / "stress.pdf")
    assert (
        verify_quotation_signed_pdf(
            sp["pdf_bytes"], expected_public_key_pem=sp["public_key_pem"].encode("ascii")
        )["valid"]
        is True
    )

    # IQ/OQ Refresh check
    repo_root = Path(__file__).resolve().parents[1]
    iq_oq = run_iq_oq_qualification_suite(repo_root=repo_root)
    assert iq_oq["status"] == "PASS"
    iq_ids = {c["id"]: c for c in iq_oq["checks"]}
    assert iq_ids["IQ-05"]["passed"] is True
    assert iq_ids["OQ-05"]["passed"] is True
    assert iq_ids["OQ-06"]["passed"] is True

    # OpenAPI + FastAPI routes
    spec = yaml.safe_load((repo_root / "schemas" / "openapi.yaml").read_text(encoding="utf-8"))
    assert "/quotations/rotorcraft/portfolio-capacity/export-xlsx" in spec["paths"]
    assert "/quotations/rotorcraft/portfolio-capacity/export-pdf" in spec["paths"]
    assert "/calc/batch-stress-dossier" in spec["paths"]

    client = TestClient(create_app())
    r_px = client.post(
        "/quotations/rotorcraft/portfolio-capacity/export-xlsx",
        json={
            "tenant_id": "airbus",
            "rfq_specs": [
                {
                    "rfq_text": "CS-29 static & F&DT Net 60.",
                    "archetype_ids": ["Q-DES-02", "Q-STR-03"],
                },
                {"rfq_text": "CS-29 hoist Net 60.", "archetype_ids": ["Q-STR-03", "Q-DOA-02"]},
            ],
            "team_headcount": {"LEAD_CVE": 1, "STRESS_ENG": 2},
            "onshore_country": "DE",
            "nearshore_country": "ES",
        },
    )
    assert r_px.status_code == 200
    assert int(r_px.headers["X-AeroRegu-Formula-Count"]) >= 20

    r_pp = client.post(
        "/quotations/rotorcraft/portfolio-capacity/export-pdf",
        json={
            "tenant_id": "airbus",
            "rfq_specs": [
                {
                    "rfq_text": "CS-29 static & F&DT Net 60.",
                    "archetype_ids": ["Q-DES-02", "Q-STR-03"],
                },
            ],
        },
    )
    assert r_pp.status_code == 200
    assert verify_quotation_signed_pdf(r_pp.content)["valid"] is True

    r_sd = client.post(
        "/calc/batch-stress-dossier",
        json={
            "dossier_id": "API-STRESS-01",
            "tenant_id": "airbus",
            "record": True,
            "checks": checks[:2],
        },
    )
    assert r_sd.status_code == 200
    assert r_sd.json()["result"]["formal_proved_count"] == 2
    assert r_sd.json()["result"]["overall_status"] == "ALL_MARGINS_POSITIVE"

    # CLI quote portfolio-level --xlsx-out/--pdf-out + quote stress-dossier
    runner = CliRunner()
    cli_x = tmp_path / "cli_port.xlsx"
    cli_p = tmp_path / "cli_port.pdf"
    res_cli_port = runner.invoke(
        cli_app,
        [
            "quote",
            "portfolio-level",
            "--rfq-count",
            "2",
            "--country",
            "DE",
            "--onshore",
            "DE",
            "--nearshore",
            "ES",
            "--lead-cve",
            "1",
            "--xlsx-out",
            str(cli_x),
            "--pdf-out",
            str(cli_p),
            "--json",
        ],
    )
    assert res_cli_port.exit_code == 0, res_cli_port.output
    assert cli_x.is_file() and cli_p.is_file()

    cli_sx = tmp_path / "cli_stress.xlsx"
    cli_sp = tmp_path / "cli_stress.pdf"
    res_cli_sd = runner.invoke(
        cli_app,
        [
            "quote",
            "stress-dossier",
            "--dossier-id",
            "CLI-S5",
            "--xlsx-out",
            str(cli_sx),
            "--pdf-out",
            str(cli_sp),
            "--json",
        ],
    )
    assert res_cli_sd.exit_code == 0, res_cli_sd.output
    assert cli_sx.is_file() and cli_sp.is_file()
    sd_json = json.loads(res_cli_sd.output)
    assert sd_json["check_count"] == 4
    assert sd_json["formal_proved_count"] == 4

    # MCP 49+ tools + calls
    tools_list = handle_mcp_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(tools_list["result"]["tools"]) >= 49

    m1 = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "export_portfolio_capacity_oem_artifacts",
                "arguments": {
                    "onshore_country": "DE",
                    "nearshore_country": "ES",
                    "team_headcount": {"LEAD_CVE": 1, "STRESS_ENG": 2},
                    "xlsx_output_path": str(tmp_path / "mcp_p.xlsx"),
                    "pdf_output_path": str(tmp_path / "mcp_p.pdf"),
                },
            },
        }
    )
    assert m1["result"]["isError"] is False
    assert m1["result"]["structuredContent"]["cve_governance_preserved"] is True

    m2 = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "run_batch_stress_summary_dossier",
                "arguments": {
                    "dossier_id": "MCP-STRESS-01",
                    "checks": checks,
                    "xlsx_output_path": str(tmp_path / "mcp_s.xlsx"),
                    "pdf_output_path": str(tmp_path / "mcp_s.pdf"),
                },
            },
        }
    )
    assert m2["result"]["isError"] is False
    assert m2["result"]["structuredContent"]["overall_status"] == "ALL_MARGINS_POSITIVE"
    assert m2["result"]["structuredContent"]["formal_proved_count"] == 4
