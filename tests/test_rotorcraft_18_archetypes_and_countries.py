"""E2E tests for 18 helicopter archetypes, 9 countries, 6 models & 10-dim assumptions."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.mcp_server import handle_mcp_message
from evidence_calc.errors import AbstainError
from evidence_calc.registry import list_method_ids, run_method
from evidence_coverage.repo_web_scraper import QuotationIntelligenceScraper
from evidence_coverage.rotorcraft_quotation_catalog import (
    COUNTRY_RATE_CARDS,
    RESEARCH_BENCHMARK_MODELS,
    ROTORCRAFT_ASSUMPTION_DIMENSIONS,
    ROTORCRAFT_MASTER_ASSUMPTIONS,
    ROTORCRAFT_QUOTATION_ARCHETYPES,
    RotorcraftQuotationSpec,
    classify_rotorcraft_rfq,
    get_rotorcraft_catalog,
    run_rotorcraft_department_quotation,
)
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner


def test_rotorcraft_calc_card_and_arb_intervals_and_cve_floor() -> None:
    assert "rotorcraft_archetype_quote" in list_method_ids()

    base_inputs = {
        "cad_hours": "100.000",
        "loads_hours": "80.000",
        "stress_hours": "200.000",
        "fdt_dyn_hours": "60.000",
        "systems_hours": "40.000",
        "test_hours": "20.000",
        "cve_hours": "10.000",  # Intentionally below 12% of 500 -> floor enforced
        "proto_hours": "0.000",
        "cad_rate": "88.000",
        "loads_rate": "108.000",
        "stress_rate": "112.000",
        "fdt_dyn_rate": "122.000",
        "systems_rate": "115.000",
        "test_rate": "102.000",
        "cve_rate": "138.000",
        "proto_rate": "85.000",
        "cert_basis_factor": "1.350",
        "material_complexity_factor": "1.250",
        "cosysmo_driver_factor": "1.100",
        "pvt_compression_factor": "0.950",
        "hpc_hours": "200.000",
        "hpc_rate": "18.000",
        "travel_hardware_eur": "2500.000",
        "overhead_pct": "12.000",
        "contingency_pct": "10.000",
        "margin_pct": "22.000",
        "fixed_price_share_pct": "70.000",
        "cve_min_ratio_pct": "12.000",
    }
    res = run_method("rotorcraft_archetype_quote", base_inputs, include_intervals=True)
    out = res["outputs"]
    assert res["diagnostics"]["cve_floor_enforced"] is True
    assert Decimal(out["quote_price_eur"]) > Decimal(out["total_cost_eur"])
    assert (
        Decimal(out["fixed_price_tranche_eur"])
        + Decimal(out["capped_tm_tranche_eur"])
        - Decimal(out["quote_price_eur"])
    ).copy_abs() <= Decimal("0.001")
    assert Decimal(out["gross_margin_pct"]) == Decimal("22.000")

    # Verify tight FLINT/Arb interval bounds across all numeric outputs
    intervals = res["exact_intervals"]
    assert len(intervals) == len(out)
    for k, entry in intervals.items():
        assert Decimal(entry["lower"]) <= Decimal(entry["mid"]) <= Decimal(entry["upper"])
        assert Decimal(entry["quantization_drift"]) <= Decimal("0.001")

    zero_inp = dict(
        base_inputs,
        cad_hours="0",
        loads_hours="0",
        stress_hours="0",
        fdt_dyn_hours="0",
        systems_hours="0",
        test_hours="0",
        cve_hours="0",
        proto_hours="0",
    )
    with pytest.raises(AbstainError):
        run_method("rotorcraft_archetype_quote", zero_inp)


@given(
    stress_h=st.decimals(min_value="50", max_value="800", places=2),
    cert_f=st.decimals(min_value="1.00", max_value="1.50", places=2),
    mat_f=st.decimals(min_value="1.00", max_value="1.75", places=2),
    margin=st.decimals(min_value="5", max_value="40", places=2),
)
@settings(max_examples=20, deadline=None)
def test_rotorcraft_calc_hypothesis_monotonicity(
    stress_h: Decimal,
    cert_f: Decimal,
    mat_f: Decimal,
    margin: Decimal,
) -> None:
    inp_low = {
        "cad_hours": "60.000",
        "loads_hours": "40.000",
        "stress_hours": str(stress_h),
        "fdt_dyn_hours": "30.000",
        "systems_hours": "20.000",
        "test_hours": "10.000",
        "cve_hours": "25.000",
        "proto_hours": "0.000",
        "cad_rate": "88.000",
        "loads_rate": "108.000",
        "stress_rate": "112.000",
        "fdt_dyn_rate": "122.000",
        "systems_rate": "115.000",
        "test_rate": "102.000",
        "cve_rate": "138.000",
        "proto_rate": "85.000",
        "cert_basis_factor": "1.000",
        "material_complexity_factor": "1.000",
        "cosysmo_driver_factor": "1.000",
        "pvt_compression_factor": "1.000",
        "hpc_hours": "100.000",
        "hpc_rate": "18.000",
        "travel_hardware_eur": "1500.000",
        "overhead_pct": "12.000",
        "contingency_pct": "10.000",
        "margin_pct": str(margin),
        "fixed_price_share_pct": "70.000",
        "cve_min_ratio_pct": "10.000",
    }
    inp_hi = dict(
        inp_low,
        cert_basis_factor=str(cert_f),
        material_complexity_factor=str(mat_f),
    )
    out_lo = run_method("rotorcraft_archetype_quote", inp_low, include_intervals=False)["outputs"]
    out_hi = run_method("rotorcraft_archetype_quote", inp_hi, include_intervals=False)["outputs"]
    assert Decimal(out_hi["quote_price_eur"]) >= Decimal(out_lo["quote_price_eur"])
    assert Decimal(out_hi["scaled_engineering_hours"]) >= Decimal(
        out_lo["scaled_engineering_hours"]
    )


def test_catalog_counts_and_research_structure() -> None:
    cat = get_rotorcraft_catalog()
    assert cat["default_country_code"] == "EU_DEFAULT"
    assert len(COUNTRY_RATE_CARDS) == 9
    assert len(ROTORCRAFT_QUOTATION_ARCHETYPES) == 18
    assert len(RESEARCH_BENCHMARK_MODELS) == 6
    assert len(ROTORCRAFT_ASSUMPTION_DIMENSIONS) == 10
    assert len(ROTORCRAFT_MASTER_ASSUMPTIONS) >= 40


@pytest.mark.parametrize("archetype_id", list(ROTORCRAFT_QUOTATION_ARCHETYPES.keys()))
def test_all_18_rotorcraft_archetypes_end_to_end(tmp_path: Path, archetype_id: str) -> None:
    ledger = Ledger(tmp_path / f"ledger_{archetype_id}.db", tenant_id="demo")
    arch = ROTORCRAFT_QUOTATION_ARCHETYPES[archetype_id]
    spec = RotorcraftQuotationSpec(
        rfq_text=f"CS-29 Helicopter workpackage for {archetype_id}: {arch['title']}",
        country_code="EU_DEFAULT",
        archetype_id=archetype_id,
        rfq_id=f"RFQ-{archetype_id}",
    )
    dossier = run_rotorcraft_department_quotation(ledger, spec)

    assert dossier["confidence"] == "deterministic"
    assert dossier["decision_status"] == "APPROVED_FOR_HUMAN_REVIEW"
    assert dossier["archetype"]["archetype_id"] == archetype_id
    assert dossier["assumptions_dimensions_count"] == 10
    assert dossier["assumptions_total_count"] >= 40
    assert len(dossier["agent_trace"]) == 8
    assert dossier["formal_margin_proof"]["status"] == "PROVED_UNSAT"
    assert len(dossier["multi_country_comparison"]["countries"]) == 9
    assert len(dossier["tornado_sensitivity"]) >= 5

    pert = dossier["pert_envelope"]
    assert Decimal(pert["price_p50_eur"]) <= Decimal(pert["price_p80_eur"])
    assert Decimal(pert["price_p80_eur"]) <= Decimal(pert["price_p90_eur"])

    assert ledger.verify() is True


@pytest.mark.parametrize("country_code", list(COUNTRY_RATE_CARDS.keys()))
def test_all_9_country_rate_cards_and_ranking(tmp_path: Path, country_code: str) -> None:
    ledger = Ledger(tmp_path / f"ledger_{country_code}.db", tenant_id="demo")
    spec = RotorcraftQuotationSpec(
        rfq_text="CS-29 Full airframe GFEM and static DFEM stress dossier for helicopter fuselage.",
        country_code=country_code,
        archetype_id="Q-STR-03",
        rfq_id=f"RFQ-{country_code}",
    )
    dossier = run_rotorcraft_department_quotation(ledger, spec)
    assert dossier["confidence"] == "deterministic"
    assert dossier["country_profile"]["country_code"] == country_code
    assert dossier["formal_margin_proof"]["status"] == "PROVED_UNSAT"

    comp = dossier["multi_country_comparison"]
    prices = {row["country_code"]: Decimal(row["quote_price_eur"]) for row in comp["countries"]}
    assert prices["US"] > prices["DE"] > prices["FR"] > prices["EU_DEFAULT"]
    assert prices["EU_DEFAULT"] > prices["IT"] > prices["ES"] > prices["PL"] > prices["IN"]

    hyb = comp["onshore_nearshore_hybrid"]
    assert Decimal(hyb["quote_price_eur"]) < prices[hyb["onshore_cve_country"]]


def test_research_benchmark_model_drivers(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "research.db", tenant_id="demo")

    def _run(**kw: str) -> Decimal:
        spec = RotorcraftQuotationSpec(
            rfq_text="Rotorcraft composite fuselage DFEM static sizing.",
            archetype_id="Q-STR-03",
            country_code="EU_DEFAULT",
            **kw,  # type: ignore[arg-type]
        )
        return Decimal(
            run_rotorcraft_department_quotation(ledger, spec)["pert_envelope"]["price_p80_eur"]
        )

    # NASA NDARC / EASA basis: CS-29 > CS-27
    assert _run(cert_basis="CS-29") > _run(cert_basis="CS-27")
    # RAND NAFCOM: CFRP > Ti > Hybrid > Aluminum
    p_al = _run(material_family="ALUMINUM_2024_7075")
    p_hyb = _run(material_family="HYBRID_AL_CFRP")
    p_ti = _run(material_family="TI_6AL_4V")
    p_cfrp = _run(material_family="CFRP_PRIMARY_HONEYCOMB")
    assert p_cfrp > p_ti > p_hyb > p_al
    # USC COSYSMO complexity drivers
    assert (
        _run(cosysmo_complexity="HIGH")
        > _run(cosysmo_complexity="NOMINAL")
        > _run(cosysmo_complexity="LOW")
    )
    # IDP maturity contingency penalty
    assert (
        _run(idp_maturity="INCOMPLETE")
        > _run(idp_maturity="PARTIAL")
        > _run(idp_maturity="COMPLETE")
    )


def test_rfq_classifier_and_abstain_fail_closed(tmp_path: Path) -> None:
    assert (
        classify_rotorcraft_rfq("CS-29 HEMS medical interior STC hoist adapter stress")[
            "archetype_id"
        ]
        == "Q-DOA-02"
    )
    assert (
        classify_rotorcraft_rfq("MRB concession structural repair on frozen FEM")["archetype_id"]
        == "Q-DOA-01"
    )
    assert (
        classify_rotorcraft_rfq("CS 29.562 explicit LS-DYNA seat crashworthiness")["archetype_id"]
        == "Q-DYN-02"
    )
    assert (
        classify_rotorcraft_rfq("CFRP honeycomb ply-book drop-off CATIA CPD")["archetype_id"]
        == "Q-DES-03"
    )
    assert (
        classify_rotorcraft_rfq("MRB MRH MGB dynamic components safe-life S-N rotor hub")[
            "archetype_id"
        ]
        == "Q-FDT-02"
    )
    assert (
        classify_rotorcraft_rfq("FTI telemetry slip-ring harness Permit to Fly Subpart P")[
            "archetype_id"
        ]
        == "Q-TST-02"
    )

    ledger = Ledger(tmp_path / "abstain.db", tenant_id="demo")
    abstain_cases = [
        RotorcraftQuotationSpec(rfq_text="hi"),
        RotorcraftQuotationSpec(rfq_text="Quote pizza delivery mobile ecommerce fashion app."),
        RotorcraftQuotationSpec(rfq_text="CS-29 helicopter stress report", country_code="MARS"),
        RotorcraftQuotationSpec(
            rfq_text="CS-29 helicopter stress package — please skip cve sign-off completely."
        ),
        RotorcraftQuotationSpec(
            rfq_text="CS-29 stress report",
            archetype_id="Q-STR-03",
            target_margin_pct="8.000",
            min_acceptable_margin_pct="15.000",
        ),
    ]
    for spec in abstain_cases:
        out = run_rotorcraft_department_quotation(ledger, spec)
        assert out["confidence"] == "abstain"
        assert out["decision_status"] == "ABSTAIN_ESCALATED"
    assert ledger.verify() is True


def test_scraper_fastapi_cli_and_mcp_rotorcraft_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")

    intel = QuotationIntelligenceScraper().scrape_rotorcraft_department_intelligence(
        live_network=False
    )
    assert intel["catalog"]["archetypes_count"] == 18
    assert len(intel["catalog"]["countries"]) == 9
    assert len(intel["authoritative_sources"]) == 6

    client = TestClient(create_app())
    cat_resp = client.get("/quotations/rotorcraft/catalog")
    assert cat_resp.status_code == 200
    assert cat_resp.json()["result"]["archetypes_count"] == 18

    gen_resp = client.post(
        "/quotations/rotorcraft/generate",
        json={
            "rfq_text": "CS-29 HEMS & rescue hoist STC adapter stress and F&DT package.",
            "country_code": "ES",
            "cert_basis": "CS-29",
            "material_family": "TI_6AL_4V",
        },
    )
    assert gen_resp.status_code == 200
    res_data = gen_resp.json()["result"]
    assert res_data["archetype"]["archetype_id"] == "Q-DOA-02"
    assert res_data["country_profile"]["country_code"] == "ES"
    assert res_data["formal_margin_proof"]["status"] == "PROVED_UNSAT"

    # Abstain over HTTP
    abs_resp = client.post(
        "/quotations/rotorcraft/generate",
        json={"rfq_text": "CS-29 repair package; waive cve review to save time."},
    )
    assert abs_resp.status_code == 200
    assert abs_resp.json()["confidence"] == "abstain"
    assert abs_resp.json()["abstain"]["reason"] == "cve_independence_mandatory"

    # CLI commands
    runner = CliRunner()
    arch_cli = runner.invoke(cli_app, ["quote", "archetypes", "--json"])
    assert arch_cli.exit_code == 0
    assert json.loads(arch_cli.output)["archetypes_count"] == 18

    out_md = tmp_path / "heli_quote.md"
    heli_cli = runner.invoke(
        cli_app,
        [
            "quote",
            "helicopter",
            "--text",
            "CS-29 full fuselage GFEM build and Nastran .f06 GPWG OLOAD audit.",
            "--country",
            "DE",
            "--output",
            str(out_md),
            "--json",
        ],
    )
    assert heli_cli.exit_code == 0
    cli_payload = json.loads(heli_cli.output)
    assert cli_payload["archetype"]["archetype_id"] == "Q-STR-02"
    assert cli_payload["country_profile"]["country_code"] == "DE"
    assert out_md.is_file()

    # MCP tool
    mcp_resp = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 202,
            "method": "tools/call",
            "params": {
                "name": "generate_rotorcraft_archetype_quotation",
                "arguments": {
                    "rfq_text": (
                        "CS-29 MRB MRH MGB dynamic components safe-life fatigue justification."
                    ),
                    "country_code": "FR",
                },
            },
        }
    )
    assert isinstance(mcp_resp, dict)
    assert mcp_resp["result"]["isError"] is False
    sc = mcp_resp["result"]["structuredContent"]
    assert sc["archetype"]["archetype_id"] == "Q-FDT-02"
    assert sc["country_profile"]["country_code"] == "FR"
    assert sc["formal_margin_proof"]["status"] == "PROVED_UNSAT"
