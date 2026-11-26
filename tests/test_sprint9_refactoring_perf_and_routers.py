"""Sprint 9 verification tests: performance bottlenecks, unified PDFs, MCP schemas & routers."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from evidence_api import mcp_schemas, mcp_server
from evidence_api.app import create_app
from evidence_calc.registry import list_cards
from evidence_coverage.composite_dag_quotation import (
    CompositeRotorcraftQuotationSpec,
    run_composite_rotorcraft_quotation,
)
from evidence_coverage.pdf_layout import _measure_width, _wrap_text
from evidence_coverage.quotation_change_order import compute_quotation_change_order
from evidence_coverage.quotation_exporter import (
    export_change_order_signed_pdf,
    export_evm_postmortem_signed_pdf,
    export_portfolio_capacity_signed_pdf,
    verify_quotation_signed_pdf,
)
from evidence_kernel.ledger import Ledger
from evidence_kernel.paths import repo_root


def _test_keypair() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    return (
        priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )


def _assert_clean_corporate_pdf(pdf_bytes: bytes, expected_pub_pem: bytes) -> None:
    import pymupdf

    ver = verify_quotation_signed_pdf(pdf_bytes, expected_public_key_pem=expected_pub_pem)
    assert ver["valid"] is True
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        assert doc.page_count >= 1
        for p_idx in range(doc.page_count):
            page = doc[p_idx]
            assert page.get_text("text").strip()
            blocks = page.get_text("blocks")
            for img in page.get_image_info(xrefs=True):
                ix0, iy0, ix1, iy1 = img["bbox"]
                for blk in blocks:
                    bx0, by0, bx1, by1, btext, *_ = blk
                    if not str(btext).strip():
                        continue
                    inter_x = max(0.0, min(ix1, bx1) - max(ix0, bx0))
                    inter_y = max(0.0, min(iy1, by1) - max(iy0, by0))
                    assert inter_x * inter_y < 120.0


def test_sprint9_pdf_width_cache_and_lazy_bom_imports() -> None:
    import pymupdf

    font = pymupdf.Font("helv")
    for sample in ("AeroRegu H145 HEMS STC 2026", "CS-29.301(a) / PROVED_UNSAT"):
        assert abs(_measure_width(sample, 8.0) - font.text_length(sample, fontsize=8.0)) < 0.05
    wrapped = _wrap_text("Diseño estructural aeronáutico — CS-29 HEMS", 95.0, 8.0)
    assert len(wrapped) >= 2

    # Clean Python subprocess parsing a BOM PDF must NOT eagerly import python-docx
    code = (
        "import io, sys, pymupdf; "
        "from evidence_ingest.bom_drawing_extractor import extract_bom_and_drawings; "
        "doc = pymupdf.open(); pg = doc.new_page(); "
        "pg.insert_text((40, 80), 'PN: H145-BRK-01 QTY: 2 MASS: 1.50 kg'); "
        "pdf_b = doc.tobytes(); doc.close(); "
        "res = extract_bom_and_drawings(pdf_b, filename='bom.pdf'); "
        "assert res['bom_parts_count'] == 1; "
        "assert 'docx' not in sys.modules, f'unexpected docx import: {sys.modules[\"docx\"]}'"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_sprint9_list_cards_warm_cache_and_plugin_live(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_PLUGINS_DIR", str(tmp_path / "plugins"))
    _ = list_cards()  # warm built-in ID cache
    t0 = time.perf_counter()
    for _ in range(20):
        cards = list_cards()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert len(cards) >= 60
    assert elapsed_ms < 50.0


def test_sprint9_unified_corporate_pdf_exporters_and_dag_tornado(tmp_path: Path) -> None:
    priv_pem, pub_pem = _test_keypair()
    ledger = Ledger(tmp_path / "s9.db", tenant_id="sprint9")
    base_spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-S9-BASE",
        rfq_text="CS-29 HEMS hoist primary structure static, F&DT & STC Net 60.",
        archetype_ids=(
            "Q-DES-02",
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
    base_dossier = run_composite_rotorcraft_quotation(ledger, base_spec)
    assert len(base_dossier["tornado_sensitivity"]) == 4

    rev_spec = CompositeRotorcraftQuotationSpec(
        rfq_id="RFQ-S9-REV",
        rfq_text="CS-29 HEMS hoist + structural redesign Net 60.",
        archetype_ids=base_spec.archetype_ids + ("Q-DES-04",),
        country_code="ES",
        unit_count=4,
    )
    ccn = compute_quotation_change_order(
        ledger, base_dossier, rev_spec, cr_id="CCN-S9", change_reason="Added Q-DES-04"
    )
    pdf_ccn = export_change_order_signed_pdf(ccn, private_key_pem=priv_pem, public_key_pem=pub_pem)
    _assert_clean_corporate_pdf(pdf_ccn["pdf_bytes"], pub_pem)

    from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
    from evidence_coverage.portfolio_capacity_leveler import (
        level_portfolio_capacity,
        optimize_portfolio_nearshore_allocation,
    )

    port_res = level_portfolio_capacity([base_dossier])
    ns_plan = optimize_portfolio_nearshore_allocation(
        port_res, onshore_country="DE", nearshore_country="ES", cve_onshore_only=True
    )
    pdf_port = export_portfolio_capacity_signed_pdf(
        port_res, nearshore_plan=ns_plan, private_key_pem=priv_pem, public_key_pem=pub_pem
    )
    _assert_clean_corporate_pdf(pdf_port["pdf_bytes"], pub_pem)

    evm_rep = run_bid_actual_evm_postmortem(
        ledger,
        base_dossier,
        [{"archetype_id": "Q-STR-03", "actual_hours": "810.00", "earned_pct": "100"}],
        project_id="POST-S9",
    )
    pdf_evm = export_evm_postmortem_signed_pdf(
        evm_rep, private_key_pem=priv_pem, public_key_pem=pub_pem
    )
    _assert_clean_corporate_pdf(pdf_evm["pdf_bytes"], pub_pem)


def test_sprint9_modular_routers_mcp_schemas_and_line_budgets() -> None:
    import yaml

    root = repo_root()
    app_py = (root / "apps" / "api" / "src" / "evidence_api" / "app.py").read_text(encoding="utf-8")
    mcp_py = (root / "apps" / "api" / "src" / "evidence_api" / "mcp_server.py").read_text(
        encoding="utf-8"
    )
    assert len(app_py.splitlines()) < 3050
    assert len(mcp_py.splitlines()) < 2350
    assert mcp_server.MCP_TOOLS is mcp_schemas.MCP_TOOLS
    assert mcp_server.MCP_COMPACT_TOOLS is mcp_schemas.MCP_COMPACT_TOOLS
    assert mcp_server.MCP_RESOURCES is mcp_schemas.MCP_RESOURCES
    assert mcp_server.MCP_PROMPTS is mcp_schemas.MCP_PROMPTS

    app_instance = create_app()
    spec = yaml.safe_load((root / "schemas" / "openapi.yaml").read_text(encoding="utf-8"))
    live_paths = {
        r.path
        for r in app_instance.routes
        if getattr(r, "methods", None)
        and r.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }
    assert live_paths == set(spec["paths"].keys())
