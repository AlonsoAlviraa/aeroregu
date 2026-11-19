from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.mcp_server import handle_mcp_message
from evidence_coverage.overnight import run_overnight_cycle
from evidence_ingest.fem_parsers import parse_nastran_bdf, parse_nastran_f06
from evidence_ingest.router import ingest_bytes
from evidence_kernel.ledger import Ledger
from starlette.requests import Request
from typer.testing import CliRunner

BDF_REV_A = """$ UNITS: MM_T_N_MPA
SOL 101
CEND
SUBCASE 1
  LABEL = LIMIT MANEUVER 2.5G
  LOAD = 101
BEGIN BULK
GRID    1       0       0.0     0.0     0.0
PSHELL  100     1       3.0
MAT1    1       71000.  27000.  0.33
FORCE   101     1       0       5000.   0.0     0.0     1.0
CONM2   50      1       0       950.0   0.0     0.0     0.0
ENDDATA
"""

BDF_REV_B = """$ UNITS: MM_T_N_MPA
SOL 101
CEND
SUBCASE 1
  LABEL = LIMIT MANEUVER 2.5G
  LOAD = 101
SUBCASE 2
  LABEL = CRASH 20G FORWARD
  LOAD = 102
BEGIN BULK
GRID    1       0       0.0     0.0     0.0
PSHELL  100     1       2.5
PCOMP   200     0.0     0.0     0.0     STRN    0.0     0.0     SYM
+       2       0.125   0.0     YES     2       0.125   45.0    YES
MAT1    1       71000.  27000.  0.33
FORCE   101     1       0       5000.   0.0     0.0     1.0
CONM2   50      1       0       980.0   0.0     0.0     0.0
ENDDATA
"""

F06_CLEAN = """1    NASTRAN SOL 101
                                         O L O A D    R E S U L T A N T
     SUBCASE    T1            T2            T3            R1            R2            R3
0          1   0.000000E+00  0.000000E+00  5.000000E+03  0.000000E+00  0.000000E+00  0.000000E+00

                                      S P C F O R C E   R E S U L T A N T
     SUBCASE    T1            T2            T3            R1            R2            R3
0          1   0.000000E+00  0.000000E+00 -5.000000E+03  0.000000E+00  0.000000E+00
"""


def _build_stress_report_pdf_bytes() -> bytes:
    """Create a real vector PDF containing a multi-column Stress Summary table."""
    html = """
    <html><body style="font-family: sans-serif; font-size: 10pt;">
      <h3>HELICOPTER TAILBOOM STRESS REPORT — REV A</h3>
      <table style="border-collapse: collapse; width: 100%;">
        <tr>
          <th style="border: 1px solid #000; padding: 6px;">PID</th>
          <th style="border: 1px solid #000; padding: 6px;">Component</th>
          <th style="border: 1px solid #000; padding: 6px;">Thickness (mm)</th>
          <th style="border: 1px solid #000; padding: 6px;">MS_min</th>
        </tr>
        <tr>
          <td style="border: 1px solid #000; padding: 6px;">100</td>
          <td style="border: 1px solid #000; padding: 6px;">Tailboom Skin</td>
          <td style="border: 1px solid #000; padding: 6px;">3.0</td>
          <td style="border: 1px solid #000; padding: 6px;">0.210</td>
        </tr>
        <tr>
          <td style="border: 1px solid #000; padding: 6px;">200</td>
          <td style="border: 1px solid #000; padding: 6px;">Composite Frame</td>
          <td style="border: 1px solid #000; padding: 6px;">0.5</td>
          <td style="border: 1px solid #000; padding: 6px;">0.340</td>
        </tr>
      </table>
    </body></html>
    """
    story = pymupdf.Story(html=html)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    rect = pymupdf.paper_rect("a4")
    dev = writer.begin_page(rect)
    story.place(rect + (36, 36, -36, -36))
    story.draw(dev, None)
    writer.end_page()
    writer.close()
    return buf.getvalue()


def _find_route_endpoint(app: Any, path: str, method: str = "POST") -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route {method} {path} not found")


def _make_request(path: str, cookie: str = "") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_e2e_real_pdf_table_vs_bdf_across_api_mcp_cli_and_overnight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")

    # 1. Real PDF ingestion -> verify table_rows extracted from vector PDF
    pdf_bytes = _build_stress_report_pdf_bytes()
    rep_ing = ingest_bytes(pdf_bytes, "tailboom_stress_report.pdf")
    rep_blocks = [b.as_dict() if hasattr(b, "as_dict") else b for b in rep_ing["blocks"]]
    assert any(b.get("block_kind") == "table" and b.get("table_rows") for b in rep_blocks)

    # 2. FastAPI Route: POST /nafems/audit detects PSHELL 100 drift (3.0 mm PDF vs 2.5 mm BDF Rev B)
    app = create_app()
    audit_fn = _find_route_endpoint(app, "/nafems/audit", "POST")
    audit_resp = audit_fn(
        {
            "bdf_text": BDF_REV_B,
            "f06_text": F06_CLEAN,
            "report_blocks": rep_blocks,
            "require_unit_system": True,
            "required_load_families": [
                {"family_id": "limit", "regulation_ref": "CS 29.337", "keywords": ["maneuver"]},
                {"family_id": "crash", "regulation_ref": "CS 29.561", "keywords": ["crash"]},
            ],
        }
    )
    assert audit_resp.status_code == 200
    audit_res = json.loads(audit_resp.body)["result"]
    assert audit_res["overall_pass"] is False
    assert audit_res["property_drift"]["discrepancy_count"] == 1
    assert audit_res["property_drift"]["discrepancies"][0]["pid"] == "100"
    assert audit_res["subcase_coverage"]["complete"] is True

    # 3. FastAPI Route: POST /nafems/bdf-diff requires auth (401) & invalidates Ledger after login
    diff_fn = _find_route_endpoint(app, "/nafems/bdf-diff", "POST")
    unauth = diff_fn(
        {"tenant_id": "demo", "rev_a_bdf_text": BDF_REV_A, "rev_b_bdf_text": BDF_REV_B},
        _make_request("/nafems/bdf-diff"),
    )
    assert unauth.status_code == 401

    login_fn = _find_route_endpoint(app, "/auth/login", "POST")
    login_resp = login_fn(
        {"actor_id": "author", "password": "author-local", "tenant_id": "demo"},
        _make_request("/auth/login"),
    )
    assert login_resp.status_code == 200
    set_cookie = login_resp.headers.get("set-cookie", "")
    session_cookie = set_cookie.split(";", 1)[0]
    assert "el_session=" in session_cookie

    diff_resp = diff_fn(
        {"tenant_id": "demo", "rev_a_bdf_text": BDF_REV_A, "rev_b_bdf_text": BDF_REV_B},
        _make_request("/nafems/bdf-diff", cookie=session_cookie),
    )
    assert diff_resp.status_code == 200
    diff_res = json.loads(diff_resp.body)["result"]
    assert diff_res["has_structural_impact"] is True
    assert len(diff_res["invalidated_cell_ids"]) >= 1

    # 4. MCP tool call: evidence_nafems_audit & evidence_nafems_bdf_diff
    mcp_res = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 77,
            "method": "tools/call",
            "params": {
                "name": "evidence_nafems_audit",
                "arguments": {
                    "bdf_text": BDF_REV_B,
                    "f06_text": F06_CLEAN,
                    "report_blocks": rep_blocks,
                    "require_unit_system": True,
                },
            },
        },
        require_auth_for_writes=False,
        is_authenticated=True,
    )
    assert mcp_res is not None
    assert mcp_res["result"]["isError"] is False
    assert mcp_res["result"]["structuredContent"]["property_drift"]["discrepancy_count"] == 1

    # 5. CLI: aeroregu cae nafems-audit & aeroregu cae bdf-diff
    bdf_a_path = tmp_path / "rev_a.bdf"
    bdf_b_path = tmp_path / "rev_b.bdf"
    pdf_path = tmp_path / "report.pdf"
    bdf_a_path.write_text(BDF_REV_A, encoding="utf-8")
    bdf_b_path.write_text(BDF_REV_B, encoding="utf-8")
    pdf_path.write_bytes(pdf_bytes)

    runner = CliRunner()
    c1 = runner.invoke(
        cli_app,
        [
            "cae",
            "nafems-audit",
            str(bdf_b_path),
            "--report",
            str(pdf_path),
            "--require-units",
            "--json",
        ],
    )
    assert c1.exit_code == 0, c1.output
    cli_audit = json.loads(c1.output)
    assert cli_audit["property_drift"]["discrepancies"][0]["pid"] == "100"

    c2 = runner.invoke(cli_app, ["cae", "bdf-diff", str(bdf_a_path), str(bdf_b_path), "--json"])
    assert c2.exit_code == 0, c2.output
    cli_diff = json.loads(c2.output)
    assert cli_diff["has_structural_impact"] is True

    # 6. Overnight integration: nafems_inputs feeds directly into morning briefing queue
    ledger = Ledger(tmp_path / "overnight_nafems.sqlite3", "demo")
    bdf_b_parsed = parse_nastran_bdf(
        BDF_REV_B.encode("utf-8"), hashlib.sha256(BDF_REV_B.encode("utf-8")).hexdigest()
    )
    f06_parsed = parse_nastran_f06(
        F06_CLEAN.encode("utf-8"), hashlib.sha256(F06_CLEAN.encode("utf-8")).hexdigest()
    )
    ov = run_overnight_cycle(
        ledger,
        run_fuzzer=False,
        nafems_inputs={
            "bdf_parsed": bdf_b_parsed,
            "f06_parsed": f06_parsed,
            "report_blocks": rep_blocks,
            "require_unit_system": True,
        },
    )
    assert ov["nafems_audit"]["property_drift"]["discrepancy_count"] == 1
    assert ov["briefing"]["executive_summary"]["open_items"] >= 1
