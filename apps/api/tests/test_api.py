import io
import json
import zipfile

import pytest
from evidence_api.__main__ import main
from evidence_api.app import create_app
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import verify_chain_document
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "test-session-secret-0123456789")
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    return TestClient(create_app())


def _login(client: TestClient, actor: str = "author") -> None:
    response = client.post("/auth/login", json={"actor_id": actor, "password": f"{actor}-local"})
    assert response.status_code == 200


def test_storyboard_path(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    health = client.get("/health").json()
    assert health["result"]["gateway"] == "fixture"
    requirements = client.get("/requirements").json()["result"]["requirements"]
    assert len(requirements) == 8
    assert requirements[0]["source_file_hash_label"] == "NOT_VERIFIED"
    aircraft = client.get("/aircraft").json()["result"]
    assert aircraft["provenance"]["origin"] == "synthetic"
    assert client.post("/export/zip").status_code == 401
    assert client.post("/calc/run", json={"example": "first_cell"}).status_code == 401
    _login(client)
    first = client.post(
        "/calc/run", json={"example": "first_cell", "created_at": "2026-11-03T18:00:00Z"}
    )
    second = client.post(
        "/calc/run", json={"example": "first_cell", "created_at": "2026-11-03T18:00:00Z"}
    )
    assert first.status_code == 200
    assert first.json()["inputs_hash"] == second.json()["inputs_hash"]
    assert first.json()["confidence"] == "deterministic"
    gaps = client.get("/coverage/gaps").json()["result"]
    assert gaps["cell_count"] == "135"
    assert int(gaps["calc_count"]) >= 1
    assert int(gaps["gap_count"]) >= 1
    unit = client.post("/notes/check", json={"example": "unit_scale"}).json()
    assert unit["result"]["flag"] == "unit_scale"
    missing = client.post("/notes/check", json={"example": "missing_input"}).json()
    assert missing["confidence"] == "abstain"
    assert "result" not in missing
    page = client.get("/").text
    assert "This tool assists a human reviewer. It does not determine compliance." in page
    assert "compliant" not in page.lower()
    assert "100" not in page
    archive = client.post("/export/zip")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        chain = json.loads(bundle.read("chain.json"))
        readme = bundle.read("README.txt").decode()
    assert verify_chain_document(chain)
    assert "compliant" not in readme.lower()
    assert "evidence_kernel verify" in readme
    login = client.post("/auth/login", json={"actor_id": "reviewer", "password": "reviewer-local"})
    assert login.status_code == 200
    target = chain[-1]["event_hash"]
    signoff = {
        "event_type": "human_signoff",
        "tenant_id": "demo",
        "actor_id": "reviewer",
        "created_at": "2026-11-03T18:05:00Z",
        "payload": {
            "actor_id": "reviewer",
            "statement": "reviewed this event",
            "target_event_hash": target,
        },
        "envelope": make_envelope(
            sources=[project_source("reviewer", "https://aeroregu.local/reviewer", "ASSUMPTION")],
            method_version="human_signoff@1.0.0",
            inputs={"target_event_hash": target},
            confidence="quoted",
            result={"statement": "reviewed this event"},
        ),
    }
    recorded = client.post("/ledger/append", json=signoff)
    assert recorded.status_code == 200
    again = client.post("/export/zip")
    with zipfile.ZipFile(io.BytesIO(again.content)) as bundle:
        signed = json.loads(bundle.read("chain.json"))
    assert verify_chain_document(signed)
    assert signed[-1]["body"]["payload"]["statement"] == "reviewed this event"


def test_the_demo_process_refuses_a_short_session_secret(monkeypatch) -> None:
    monkeypatch.delenv("EVIDENCE_SESSION_SECRET", raising=False)
    with pytest.raises(SystemExit):
        main()


def test_login_without_a_session_secret_does_not_authenticate(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.delenv("EVIDENCE_SESSION_SECRET", raising=False)
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    client = TestClient(create_app())
    denied = client.post("/auth/login", json={"actor_id": "author", "password": "author-local"})
    assert denied.status_code == 401
    assert denied.json()["abstain"]["reason"] == "session_secret_missing"
    assert "result" not in denied.json()
    recorded = client.post("/calc/run", json=_record_body())
    assert recorded.status_code == 401


def test_supervisor_low_decision_gate_abstains_without_a_result(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    response = client.post(
        "/supervisor/run",
        json={
            "scenario": "gate_low",
            "use_decision_gate": True,
            "created_at": "2026-11-10T12:00:00Z",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["confidence"] == "abstain"
    assert body["abstain"]["reason"] == "decision_gate"
    assert "result" not in body


def test_the_demo_process_binds_the_loopback_interface(monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "loopback-bind-check-secret")
    captured: dict[str, str] = {}

    def fake_run(*_args: object, **kwargs: object) -> None:
        captured["host"] = str(kwargs["host"])

    monkeypatch.setattr("evidence_api.__main__.uvicorn.run", fake_run)
    main()
    assert captured["host"] == "127.0.0.1"


def _chain_length() -> int:
    from evidence_api.app import open_ledger

    return len(open_ledger().events())


def _record_body() -> dict:
    from evidence_coverage.grid import calc_inputs_for, generate_cells

    return {
        "method_id": "rigid_body_point_mass",
        "inputs": calc_inputs_for(generate_cells()[0]),
        "record": True,
        "created_at": "2026-11-03T18:00:00Z",
    }


def test_recorded_calc_without_a_session_does_not_append(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    before = _chain_length()
    response = client.post("/calc/run", json=_record_body())
    assert response.status_code == 401
    assert _chain_length() == before


def test_recorded_calc_with_a_bad_cookie_does_not_append(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.cookies.set("el_session", "author.not-valid")
    before = _chain_length()
    response = client.post("/calc/run", json=_record_body())
    assert response.status_code == 401
    assert _chain_length() == before


def test_first_cell_without_a_session_does_not_append(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    before = _chain_length()
    response = client.post(
        "/calc/run", json={"example": "first_cell", "created_at": "2026-11-03T18:00:00Z"}
    )
    assert response.status_code == 401
    assert _chain_length() == before


def test_calc_that_does_not_record_stays_open(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    body = _record_body()
    del body["record"]
    before = _chain_length()
    response = client.post("/calc/run", json=body)
    assert response.status_code == 200
    assert response.json()["confidence"] == "deterministic"
    assert _chain_length() == before


def test_recorded_calc_with_the_session_appends(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    before = _chain_length()
    response = client.post("/calc/run", json=_record_body())
    assert response.status_code == 200
    assert _chain_length() == before + 1


def test_export_without_a_session_is_not_a_zip(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post("/export/zip")
    assert response.status_code == 401
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(response.content))


def test_export_with_a_bad_cookie_is_not_a_zip(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    client.cookies.set("el_session", "author.not-valid")
    response = client.post("/export/zip")
    assert response.status_code == 401
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(response.content))


def test_supervisor_refuter_hit(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/supervisor/run", json={"scenario": "refuter_hit"}).status_code == 401
    _login(client)
    response = client.post(
        "/supervisor/run",
        json={"scenario": "refuter_hit", "created_at": "2026-11-03T18:00:00Z"},
    )
    body = response.json()
    assert body["confidence"] == "abstain"
    assert body["abstain"]["reason"] == "refuter_hit"
    assert "result" not in body


def test_security_headers_and_enterprise_agent_workflow(tmp_path, monkeypatch) -> None:
    from evidence_calc.registry import run_method
    from evidence_coverage.grid import calc_inputs_for, generate_cells

    client = _client(tmp_path, monkeypatch)
    health_resp = client.get("/health")
    assert health_resp.headers["X-Content-Type-Options"] == "nosniff"
    assert health_resp.headers["X-Frame-Options"] == "DENY"
    assert health_resp.headers["Referrer-Policy"] == "no-referrer"
    assert health_resp.headers["Cache-Control"] == "no-store"

    assert client.post("/coverage/mass-shift", json={}).status_code == 401
    _login(client)

    cell = generate_cells()[0]
    inputs = calc_inputs_for(cell)
    bad_stated = run_method("rigid_body_point_mass", dict(inputs, cg_x_m="0.200"))["outputs"]
    flagged = client.post(
        "/supervisor/run",
        json={
            "cell_id": cell.cell_id,
            "calc_inputs": inputs,
            "stated_outputs": bad_stated,
            "created_at": "2026-11-03T18:00:00Z",
        },
    ).json()
    assert flagged["confidence"] == "deterministic"
    assert flagged["result"]["fault_kind"] == "sign"
    assert flagged["result"]["cell_updated"] is False
    assert client.get("/coverage/gaps").json()["result"]["calc_count"] == "0"

    clean_sup = client.post(
        "/supervisor/run",
        json={
            "example": "first_cell",
            "created_at": "2026-11-03T18:01:00Z",
        },
    ).json()
    assert clean_sup["result"]["cell_updated"] is True
    assert clean_sup["result"]["fault_kind"] == "clean"
    assert client.get("/coverage/gaps").json()["result"]["calc_count"] == "1"

    shifted = client.post(
        "/coverage/mass-shift",
        json={"created_at": "2026-11-03T18:02:00Z"},
    ).json()["result"]
    assert shifted["invalidated_cells"] == [cell.cell_id]
    assert shifted["delta_reverification_manifest"]["requires_reverification"] is True
    assert shifted["delta_reverification_manifest"]["stale_cells_requiring_rerun"] == [cell.cell_id]

    summary = client.get("/dossier/summary").json()["result"]
    assert summary["dossier_hash"] == shifted["dossier_hash"]
    assert summary["chain_verified"] is True
    assert len(summary["agent_audit_trail"]["recompute_flags"]) == 1
    assert summary["agent_audit_trail"]["recompute_flags"][0]["fault_kind"] == "sign"

    archive = client.post("/export/zip")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        exported_dossier = json.loads(bundle.read("dossier.json"))
        exported_sdoc = bundle.read("dossier.sdoc").decode("utf-8")
        exported_oscal = json.loads(bundle.read("oscal_sar.json"))
        exported_formal = json.loads(bundle.read("formal_proof.json"))
    assert exported_dossier["dossier_hash"] == summary["dossier_hash"]
    assert "[DOCUMENT]" in exported_sdoc
    assert exported_oscal["assessment-results"]["metadata"]["oscal-version"] == "1.1.2"
    assert exported_formal["envelope_proved"] is True

    sdoc_resp = client.get("/dossier/strictdoc")
    assert sdoc_resp.status_code == 200
    assert "[DOCUMENT]" in sdoc_resp.text
    assert "REQ-AERO-" in sdoc_resp.text

    oscal_resp = client.get("/dossier/oscal")
    assert oscal_resp.status_code == 200
    sar_data = oscal_resp.json()["result"]["assessment-results"]
    assert sar_data["metadata"]["oscal-version"] == "1.1.2"


def test_supervisor_constrained_gateway_execution(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    res = client.post(
        "/supervisor/run",
        json={
            "example": "first_cell",
            "constrained": True,
            "created_at": "2026-11-03T18:00:00Z",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["confidence"] == "deterministic"
    assert data["result"]["fault_kind"] == "clean"


def test_formal_prove_endpoints(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    # Unauthorized request without login
    unauth = client.post("/formal/prove", json={"kind": "flight_envelope"})
    assert unauth.status_code == 401

    _login(client)
    # Flight envelope safe unsat proof
    res_env = client.post("/formal/prove", json={"kind": "flight_envelope"})
    assert res_env.status_code == 200
    data_env = res_env.json()["result"]
    assert data_env["envelope_proved"] is True
    assert data_env["status"] == "PROVED_UNSAT"
    assert len(data_env["proof_hash"]) == 64

    # Structural margin safe unsat proof
    safe_body = {
        "kind": "structural_margin",
        "bounds": {
            "area_mm2": ("100.000", "120.000"),
            "shear_force_n": ("1000.000", "2000.000"),
            "tensile_force_n": ("2000.000", "3000.000"),
        },
        "allowables": {
            "shear_allowable_mpa": "150.000",
            "tensile_allowable_mpa": "250.000",
        },
        "safety_factor": "1.500",
    }
    res_struct = client.post("/formal/prove", json=safe_body)
    assert res_struct.status_code == 200
    data_struct = res_struct.json()["result"]
    assert data_struct["proved"] is True
    assert data_struct["status"] == "PROVED_UNSAT"

    # Structural margin counterexample sat
    failing_body = {
        "kind": "structural_margin",
        "bounds": {
            "area_mm2": ("10.000", "20.000"),
            "shear_force_n": ("50000.000", "80000.000"),
            "tensile_force_n": ("50000.000", "80000.000"),
        },
        "allowables": {
            "shear_allowable_mpa": "100.000",
            "tensile_allowable_mpa": "100.000",
        },
        "safety_factor": "1.500",
    }
    res_fail = client.post("/formal/prove", json=failing_body)
    assert res_fail.status_code == 200
    data_fail = res_fail.json()["result"]
    assert data_fail["proved"] is False
    assert data_fail["status"] == "COUNTEREXAMPLE_FOUND"
    assert data_fail["counterexample"] is not None


def test_supervisor_with_formal_verification(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    res = client.post(
        "/supervisor/run",
        json={
            "example": "first_cell",
            "formal_verification": True,
            "created_at": "2026-11-03T18:00:00Z",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["confidence"] == "deterministic"
    assert "formal_proof" in data
    assert data["formal_proof"]["proved"] is True
    assert data["formal_proof"]["status"] == "PROVED_UNSAT"


def test_merkle_proof_gate_signoff_and_compare_endpoints(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.post("/ledger/signoff", json={}).status_code == 401

    _login(client, actor="author")
    calc_res = client.post(
        "/calc/run",
        json={"example": "first_cell", "created_at": "2026-11-12T12:00:00Z"},
    )
    assert calc_res.status_code == 200

    verify_res = client.get("/ledger/verify")
    assert verify_res.status_code == 200
    verify_data = verify_res.json()["result"]
    assert verify_data["chain_verified"] is True
    assert len(verify_data["merkle_root"]) == 64

    head_hash = verify_data["head_hash"]
    proof_res = client.get(f"/ledger/proof/{head_hash}")
    assert proof_res.status_code == 200
    proof = proof_res.json()["result"]
    assert proof["merkle_root"] == verify_data["merkle_root"]

    assert client.get(f"/ledger/proof/{'f' * 64}").status_code == 404

    gate_before = client.get("/coverage/gate").json()["result"]
    assert gate_before["gate_status"] == "blocked"
    assert "coverage_gaps_remaining" in gate_before["blockers"]

    _login(client, actor="reviewer")
    signoff_res = client.post(
        "/ledger/signoff",
        json={"actor_id": "reviewer", "created_at": "2026-11-12T12:01:00Z"},
    )
    assert signoff_res.status_code == 200
    assert signoff_res.json()["result"]["target_event_hash"] == head_hash

    cell_status_res = client.post(
        "/coverage/cell-status",
        json={
            "actor_id": "reviewer",
            "cell_id": "m800.000-cg-0.200-lf-1.000-unone",
            "status": "not_in_envelope",
            "created_at": "2026-11-12T12:02:00Z",
        },
    )
    assert cell_status_res.status_code == 200
    assert cell_status_res.json()["result"]["status"] == "not_in_envelope"

    compare_res = client.post(
        "/calc/compare",
        json={
            "method_id": "hover_power_screen",
            "inputs": {
                "thrust_n": "9800.000",
                "disk_area_m2": "10.000",
                "air_density_kg_m3": "1.225",
                "figure_of_merit": "0.700",
                "power_available_kw": "350.000",
            },
            "stated_outputs": {
                "disk_loading_pa": "1960.000",
                "induced_velocity_m_s": "40.000",
                "ideal_power_kw": "392.000",
                "shaft_power_kw": "560.000",
                "power_margin_ratio": "0.400",
            },
        },
    )
    assert compare_res.status_code == 200
    assert compare_res.json()["result"]["fault_kind"] == "arithmetic"


def test_ingest_units_sweep_hover_consistency_and_tenant_isolation(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client, actor="author")

    # Reject invalid tenant format
    assert client.get("/coverage/cells?tenant_id=../escape").status_code == 400

    # Unit normalization (kN -> N)
    calc_res = client.post(
        "/calc/run",
        json={
            "method_id": "bolt_screen",
            "normalize_units": True,
            "inputs": {
                "shear_force_n": "3.000",
                "tensile_force_n": "4.000",
                "area_mm2": "80.000",
                "shear_allowable_mpa": "250.000",
                "tensile_allowable_mpa": "250.000",
                "_input_units": {
                    "shear_force_n": "kN",
                    "tensile_force_n": "kN",
                    "area_mm2": "mm^2",
                    "shear_allowable_mpa": "MPa",
                    "tensile_allowable_mpa": "MPa",
                },
            },
        },
    )
    assert calc_res.status_code == 200
    assert len(calc_res.headers["X-Evidence-Request-Hash"]) == 64
    calc_result = calc_res.json()["result"]
    assert calc_result["shear_stress_mpa"] == "37.500"
    assert len(calc_result["unit_conversions"]) == 2

    # Ingest document + record to ledger
    ingest_res = client.post(
        "/ingest/document",
        json={
            "filename": "spec.md",
            "content_text": "VTOL.2210 Structural design loads\nVTOL.2220 Fatigue check",
            "record": True,
            "actor_id": "author",
            "created_at": "2026-11-12T12:00:00Z",
        },
    )
    assert ingest_res.status_code == 200
    assert len(ingest_res.json()["result"]["recorded_event_hashes"]) == 2

    # Hover power Z3 SMT formal proof
    hover_res = client.post(
        "/formal/prove",
        json={
            "kind": "hover_power",
            "actor_id": "author",
            "bounds": {"thrust_n": ["2000.000", "9800.000"]},
            "disk_area_m2": "10.000",
            "max_power_available_kw": "350.000",
        },
    )
    assert hover_res.status_code == 200
    assert hover_res.json()["result"]["proved"] is True

    # Coverage cells & sweep
    sweep_res = client.post(
        "/coverage/sweep",
        json={
            "actor_id": "author",
            "target_status": "gap",
            "limit": 3,
            "created_at": "2026-11-12T12:01:00Z",
        },
    )
    assert sweep_res.status_code == 200
    assert sweep_res.json()["result"]["processed_count"] == "3"

    cells_res = client.get("/coverage/cells?status=calc&limit=10")
    assert cells_res.status_code == 200
    assert cells_res.json()["result"]["total"] == 3

    # Ledger events query & Merkle consistency proof
    events_res = client.get("/ledger/events?event_type=requirement_recorded&limit=10")
    assert events_res.status_code == 200
    assert events_res.json()["result"]["total"] == 2
    assert len(events_res.json()["result"]["events"]) == 2

    cons_res = client.get("/ledger/consistency?old_count=2")
    assert cons_res.status_code == 200
    assert cons_res.json()["result"]["consistent"] is True

    # Multi-tenant cookie isolation: demo session cannot write into alpha-team
    assert (
        client.post(
            "/coverage/sweep",
            json={"tenant_id": "alpha-team", "actor_id": "author", "limit": 1},
        ).status_code
        == 401
    )

    # Zip export contains in-toto attestation_bundle.json
    zip_res = client.post("/export/zip")
    assert zip_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_res.content)) as bundle:
        assert "attestation_bundle.json" in bundle.namelist()
        att = json.loads(bundle.read("attestation_bundle.json"))
        assert att["_type"] == "https://in-toto.io/Statement/v1"


def test_agent_runtime_preflight_probe_and_invoke_endpoints(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client, actor="author")

    runtime_res = client.get("/agents/runtime")
    assert runtime_res.status_code == 200
    runtime_data = runtime_res.json()["result"]
    assert runtime_data["active_mode"] == "fixture"
    assert "laptop-cpu-16gb" in runtime_data["edge_presets"]

    probe_res = client.post("/agents/probe", json={"target": "all"})
    assert probe_res.status_code == 200
    assert probe_res.json()["result"]["api"]["configured"] is False

    preflight_res = client.post(
        "/agents/edge/preflight",
        json={
            "edge_preset": "offline-wasm-webgpu",
            "text": "SL-1.REQ-01 Peak force 9800.000 N\nBoilerplate line without metrics.",
        },
    )
    assert preflight_res.status_code == 200
    assert preflight_res.json()["result"]["signal_block_count"] == 1

    invoke_res = client.post(
        "/agents/invoke",
        json={
            "agent_id": "reader",
            "text": "SL-1.REQ-01 Design loads",
            "runtime_mode": "fixture",
            "compact_for_edge": True,
            "record": True,
            "actor_id": "author",
        },
    )
    assert invoke_res.status_code == 200
    inv_data = invoke_res.json()["result"]
    assert inv_data["output"]["requirements"][0]["id"] == "ITEM-1"
    assert len(inv_data["recorded_event_hash"]) == 64

    sup_edge_res = client.post(
        "/supervisor/run",
        json={
            "example": "first_cell",
            "actor_id": "author",
            "runtime_mode": "fixture",
            "compact_for_edge": True,
            "edge_preset": "laptop-cpu-16gb",
            "use_decision_gate": True,
        },
    )
    assert sup_edge_res.status_code == 200
    assert len(sup_edge_res.json()["result"]["agent_telemetry"]) == 5


def test_supervisor_stream_sse_and_fail_closed_runtime_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("EDGE_MODEL_URL", raising=False)
    client = _client(tmp_path, monkeypatch)
    _login(client, actor="author")

    # 1. Explicit live mode without URL must fail-closed, never fall back to FixtureGateway
    fail_closed = client.post(
        "/supervisor/run",
        json={
            "example": "first_cell",
            "actor_id": "author",
            "runtime_mode": "api",
        },
    )
    assert fail_closed.status_code == 200
    fc_body = fail_closed.json()
    assert fc_body["confidence"] == "abstain"
    assert fc_body["abstain"]["reason"] == "api_not_configured"
    assert "result" not in fc_body

    # 2. SSE streaming endpoint emits real-time stage/turn events ending in 'done'
    stream_res = client.post(
        "/supervisor/stream",
        json={
            "example": "first_cell",
            "actor_id": "author",
            "runtime_mode": "fixture",
            "use_decision_gate": True,
        },
    )
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.headers["content-type"]
    frames: list[tuple[str, dict]] = []
    for raw_frame in stream_res.text.strip().split("\n\n"):
        lines = [line for line in raw_frame.splitlines() if line]
        ev_line = next((line for line in lines if line.startswith("event: ")), "")
        data_line = next((line for line in lines if line.startswith("data: ")), "")
        if ev_line and data_line:
            frames.append((ev_line[7:].strip(), json.loads(data_line[6:])))

    event_names = [name for name, _ in frames]
    assert event_names == [
        "stage",
        "agent_turn",
        "agent_turn",
        "calc",
        "agent_turn",
        "agent_turn",
        "agent_turn",
        "done",
    ]
    done_payload = frames[-1][1]
    assert done_payload["envelope"]["confidence"] == "deterministic"
    assert done_payload["envelope"]["result"]["cell_updated"] is True
    assert client.get("/ledger/verify").json()["result"]["chain_verified"] is True
