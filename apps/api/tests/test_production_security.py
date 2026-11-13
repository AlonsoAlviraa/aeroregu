from __future__ import annotations

import json
import zipfile
from pathlib import Path

from evidence_api.app import MAX_INGEST_BYTES, _token, create_app
from evidence_ingest.requirements import parse_requirements
from evidence_ingest.router import ingest_bytes
from evidence_kernel.__main__ import main as kernel_cli_main
from evidence_kernel.__main__ import verify_zip_bundle
from fastapi.testclient import TestClient


def _auth_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")
    client = TestClient(create_app())
    login = client.post(
        "/auth/login",
        json={"actor_id": "author", "password": "author-local", "tenant_id": "demo"},
    )
    assert login.status_code == 200
    return client


def test_export_zip_is_100pct_dsse_signed_and_verifiable_offline(
    tmp_path: Path, monkeypatch
) -> None:
    client = _auth_client(tmp_path, monkeypatch)
    calc_res = client.post(
        "/calc/run",
        json={"example": "first_cell", "created_at": "2026-11-13T10:00:00Z"},
    )
    assert calc_res.status_code == 200
    calc_result = calc_res.json()["result"]
    assert "exact_intervals" in calc_result
    assert "weight_n" in calc_result["exact_intervals"]

    pub_res = client.get("/attestation/public-key")
    assert pub_res.status_code == 200
    pub_pem_api = pub_res.json()["result"]["public_key_pem"].encode("utf-8")

    zip_res = client.post("/export/zip")
    assert zip_res.status_code == 200
    bundle_path = tmp_path / "export_bundle.zip"
    bundle_path.write_bytes(zip_res.content)

    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = set(zf.namelist())
        assert {
            "chain.json",
            "merkle_root.txt",
            "attestation_bundle.json",
            "attestation_bundle.dsse.json",
            "attestation_public_key.pem",
        }.issubset(names)

    ok, report = verify_zip_bundle(bundle_path, public_key_pem=pub_pem_api)
    assert ok is True
    assert report["dsse_signature_ok"] is True
    assert report["dsse_digest_ok"] is True
    assert report["chain_ok"] is True
    assert kernel_cli_main(["verify", str(bundle_path)]) == 0

    # Tamper any byte of attestation_bundle.json -> offline verifier must fail closed
    tampered_path = tmp_path / "tampered.zip"
    with zipfile.ZipFile(bundle_path, "r") as zin, zipfile.ZipFile(tampered_path, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "attestation_bundle.json":
                doc = json.loads(data.decode("utf-8"))
                doc["predicate"]["event_count"] = "999"
                data = json.dumps(doc).encode("utf-8")
            zout.writestr(item.filename, data)
    bad_ok, bad_report = verify_zip_bundle(tampered_path)
    assert bad_ok is False
    assert bad_report["error"] == "dsse_digest_mismatch"
    assert kernel_cli_main(["verify", str(tampered_path)]) == 1


def test_production_hardening_tokens_probe_and_ingest_limits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_PRODUCTION", "1")
    prod_client = TestClient(create_app())

    # Default demo password rejected in production unless explicitly provisioned
    denied_login = prod_client.post(
        "/auth/login",
        json={"actor_id": "author", "password": "author-local", "tenant_id": "demo"},
    )
    assert denied_login.status_code == 401

    # Unauthenticated probe blocked
    assert prod_client.post("/agents/probe", json={"target": "all"}).status_code == 401

    # Oversized ingest rejected with 413
    oversize_res = prod_client.post(
        "/ingest/document",
        json={"filename": "huge.txt", "content_text": "x" * (MAX_INGEST_BYTES + 8)},
    )
    assert oversize_res.status_code == 413

    # Expired token rejected even in dev mode
    monkeypatch.setenv("EVIDENCE_PRODUCTION", "0")
    dev_client = TestClient(create_app())
    _auth_client(tmp_path / "dev", monkeypatch)
    expired = _token("author", "demo", ttl_seconds=-30)
    dev_client.cookies.set("el_session", expired)
    assert dev_client.post("/export/zip").status_code == 401


def test_regulatory_cs27_cs29_pdf_bbox_and_pilot_metrics(tmp_path: Path, monkeypatch) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "CS-27.301 Flight ground and water loads distribution")
    pdf_bytes = doc.tobytes()
    doc.close()

    parsed = ingest_bytes(pdf_bytes, "cs27_extract.pdf")
    reqs = parsed["requirements"]
    assert any(r["id"] == "CS-27.301" for r in reqs)
    cs27 = next(r for r in reqs if r["id"] == "CS-27.301")
    assert cs27["page_no"] == 1
    assert isinstance(cs27["bbox"], list) and len(cs27["bbox"]) == 4

    # Also validate parse_requirements handles CS-29.301(a), FAR 27.301, DO-178C cleanly
    from evidence_ingest.blocks import Block

    b = Block(
        "CS-29.301(a) Limit load factor check",
        0,
        37,
        "f" * 64,
        page_no=2,
        bbox=(1.0, 2.0, 3.0, 4.0),
    )
    multi = parse_requirements([b])
    assert multi[0]["id"] == "CS-29.301(a)"
    assert multi[0]["page_no"] == 2
    assert multi[0]["bbox"] == ["1.00", "2.00", "3.00", "4.00"]

    # Signoff telemetry & /metrics/pilot
    client = _auth_client(tmp_path / "pilot", monkeypatch)
    calc_res = client.post(
        "/calc/run",
        json={"example": "first_cell", "created_at": "2026-11-13T10:00:00Z"},
    )
    assert calc_res.status_code == 200
    client.post(
        "/auth/login",
        json={"actor_id": "reviewer", "password": "reviewer-local", "tenant_id": "demo"},
    )
    sign_res = client.post(
        "/ledger/signoff",
        json={
            "actor_id": "reviewer",
            "created_at": "2026-11-13T10:05:00Z",
            "review_duration_ms": 4200,
        },
    )
    assert sign_res.status_code == 200
    assert sign_res.json()["result"]["review_duration_ms"] == 4200

    metrics = client.get("/metrics/pilot").json()["result"]
    assert metrics["signed_reviews"] == 1
    assert metrics["timed_reviews"] == 1
    assert metrics["avg_review_duration_ms"] == 4200


def test_audit_security_bugfixes_caching_and_openapi_sync(tmp_path: Path, monkeypatch) -> None:
    import hashlib
    import hmac
    import sqlite3

    import yaml
    from evidence_api.app import _attestation_keypair, _bolt_inputs, open_ledger
    from evidence_api.mcp_server import handle_mcp_message
    from evidence_kernel.formal import SMTSolverProofEngine
    from evidence_kernel.ledger import PBKDF2_ITERATIONS

    home = tmp_path / "audit_home"
    monkeypatch.setenv("EVIDENCE_HOME", str(home))
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")

    # SEC-06: Password digest enforces >= 600,000 PBKDF2 iterations
    ledger = open_ledger("demo")
    with sqlite3.connect(ledger.path) as conn:
        pw_hash = conn.execute(
            "SELECT password_hash FROM actors WHERE actor_id = 'author'"
        ).fetchone()[0]
    assert pw_hash.startswith(f"pbkdf2_sha256${PBKDF2_ITERATIONS}$")
    assert PBKDF2_ITERATIONS >= 600_000

    # BUG-03 + P1: Repeated open_ledger() reuses cached instance
    assert open_ledger("demo") is ledger

    # SEC-03: Keypair lives under EVIDENCE_HOME (never inside repo data/)
    _attestation_keypair()
    assert (home / ".keys" / "attestation_ed25519.pem").is_file()

    # BUG-01: MCP evidence_calc_run supports stated_outputs cleanly
    calc_msg = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "evidence_calc_run",
                "arguments": {
                    "method_id": "bolt_screen",
                    "inputs": _bolt_inputs("3000.000"),
                    "stated_outputs": {
                        "shear_stress_mpa": "37.500",
                        "tensile_stress_mpa": "50.000",
                        "shear_ratio": "0.150",
                        "tensile_ratio": "0.200",
                        "interaction_ratio": "0.999",
                    },
                },
            },
        }
    )
    assert isinstance(calc_msg, dict)
    assert calc_msg["result"]["isError"] is False
    sc = calc_msg["result"]["structuredContent"]
    assert sc["fault_kind"] == "unexplained"
    assert sc["delta_vs_stated"]["interaction_ratio"]["match"] is False

    # SEC-02: MCP path confinement rejects outside writes/reads & succeeds inside exports/
    bad_export = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "evidence_bundle_export",
                "arguments": {"output_path": str(tmp_path / "escape.zip")},
            },
        }
    )
    assert bad_export is not None
    assert bad_export["result"]["isError"] is True
    assert bad_export["result"]["structuredContent"]["error"] == "path_outside_allowed_root"

    good_export = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "evidence_bundle_export",
                "arguments": {"output_path": "audit_safe.zip"},
            },
        }
    )
    assert good_export is not None
    assert good_export["result"]["isError"] is False
    exported_file = Path(good_export["result"]["structuredContent"]["output_path"])
    assert exported_file.is_relative_to((home / "exports").resolve())

    bad_verify = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "evidence_bundle_verify",
                "arguments": {"bundle_path": str(tmp_path / "escape.zip")},
            },
        }
    )
    assert bad_verify is not None
    assert bad_verify["result"]["structuredContent"]["error"] == "path_outside_allowed_root"

    good_verify = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "evidence_bundle_verify",
                "arguments": {"bundle_path": "audit_safe.zip"},
            },
        }
    )
    assert good_verify is not None
    assert good_verify["result"]["isError"] is False
    assert good_verify["result"]["structuredContent"]["dsse_signature_ok"] is True

    # SEC-01 + HTTP auth hardening in production mode (isolated production home)
    prod_home = tmp_path / "prod_home"
    monkeypatch.setenv("EVIDENCE_HOME", str(prod_home))
    monkeypatch.setenv("EVIDENCE_PRODUCTION", "1")
    monkeypatch.setenv("EVIDENCE_AUTHOR_PASSWORD", "ProdAuthor!Pass123")
    prod_client = TestClient(create_app())

    for protected_tool in ("evidence_verify_case", "evidence_bundle_verify"):
        blocked = prod_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": protected_tool,
                    "arguments": (
                        {"text": "CS-27.301 load check"}
                        if protected_tool == "evidence_verify_case"
                        else {"bundle_path": "audit_safe.zip"}
                    ),
                },
            },
        )
        assert blocked.status_code == 200
        assert blocked.json()["result"]["isError"] is True
        assert blocked.json()["result"]["structuredContent"]["error"] == "auth_required"

    # SEC-04: Reject legacy 1-part and 2-part tokens without TTL
    secret = b"enterprise-secret-key-24-plus-chars"
    for legacy_sub in ("author", "demo:author"):
        mac = hmac.new(secret, legacy_sub.encode(), hashlib.sha256).hexdigest()
        prod_client.cookies.set("el_session", f"{legacy_sub}.{mac}")
        assert prod_client.get("/auth/me").status_code == 401
        assert prod_client.post("/export/zip").status_code == 401

    # SEC-05 + P2: Login cookie carries Secure over HTTPS, /auth/me works, /auth/logout revokes
    prod_client.cookies.clear()
    login_resp = prod_client.post(
        "/auth/login",
        headers={"x-forwarded-proto": "https"},
        json={"actor_id": "author", "password": "ProdAuthor!Pass123", "tenant_id": "demo"},
    )
    assert login_resp.status_code == 200
    assert "Secure" in login_resp.headers.get("set-cookie", "")
    # Inject returned cookie explicitly over HTTP test client to verify /auth/me + /auth/logout
    session_cookie = login_resp.cookies.get("el_session")
    assert session_cookie
    prod_client.cookies.set("el_session", session_cookie)
    me_resp = prod_client.get("/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["result"]["actor_id"] == "author"

    # BUG-02: No unhandled 500s on missing/unknown fields
    assert prod_client.post("/calc/run", json={}).status_code == 400
    assert (
        prod_client.post(
            "/calc/run",
            json={
                "method_id": "bolt_screen",
                "inputs": _bolt_inputs("3000.000"),
                "record": True,
                "cell_id": "non-existent-cell",
            },
        ).status_code
        == 404
    )
    assert prod_client.post("/notes/check", json={}).status_code == 400
    assert prod_client.post("/ledger/append", json={"actor_id": "author"}).status_code == 400

    # Logout revokes token so replaying old cookie fails with 401
    out_resp = prod_client.post("/auth/logout")
    assert out_resp.status_code == 200
    prod_client.cookies.set("el_session", session_cookie)
    assert prod_client.get("/auth/me").status_code == 401

    # P2: Rate limit triggers cleanly on repeated logins when threshold is low
    monkeypatch.setenv("EVIDENCE_LOGIN_RATE_LIMIT", "2")
    assert (
        prod_client.post(
            "/auth/login",
            json={"actor_id": "author", "password": "wrong", "tenant_id": "rl"},
        ).status_code
        == 401
    )
    assert (
        prod_client.post(
            "/auth/login",
            json={"actor_id": "author", "password": "wrong", "tenant_id": "rl"},
        ).status_code
        == 401
    )
    assert (
        prod_client.post(
            "/auth/login",
            json={"actor_id": "author", "password": "wrong", "tenant_id": "rl"},
        ).status_code
        == 429
    )

    # P1: SMT cache returns identical object across repeated identical queries
    engine = SMTSolverProofEngine()
    bounds = {
        "area_mm2": ("110.000", "130.000"),
        "shear_force_n": ("1000.000", "2000.000"),
        "tensile_force_n": ("2000.000", "3000.000"),
    }
    allow = {"shear_allowable_mpa": "150.000", "tensile_allowable_mpa": "250.000"}
    p1 = engine.prove_structural_margin(bounds, allow, "1.500")
    p2 = engine.prove_structural_margin(bounds, allow, "1.500")
    assert p1 is p2

    # P1: OpenAPI YAML matches every live HTTP route
    app_instance = create_app()
    spec_path = Path(__file__).resolve().parents[3] / "schemas" / "openapi.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    live_paths = {
        r.path
        for r in app_instance.routes
        if getattr(r, "methods", None)
        and r.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }
    assert live_paths == set(spec["paths"].keys())
