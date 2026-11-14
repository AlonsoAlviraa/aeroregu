from __future__ import annotations

from pathlib import Path

from evidence_api.app import create_app
from evidence_api.mcp_server import handle_mcp_message
from evidence_coverage.cross_artifact import audit_cross_artifact_consistency
from evidence_ingest.router import ingest_bytes
from evidence_kernel.ledger import Ledger
from fastapi.testclient import TestClient


def _sample_f06_bytes() -> bytes:
    return (
        b"1    NASTRAN SOL 101 LINEAR STATIC\n"
        b"                         G R I D   P O I N T   W E I G H T   G E N E R A T O R\n"
        b"     MASS AXIS SYSTEM (S)     MASS              X-C.G.        Y-C.G.        Z-C.G.\n"
        b"            X               9.820000E+02      2.400000E-01  0.000000E+00  1.500000E-01\n"
        b"            Y               9.820000E+02      2.400000E-01  0.000000E+00  1.500000E-01\n"
        b"            Z               9.820000E+02      2.400000E-01  0.000000E+00  1.500000E-01\n"
        b"\n"
        b"                                         O L O A D    R E S U L T A N T\n"
        b"     SUBCASE    T1            T2            T3            "
        b"R1            R2            R3\n"
        b"0          1   0.000000E+00  0.000000E+00  1.480000E+04  "
        b"0.000000E+00  0.000000E+00  0.000000E+00\n"
        b"\n"
        b"                                      S P C F O R C E   R E S U L T A N T\n"
        b"     SUBCASE    T1            T2            T3            "
        b"R1            R2            R3\n"
        b"0          1   0.000000E+00  0.000000E+00 -1.395000E+04  "
        b"0.000000E+00  0.000000E+00  0.000000E+00\n"
    )


def test_nastran_f06_parser_and_cross_artifact_invalidation(tmp_path: Path) -> None:
    f06_parsed = ingest_bytes(_sample_f06_bytes(), "airframe_loads.f06")
    assert f06_parsed["media_type"] == "nastran_f06"
    f06 = f06_parsed["cad_cae"]
    assert f06["gpwg_mass_kg"] == "982"
    assert len(f06["oload_resultants"]) == 1
    assert len(f06["spcforce_resultants"]) == 1

    ledger = Ledger(tmp_path / "ca.sqlite3", "demo")
    res = audit_cross_artifact_consistency(
        ledger,
        requirements={
            "mass_min_kg": "750",
            "mass_max_kg": "960",
            "cg_x_bounds_m": ["-0.200", "0.220"],
        },
        cad={"parameters": [{"name": "cg_x_m", "value": "0.265", "unit": "m"}]},
        fem={
            "parameters": [
                {"name": "mass_kg", "value": "982.0", "unit": "kg"},
                {"name": "thrust_n", "value": "14800.0", "unit": "N"},
            ]
        },
        fem_f06=f06_parsed,
        report={"mass_kg": "950.0", "cg_x_m": "0.180", "resultant_force_n": "14800.0"},
        invalidate_cells=True,
    )
    assert res["consistent"] is False
    assert res["critical_count"] >= 2
    cats = {d["category"] for d in res["discrepancies"]}
    assert "cross_artifact_mass_mismatch" in cats
    assert "cg_envelope_exceedance" in cats
    assert "fem_load_reaction_imbalance" in cats
    assert len(res["invalidated_cell_ids"]) >= 1


def test_overnight_briefing_api_batch_signoff_and_mcp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")
    client = TestClient(create_app())

    # 1. Seed initial calc event as author so SoD checks work on batch signoff
    login_author = client.post(
        "/auth/login",
        json={"actor_id": "author", "password": "author-local", "tenant_id": "demo"},
    )
    assert login_author.status_code == 200
    assert (
        client.post("/calc/run", json={"example": "first_cell", "tenant_id": "demo"}).status_code
        == 200
    )

    # 2. Trigger full overnight cycle (cross-artifact + envelope_critic Z3+cvc5 + bench_attacker)
    run_res = client.post(
        "/overnight/run",
        json={"tenant_id": "demo", "use_showcase": True, "run_fuzzer": True},
    )
    assert run_res.status_code == 200
    payload = run_res.json()["result"]
    assert payload["cross_artifact"]["consistent"] is False
    assert payload["bench_attacker"]["gold_labels_modified"] is False
    assert payload["envelope_critic"]["human_status_mutated"] is False
    assert payload["briefing"]["executive_summary"]["open_items"] >= 3

    brief_res = client.get("/overnight/briefing?tenant_id=demo")
    assert brief_res.status_code == 200
    queue = brief_res.json()["result"]["queue"]
    assert len(queue) >= 3
    finding_ids = [item["finding_id"] for item in queue[:3]]

    # 3. Author MUST be blocked from CVE batch signoff (403 cve_role_required)
    blocked = client.post(
        "/overnight/batch-signoff",
        json={"tenant_id": "demo", "finding_ids": finding_ids},
    )
    assert blocked.status_code == 403
    assert blocked.json()["abstain"]["reason"] == "cve_role_required"

    # 4. Login as distinct CVE reviewer and execute batch signoff
    login_cve = client.post(
        "/auth/login",
        json={"actor_id": "reviewer", "password": "reviewer-local", "tenant_id": "demo"},
    )
    assert login_cve.status_code == 200
    sign_res = client.post(
        "/overnight/batch-signoff",
        json={
            "tenant_id": "demo",
            "finding_ids": finding_ids,
            "statement": "CVE batch audit passed after design update",
            "enforce_distinct_reviewer": True,
        },
    )
    assert sign_res.status_code == 200
    assert sign_res.json()["result"]["signed_count"] == len(finding_ids)

    # 5. Check Prometheus /metrics, persistence, and DLQ endpoints
    prom_res = client.get("/metrics")
    assert prom_res.status_code == 200
    assert "aeroregu_smt_solver_duration_seconds" in prom_res.text

    pers = client.get("/system/persistence?tenant_id=demo")
    assert pers.status_code == 200
    assert pers.json()["result"]["schema_version"] == 3

    # 6. Check MCP tools directly
    mcp_res = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": "evidence_observability_metrics", "arguments": {}},
        },
        require_auth_for_writes=False,
        is_authenticated=True,
    )
    assert mcp_res is not None
    assert "result" in mcp_res
    assert mcp_res["result"]["isError"] is False
