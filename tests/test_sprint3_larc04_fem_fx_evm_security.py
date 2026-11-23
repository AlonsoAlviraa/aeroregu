"""Sprint 3 Mega-Suite: Plugin Guard, 5 Stress Cards (Arb+Z3+Hyp), FEM, FX+Z3, EVM."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.formal_methods import run_formal_proof_for_method
from evidence_api.mcp_server import handle_mcp_message
from evidence_calc.allowables import (
    allowable_catalog_sha256,
    list_materials,
    lookup_allowable,
)
from evidence_calc.errors import AbstainError
from evidence_calc.plugins import delete_plugin_card, validate_plugin_card
from evidence_calc.registry import list_method_ids, run_method
from evidence_coverage.advanced_quotation_calibration import run_advanced_calibration_suite
from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
from evidence_coverage.composite_dag_quotation import (
    CompositeRotorcraftQuotationSpec,
    run_composite_rotorcraft_quotation,
)
from evidence_coverage.deep_idp_quotation_extractor import extract_deep_idp_engineering_package
from evidence_coverage.historical_quotation_calibrator import (
    HistoricalQuotationRecord,
    generate_reference_historical_corpus,
)
from evidence_coverage.quotation_fx_hedging import evaluate_quotation_fx_hedging
from evidence_ingest.fem_parsers import parse_abaqus_inp, parse_nastran_f06
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner


def test_sprint3_1_plugin_shadowing_fix_and_expanded_allowables() -> None:
    """Protect all built-in cards against plugin shadowing & validate 8 MMPDS/CMH-17 materials."""
    protected_samples = (
        "bolt_screen",
        "clt_laminate_abd_stiffness",
        "rotor_blade_centrifugal_bending",
        "larc04_composite_failure",
        "aerospace_multiyear_cashflow_learning",
    )
    for mid in protected_samples:
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

    mats = list_materials()
    assert len(mats) >= 8
    for mat_id in ("AL-LI-2198-T8", "AS4-8552-PW", "T800-M21-UD"):
        assert mat_id in mats

    al_li_a = lookup_allowable(
        "AL-LI-2198-T8", basis="A", property_name="fty_mpa", environment="RTD"
    )
    al_li_b = lookup_allowable(
        "AL-LI-2198-T8", basis="B", property_name="fty_mpa", environment="RTD"
    )
    t800_etw = lookup_allowable(
        "T800-M21-UD",
        basis="A",
        property_name="fcy_mpa",
        thickness_mm="18",
        temp_c="80",
        environment="ETW",
    )
    t800_rtd = lookup_allowable(
        "T800-M21-UD", basis="A", property_name="fcy_mpa", environment="RTD"
    )
    assert Decimal(al_li_b["allowable_value_mpa"]) > Decimal(al_li_a["allowable_value_mpa"])
    assert Decimal(t800_etw["allowable_value_mpa"]) < Decimal(t800_rtd["allowable_value_mpa"])
    assert t800_etw["catalog_sha256"] == allowable_catalog_sha256()


def test_sprint3_2_five_new_cards_arb_intervals_and_z3_counterexamples() -> None:
    """Verify all 47 built-in cards, Arb 50-digit half-ULP precision, & Z3 UNSAT/SAT proofs."""
    built_ins = list_method_ids(include_plugins=False)
    assert len(built_ins) == 47

    samples: dict[str, dict[str, str]] = {
        "larc04_composite_failure": {
            "sigma_1_mpa": "-380",
            "sigma_2_mpa": "-42",
            "tau_12_mpa": "28",
            "x_t_mpa": "2200",
            "x_c_mpa": "1350",
            "y_t_mpa": "60",
            "y_c_mpa": "220",
            "s_l_mpa": "85",
            "alpha_0_deg": "53",
            "eta_l": "0.28",
            "g_12_mpa": "4700",
            "phi_0_deg": "1.5",
        },
        "cs29_bird_strike_penetration_screen": {
            "bird_mass_kg": "1.0",
            "impact_velocity_m_s": "75",
            "bird_density_kg_m3": "950",
            "bird_diameter_mm": "120",
            "panel_thickness_mm": "6.5",
            "panel_shear_allowable_mpa": "180",
            "safety_factor": "1.5",
        },
        "campbell_rotor_harmonic_clearance": {
            "omega_min_rpm": "360",
            "omega_max_rpm": "400",
            "blade_count": "4",
            "structural_freq_hz": "38.5",
            "min_clearance_pct": "10",
        },
        "tailboom_boxbeam_combined_stress": {
            "bending_moment_n_m": "18500",
            "torque_n_m": "9200",
            "transverse_shear_n": "14000",
            "box_width_mm": "320",
            "box_height_mm": "420",
            "skin_thickness_mm": "2.2",
            "cap_area_mm2": "340",
            "yield_allowable_mpa": "310",
            "shear_buckling_allowable_mpa": "95",
            "safety_factor": "1.5",
        },
        "statistical_ab_basis_tolerance_bound": {
            "sample_count": "30",
            "sample_mean_mpa": "620",
            "sample_std_mpa": "24",
            "design_stress_mpa": "420",
        },
    }

    for mid, inp in samples.items():
        res = run_method(mid, inp, include_intervals=True, normalize_units=True)
        assert res["method_id"] == mid
        for field_name, iv in res["exact_intervals"].items():
            assert Decimal(str(iv["lower"])) <= Decimal(str(iv["upper"]))
            staged = str(iv["staged"])
            decs = len(staged.split(".", 1)[1]) if "." in staged else 0
            half_ulp = Decimal("10") ** (-decs) * Decimal("0.51")
            assert Decimal(str(iv["quantization_drift"])) <= half_ulp, (
                f"{mid}.{field_name} exceeded half-ULP: {iv['quantization_drift']}"
            )

        # Safe Z3 formal envelope check
        ok_proof = run_formal_proof_for_method(mid, inp)
        assert ok_proof["proved"] is True, f"{mid} failed safe proof: {ok_proof}"
        assert ok_proof["status"] in ("PROVED", "PROVED_UNSAT")

    # Unsafe counterexample proofs for each of the 5 methods
    unsafe_cases = [
        ("larc04_composite_failure", {"sigma_2_mpa": ["70", "90"]}),
        ("cs29_bird_strike_penetration_screen", {"panel_thickness_mm": ["0.5", "1.0"]}),
        ("campbell_rotor_harmonic_clearance", {"structural_freq_hz": ["25.0", "27.0"]}),
        ("tailboom_boxbeam_combined_stress", {"bending_moment_n_m": ["900000", "950000"]}),
        ("statistical_ab_basis_tolerance_bound", {"design_stress_mpa": ["590", "610"]}),
    ]
    for mid, bad_bounds in unsafe_cases:
        bad_proof = run_formal_proof_for_method(mid, samples[mid], bad_bounds)
        assert bad_proof["proved"] is False
        assert bad_proof["status"] == "COUNTEREXAMPLE_FOUND"
        assert bad_proof["counterexample"] is not None


@given(
    vel=st.decimals(min_value=Decimal("40"), max_value=Decimal("160"), places=1),
    panel_t=st.decimals(min_value=Decimal("1.5"), max_value=Decimal("25.0"), places=2),
    n_samples=st.integers(min_value=12, max_value=200),
)
@settings(max_examples=20, deadline=None)
def test_sprint3_3_hypothesis_monotonicity_properties(
    vel: Decimal, panel_t: Decimal, n_samples: int
) -> None:
    """Property test: bird-strike KE ~ v^2 and A-basis k_A decreases monotonically with n."""
    r1 = run_method(
        "cs29_bird_strike_penetration_screen",
        {
            "bird_mass_kg": "1.0",
            "impact_velocity_m_s": str(vel),
            "bird_density_kg_m3": "950",
            "bird_diameter_mm": "120",
            "panel_thickness_mm": str(panel_t),
            "panel_shear_allowable_mpa": "180",
            "safety_factor": "1.5",
        },
    )
    r2 = run_method(
        "cs29_bird_strike_penetration_screen",
        {
            "bird_mass_kg": "1.0",
            "impact_velocity_m_s": str(vel),
            "bird_density_kg_m3": "950",
            "bird_diameter_mm": "120",
            "panel_thickness_mm": str(panel_t + Decimal("2.0")),
            "panel_shear_allowable_mpa": "180",
            "safety_factor": "1.5",
        },
    )
    assert Decimal(r2["outputs"]["margin_of_safety"]) > Decimal(r1["outputs"]["margin_of_safety"])

    s_lo = run_method(
        "statistical_ab_basis_tolerance_bound",
        {
            "sample_count": str(n_samples),
            "sample_mean_mpa": "600",
            "sample_std_mpa": "20",
            "design_stress_mpa": "350",
        },
    )
    s_hi = run_method(
        "statistical_ab_basis_tolerance_bound",
        {
            "sample_count": str(n_samples + 10),
            "sample_mean_mpa": "600",
            "sample_std_mpa": "20",
            "design_stress_mpa": "350",
        },
    )
    assert Decimal(s_hi["outputs"]["k_a_factor"]) < Decimal(s_lo["outputs"]["k_a_factor"])
    assert Decimal(s_hi["outputs"]["a_basis_mpa"]) > Decimal(s_lo["outputs"]["a_basis_mpa"])


def test_sprint3_4_fem_sol105_gpforce_abaqus_include_composite_and_deep_idp(
    tmp_path: Path,
) -> None:
    """Verify SOL 105 buckling, GPFORCE freebody, Abaqus *INCLUDE/*SHELL SECTION COMPOSITE & IDP."""
    f06_text = (
        "NASTRAN EXECUTIVE CONTROL DECK: SOL 105 BUCKLING\n"
        "                         R E A L   E I G E N V A L U E S\n"
        "   MODE    EXTRACTION      EIGENVALUE\n"
        "    NO.       ORDER\n"
        "      1         1       8.800000E-01\n"
        "      2         2       1.420000E+00\n"
        "                 G R I D   P O I N T   F O R C E   B A L A N C E\n"
        "   POINT-ID    ELEMENT-ID    SOURCE             T1             T2             T3"
        "             R1             R2             R3\n"
        "         10                  APP-LOAD     0.000000E+00   0.000000E+00   5.000000E+03"
        "   0.000000E+00   0.000000E+00   0.000000E+00\n"
        "         10       201        CQUAD4       0.000000E+00   0.000000E+00  -5.000000E+03"
        "   0.000000E+00   0.000000E+00   0.000000E+00\n"
        "         10                  *TOTALS*     0.000000E+00   0.000000E+00   0.000000E+00"
        "   0.000000E+00   0.000000E+00   0.000000E+00\n"
    )
    f06_parsed = parse_nastran_f06(f06_text.encode("utf-8"), "hash-f06")
    assert f06_parsed["modal_eigenvalues"] == []
    assert len(f06_parsed["buckling_eigenvalues"]) == 2
    assert Decimal(f06_parsed["critical_buckling_factor"]) == Decimal("0.88")
    assert Decimal(f06_parsed["buckling_ms_min"]) == Decimal("-0.12")
    assert f06_parsed["gpforce_freebody"]["freebody_balanced"] is True
    assert f06_parsed["gpforce_freebody"]["grid_count"] == 1

    # Abaqus sandboxed *INCLUDE + traversal block + *SHELL SECTION, COMPOSITE
    abq_dir = tmp_path / "abq_model"
    sub_dir = abq_dir / "parts"
    sub_dir.mkdir(parents=True)
    outside = tmp_path / "secret.inp"
    outside.write_text("*NODE\n999, 0.0, 0.0, 0.0\n", encoding="utf-8")

    (sub_dir / "laminate_panel.inp").write_text(
        "*NODE, NSET=SKIN_N\n"
        "1, 0.0, 0.0, 0.0\n"
        "2, 1.0, 0.0, 0.0\n"
        "3, 1.0, 1.0, 0.0\n"
        "4, 0.0, 1.0, 0.0\n"
        "*ELEMENT, TYPE=S4R, ELSET=SKIN_EL\n"
        "10, 1, 2, 3, 4\n"
        "*SHELL SECTION, ELSET=SKIN_EL, COMPOSITE\n"
        "0.125, 3, IM7_8552, 0.0\n"
        "0.125, 3, IM7_8552, 45.0\n"
        "0.125, 3, IM7_8552, -45.0\n"
        "0.125, 3, IM7_8552, 90.0\n",
        encoding="utf-8",
    )
    master_inp = abq_dir / "master.inp"
    master_inp.write_text(
        "*HEADING\nComposite Tailboom Skin\n"
        "*INCLUDE, INPUT=parts/laminate_panel.inp\n"
        "*INCLUDE, INPUT=../secret.inp\n"
        "*STEP, NAME=LIMIT_LOAD\n"
        "*CLOAD\n"
        "2, 3, 4500.0\n"
        "*END STEP\n",
        encoding="utf-8",
    )
    abq_parsed = parse_abaqus_inp(master_inp.read_bytes(), "hash-abq", base_dir=abq_dir)
    # Path traversal include is rejected; sandboxed include is expanded
    assert len(abq_parsed["include_tree"]) == 1
    assert abq_parsed["include_tree"][0]["relative_path"] == "parts/laminate_panel.inp"
    assert abq_parsed["mesh"]["node_count"] == 4
    assert "999" not in {n["id"] for n in abq_parsed["mesh"]["nodes"]}
    assert len(abq_parsed["composite_sections"]) == 1
    assert abq_parsed["composite_sections"][0]["ply_count"] == 4
    assert Decimal(abq_parsed["composite_sections"][0]["total_thickness"]) == Decimal("0.5")

    deep = extract_deep_idp_engineering_package(
        {"abaqus_path": str(master_inp), "f06_text": f06_text}
    )
    assert deep["abaqus_summary"]["present"] is True
    assert deep["abaqus_summary"]["total_composite_plies"] == 4
    assert deep["f06_audit"]["buckling_modes_count"] == 2
    assert Decimal(deep["f06_audit"]["critical_buckling_factor"]) == Decimal("0.88")
    assert Decimal(deep["estimated_solve_postproc_hours"]) >= Decimal("14.00")


def test_sprint3_5_fx_hedging_z3_smt_and_evm_postmortem_calibration_loop(
    tmp_path: Path,
) -> None:
    """Verify Multi-Currency FX Z3 margin proof & closed-loop Bid-to-Actual EVM post-mortem."""
    fx_hedged = evaluate_quotation_fx_hedging(
        quoted_price_eur="500000",
        cost_eur="375000",
        billing_currency="USD",
        cost_currency="EUR",
        hedge_ratio_pct="90.000",
        fx_shock_band_pct="10.000",
        cost_drift_band_pct="5.000",
        min_acceptable_margin_pct="15.000",
    )
    assert fx_hedged["formal_fx_margin_proof"]["status"] == "PROVED_UNSAT"
    assert fx_hedged["formal_fx_margin_proof"]["proved"] is True
    assert len(fx_hedged["sensitivity_scenarios"]) == 5

    fx_unhedged = evaluate_quotation_fx_hedging(
        quoted_price_eur="500000",
        cost_eur="375000",
        billing_currency="USD",
        cost_currency="EUR",
        hedge_ratio_pct="0.000",
        fx_shock_band_pct="10.000",
        cost_drift_band_pct="5.000",
        min_acceptable_margin_pct="15.000",
    )
    assert fx_unhedged["formal_fx_margin_proof"]["status"] == "COUNTEREXAMPLE_FOUND"
    assert fx_unhedged["formal_fx_margin_proof"]["proved"] is False
    assert fx_unhedged["formal_fx_margin_proof"]["counterexample"] is not None

    ledger = Ledger(tmp_path / "evm.sqlite3", tenant_id="sprint3")
    base_dossier = run_composite_rotorcraft_quotation(
        ledger,
        CompositeRotorcraftQuotationSpec(
            rfq_id="RFQ-EVM-BASE",
            rfq_text="CS-29 metallic fitting static analysis Net 60.",
            archetype_ids=("Q-DES-02", "Q-STR-03", "Q-DOA-02"),
            country_code="ES",
            tenant_id="sprint3",
            created_at="2026-11-23T12:00:00Z",
        ),
    )
    nodes = base_dossier["composite_wbs_dag"]["nodes"]
    # Simulate cost/hours overrun on Q-STR-03
    csv_lines = ["archetype_id,actual_hours,earned_pct,broken_assumptions"]
    for n in nodes:
        aid = n["archetype_id"]
        h = Decimal(n["net_hours"])
        if aid == "Q-STR-03":
            h = (h * Decimal("1.35")).quantize(Decimal("0.01"))
            csv_lines.append(f"{aid},{h},100,ASM-IDP-01;ASM-TS-01")
        else:
            csv_lines.append(f"{aid},{h},100,")

    pm = run_bid_actual_evm_postmortem(
        ledger,
        base_dossier,
        actuals_csv="\n".join(csv_lines),
        project_id="PROJ-H145-HOIST",
        actual_ecn_iterations=4,
        idp_rework_hours="45",
        unbilled_scope_hours="30",
        created_at="2026-11-23T12:05:00Z",
    )
    assert Decimal(pm["evm_summary"]["cpi"]) < Decimal("1.000")
    assert pm["health_status"] in ("WATCH_VARIANCE", "OVERRUN_CALIBRATION_ALERT")
    asm_ids = {a["assumption_id"] for a in pm["broken_assumptions_attributed"]}
    assert {"ASM-IDP-01", "ASM-SCH-01", "ASM-TS-01"}.issubset(asm_ids)
    assert ledger.verify_incremental(from_latest_checkpoint=False)["ok"] is True

    # Closed loop: feed post-mortem historical records into advanced calibration
    rec_objs = [
        HistoricalQuotationRecord(
            **{
                **r,
                "broken_assumption_ids": tuple(r["broken_assumption_ids"]),
            }
        )
        for r in pm["calibrated_historical_records"]
    ]
    assert len(rec_objs) == len(nodes)
    mixed_corpus = list(generate_reference_historical_corpus(216)) + rec_objs
    cal_res = run_advanced_calibration_suite(
        corpus=mixed_corpus, archetype_id="Q-STR-03", country_code="ES"
    )
    assert Decimal(cal_res["kfold_cv"]["global_post_mape_pct"]) < Decimal(
        cal_res["kfold_cv"]["global_pre_mape_pct"]
    )


def test_sprint3_6_api_cli_and_mcp_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify FastAPI FX & EVM routes, production auth guard, CLI subcommands, and 45 MCP tools."""
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")
    monkeypatch.setenv("EVIDENCE_PRODUCTION", "0")

    client = TestClient(create_app())
    fx_resp = client.post(
        "/quotations/rotorcraft/fx-hedging",
        json={
            "quoted_price_eur": "500000",
            "cost_eur": "375000",
            "billing_currency": "USD",
            "hedge_ratio_pct": "90.000",
        },
    )
    assert fx_resp.status_code == 200
    assert fx_resp.json()["result"]["formal_fx_margin_proof"]["status"] == "PROVED_UNSAT"

    evm_resp = client.post(
        "/quotations/rotorcraft/evm-postmortem",
        json={
            "tenant_id": "demo",
            "project_id": "API-POST-01",
            "actual_ecn_iterations": 3,
            "actuals": [{"archetype_id": "Q-STR-03", "actual_hours": "320", "earned_pct": "100"}],
        },
    )
    assert evm_resp.status_code == 200
    assert evm_resp.json()["result"]["project_id"] == "API-POST-01"

    # CLI check
    runner = CliRunner()
    old_argv = sys.argv
    try:
        sys.argv = ["aeroregu"]
        fx_cli = runner.invoke(cli_app, ["quote", "fx-hedge", "--hedge-pct", "90", "--json"])
        assert fx_cli.exit_code == 0, fx_cli.output
        assert json.loads(fx_cli.output)["formal_fx_margin_proof"]["status"] == "PROVED_UNSAT"

        evm_cli = runner.invoke(
            cli_app, ["quote", "evm-postmortem", "--project-id", "CLI-POST-01", "--json"]
        )
        assert evm_cli.exit_code == 0, evm_cli.output
        assert json.loads(evm_cli.output)["project_id"] == "CLI-POST-01"
    finally:
        sys.argv = old_argv

    # MCP checks (45 tools + unauthenticated write gate for EVM postmortem in production mode)
    mcp_list = handle_mcp_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert mcp_list is not None
    assert len(mcp_list["result"]["tools"]) == 45

    mcp_fx = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "evaluate_quotation_fx_hedging",
                "arguments": {"billing_currency": "GBP", "hedge_ratio_pct": "90"},
            },
        }
    )
    assert mcp_fx["result"]["isError"] is False
    assert mcp_fx["result"]["structuredContent"]["billing_currency"] == "GBP"

    blocked_evm = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "run_bid_actual_evm_postmortem",
                "arguments": {"tenant_id": "demo"},
            },
        },
        require_auth_for_writes=True,
        is_authenticated=False,
    )
    assert blocked_evm["result"]["isError"] is True
    assert blocked_evm["result"]["structuredContent"]["error"] == "auth_required"
