"""Sprint 4 Mega-Suite: 52 Stress Cards, NAFEMS SOL105/GPFORCE/Abaqus, EVM/FX Exports, UI v3."""

from __future__ import annotations

import io
import json
import sys
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest
import yaml
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.formal_methods import METHOD_DEFAULT_INPUTS, run_formal_proof_for_method
from evidence_api.mcp_server import handle_mcp_message
from evidence_calc.errors import AbstainError
from evidence_calc.plugins import delete_plugin_card, validate_plugin_card
from evidence_calc.registry import list_method_ids, run_method
from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
from evidence_coverage.composite_dag_quotation import (
    CompositeRotorcraftQuotationSpec,
    run_composite_rotorcraft_quotation,
)
from evidence_coverage.nafems_audit import (
    audit_abaqus_composite_layup_vs_report,
    audit_gpforce_freebody_equilibrium,
    audit_sol105_buckling_margins,
    run_full_nafems_audit,
)
from evidence_coverage.pdf_report import _DSSE_ATTACHMENT_NAME
from evidence_coverage.quotation_exporter import (
    export_evm_postmortem_signed_pdf,
    export_evm_postmortem_xlsx,
    verify_quotation_signed_pdf,
)
from evidence_coverage.quotation_fx_hedging import evaluate_quotation_fx_hedging
from evidence_ingest.fem_parsers import parse_abaqus_inp, parse_nastran_bdf, parse_nastran_f06
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook
from typer.testing import CliRunner


def test_sprint4_1_five_new_cards_52_total_arb_z3_and_plugin_guard() -> None:
    """Verify complete 52-card catalog, plugin guard, 50-digit Arb bounds, & Z3 UNSAT/SAT proofs."""
    built_ins = list_method_ids(include_plugins=False)
    assert len(built_ins) >= 52

    new_cards = (
        "bolt_prying_combined_tension_shear",
        "goland_reissner_adhesive_peel_shear",
        "orthotropic_composite_plate_buckling",
        "skin_stringer_crippling_interaction",
        "walker_mean_stress_crack_growth",
    )
    for mid in new_cards:
        assert mid in built_ins
        with pytest.raises(AbstainError, match="builtin_method_protected"):
            validate_plugin_card(
                {
                    "method_id": mid,
                    "title": "Shadow Attempt",
                    "quantum": "0.01",
                    "required": ["x"],
                    "limits": {"x": {"min": "0", "max": "10"}},
                    "formulas": [{"output": "y", "expr": "x * 2"}],
                }
            )
        assert delete_plugin_card(mid) is False

        res = run_method(
            mid, METHOD_DEFAULT_INPUTS[mid], include_intervals=True, normalize_units=True
        )
        for field_name, iv in res["exact_intervals"].items():
            assert Decimal(str(iv["lower"])) <= Decimal(str(iv["upper"]))
            staged = str(iv["staged"])
            decs = len(staged.split(".", 1)[1]) if "." in staged else 0
            half_ulp = Decimal("10") ** (-decs) * Decimal("0.51")
            assert Decimal(str(iv["quantization_drift"])) <= half_ulp, (
                f"{mid}.{field_name} drift exceeded {half_ulp}: {iv['quantization_drift']}"
            )

        ok_proof = run_formal_proof_for_method(mid, METHOD_DEFAULT_INPUTS[mid])
        assert ok_proof["proved"] is True, f"{mid} failed default Z3 proof: {ok_proof}"
        assert ok_proof["status"] in ("PROVED", "PROVED_UNSAT")

    unsafe_cases = [
        ("bolt_prying_combined_tension_shear", {"applied_tension_n": ["28000", "32000"]}),
        (
            "goland_reissner_adhesive_peel_shear",
            {"tensile_load_per_width_n_mm": ["220", "250"]},
        ),
        ("orthotropic_composite_plate_buckling", {"nx_comp_n_per_mm": ["900", "1000"]}),
        ("skin_stringer_crippling_interaction", {"applied_compression_n": ["500000", "550000"]}),
        ("walker_mean_stress_crack_growth", {"required_cycles": ["250000", "300000"]}),
    ]
    for mid, bad_bounds in unsafe_cases:
        bad = run_formal_proof_for_method(mid, METHOD_DEFAULT_INPUTS[mid], bad_bounds)
        assert bad["proved"] is False
        assert bad["status"] == "COUNTEREXAMPLE_FOUND"
        assert bad["counterexample"] is not None


@given(
    kic=st.decimals(min_value=Decimal("28"), max_value=Decimal("55"), places=1),
    tension=st.decimals(min_value=Decimal("2000"), max_value=Decimal("12000"), places=1),
)
@settings(max_examples=20, deadline=None)
def test_sprint4_2_hypothesis_walker_and_prying_invariants(kic: Decimal, tension: Decimal) -> None:
    """Property test: higher Kic extends Walker life; higher tension raises bolt prying."""
    w_lo = run_method(
        "walker_mean_stress_crack_growth",
        {
            **METHOD_DEFAULT_INPUTS["walker_mean_stress_crack_growth"],
            "fracture_toughness_kic_mpa_sqrt_m": str(kic),
        },
    )
    w_hi = run_method(
        "walker_mean_stress_crack_growth",
        {
            **METHOD_DEFAULT_INPUTS["walker_mean_stress_crack_growth"],
            "fracture_toughness_kic_mpa_sqrt_m": str(kic + Decimal("8.0")),
        },
    )
    assert Decimal(w_hi["outputs"]["unfactored_life_cycles"]) > Decimal(
        w_lo["outputs"]["unfactored_life_cycles"]
    )

    p_lo = run_method(
        "bolt_prying_combined_tension_shear",
        {
            **METHOD_DEFAULT_INPUTS["bolt_prying_combined_tension_shear"],
            "applied_tension_n": str(tension),
        },
    )
    p_hi = run_method(
        "bolt_prying_combined_tension_shear",
        {
            **METHOD_DEFAULT_INPUTS["bolt_prying_combined_tension_shear"],
            "applied_tension_n": str(tension + Decimal("1500")),
        },
    )
    assert Decimal(p_hi["outputs"]["total_bolt_tension_n"]) > Decimal(
        p_lo["outputs"]["total_bolt_tension_n"]
    )


def test_sprint4_3_nafems_sol105_gpforce_abaqus_layup_audit() -> None:
    """Verify SOL 105 buckling, GPFORCE equilibrium, and Abaqus composite NAFEMS audit checks."""
    bdf_txt = (
        "$ UNITS: N_MM_T\n"
        "SOL 105\n"
        "SUBCASE 1\n"
        "  LABEL = COMPRESSION BUCKLING\n"
        "  LOAD = 10\n"
        "  SPC = 1\n"
        "BEGIN BULK\n"
        "GRID,1,,0.0,0.0,0.0\n"
        "GRID,2,,100.0,0.0,0.0\n"
        "PSHELL,1,1,2.5\n"
        "MAT1,1,71700.0,,0.33,2.8E-9\n"
        "CQUAD4,1,1,1,2,2,1\n"
        "FORCE,10,2,0,1000.0,0.0,0.0,1.0\n"
        "ENDDATA\n"
    )
    bdf_p = parse_nastran_bdf(bdf_txt.encode("utf-8"), "h-bdf")

    f06_pass = (
        "SOL 105 BUCKLING\n"
        "OLOAD RESULTANT\n"
        "SUBCASE 1   1.000000E+03  0.000000E+00  0.000000E+00  0.0  0.0  0.0\n"
        "SPCFORCE RESULTANT\n"
        "SUBCASE 1  -1.000000E+03  0.000000E+00  0.000000E+00  0.0  0.0  0.0\n"
        "GRID POINT WEIGHT GENERATOR\n"
        "TOTAL MASS = 1.250000E+01\n"
        "EPSILON = 1.000000E-11\n"
        "                         R E A L   E I G E N V A L U E S\n"
        "   MODE    EXTRACTION      EIGENVALUE\n"
        "      1         1       1.450000E+00\n"
        "      2         2       2.100000E+00\n"
        "                 G R I D   P O I N T   F O R C E   B A L A N C E\n"
        "   POINT-ID    ELEMENT-ID    SOURCE             T1             T2             T3"
        "             R1             R2             R3\n"
        "         1                  *TOTALS*     0.000000E+00   0.000000E+00   0.000000E+00"
        "   0.000000E+00   0.000000E+00   0.000000E+00\n"
    )
    f06_p = parse_nastran_f06(f06_pass.encode("utf-8"), "h-f06-ok")

    abq_txt = (
        "*HEADING\nSkin Panel\n"
        "*NODE\n1, 0.0, 0.0, 0.0\n2, 1.0, 0.0, 0.0\n"
        "*ELEMENT, TYPE=S4R, ELSET=SKIN_EL\n1, 1, 2, 2, 1\n"
        "*SHELL SECTION, ELSET=SKIN_EL, COMPOSITE\n"
        "0.125, 3, IM7_8552, 0.0\n"
        "0.125, 3, IM7_8552, 45.0\n"
        "0.125, 3, IM7_8552, -45.0\n"
        "0.125, 3, IM7_8552, 90.0\n"
    )
    abq_p = parse_abaqus_inp(abq_txt.encode("utf-8"), "h-abq")

    full_ok = run_full_nafems_audit(
        bdf_parsed=bdf_p,
        bdf_hash="h-bdf",
        f06_parsed=f06_p,
        f06_hash="h-f06-ok",
        check_buckling=True,
        min_buckling_factor="1.100",
        check_gpforce=True,
        abaqus_parsed=abq_p,
        abaqus_report_claims={"SKIN_EL": {"ply_count": 4, "total_thickness": "0.50"}},
    )
    assert full_ok["overall_pass"] is True
    assert full_ok["sol105_buckling"]["clear"] is True
    assert full_ok["gpforce_equilibrium"]["balanced"] is True
    assert full_ok["abaqus_composite_drift"]["consistent"] is True

    # Failing buckling (< 1.0), imbalanced GPFORCE (> 0.01 N), and Abaqus layup mismatch
    f06_fail = f06_pass.replace("1.450000E+00", "8.200000E-01").replace(
        "0.000000E+00   0.000000E+00   0.000000E+00",
        "1.250000E+02   0.000000E+00   0.000000E+00",
        1,
    )
    f06_f = parse_nastran_f06(f06_fail.encode("utf-8"), "h-f06-bad")
    assert audit_sol105_buckling_margins(f06_f)["clear"] is False
    assert audit_gpforce_freebody_equilibrium(f06_f)["balanced"] is False
    assert (
        audit_abaqus_composite_layup_vs_report(
            abq_p, report_claims={"SKIN_EL": {"ply_count": 8, "total_thickness": "1.00"}}
        )["consistent"]
        is False
    )


def test_sprint4_4_evm_fx_excel_and_dsse_signed_pdf_security(tmp_path: Path) -> None:
    """Verify EVM+FX live-formula Excel (CWE-1236 safe) & Ed25519 DSSE/QR signed PDF."""
    ledger = Ledger(tmp_path / "evm_exp.sqlite3", tenant_id="sprint4")
    base = run_composite_rotorcraft_quotation(
        ledger,
        CompositeRotorcraftQuotationSpec(
            rfq_id="RFQ-EXP-01",
            rfq_text="CS-29 frame static analysis Net 60.",
            archetype_ids=("Q-DES-02", "Q-STR-03", "Q-DOA-02"),
            country_code="ES",
            tenant_id="sprint4",
            created_at="2026-11-25T12:00:00Z",
        ),
    )
    evil_pid = '=CMD|" /C calc"!A0'
    pm = run_bid_actual_evm_postmortem(
        ledger,
        base,
        actuals=[{"archetype_id": "Q-STR-03", "actual_hours": "420", "earned_pct": "100"}],
        project_id=evil_pid,
        actual_ecn_iterations=4,
        idp_rework_hours="24",
        created_at="2026-11-25T12:05:00Z",
    )
    fx = evaluate_quotation_fx_hedging(
        quoted_price_eur=pm["evm_summary"]["quoted_selling_price_eur"],
        cost_eur=pm["evm_summary"]["bac_cost_eur"],
        billing_currency="USD",
        hedge_ratio_pct="90.000",
    )

    x_out = export_evm_postmortem_xlsx(pm, fx_report=fx, output_path=tmp_path / "evm_fx.xlsx")
    assert len(x_out["sheet_names"]) == 4
    assert x_out["formula_count"] >= 25
    wb = load_workbook(io.BytesIO(x_out["xlsx_bytes"]), data_only=False)
    assert str(wb["1_EVM_Summary"]["B4"].value).startswith("'")  # CWE-1236 neutralized
    assert str(wb["1_EVM_Summary"]["B7"].value).startswith("='2_WBS_Earned_Value'!")

    p_out = export_evm_postmortem_signed_pdf(
        pm, fx_report=fx, output_path=tmp_path / "evm_signed.pdf"
    )
    ver_ok = verify_quotation_signed_pdf(p_out["pdf_bytes"])
    assert ver_ok["valid"] is True

    # Tamper embedded DSSE envelope -> verify fails closed
    import base64

    doc = pymupdf.open(stream=p_out["pdf_bytes"], filetype="pdf")
    raw_dsse = doc.embfile_get(_DSSE_ATTACHMENT_NAME)
    dsse_obj = json.loads(raw_dsse.decode("utf-8"))
    altered_payload = base64.b64decode(dsse_obj["payload"]).replace(b'"cpi"', b'"cpi_x"')
    dsse_obj["payload"] = base64.b64encode(altered_payload).decode("ascii")
    tampered = json.dumps(dsse_obj).encode("utf-8")
    doc.embfile_del(_DSSE_ATTACHMENT_NAME)
    doc.embfile_add(_DSSE_ATTACHMENT_NAME, tampered, filename=_DSSE_ATTACHMENT_NAME)
    tampered_bytes = doc.tobytes()
    doc.close()
    assert verify_quotation_signed_pdf(tampered_bytes)["valid"] is False


def test_sprint4_5_api_openapi_cli_mcp47_and_cockpit_v3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify API EVM exports, NAFEMS SOL105 endpoint, OpenAPI parity, Cockpit v3, CLI & 47 MCP."""
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")
    monkeypatch.setenv("EVIDENCE_PRODUCTION", "0")

    repo_root = Path(__file__).resolve().parents[1]
    spec = yaml.safe_load((repo_root / "schemas" / "openapi.yaml").read_text(encoding="utf-8"))
    for p in (
        "/quotations/rotorcraft/evm-postmortem/export-xlsx",
        "/quotations/rotorcraft/evm-postmortem/export-pdf",
        "/nafems/audit-sol105-gpforce",
    ):
        assert p in spec["paths"]

    client = TestClient(create_app())
    html = client.get("/").text
    assert 'id="quote-abaqus-file"' in html
    assert 'id="quote-fx-evm-details"' in html
    assert 'id="quote-fx-table"' in html
    assert 'id="quote-evm-table"' in html
    assert "compliant" not in html.lower()
    assert "100" not in html

    js = client.get("/static/quotation_cockpit.js").text
    assert "runFxHedging" in js
    assert "runEvmPostmortem" in js
    assert "abaqus_text" in js

    xlsx_http = client.post(
        "/quotations/rotorcraft/evm-postmortem/export-xlsx",
        json={"tenant_id": "demo", "project_id": "API-EVM-01", "billing_currency": "USD"},
    )
    assert xlsx_http.status_code == 200
    assert "X-AeroRegu-SHA256" in xlsx_http.headers

    pdf_http = client.post(
        "/quotations/rotorcraft/evm-postmortem/export-pdf",
        json={"tenant_id": "demo", "project_id": "API-EVM-01", "billing_currency": "GBP"},
    )
    assert pdf_http.status_code == 200
    assert verify_quotation_signed_pdf(pdf_http.content)["valid"] is True

    f06_sample = (
        "SOL 105 BUCKLING\n"
        "                         R E A L   E I G E N V A L U E S\n"
        "   MODE    EXTRACTION      EIGENVALUE\n"
        "      1         1       1.350000E+00\n"
        "                 G R I D   P O I N T   F O R C E   B A L A N C E\n"
        "         1                  *TOTALS*     0.000000E+00   0.000000E+00   0.000000E+00"
        "   0.000000E+00   0.000000E+00   0.000000E+00\n"
    )
    naf_res = client.post("/nafems/audit-sol105-gpforce", json={"f06_text": f06_sample})
    assert naf_res.status_code == 200
    assert naf_res.json()["result"]["overall_pass"] is True
    assert naf_res.json()["result"]["sol105_buckling"]["clear"] is True
    assert naf_res.json()["result"]["gpforce_equilibrium"]["balanced"] is True

    # CLI checks
    f06_p = tmp_path / "b.f06"
    f06_p.write_text(f06_sample, encoding="utf-8")
    runner = CliRunner()
    old_argv = sys.argv
    try:
        sys.argv = ["aeroregu"]
        evm_cli = runner.invoke(
            cli_app,
            [
                "quote",
                "evm-postmortem",
                "--project-id",
                "CLI-EVM-4",
                "--xlsx-out",
                str(tmp_path / "cli_evm.xlsx"),
                "--pdf-out",
                str(tmp_path / "cli_evm.pdf"),
                "--json",
            ],
        )
        assert evm_cli.exit_code == 0, evm_cli.output
        assert (tmp_path / "cli_evm.xlsx").is_file()
        assert verify_quotation_signed_pdf((tmp_path / "cli_evm.pdf").read_bytes())["valid"] is True

        fem_cli = runner.invoke(
            cli_app, ["quote", "fem-vv-audit", "--f06-file", str(f06_p), "--json"]
        )
        assert fem_cli.exit_code == 0, fem_cli.output
        assert json.loads(fem_cli.output)["sol105_buckling"]["clear"] is True
    finally:
        sys.argv = old_argv

    # MCP 47 tools + execution + prod auth check
    mcp_list = handle_mcp_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(mcp_list["result"]["tools"]) >= 47

    mcp_fem = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "audit_fem_sol105_gpforce_abaqus",
                "arguments": {"f06_text": f06_sample},
            },
        }
    )
    assert mcp_fem["result"]["isError"] is False
    assert mcp_fem["result"]["structuredContent"]["sol105_buckling"]["clear"] is True

    blocked_exp = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "export_evm_postmortem_oem_artifacts", "arguments": {}},
        },
        require_auth_for_writes=True,
        is_authenticated=False,
    )
    assert blocked_exp["result"]["isError"] is True
    assert blocked_exp["result"]["structuredContent"]["error"] == "auth_required"
