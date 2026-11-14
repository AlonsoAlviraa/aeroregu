from __future__ import annotations

import json
from pathlib import Path

import pytest
from evidence_api.app import app
from evidence_api.cli import app as cli_app
from fastapi.testclient import TestClient
from typer.testing import CliRunner

STEP_API_TEXT = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('API Test AP242'),'2;1');
FILE_NAME('hub.stp','2026-11-12T12:00:00',('Eng'),('AeroRegu'),'STEP AP242','','');
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));
ENDSEC;
DATA;
#10=PRODUCT('HUB','HUB','',(#11));
#20=CARTESIAN_POINT('CG_Point',(45.0,-12.0,165.0));
#26=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));
#29=(MASS_UNIT()NAMED_UNIT(*)SI_UNIT(.KILO.,.GRAM.));
#30=PROPERTY_DEFINITION('center_of_gravity','CG',#10);
#31=REPRESENTATION('CG_REP',(#20),#99);
#32=PROPERTY_DEFINITION_REPRESENTATION(#30,#31);
#33=MEASURE_REPRESENTATION_ITEM('shear_force_n',NUMERIC_MEASURE(2500.0),$);
#34=MEASURE_REPRESENTATION_ITEM('tensile_force_n',NUMERIC_MEASURE(3600.0),$);
#35=MEASURE_REPRESENTATION_ITEM('area_mm2',NUMERIC_MEASURE(80.0),$);
#36=MEASURE_REPRESENTATION_ITEM('shear_allowable_mpa',NUMERIC_MEASURE(250.0),$);
#37=MEASURE_REPRESENTATION_ITEM('tensile_allowable_mpa',NUMERIC_MEASURE(250.0),$);
#38=REPRESENTATION('BOLT',(#33,#34,#35,#36,#37),#99);
#39=PROPERTY_DEFINITION('BOLT_PROPS','Loads',#10);
#40=PROPERTY_DEFINITION_REPRESENTATION(#39,#38);
ENDSEC;
END-ISO-10303-21;
"""

CATIA_XML_TEXT = """<CATProduct name="EVTOL">
  <Parameters>
    <Parameter name="thrust_n" value="9800.0" unit="N" />
    <Parameter name="disk_area_m2" value="10.5" unit="m2" />
    <Parameter name="air_density_kg_m3" value="1.225" unit="kg/m3" />
    <Parameter name="figure_of_merit" value="0.72" />
    <Parameter name="power_available_kw" value="350.0" unit="kW" />
  </Parameters>
  <MassProperties>
    <CenterOfGravity x="0.035" y="-0.008" z="0.172" unit="m" />
  </MassProperties>
</CATProduct>
"""


def test_static_viewer3d_and_demo_html_guardrails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    client = TestClient(app)

    js_resp = client.get("/static/viewer3d.js")
    assert js_resp.status_code == 200
    assert "AeroRegu3DViewer" in js_resp.text

    html_resp = client.get("/")
    assert html_resp.status_code == 200
    assert "/static/viewer3d.js" in html_resp.text
    assert "100" not in html_resp.text
    assert "compliant" not in html_resp.text.lower()


def test_http_cad_ingest_bind_and_envelope_3d_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    client = TestClient(app)

    ing = client.post(
        "/cad/ingest",
        json={
            "filename": "hub.stp",
            "content_text": STEP_API_TEXT,
            "auto_run": True,
            "stated_outputs": {"bolt_screen": {"shear_stress_mpa": "31.250"}},
        },
    )
    assert ing.status_code == 200
    body = ing.json()
    assert body["confidence"] == "deterministic"
    res = body["result"]
    assert res["cad_cae"]["format"] == "step_ap242"
    assert "bolt_screen" in res["bindings"]["ready_methods"]
    bolt_exec = res["bindings"]["cards"]["bolt_screen"]["execution"]
    assert bolt_exec["outputs"]["shear_stress_mpa"] == "31.250"

    # Explicit /cad/bind endpoint
    bnd = client.post(
        "/cad/bind",
        json={
            "parameters": [
                {"name": "thrust_n", "value": "9800", "unit": "N"},
                {"name": "disk_area_m2", "value": "10.5", "unit": "m2"},
                {"name": "air_density_kg_m3", "value": "1.225", "unit": "kg/m3"},
                {"name": "figure_of_merit", "value": "0.72", "unit": ""},
                {"name": "power_available_kw", "value": "350", "unit": "kW"},
            ],
            "auto_run": True,
        },
    )
    assert bnd.status_code == 200
    assert "hover_power_screen" in bnd.json()["result"]["ready_methods"]

    # 3D V-n and CG cloud GET + POST
    e3d_get = client.get("/coverage/envelope-3d")
    assert e3d_get.status_code == 200
    assert e3d_get.json()["result"]["cg_cloud"]["coverage_points"] > 0

    e3d_post = client.post(
        "/coverage/envelope-3d",
        json={
            "cad_cg_points": [
                {"point_id": "STEP-CG", "x_cg_m": "0.045", "y_cg_m": "-0.012", "z_cg_m": "0.165"}
            ],
            "mass_kg_override": "950.000",
        },
    )
    assert e3d_post.status_code == 200
    cloud = e3d_post.json()["result"]["cg_cloud"]
    assert cloud["cad_cae_points"] == 1


def test_mcp_cad_cae_and_envelope_3d_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    client = TestClient(app)

    call_cad = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {
                "name": "evidence_cad_cae_ingest",
                "arguments": {
                    "filename": "evtol.xml",
                    "content_text": CATIA_XML_TEXT,
                    "auto_run": True,
                },
            },
        },
    )
    assert call_cad.status_code == 200
    cad_res = call_cad.json()["result"]
    assert cad_res["isError"] is False
    assert "hover_power_screen" in cad_res["structuredContent"]["bindings"]["ready_methods"]

    call_3d = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {"name": "evidence_envelope_3d", "arguments": {"tenant_id": "demo"}},
        },
    )
    assert call_3d.status_code == 200
    env_res = call_3d.json()["result"]
    assert env_res["isError"] is False
    assert env_res["structuredContent"]["smt_proof"]["envelope_proved"] is True


def test_cli_cad_inspect_and_coverage_envelope_3d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    sample = tmp_path / "evtol.xml"
    sample.write_text(CATIA_XML_TEXT, encoding="utf-8")
    runner = CliRunner()

    r1 = runner.invoke(cli_app, ["cad", "inspect", str(sample), "--json"])
    assert r1.exit_code == 0, r1.output
    parsed = json.loads(r1.output)
    assert "hover_power_screen" in parsed["bindings"]["ready_methods"]

    r2 = runner.invoke(cli_app, ["coverage", "envelope-3d", "--json"])
    assert r2.exit_code == 0, r2.output
    env = json.loads(r2.output)
    assert len(env["vn_envelope"]["mass_slices"]) == 4
