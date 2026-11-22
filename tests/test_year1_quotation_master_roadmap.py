"""End-to-End Year-1 Master Roadmap Mega-Test Suite (Q1-Q4) for AeroRegu Quotation Engine.

Verifies:
- Q1: Multi-archetype Composite WBS DAG (CPM ES/EF/LS/LF/Float + cycle ABSTAIN + synergy reuse)
      + `aerospace_multiyear_cashflow_learning` (Wright & Crawford, Y1..Y5 inflation, monthly
      cashflow, Peak Negative CF, working capital financing, NPV, FLINT/Arb 50-digit intervals,
      Hypothesis monotonicity, Z3 SMT UNSAT & SAT counterexample proofs).
- Q2: Deep Physical IDP Extraction coupled to `fem_parsers.py` (nested INCLUDE, CORD2R, DOFs,
      PSHELL/PCOMP/PBAR/PBUSH), `cae_binary.py` (.op2/.h5 streaming & equilibrium), `cad_brep.py`
      (STEP B-Rep Buy-to-Fly, surface area, machining complexity), and `bom_drawing_extractor.py`
      (PDF with verified `page_no` + `bbox` citations, XLSX, DOCX).
- Q3: Clause-by-Clause Contractual Auditor (4 classes + all 6 poison-clause detectors + CVE waiver
      ABSTAIN) + Native 7-tab live-formula Excel `.xlsx` exporter + Ed25519 DSSE + ISO QR signed
      PDF dossier offline verification & tamper rejection.
- Q4: Stratified K-Fold CV, IQR/MAD outlier injection & detection, temporal drift diagnostics,
      Win-Rate vs P50..P90 calibration, ERP/SAP CSV/XLSX template round-trip, and full FastAPI,
      CLI, MCP & `demo.html` / `quotation_cockpit.js` interactive cockpit verification.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from docx import Document as DocxDocument
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.mcp_server import handle_mcp_message
from evidence_calc.errors import AbstainError
from evidence_calc.registry import list_method_ids, run_method
from evidence_coverage.advanced_quotation_calibration import (
    calibrate_win_rate_by_percentile,
    detect_calibration_drift,
    detect_historical_outliers,
    export_erp_sap_import_template,
    run_stratified_kfold_calibration,
)
from evidence_coverage.composite_dag_quotation import (
    COUNTRY_INFLATION_PROFILES,
    CompositeRotorcraftQuotationSpec,
    QuotationAbstain,
    build_composite_wbs_dag,
    prove_multiyear_npv_and_margin_envelope,
    run_composite_rotorcraft_quotation,
)
from evidence_coverage.contract_clause_auditor import audit_rfq_contract_clauses
from evidence_coverage.deep_idp_quotation_extractor import extract_deep_idp_engineering_package
from evidence_coverage.historical_quotation_calibrator import (
    HistoricalQuotationRecord,
    generate_reference_historical_corpus,
    ingest_historical_quotations,
)
from evidence_coverage.quotation_exporter import (
    export_quotation_signed_pdf,
    export_quotation_xlsx,
    verify_quotation_signed_pdf,
)
from evidence_ingest.bom_drawing_extractor import extract_bom_and_drawings
from evidence_ingest.cad_brep import analyze_step_brep
from evidence_ingest.cae_binary import (
    DTYPE_ELEM,
    DTYPE_EQUILIBRIUM,
    DTYPE_NODE,
    DTYPE_STRESS_CHUNK,
    write_cae_h5_stream,
    write_nastran_op2_stream,
)
from evidence_ingest.fem_parsers import parse_nastran_bdf
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import Workbook, load_workbook
from typer.testing import CliRunner


# ==============================================================================
# Q1: Composite Multi-Archetype WBS DAG (CPM + Synergy) & Multi-Year Financials
# ==============================================================================
def test_q1_composite_8_archetype_wbs_dag_cpm_synergy_and_cycle_abstain() -> None:
    nodes_8 = [
        "Q-DES-02",
        "Q-DES-04",
        "Q-STR-01",
        "Q-STR-02",
        "Q-STR-03",
        "Q-FDT-01",
        "Q-DOA-02",
        "Q-TST-01",
    ]
    dag = build_composite_wbs_dag(
        nodes_8,
        country_code="ES",
        cert_basis="CS-29",
        material_family="HYBRID_AL_CFRP",
    )
    assert dag["node_count"] == 8
    assert dag["edge_count"] >= 9
    assert Decimal(dag["synergy_hours_saved"]) > Decimal("0")
    assert Decimal(dag["synergy_price_saved_eur"]) > Decimal("0")
    assert Decimal(dag["project_duration_weeks"]) > Decimal("10")
    assert dag["critical_path_archetypes"][0] == "Q-DES-02"
    assert dag["critical_path_archetypes"][-1] == "Q-TST-01"
    # Verify CPM invariants on every node and CVE floor preservation
    for n in dag["nodes"]:
        es = Decimal(n["early_start_week"])
        ef = Decimal(n["early_finish_week"])
        ls = Decimal(n["late_start_week"])
        lf = Decimal(n["late_finish_week"])
        dur = Decimal(n["duration_weeks"])
        flt = Decimal(n["total_float_weeks"])
        assert ef == es + dur
        assert lf == ls + dur
        assert flt == ls - es
        assert Decimal(n["cve_share_pct"]) >= Decimal("5.00")

    # Parallel branch float check: Q-DES-02 (shorter) vs Q-DES-03 (longer) feeding Q-DES-04
    dag_parallel = build_composite_wbs_dag(["Q-DES-02", "Q-DES-03", "Q-DES-04"])
    by_id = {n["archetype_id"]: n for n in dag_parallel["nodes"]}
    assert by_id["Q-DES-03"]["is_critical"] is True
    assert Decimal(by_id["Q-DES-02"]["total_float_weeks"]) > Decimal("0")

    # Fail-closed ABSTAIN on cyclic WBS dependency graph
    with pytest.raises(QuotationAbstain, match="cyclic_wbs_dag"):
        build_composite_wbs_dag(
            ["Q-DES-02", "Q-STR-03"],
            custom_edges=[("Q-STR-03", "Q-DES-02", "CAD_DMU")],
        )


def test_q1_multiyear_cashflow_learning_card_arb_and_z3_proofs() -> None:
    assert "aerospace_multiyear_cashflow_learning" in list_method_ids()
    assert len(COUNTRY_INFLATION_PROFILES) == 9

    inp = {
        "first_unit_cost_eur": "180000.000",
        "unit_count": "4",
        "learning_rate_pct": "85.000",
        "crawford_weight_pct": "50.000",
        "program_years": "4",
        "annual_inflation_pct": "3.300",
        "target_margin_pct": "24.000",
        "wacc_annual_pct": "7.800",
        "payment_terms_days": "60",
        "milestone_ko_pct": "20.000",
        "milestone_pdr_pct": "20.000",
        "milestone_cdr_pct": "25.000",
        "milestone_test_pct": "20.000",
        "milestone_cve_pct": "15.000",
    }
    res = run_method("aerospace_multiyear_cashflow_learning", inp, include_intervals=True)
    out = res["outputs"]
    assert Decimal(out["wright_last_unit_cost_eur"]) < Decimal("180000.000")
    assert Decimal(out["crawford_last_unit_cost_eur"]) < Decimal("180000.000")
    assert Decimal(out["escalated_total_cost_eur"]) > Decimal(out["active_base_total_cost_eur"])
    assert Decimal(out["peak_negative_cashflow_eur"]) > Decimal("0")
    assert Decimal(out["working_capital_financing_cost_eur"]) > Decimal("0")
    assert Decimal(out["net_present_value_eur"]) > Decimal("0")
    assert len(res["exact_intervals"]) == 16
    for iv in res["exact_intervals"].values():
        assert Decimal(iv["lower"]) <= Decimal(iv["mid"]) <= Decimal(iv["upper"])
        assert Decimal(iv["quantization_drift"]) <= Decimal("0.001")

    # Bad milestone sum != 100 triggers deterministic AbstainError
    with pytest.raises(AbstainError):
        run_method(
            "aerospace_multiyear_cashflow_learning",
            dict(inp, milestone_cve_pct="5.000"),
        )

    # Z3 SMT UNSAT proof across continuous drift, inflation, and WACC bounds
    proof_ok = prove_multiyear_npv_and_margin_envelope(
        quoted_price_eur=out["quoted_price_eur"],
        active_base_total_cost_eur=out["active_base_total_cost_eur"],
        program_years=4,
        payment_terms_days=60,
        milestone_pcts=("20.000", "20.000", "25.000", "20.000", "15.000"),
        wc_deficit_exposure_eur="240000.000",
        min_npv_eur="0.000",
        min_net_margin_pct="8.000",
    )
    assert proof_ok["status"] == "PROVED_UNSAT"
    assert proof_ok["proved"] is True

    # Z3 SMT SAT counterexample when margin floor exceeds achievable margin under drift
    proof_fail = prove_multiyear_npv_and_margin_envelope(
        quoted_price_eur=out["quoted_price_eur"],
        active_base_total_cost_eur=out["active_base_total_cost_eur"],
        program_years=4,
        payment_terms_days=60,
        milestone_pcts=("20.000", "20.000", "25.000", "20.000", "15.000"),
        wc_deficit_exposure_eur="240000.000",
        min_npv_eur="0.000",
        min_net_margin_pct="22.000",
    )
    assert proof_fail["status"] == "COUNTEREXAMPLE_FOUND"
    assert proof_fail["proved"] is False
    assert proof_fail["counterexample"] is not None


@given(
    lr=st.decimals(min_value="72.0", max_value="95.0", places=1),
    inf=st.decimals(min_value="1.0", max_value="8.0", places=1),
    units=st.integers(min_value=2, max_value=12),
)
@settings(max_examples=15, deadline=None)
def test_q1_multiyear_learning_and_inflation_hypothesis(
    lr: Decimal, inf: Decimal, units: int
) -> None:
    base = {
        "first_unit_cost_eur": "100000.000",
        "unit_count": str(units),
        "learning_rate_pct": str(lr),
        "crawford_weight_pct": "50.000",
        "program_years": "3",
        "annual_inflation_pct": str(inf),
        "target_margin_pct": "20.000",
        "wacc_annual_pct": "7.000",
        "payment_terms_days": "30",
        "milestone_ko_pct": "20",
        "milestone_pdr_pct": "20",
        "milestone_cdr_pct": "20",
        "milestone_test_pct": "20",
        "milestone_cve_pct": "20",
    }
    no_inf = dict(base, annual_inflation_pct="0.000", learning_rate_pct="100.000")
    out = run_method("aerospace_multiyear_cashflow_learning", base, include_intervals=False)[
        "outputs"
    ]
    out_flat = run_method("aerospace_multiyear_cashflow_learning", no_inf, include_intervals=False)[
        "outputs"
    ]
    assert Decimal(out["active_base_total_cost_eur"]) < Decimal(
        out_flat["active_base_total_cost_eur"]
    )
    assert Decimal(out["escalated_total_cost_eur"]) > Decimal(out["active_base_total_cost_eur"])


# ==============================================================================
# Q2: Deep Physical IDP (Nested INCLUDE BDF, OP2/H5, STEP B-Rep BTF & BOM/BBox)
# ==============================================================================
def _make_sample_step_box_with_cutout() -> bytes:
    # Rotated 45 deg solid block 100x40x20 mm plus cylindrical flange via STEP CSG BLOCK
    # plus second block so assembly BTF > 1.0 or rotated PCA OBB test
    return (
        b"ISO-10303-21;\n"
        b"HEADER;\n"
        b"FILE_SCHEMA(('MANAGED_MODEL_BASED_3D_ENGINEERING'));\n"
        b"ENDSEC;\n"
        b"DATA;\n"
        b"#1=CARTESIAN_POINT('',(0.,0.,0.));\n"
        b"#2=DIRECTION('',(0.,0.,1.));\n"
        b"#3=DIRECTION('',(0.70710678,0.70710678,0.));\n"
        b"#4=AXIS2_PLACEMENT_3D('',#1,#2,#3);\n"
        b"#5=BLOCK('SPAR_WEB',#4,120.,30.,20.);\n"
        b"#6=CARTESIAN_POINT('',(0.,80.,0.));\n"
        b"#7=AXIS2_PLACEMENT_3D('',#6,#2,#3);\n"
        b"#8=BLOCK('LUG_BOSS',#7,40.,40.,25.);\n"
        b"#9=MATERIAL_DESIGNATION('TI-6AL-4V','AMS4911');\n"
        b"ENDSEC;\n"
        b"END-ISO-10303-21;\n"
    )


def test_q2_deep_idp_nested_include_op2_h5_step_btf_and_pdf_xlsx_docx_bom(tmp_path: Path) -> None:
    # 1. Nested Nastran INCLUDE tree with local CORD2R, SPC1, RBE2, PSHELL/PCOMP/PBAR/PBUSH
    sub_dir = tmp_path / "fem" / "includes"
    sub_dir.mkdir(parents=True)
    mats_inc = sub_dir / "materials_props.bdf"
    mats_inc.write_text(
        "CORD2R,10,0,0.0,0.0,0.0,0.0,0.0,1.0,1.0,0.0,0.0\n"
        "PSHELL,1,1,2.500\n"
        "PCOMP,2,,,,,,,SYM\n"
        ",1,0.125,0.0,YES,1,0.125,45.0,YES\n"
        "PBAR,3,1,450.0\n"
        "PBUSH,4,K,1.0E5,1.0E5,1.0E5\n"
        "MAT1,1,71700.0,,0.33,2.81E-9\n",
        encoding="utf-8",
    )
    mesh_inc = tmp_path / "fem" / "mesh.bdf"
    mesh_inc.write_text(
        "INCLUDE 'includes/materials_props.bdf'\n"
        "GRID,1,10,0.0,0.0,0.0\n"
        "GRID,2,10,100.0,0.0,0.0\n"
        "GRID,3,0,100.0,100.0,0.0\n"
        "GRID,4,0,0.0,100.0,0.0\n"
        "CQUAD4,101,1,1,2,3,4\n"
        "CBAR,102,3,1,2,0.,0.,1.\n"
        "CBUSH,103,4,2,3,0\n"
        "RBE2,200,1,123456,2,3\n"
        "SPC1,1,123456,1\n",
        encoding="utf-8",
    )
    main_bdf = tmp_path / "fem" / "main.bdf"
    main_bdf.write_text(
        "SUBCASE 1\nLABEL=LIMIT_LOAD\nLOAD=10\nSPC=1\n"
        "BEGIN BULK\n"
        "INCLUDE 'mesh.bdf'\n"
        "FORCE,10,3,0,5000.0,0.0,0.0,1.0\n"
        "ENDDATA\n",
        encoding="utf-8",
    )
    bdf_parsed = parse_nastran_bdf(main_bdf.read_bytes(), "hash", base_dir=main_bdf.parent)
    assert len(bdf_parsed["include_tree"]) == 2
    assert len(bdf_parsed["coordinate_systems"]) == 1
    assert bdf_parsed["local_cp_grid_count"] == 2
    assert bdf_parsed["dof_summary"]["raw_dofs"] == 24
    assert bdf_parsed["dof_summary"]["active_dofs"] < 24
    assert len(bdf_parsed["properties"]["pshell"]) == 1
    assert len(bdf_parsed["properties"]["pcomp"]) == 1
    assert len(bdf_parsed["properties"]["pbar"]) == 1
    assert len(bdf_parsed["properties"]["pbush"]) == 1

    # 2. Binary .op2 and .h5 stream generation
    nodes = np.array([(1, 0, 0, 0), (2, 100, 0, 0), (3, 100, 100, 0)], dtype=DTYPE_NODE)
    elems = np.array([(101, 1, 3, 1, 2, 3, 3, 450.0)], dtype=DTYPE_ELEM)
    eq = np.array(
        [(1, 0.0, 0.0, 5000.0, 0.0, 0.0, 0.0, 0.0, 0.0, -5000.0, 0.0, 0.0, 0.0)],
        dtype=DTYPE_EQUILIBRIUM,
    )
    stress = np.array([(1, 101, 1, 3, 210.0, 45.0, 0.35)], dtype=DTYPE_STRESS_CHUNK)
    op2_path = tmp_path / "run.op2"
    h5_path = tmp_path / "run.h5"
    write_nastran_op2_stream(
        op2_path, nodes=nodes, elements=elems, equilibrium=eq, stress_chunks=[stress]
    )
    write_cae_h5_stream(
        h5_path, nodes=nodes, elements=elems, equilibrium=eq, stress_chunks=[stress]
    )

    # 3. STEP AP242 B-Rep Buy-to-Fly & Surface Area
    step_bytes = _make_sample_step_box_with_cutout()
    step_path = tmp_path / "assembly.stp"
    step_path.write_bytes(step_bytes)
    brep = analyze_step_brep(step_bytes, "stephash")
    assert Decimal(brep["assembly_buy_to_fly_ratio"]) >= Decimal("1.000")
    assert Decimal(brep["assembly_surface_area_m2"]) > Decimal("0")
    assert Decimal(brep["machining_complexity_index"]) >= Decimal("1.000")

    # 4. PDF BOM/Drawing with bbox + XLSX BOM + DOCX BOM
    pdf_path = tmp_path / "bom_drawings.pdf"
    pdoc = pymupdf.open()
    pg = pdoc.new_page(width=595, height=842)
    pg.insert_text((40, 60), "PN: H160-SPAR-01 QTY: 4 MASS: 2.5 kg")
    pg.insert_text((40, 95), "DWG: DWG-H160-100 REV: C")
    pdoc.save(str(pdf_path))
    pdoc.close()
    pdf_ext = extract_bom_and_drawings(pdf_path)
    assert pdf_ext["bom_parts_count"] == 1
    assert pdf_ext["drawings_count"] == 1
    assert len(pdf_ext["verified_bbox_citations"]) == 2
    assert pdf_ext["verified_bbox_citations"][0]["page_no"] == 1
    assert len(pdf_ext["verified_bbox_citations"][0]["bbox"]) == 4

    xlsx_bom_path = tmp_path / "bom.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(["Part Number", "Description", "Qty", "Material", "Mass kg"])
    ws.append(["H145-HOIST-BRKT", "Hoist Support Bracket", 2, "Ti-6Al-4V", 3.25])
    wb.save(xlsx_bom_path)
    xlsx_ext = extract_bom_and_drawings(xlsx_bom_path)
    assert xlsx_ext["bom_parts_count"] == 1
    assert xlsx_ext["bom_total_quantity"] == 2
    assert Decimal(xlsx_ext["bom_total_mass_kg"]) == Decimal("6.5")

    docx_bom_path = tmp_path / "drawings.docx"
    ddoc = DocxDocument()
    tbl = ddoc.add_table(rows=2, cols=4)
    for c_i, h_t in enumerate(("Drawing Number", "Title", "Rev", "Sheet")):
        tbl.rows[0].cells[c_i].text = h_t
    for c_i, v_t in enumerate(("DWG-HOIST-02", "Hoist Boom Arm", "B", "1")):
        tbl.rows[1].cells[c_i].text = v_t
    ddoc.save(docx_bom_path)
    docx_ext = extract_bom_and_drawings(docx_bom_path)
    assert docx_ext["drawings_count"] == 1

    # 5. Deep IDP Package coupling all artifacts
    deep = extract_deep_idp_engineering_package(
        {
            "bdf_path": str(main_bdf),
            "op2_path": str(op2_path),
            "h5_path": str(h5_path),
            "step_path": str(step_path),
            "rfq_documents": [
                {"path": str(pdf_path), "filename": pdf_path.name},
                {"path": str(xlsx_bom_path), "filename": xlsx_bom_path.name},
                {"path": str(docx_bom_path), "filename": docx_bom_path.name},
            ],
        }
    )
    assert deep["bdf_summary"]["include_count"] == 2
    assert deep["cae_binary_summary"]["files_parsed"] == 2
    assert Decimal(deep["estimated_solve_postproc_hours"]) > Decimal("0")
    assert deep["bom_and_drawings"]["bom_parts_count"] == 2
    assert deep["bom_and_drawings"]["drawings_count"] == 2
    assert len(deep["bom_and_drawings"]["verified_bbox_citations"]) == 2


# ==============================================================================
# Q3: Contractual Clause Audit (6 Poison Clauses) + Excel + Signed PDF DSSE/QR
# ==============================================================================
def test_q3_contract_auditor_poison_clauses_xlsx_and_signed_pdf(tmp_path: Path) -> None:
    # 1. Verify all 6 poison clauses are detected & classified accurately
    poison_rfq = "\n".join(
        [
            "1. Contractor accepts uncapped liquidated damages with unlimited liability.",
            "2. All redesigns included in fixed price with unlimited design iterations.",
            "3. Supplier shall assign all Background IP and internal automation scripts.",
            "4. Payment contingent solely on EASA approval without long-stop date.",
            "5. Warranty retention of 18% held for 36 months post-delivery.",
            "6. Contractor agrees to waive CVE review to accelerate sign-off.",
            "7. Standard CS-29 structural analysis per AS9100 quality.",
            "8. Preliminary loads to follow at KO+5 days.",
        ]
    )
    audit = audit_rfq_contract_clauses(poison_rfq)
    poison_ids = {p["poison_id"] for p in audit["poison_clauses_detected"]}
    assert poison_ids == {
        "UNCAPPED_LIQUIDATED_DAMAGES",
        "UNLIMITED_FREE_REDESIGN",
        "BACKGROUND_IP_ASSIGNMENT",
        "OPEN_ENDED_AUTHORITY_PAYMENT_GATE",
        "EXCESSIVE_WARRANTY_RETENTION",
        "CVE_INDEPENDENCE_WAIVER",
    }
    assert audit["overall_contract_gate"] == "REJECT_OR_ABSTAIN"
    assert audit["status_counts"]["SUPPORTED"] >= 1
    assert audit["status_counts"]["PARTIALLY_SUPPORTED_WITH_ASSUMPTION"] >= 1
    assert audit["status_counts"]["CHANGE_ORDER_REQUIRED"] >= 2
    assert audit["status_counts"]["REJECT_OR_ABSTAIN"] >= 3

    # 2. Composite Quotation fails closed (ABSTAIN) when CVE waiver or uncapped LD present
    ledger = Ledger(tmp_path / "q3_abstain.sqlite3", tenant_id="demo")
    abstain_res = run_composite_rotorcraft_quotation(
        ledger,
        CompositeRotorcraftQuotationSpec(
            rfq_text=poison_rfq,
            archetype_ids=("Q-STR-03", "Q-DOA-02"),
            country_code="ES",
        ),
    )
    assert abstain_res["confidence"] == "abstain"
    assert abstain_res["decision_status"] == "ABSTAIN_ESCALATED"

    # 3. Clean composite quote -> native 7-tab formulated Excel + signed DSSE/QR PDF
    clean_ledger = Ledger(tmp_path / "q3_clean.sqlite3", tenant_id="demo")
    clean_dossier = run_composite_rotorcraft_quotation(
        clean_ledger,
        CompositeRotorcraftQuotationSpec(
            rfq_text="CS-29 HEMS rescue hoist composite frame static, F&DT & STC. AS9100, Net 60.",
            archetype_ids=(
                "Q-DES-02",
                "Q-DES-04",
                "Q-STR-01",
                "Q-STR-02",
                "Q-STR-03",
                "Q-FDT-01",
                "Q-DOA-02",
                "Q-TST-01",
            ),
            country_code="ES",
            unit_count=3,
            program_years=3,
        ),
    )
    assert clean_dossier["confidence"] == "deterministic"
    assert clean_dossier["decision_status"] == "APPROVED_FOR_HUMAN_REVIEW"

    xlsx_path = tmp_path / "quote.xlsx"
    xlsx_res = export_quotation_xlsx(clean_dossier, output_path=xlsx_path)
    assert len(xlsx_res["sheet_names"]) == 7
    assert xlsx_res["formula_count"] >= 100
    wb = load_workbook(io.BytesIO(xlsx_res["xlsx_bytes"]), data_only=False)
    assert wb.sheetnames == [
        "Resumen Ejecutivo",
        "WBS Multi-Arquetipo & CPM",
        "Comparativa 9 Paises",
        "Flujo Caja & Aprendizaje",
        "Registro 45 Supuestos",
        "Matriz Contractual",
        "Benchmark k-NN Historico",
    ]
    assert str(wb["Resumen Ejecutivo"]["B8"].value).startswith("=")
    assert str(wb["WBS Multi-Arquetipo & CPM"]["E2"].value).startswith("=")
    wb.close()

    pdf_path = tmp_path / "signed_quote.pdf"
    pdf_res = export_quotation_signed_pdf(clean_dossier, output_path=pdf_path)
    verified = verify_quotation_signed_pdf(pdf_res["pdf_bytes"])
    assert verified["valid"] is True
    assert verified["attestation"]["merkle_root"] == clean_dossier["merkle_root"]

    # Tamper embedded DSSE payload -> offline verification MUST fail
    with pymupdf.open(stream=pdf_res["pdf_bytes"], filetype="pdf") as bad_doc:
        tampered_dsse = json.loads(bad_doc.embfile_get("dsse_attestation.json").decode("utf-8"))
        tampered_dsse["payload"] = "eyJ0YW1wZXJlZCI6dHJ1ZX0="
        bad_doc.embfile_del("dsse_attestation.json")
        bad_doc.embfile_add("dsse_attestation.json", json.dumps(tampered_dsse).encode("utf-8"))
        tampered_bytes = bad_doc.tobytes()
    assert verify_quotation_signed_pdf(tampered_bytes)["valid"] is False


# ==============================================================================
# Q4: K-Fold CV, Outlier & Drift, Win-Rate, ERP Template & API/CLI/MCP/UI
# ==============================================================================
def test_q4_kfold_outliers_drift_winrate_erp_and_api_cli_mcp_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")

    corpus = generate_reference_historical_corpus(2160)
    # Inject 3 extreme exogenous overrun outliers (5x burned hours)
    injected = list(corpus)
    for idx in range(3):
        base = corpus[idx]
        injected.append(
            HistoricalQuotationRecord(
                **{
                    **base.__dict__,
                    "quote_id": f"OUTLIER-{idx + 1}",
                    "actual_burned_hours": str(Decimal(base.quoted_hours) * Decimal("5.500")),
                    "outcome": "WON_OVERRUN",
                    "record_sha256": f"out_{idx}",
                }
            )
        )
    out_rep = detect_historical_outliers(injected)
    flagged_ids = {o["quote_id"] for o in out_rep["outliers"]}
    assert {"OUTLIER-1", "OUTLIER-2", "OUTLIER-3"}.issubset(flagged_ids)

    kfold = run_stratified_kfold_calibration(injected, k_folds=5, exclude_outliers=True)
    assert kfold["k_folds"] == 5
    assert kfold["outliers_excluded_count"] >= 3
    assert len(kfold["per_archetype_cv_mape_pct"]) == 18
    assert len(kfold["per_country_cv_mape_pct"]) == 9
    assert Decimal(kfold["global_post_mape_pct"]) < Decimal(kfold["global_pre_mape_pct"])
    assert Decimal(kfold["global_post_mape_pct"]) < Decimal("5.50")

    # Drift detection: nominal corpus STABLE vs drifted recent window RECALIBRATE_REQUIRED
    drift_ok = detect_calibration_drift(corpus)
    assert drift_ok["drift_status"] == "STABLE"
    drifted = list(corpus[:-300]) + [
        HistoricalQuotationRecord(
            **{
                **r.__dict__,
                "actual_burned_hours": str(Decimal(r.actual_burned_hours) * Decimal("1.350")),
            }
        )
        for r in corpus[-300:]
    ]
    drift_alert = detect_calibration_drift(drifted)
    assert drift_alert["drift_status"] == "RECALIBRATE_REQUIRED"

    # Win-rate percentile optimizer
    wr = calibrate_win_rate_by_percentile(corpus, archetype_id="Q-STR-03", country_code="ES")
    assert wr["recommended_percentile"] in {"P50", "P65", "P75", "P80", "P85", "P90"}
    assert len(wr["percentile_curve"]) == 6

    # ERP/SAP CSV & XLSX templates round-trip into ingest_historical_quotations
    csv_tpl = export_erp_sap_import_template(fmt="csv", output_path=tmp_path / "erp.csv")
    xlsx_tpl = export_erp_sap_import_template(fmt="xlsx", output_path=tmp_path / "erp.xlsx")
    ing_csv = ingest_historical_quotations(tmp_path / "erp.csv")
    ing_xlsx = ingest_historical_quotations(tmp_path / "erp.xlsx")
    assert ing_csv["ingested_count"] == 3
    assert ing_xlsx["ingested_count"] == 3
    assert len(csv_tpl["columns"]) == 19
    assert len(xlsx_tpl["sha256"]) == 64

    # FastAPI endpoints & Web Cockpit UI
    client = TestClient(create_app())
    r_html = client.get("/")
    assert r_html.status_code == 200
    assert 'id="tab-quote"' in r_html.text
    assert "/static/quotation_cockpit.js" in r_html.text
    assert client.get("/static/quotation_cockpit.js").status_code == 200

    r_comp = client.post(
        "/quotations/rotorcraft/composite-dag",
        json={
            "tenant_id": "demo",
            "rfq_text": "CS-29 HEMS rescue hoist composite frame static stress, F&DT & STC",
            "archetype_ids": ["Q-DES-02", "Q-STR-01", "Q-STR-02", "Q-STR-03", "Q-DOA-02"],
            "country_code": "ES",
            "unit_count": 2,
            "program_years": 3,
        },
    )
    assert r_comp.status_code == 200
    comp_res = r_comp.json()["result"]
    assert comp_res["formal_multiyear_npv_proof"]["status"] == "PROVED_UNSAT"

    r_xlsx = client.post("/quotations/rotorcraft/export-xlsx", json={"dossier": comp_res})
    assert r_xlsx.status_code == 200
    assert "spreadsheetml" in r_xlsx.headers["content-type"]

    r_pdf = client.post("/quotations/rotorcraft/export-pdf", json={"dossier": comp_res})
    assert r_pdf.status_code == 200
    assert r_pdf.headers["content-type"] == "application/pdf"
    assert verify_quotation_signed_pdf(r_pdf.content)["valid"] is True

    assert client.get("/quotations/rotorcraft/erp-template?format=xlsx").status_code == 200
    assert (
        client.post("/quotations/rotorcraft/advanced-calibration", json={"k_folds": 5}).status_code
        == 200
    )

    # CLI & MCP E2E smoke
    runner = CliRunner()
    cli_comp = runner.invoke(
        cli_app,
        [
            "quote",
            "composite",
            "--text",
            "CS-29 HEMS hoist frame stress and STC",
            "--archetypes",
            "Q-DES-02,Q-STR-02,Q-STR-03",
            "--country",
            "ES",
            "--json",
        ],
    )
    assert cli_comp.exit_code == 0, cli_comp.output
    assert json.loads(cli_comp.output)["decision_status"] == "APPROVED_FOR_HUMAN_REVIEW"

    mcp_out = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "audit_rfq_contract_clauses",
                "arguments": {"rfq_text": "Uncapped liquidated damages and waive CVE review."},
            },
        }
    )
    assert mcp_out is not None
    assert mcp_out["result"]["structuredContent"]["overall_contract_gate"] == "REJECT_OR_ABSTAIN"
