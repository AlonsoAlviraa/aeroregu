"""Comprehensive E2E hardening & UX verification across Phases 1-4."""

from __future__ import annotations

import json
from pathlib import Path

from evidence_api.app import create_app, open_ledger
from evidence_api.cli import (
    _complete_material,
    _complete_method_id,
    _complete_tenant,
)
from evidence_api.cli import (
    app as cli_app,
)
from evidence_api.formal_methods import (
    METHOD_DEFAULT_INPUTS,
    run_formal_proof_for_method,
)
from evidence_api.mcp_server import get_mcp_inventory_counts, handle_mcp_message
from evidence_api.wizard import _DEFAULT_CALC_VALUES
from evidence_calc.registry import register_custom_card
from evidence_coverage.collaboration_ecn import ReviewThreadStore, get_review_thread_store
from evidence_kernel.hsm_eidas_scim import SCIMDirectoryService, WebAuthnStepUpVerifier
from fastapi.testclient import TestClient
from typer.testing import CliRunner


def test_phase1_rbac_and_missing_q1_q3_endpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_PRODUCTION", "1")
    monkeypatch.setenv("EVIDENCE_AUTHOR_PASSWORD", "author-prod-pass")
    monkeypatch.setenv("EVIDENCE_REVIEWER_PASSWORD", "reviewer-prod-pass")
    monkeypatch.setenv("EVIDENCE_ADMIN_PASSWORD", "admin-prod-pass")
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")

    client = TestClient(create_app())

    protected_calls = [
        ("GET", "/cae/mesh/demo-mesh", None),
        ("POST", "/plm/sync", {"system": "3dexperience", "item_id": "WING-SPAR-ASM-01"}),
        ("POST", "/ecn/diff", {"rev_a": {}, "rev_b": {}}),
        ("GET", "/reviews/threads", None),
        ("POST", "/scim/v2/Users", {"userName": "alice.cve", "roles": ["cve"]}),
        ("GET", "/legal/ma-readiness", None),
        ("POST", "/qualification/iq-oq/run", {}),
        ("POST", "/cad/brep/analyze", {"filename": "part.stp", "content_text": "ISO-10303-21;"}),
        ("POST", "/cae/binary/parse", {"filename": "res.op2", "content_base64": ""}),
        ("GET", "/security/sbom", None),
        ("GET", "/ingest/document/demo/page/1", None),
    ]
    for method, url, payload in protected_calls:
        resp = (
            client.request(method, url, json=payload)
            if payload is not None
            else client.request(method, url)
        )
        assert resp.status_code == 401, (
            f"Expected 401 on unauth {method} {url}, got {resp.status_code}"
        )

    assert client.get("/calc/materials").status_code == 200
    assert (
        client.post(
            "/calc/allowables",
            json={"material_id": "AL-7075-T651", "basis": "A", "property_name": "fty_mpa"},
        ).status_code
        == 200
    )
    assert client.get("/mcp/catalog").status_code == 200

    login_author = client.post(
        "/auth/login",
        json={"actor_id": "author", "password": "author-prod-pass", "tenant_id": "demo"},
    )
    assert login_author.status_code == 200

    for method, url, payload in [
        ("POST", "/scim/v2/Users", {"userName": "alice.cve", "roles": ["cve"]}),
        ("GET", "/legal/ma-readiness", None),
        ("POST", "/qualification/iq-oq/run", {}),
        ("GET", "/security/sbom", None),
    ]:
        resp = (
            client.request(method, url, json=payload)
            if payload is not None
            else client.request(method, url)
        )
        assert resp.status_code == 403, (
            f"Expected 403 for author on {method} {url}, got {resp.status_code}"
        )

    login_rev = client.post(
        "/auth/login",
        json={"actor_id": "reviewer", "password": "reviewer-prod-pass", "tenant_id": "demo"},
    )
    assert login_rev.status_code == 200

    scim_ok = client.post("/scim/v2/Users", json={"userName": "elena.cve", "roles": ["cve"]})
    assert scim_ok.status_code == 201
    assert scim_ok.json()["userName"] == "elena.cve"
    assert client.get("/legal/ma-readiness").status_code == 200
    assert client.post("/qualification/iq-oq/run", json={}).status_code == 200
    assert client.get("/security/sbom").status_code == 200


def test_phase1_sqlite_persistence_across_reloads(tmp_path: Path) -> None:
    review_dir = tmp_path / "reviews"
    store1 = ReviewThreadStore(storage_dir=review_dir, persist=True)
    created = store1.create_thread(
        "demo",
        target_event_hash="a" * 64,
        author_id="author",
        body="Check lug margin against MMPDS-16 A-basis",
        initial_status="OPEN",
    )
    store1.reply_thread(
        "demo", created["thread_id"], actor_id="cve", body="Validated with A-basis."
    )

    store2 = ReviewThreadStore(storage_dir=review_dir, persist=True)
    threads = store2.list_threads("demo", target_event_hash="a" * 64)
    assert len(threads) == 1
    assert threads[0]["thread_id"] == created["thread_id"]
    assert len(threads[0]["comments"]) == 2

    sec_db = tmp_path / "security_state.sqlite3"
    scim1 = SCIMDirectoryService(storage_path=sec_db)
    user = scim1.create_user("demo", {"userName": "marco.cve", "roles": ["cve"]})
    webauthn1 = WebAuthnStepUpVerifier(storage_path=sec_db)
    cred = webauthn1.register_credential("demo", "marco.cve", credential_id="cred-m1")
    challenge = webauthn1.issue_challenge("marco.cve", "demo")
    assertion = webauthn1.build_signed_assertion(challenge)
    assert cred["credential_id"] == "cred-m1"

    scim2 = SCIMDirectoryService(storage_path=sec_db)
    reloaded = scim2.get_user("demo", user["id"])
    assert reloaded is not None
    assert reloaded["userName"] == "marco.cve"
    webauthn2 = WebAuthnStepUpVerifier(storage_path=sec_db)
    verified = webauthn2.verify_assertion(
        assertion, expected_actor_id="marco.cve", expected_tenant_id="demo"
    )
    assert verified["step_up_verified"] is True
    webauthn3 = WebAuthnStepUpVerifier(storage_path=sec_db)
    consumed = webauthn3.consume_step_up_token(
        verified["webauthn_token"], actor_id="marco.cve", tenant_id="demo"
    )
    assert consumed is True


def test_phase1_signoff_governance_and_mcp_path_confinement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")

    runner = CliRunner()
    calc_res = runner.invoke(
        cli_app,
        [
            "calc",
            "run",
            "margin_of_safety",
            "--inputs",
            json.dumps(METHOD_DEFAULT_INPUTS["margin_of_safety"]),
            "--record",
            "--actor",
            "author",
            "--json",
        ],
    )
    assert calc_res.exit_code == 0, calc_res.output

    head_hash = open_ledger("demo").head_hash()
    thread_store = get_review_thread_store()
    thr = thread_store.create_thread(
        "demo",
        target_event_hash=head_hash,
        author_id="reviewer",
        body="Clarify fitting factor assumption",
        initial_status="OPEN",
    )

    blocked_cli = runner.invoke(
        cli_app,
        ["ledger", "signoff", "--actor", "reviewer", "--target", head_hash],
    )
    assert blocked_cli.exit_code == 2

    blocked_mcp = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "evidence_ledger_signoff",
                "arguments": {
                    "tenant_id": "demo",
                    "actor_id": "reviewer",
                    "target_event_hash": head_hash,
                },
            },
        }
    )
    assert blocked_mcp["result"]["isError"] is True
    assert "unresolved_review_threads" in json.dumps(blocked_mcp)

    thread_store.resolve_thread(
        "demo",
        thr["thread_id"],
        resolver_id="reviewer",
        resolution_note="Verified 1.15 fitting factor per CS-25.625.",
    )

    sod_cli = runner.invoke(
        cli_app,
        ["ledger", "signoff", "--actor", "author", "--target", head_hash],
    )
    assert sod_cli.exit_code == 2

    ok_cli = runner.invoke(
        cli_app,
        ["ledger", "signoff", "--actor", "reviewer", "--target", head_hash, "--json"],
    )
    assert ok_cli.exit_code == 0, ok_cli.output

    locked = thread_store.list_threads("demo", target_event_hash=head_hash)
    assert any(
        item["thread_id"] == thr["thread_id"] and item["status"] == "LOCKED_ON_SIGNOFF"
        for item in locked
    )

    traversal_mcp = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "evidence_dossier_pdf_export",
                "arguments": {
                    "tenant_id": "demo",
                    "output_path": "../../outside_escape.pdf",
                },
            },
        }
    )
    assert traversal_mcp["result"]["isError"] is True
    assert traversal_mcp["result"]["structuredContent"]["error"] == "output_path_outside_workspace"


def test_phase2_formal_proofs_all_32_methods_plugins_and_counterexample(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")

    counts = get_mcp_inventory_counts()
    assert counts["tools"] >= 30
    assert counts["resources"] >= 6
    assert counts["prompts"] >= 4
    assert counts["formal_methods"] >= 32

    assert len(METHOD_DEFAULT_INPUTS) >= 32
    for method_id in METHOD_DEFAULT_INPUTS:
        res = run_formal_proof_for_method(method_id)
        assert res["proved"] is True, f"{method_id} failed formal proof: {res}"
        assert res["status"] in ("PROVED", "PROVED_UNSAT"), f"{method_id}: {res}"

    ce = run_formal_proof_for_method(
        "margin_of_safety",
        {
            "applied_load_n": "30000.000",
            "allowable_load_n": "20000.000",
            "reserve_factor": "1.000",
            "fitting_factor": "1.150",
        },
    )
    assert ce["proved"] is False
    assert ce["status"] == "COUNTEREXAMPLE_FOUND"

    register_custom_card(
        {
            "method_id": "custom_axial_stress",
            "title": "Custom Axial Stress",
            "quantum": "0.001",
            "required": ["force_n", "area_m2"],
            "limits": {
                "force_n": {"min": "1", "max": "1000000"},
                "area_m2": {"min_exclusive": "0", "max": "10"},
            },
            "formulas": [{"output": "stress_pa", "expr": "force_n / area_m2"}],
        }
    )
    plugin_proof = run_formal_proof_for_method(
        "custom_axial_stress",
        {"force_n": "5000", "area_m2": "0.02"},
    )
    assert plugin_proof["proved"] is True

    client = TestClient(create_app())
    calc_resp = client.post(
        "/calc/run",
        json={
            "method_id": "margin_of_safety",
            "inputs": METHOD_DEFAULT_INPUTS["margin_of_safety"],
            "formal_proof": True,
        },
    )
    assert calc_resp.status_code == 200
    assert calc_resp.json()["result"]["formal_proof"]["proved"] is True


def test_phase3_cli_and_wizard_completeness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))

    assert len(_DEFAULT_CALC_VALUES) >= 32
    assert "lug_axial_transverse_interaction" in _complete_method_id("lug")
    assert "AL-7075-T651" in _complete_material("7075")
    assert "demo" in _complete_tenant("de")

    runner = CliRunner()
    commands = [
        ["materials", "list", "--json"],
        ["materials", "lookup", "AL-7075-T651", "--basis", "A", "--json"],
        ["plm", "sync", "--json"],
        [
            "ecn",
            "diff",
            "--rev-a",
            '{"margins": {"RIB-1": 0.25}}',
            "--rev-b",
            '{"margins": {"RIB-1": 0.12}}',
            "--json",
        ],
        ["qualification", "run", "--json"],
        ["security", "sbom", "--json"],
        ["security", "ma-readiness", "--json"],
        ["bundle", "export-qes", str(tmp_path / "bundle_qes.zip"), "--json"],
        ["ledger", "log", "--event-type", "calc_run", "--json"],
        ["coverage", "status", "--limit", "5", "--json"],
    ]
    for cmd in commands:
        res = runner.invoke(cli_app, cmd)
        assert res.exit_code == 0, f"CLI command {cmd} failed:\n{res.output}"
        json.loads(res.output)


def test_phase4_frontend_ux_and_static_modules(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    client = TestClient(create_app())

    root_resp = client.get("/")
    js_resp = client.get("/static/q4_ux_modules.js")
    cat_resp = client.get("/mcp/catalog")

    assert root_resp.status_code == 200
    assert js_resp.status_code == 200
    assert cat_resp.status_code == 200

    html = root_resp.text
    for marker in [
        "material-preset-select",
        "pdf-bbox-viewer-panel",
        "review-threads-panel",
        "ecn-diff-panel",
        "plm-bridges-panel",
        "qualification-qes-panel",
        "actor-select",
        "/static/q4_ux_modules.js",
    ]:
        assert marker in html, f"Missing frontend marker in demo.html: {marker}"

    assert "slice(0, 300)" not in html
    assert "slice(0, 600)" not in html
    assert "100" not in html
    assert "compliant" not in html.lower()

    js = js_resp.text
    for symbol in [
        "setFullJsonOutput",
        "renderDocPageBbox",
        "normalizeMeshForViewer",
        "FAMILY_TITLES",
    ]:
        assert symbol in js, f"Missing JS symbol in q4_ux_modules.js: {symbol}"
