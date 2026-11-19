"""Tests for 2,000+ historical quotation ingest, PERT calibration, IDP parser & k-NN match."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pytest
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.mcp_server import handle_mcp_message
from evidence_calc.errors import AbstainError
from evidence_calc.registry import list_method_ids, run_method
from evidence_coverage.historical_quotation_calibrator import (
    calibrate_from_historical_corpus,
    extract_idp_physical_complexity,
    generate_reference_historical_corpus,
    ingest_historical_quotations,
    retrieve_nearest_historical_quotations,
)
from evidence_coverage.rotorcraft_quotation_catalog import (
    ROTORCRAFT_QUOTATION_ARCHETYPES,
    RotorcraftQuotationSpec,
    run_rotorcraft_department_quotation,
)
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner


def test_historical_calibration_calc_card_and_arb_intervals() -> None:
    assert "rotorcraft_historical_calibration" in list_method_ids()

    base = {
        "prior_optimistic_hours": "340.000",
        "prior_most_likely_hours": "500.000",
        "prior_pessimistic_hours": "740.000",
        "empirical_p10_hours": "380.000",
        "empirical_p50_hours": "560.000",
        "empirical_p90_hours": "860.000",
        "sample_size": "60",
        "credibility_full_n": "50",
        "historical_overrun_ratio": "1.140",
        "idp_feature_complexity_factor": "1.180",
        "base_contingency_pct": "10.000",
        "broken_assumption_rate_pct": "36.000",
    }
    res = run_method("rotorcraft_historical_calibration", base, include_intervals=True)
    out = res["outputs"]
    assert out["credibility_weight"] == "1.000"
    assert out["calibrated_contingency_pct"] == "19.000"
    assert Decimal(out["calibrated_optimistic_hours"]) < Decimal(
        out["calibrated_most_likely_hours"]
    )
    assert Decimal(out["calibrated_most_likely_hours"]) < Decimal(
        out["calibrated_pessimistic_hours"]
    )
    assert Decimal(out["calibrated_pert_expected_hours"]) < Decimal(
        out["calibrated_pert_p80_hours"]
    )
    assert Decimal(out["calibrated_pert_p80_hours"]) < Decimal(out["calibrated_pert_p90_hours"])

    iv = res["exact_intervals"]
    assert len(iv) == len(out)
    for k, entry in iv.items():
        assert Decimal(entry["lower"]) <= Decimal(entry["mid"]) <= Decimal(entry["upper"])
        assert Decimal(entry["quantization_drift"]) <= Decimal("0.001")

    bad = dict(base, prior_optimistic_hours="900.000")
    with pytest.raises(AbstainError):
        run_method("rotorcraft_historical_calibration", bad)


@given(
    overrun=st.decimals(min_value="1.00", max_value="1.80", places=2),
    feat=st.decimals(min_value="0.90", max_value="1.50", places=2),
    sample_n=st.integers(min_value=1, max_value=120),
)
@settings(max_examples=20, deadline=None)
def test_historical_calibration_hypothesis_monotonicity(
    overrun: Decimal,
    feat: Decimal,
    sample_n: int,
) -> None:
    inp_lo = {
        "prior_optimistic_hours": "300.000",
        "prior_most_likely_hours": "450.000",
        "prior_pessimistic_hours": "700.000",
        "empirical_p10_hours": "320.000",
        "empirical_p50_hours": "490.000",
        "empirical_p90_hours": "780.000",
        "sample_size": str(sample_n),
        "credibility_full_n": "50",
        "historical_overrun_ratio": "1.000",
        "idp_feature_complexity_factor": "0.900",
        "base_contingency_pct": "10.000",
        "broken_assumption_rate_pct": "25.000",
    }
    inp_hi = dict(
        inp_lo,
        historical_overrun_ratio=str(overrun),
        idp_feature_complexity_factor=str(feat),
    )
    out_lo = run_method("rotorcraft_historical_calibration", inp_lo, include_intervals=False)[
        "outputs"
    ]
    out_hi = run_method("rotorcraft_historical_calibration", inp_hi, include_intervals=False)[
        "outputs"
    ]
    assert Decimal(out_hi["calibrated_pert_expected_hours"]) >= Decimal(
        out_lo["calibrated_pert_expected_hours"]
    )
    assert Decimal(out_hi["calibrated_pert_p90_hours"]) >= Decimal(
        out_lo["calibrated_pert_p90_hours"]
    )


def test_2160_quotations_ingest_csv_jsonl_backtest_and_18_archetypes(tmp_path: Path) -> None:
    corpus = generate_reference_historical_corpus(count=2160)
    assert len(corpus) == 2160

    # Write full 2,160-row CSV and JSONL files on disk and verify bulk ingestion + hashes
    csv_path = tmp_path / "historical_2160.csv"
    fieldnames = [
        "quote_id",
        "archetype_id",
        "country_code",
        "cert_basis",
        "material_family",
        "cosysmo_complexity",
        "idp_maturity",
        "fem_nodes_count",
        "load_cases_count",
        "cbush_joints_count",
        "cad_drawings_count",
        "ply_count",
        "quoted_hours",
        "actual_burned_hours",
        "quoted_price_eur",
        "actual_cost_eur",
        "ecn_iterations_actual",
        "broken_assumption_ids",
        "outcome",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in corpus:
            d = asdict(rec)
            d.pop("record_sha256", None)
            d["broken_assumption_ids"] = ";".join(rec.broken_assumption_ids)
            writer.writerow(d)

    ing_csv = ingest_historical_quotations(csv_path)
    assert ing_csv["ingested_count"] == 2160
    assert ing_csv["rejected_count"] == 0
    assert ing_csv["corpus_origin"] == "CUSTOMER_HISTORICAL_DATASET"
    assert len(ing_csv["dataset_sha256"]) == 64

    jsonl_path = tmp_path / "historical_2160.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(asdict(r)) for r in corpus),
        encoding="utf-8",
    )
    ing_jsonl = ingest_historical_quotations(jsonl_path)
    assert ing_jsonl["ingested_count"] == 2160
    assert ing_jsonl["dataset_sha256"] == ing_csv["dataset_sha256"]

    # Every single one of the 18 archetypes calibrates and reduces out-of-sample MAPE
    for a_id in ROTORCRAFT_QUOTATION_ARCHETYPES:
        cal = calibrate_from_historical_corpus(
            ing_csv["records"],
            archetype_id=a_id,
            country_code="EU_DEFAULT",
            corpus_origin=ing_csv["corpus_origin"],
        )
        assert cal["status"] == "CALIBRATED_DETERMINISTIC"
        assert cal["corpus_total_records"] == 2160
        assert cal["sample_size"] >= 20
        cred_w = Decimal(cal["calibration_outputs"]["credibility_weight"])
        assert Decimal("0.000") < cred_w <= Decimal("1.000")
        pre_mape = Decimal(cal["backtesting"]["pre_calibration_mape_pct"])
        post_mape = Decimal(cal["backtesting"]["post_calibration_mape_pct"])
        assert post_mape < pre_mape

    # Verify full Buhlmann credibility (w = 1.000) when sample_size >= credibility_full_n
    cal_full = calibrate_from_historical_corpus(
        ing_csv["records"],
        archetype_id="Q-STR-03",
        country_code="EU_DEFAULT",
        credibility_full_n="20.000",
        corpus_origin=ing_csv["corpus_origin"],
    )
    assert cal_full["calibration_outputs"]["credibility_weight"] == "1.000"


def test_idp_physical_complexity_extractor_bdf_f06_step() -> None:
    # Build dense synthetic Nastran .bdf + healthy .f06
    bdf_lines = [f"GRID,{i},0,{float(i)},0.0,0.0" for i in range(1, 2601)]
    bdf_lines.extend(f"CQUAD4,{i},1,1,2,3,4" for i in range(1, 501))
    bdf_lines.extend(f"CBUSH,{i},10,{i},{i + 1},0" for i in range(1, 46))
    bdf_lines.extend(f"PCOMP,{i}" for i in range(1, 15))
    bdf_lines.extend(f"SUBCASE {i}" for i in range(1, 31))
    bdf_text = "\n".join(bdf_lines)

    healthy_f06 = (
        " GRID POINT WEIGHT GENERATOR\n"
        " OLOAD RESULTANT\n"
        " SPCFORCE RESULTANT\n"
        " EPSILON = 2.134E-12\n"
    )
    prof_ok = extract_idp_physical_complexity({"bdf_text": bdf_text, "f06_text": healthy_f06})
    assert prof_ok.fem_nodes_count == 2600
    assert prof_ok.fem_elements_count == 500
    assert prof_ok.cbush_joints_count == 45
    assert prof_ok.pcomp_laminates_count == 14
    assert prof_ok.load_cases_count == 30
    assert prof_ok.derived_idp_maturity == "COMPLETE"
    assert prof_ok.derived_cosysmo_complexity in ("ELEVATED", "HIGH")
    assert Decimal(prof_ok.idp_feature_complexity_factor) > Decimal("1.000")

    # Corrupt / high-EPSILON .f06 downgrades IDP maturity to INCOMPLETE automatically
    bad_f06 = " USER FATAL MESSAGE 9050\n EPSILON = 1.450E-02\n"
    prof_bad = extract_idp_physical_complexity({"bdf_text": bdf_text, "f06_text": bad_f06})
    assert prof_bad.f06_has_fatal is True
    assert prof_bad.f06_epsilon_exceeded is True
    assert prof_bad.derived_idp_maturity == "INCOMPLETE"
    assert len(prof_bad.quality_findings) >= 2


def test_deterministic_knn_and_integrated_pipeline_fastapi_cli_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")

    corpus = generate_reference_historical_corpus(count=2160)
    top3 = retrieve_nearest_historical_quotations(
        corpus,
        archetype_id="Q-FDT-01",
        country_code="ES",
        cert_basis="CS-29",
        material_family="CFRP_PRIMARY_HONEYCOMB",
        cosysmo_complexity="HIGH",
        idp_maturity="COMPLETE",
        fem_nodes_count=18000,
        load_cases_count=40,
        cbush_joints_count=45,
        ply_count=48,
        k=3,
    )
    assert len(top3) == 3
    assert Decimal(top3[0]["similarity_score"]) >= Decimal(top3[1]["similarity_score"])
    assert Decimal(top3[1]["similarity_score"]) >= Decimal(top3[2]["similarity_score"])
    assert top3[0]["archetype_id"] == "Q-FDT-01"

    # Integrated dossier with IDP attachments + historical calibration
    bdf_sample = "\n".join(
        [f"GRID,{i},0,0.0,0.0,0.0" for i in range(1, 3001)]
        + [f"CBUSH,{i},10,1,2" for i in range(1, 55)]
        + [f"PCOMP,{i}" for i in range(1, 16)]
        + [f"SUBCASE {i}" for i in range(1, 35)]
    )
    bad_f06 = " GRID POINT WEIGHT GENERATOR\n EPSILON = 3.2E-03\n"
    ledger = Ledger(tmp_path / "integrated.sqlite3", tenant_id="demo")
    dossier = run_rotorcraft_department_quotation(
        ledger,
        RotorcraftQuotationSpec(
            rfq_text="CS-29 composite fuselage static DFEM justification package.",
            archetype_id="Q-STR-03",
            country_code="FR",
            idp_attachments={"bdf_text": bdf_sample, "f06_text": bad_f06},
            historical_top_k=3,
        ),
    )
    assert dossier["idp_physical_extraction"]["derived_idp_maturity"] == "INCOMPLETE"
    assert dossier["historical_calibration"]["corpus_total_records"] == 2160
    assert len(dossier["nearest_historical_quotes"]) == 3
    assert "## 5. IDP Physical Inspection" in dossier["markdown_report"]
    assert ledger.verify() is True

    # FastAPI endpoint /quotations/rotorcraft/calibrate-historical
    client = TestClient(create_app())
    resp = client.post(
        "/quotations/rotorcraft/calibrate-historical",
        json={
            "archetype_id": "Q-STR-03",
            "country_code": "ES",
            "synthetic_count": 2160,
            "idp_attachments": {"bdf_text": bdf_sample, "f06_text": bad_f06},
            "top_k": 3,
        },
    )
    assert resp.status_code == 200
    body = resp.json()["result"]
    assert body["ingest_summary"]["ingested_count"] == 2160
    assert body["idp_physical_extraction"]["derived_idp_maturity"] == "INCOMPLETE"
    assert len(body["nearest_historical_quotes"]) == 3

    # CLI quote calibrate --synthetic-count 2160 --json
    runner = CliRunner()
    cli_cal = runner.invoke(
        cli_app,
        ["quote", "calibrate", "--archetype", "Q-DYN-02", "--synthetic-count", "2160", "--json"],
    )
    assert cli_cal.exit_code == 0
    cli_data = json.loads(cli_cal.output)
    assert cli_data["ingest_summary"]["ingested_count"] == 2160
    assert cli_data["historical_calibration"]["archetype_id"] == "Q-DYN-02"
    assert len(cli_data["nearest_historical_quotes"]) == 3

    # MCP tool calibrate_and_match_historical_quotations
    mcp_resp = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 303,
            "method": "tools/call",
            "params": {
                "name": "calibrate_and_match_historical_quotations",
                "arguments": {
                    "archetype_id": "Q-FDT-02",
                    "country_code": "DE",
                    "synthetic_count": 2160,
                    "top_k": 3,
                },
            },
        }
    )
    assert isinstance(mcp_resp, dict)
    assert mcp_resp["result"]["isError"] is False
    sc = mcp_resp["result"]["structuredContent"]
    assert sc["ingest_summary"]["ingested_count"] == 2160
    assert len(sc["nearest_historical_quotes"]) == 3
