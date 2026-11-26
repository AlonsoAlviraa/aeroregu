"""Sprint 6 Full Integration Test Suite Covering All 6 Improvement Blocks."""

from __future__ import annotations

import base64
import io
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pymupdf
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from evidence_api.app import create_app
from evidence_api.mcp_server import handle_mcp_message
from evidence_calc.allowables import (
    list_materials,
    lookup_nasgro_paris_params,
    lookup_sn_fatigue_allowable,
)
from evidence_calc.units import dimension_exponents, extended_dimension_exponents
from evidence_coverage.cluster_readiness import (
    SharedWorkerCacheCoordinator,
    verify_cluster_infra_manifests,
    verify_postgres_rls_and_worm_ddl,
)
from evidence_coverage.enterprise_kms_airgap import (
    AWSKMSAdapter,
    PKCS11HSMBridge,
    VaultTransitSigner,
    generate_cyclonedx_sbom_from_uv_lock,
)
from evidence_coverage.quotation_exporter import verify_quotation_signed_pdf
from evidence_eval.b2 import predict_generic_traces
from evidence_ingest.blocks import IngestAbstain
from evidence_ingest.cad_brep import (
    _AEROSPACE_DENSITIES_KG_M3,
    analyze_step_with_ocp_or_polyhedral,
)
from evidence_ingest.cae_binary import benchmark_cae_streaming_file, run_sandboxed_cae_worker
from evidence_ingest.pdf import dual_pass_ocr_verify_text, ingest_pdf_parallel
from evidence_ingest.plm_connectors import run_plm_ecn_resilience_probe
from fastapi.testclient import TestClient
from openpyxl import load_workbook


def _make_hybrid_pdf_bytes(pages: int = 3) -> bytes:
    doc = pymupdf.open()
    for i in range(1, pages + 1):
        p = doc.new_page(width=595, height=842)
        p.insert_text((48, 72), f"CS-29.301 Flight Load Case {i}: Limit Load = {12500 + i * 100} N")
    raw = doc.tobytes()
    doc.close()
    return raw


def test_sprint6_block1_cockpit_v4_and_batch_stress_binary_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "ehome"))
    repo_root = Path(__file__).resolve().parents[1]
    demo_html = (repo_root / "apps/api/src/evidence_api/static/demo.html").read_text(
        encoding="utf-8"
    )
    cockpit_js = (repo_root / "apps/api/src/evidence_api/static/quotation_cockpit.js").read_text(
        encoding="utf-8"
    )
    q4_js = (repo_root / "apps/api/src/evidence_api/static/q4_ux_modules.js").read_text(
        encoding="utf-8"
    )

    # Guards must pass: zero "100", zero "compliant"
    assert "100" not in demo_html
    assert "compliant" not in demo_html.lower()
    for elem_id in (
        "quote-port-onshore",
        "quote-port-nearshore",
        "quote-portfolio-xlsx-btn",
        "quote-portfolio-pdf-btn",
        "quote-allow-arb-btn",
        "quote-stress-dossier-run-btn",
        "quote-stress-xlsx-btn",
        "quote-stress-pdf-btn",
        "quote-passkey-reauth-btn",
        "quote-stress-table",
    ):
        assert elem_id in demo_html

    assert "safeSetHTML" in cockpit_js
    assert "setHTML" in cockpit_js
    assert "parseRequestOptionsFromJSON" in cockpit_js
    assert "signalUnknownCredential" in cockpit_js
    assert "rotorcraft_dynamics" in q4_js

    # OpenAPI parity & FastAPI binary endpoints
    spec = yaml.safe_load((repo_root / "schemas/openapi.yaml").read_text(encoding="utf-8"))
    for ep in (
        "/calc/batch-stress-dossier/export-xlsx",
        "/calc/batch-stress-dossier/export-pdf",
        "/ingest/heavy-pdf",
        "/auth/webauthn/reauth/options",
        "/auth/webauthn/reauth/verify",
        "/security/sbom-airgap-audit",
    ):
        assert ep in spec["paths"]

    client = TestClient(create_app())
    r_x = client.post("/calc/batch-stress-dossier/export-xlsx", json={"dossier_id": "V4-S6"})
    assert r_x.status_code == 200
    assert int(r_x.headers["X-AeroRegu-Formula-Count"]) >= 12
    wb = load_workbook(io.BytesIO(r_x.content), data_only=False)
    assert "1_Stress_Summary" in wb.sheetnames

    r_p = client.post("/calc/batch-stress-dossier/export-pdf", json={"dossier_id": "V4-S6"})
    assert r_p.status_code == 200
    assert verify_quotation_signed_pdf(r_p.content)["valid"] is True


def test_sprint6_block2_pg_rls_worm_cluster_cache_and_manifests(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ddl_res = verify_postgres_rls_and_worm_ddl(repo_root / "infra/postgres/init-rls-worm.sql")
    assert ddl_res["verified"] is True

    infra_res = verify_cluster_infra_manifests(repo_root)
    assert infra_res["verified"] is True

    # Two independent worker coordinators sharing the same SQLite-WAL epoch store
    db = tmp_path / "shared_cache.db"
    worker_1 = SharedWorkerCacheCoordinator(db)
    worker_2 = SharedWorkerCacheCoordinator(db)
    ep1 = worker_1.bump_version("airbus", "ledger_head", head_hash="abc123")
    assert worker_2.is_stale("airbus", ep1 - 1, "ledger_head") is True
    assert worker_2.get_version("airbus", "ledger_head")["head_hash"] == "abc123"


def test_sprint6_block3_cad_ocp_fallback_cae_hardening_and_plm_resilience(tmp_path: Path) -> None:
    # Synced Sprint 6 densities
    assert _AEROSPACE_DENSITIES_KG_M3["INCONEL-718"] == 8190.0
    assert _AEROSPACE_DENSITIES_KG_M3["17-4PH-H1025"] == 7800.0
    assert _AEROSPACE_DENSITIES_KG_M3["E-GLASS-8552"] == 1900.0
    assert _AEROSPACE_DENSITIES_KG_M3["NOMEX-HRH10-48"] == 48.0

    # STEP B-Rep analyzer reports backend cleanly whether OCP is installed or fallback runs
    minimal_step = (
        b"ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('AP242'));\n"
        b"ENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;"
    )
    cad_res = analyze_step_with_ocp_or_polyhedral(minimal_step, default_material="INCONEL-718")
    assert cad_res["kernel_backend"] in {"opencascade_nurbs", "polyhedral_exact"}

    # Sandboxed ODB/RST multi-subcase residual verification
    odb_ok = b"ODB_AERO" + json.dumps(
        {
            "element_count": 48000,
            "subcase_count": 2,
            "ms_min": "0.184",
            "equilibrium_residuals": [
                {"fx": 0.001, "fy": -0.002, "fz": 0.0005, "mx": 0.0, "my": 0.0, "mz": 0.0},
            ],
            "subcase_pid_ms": {"101": ["0.310", "0.184"], "102": ["0.450"]},
        }
    ).encode("utf-8")
    cae_ok = run_sandboxed_cae_worker(odb_ok, "a" * 64, "odb")
    assert cae_ok["equilibrium_verified"] is True
    assert cae_ok["pid_ms_summary"]["101"] == "0.184"

    odb_bad_eq = b"ODB_AERO" + json.dumps(
        {
            "element_count": 1000,
            "equilibrium_residuals": [
                {"fx": 12.5, "fy": 0.0, "fz": 0.0, "mx": 0.0, "my": 0.0, "mz": 0.0}
            ],
        }
    ).encode("utf-8")
    assert run_sandboxed_cae_worker(odb_bad_eq, "b" * 64, "rst")["equilibrium_verified"] is False

    # Size cap fails closed
    with pytest.raises(IngestAbstain, match="sandboxed_worker_output_exceeded"):
        run_sandboxed_cae_worker(odb_ok, "c" * 64, "odb", max_output_bytes=16)

    # Streaming benchmark on AEROH5 binary file
    import numpy as np
    from evidence_ingest.cae_binary import (
        DTYPE_ELEM,
        DTYPE_EQUILIBRIUM,
        DTYPE_NODE,
        DTYPE_STRESS_CHUNK,
        write_cae_h5_stream,
    )

    h5_path = tmp_path / "bench_model.h5"
    nodes = np.zeros(4, dtype=DTYPE_NODE)
    nodes["nid"] = [1, 2, 3, 4]
    elems = np.zeros(500, dtype=DTYPE_ELEM)
    elems["eid"] = np.arange(1, 501)
    elems["pid"] = 101
    elems["etype"] = 3
    elems["allowable_mpa"] = 441.0
    eq = np.zeros(2, dtype=DTYPE_EQUILIBRIUM)
    eq["subcase_id"] = [1, 2]
    stress = np.zeros(500, dtype=DTYPE_STRESS_CHUNK)
    stress["subcase_id"] = 1
    stress["eid"] = np.arange(1, 501)
    stress["pid"] = 101
    stress["etype"] = 3
    stress["von_mises_mpa"] = 210.0
    stress["margin_of_safety"] = 0.25
    write_cae_h5_stream(
        h5_path, nodes=nodes, elements=elems, equilibrium=eq, stress_chunks=[stress]
    )
    bm = benchmark_cae_streaming_file(h5_path)
    assert bm["element_count"] == 500
    assert bm["elements_per_second"] > 0

    # PLM ECN resilience under transient 503 + expired OAuth token
    plm = run_plm_ecn_resilience_probe("3dexperience", inject_503_count=2, expire_token_once=True)
    assert plm["writeback_status"] == "attested"
    assert plm["http_503_retries_observed"] == 2
    assert plm["http_401_refreshes_observed"] >= 1
    assert "cell-rib-revb" in plm["invalidated_cells"]
    assert "cell-lug-untouched" in plm["unaffected_cells"]


def test_sprint6_block4_dual_pass_ocr_and_heavy_pdf_endpoint() -> None:
    ok_ocr = dual_pass_ocr_verify_text("CS-29 Limit Load = 12500 N", "CS-29 Limit Load = 12500 N")
    assert ok_ocr["abstain"] is False
    assert ok_ocr["numeric_exact_match"] is True

    bad_ocr = dual_pass_ocr_verify_text("CS-29 Limit Load = 12500 N", "CS-29 Limit Load = 12900 N")
    assert bad_ocr["abstain"] is True
    assert bad_ocr["reason"] == "low_ocr_confidence_numeric_mismatch"

    pdf_raw = _make_hybrid_pdf_bytes(pages=3)
    # Parallel ingest with secondary pass mismatch abstains on mismatched pages cleanly
    res_par = ingest_pdf_parallel(
        pdf_raw,
        source_uri="rfq_heavy.pdf",
        max_workers=2,
        chunk_pages=1,
        secondary_ocr_fn=lambda pno, txt: txt.replace("12600", "99999") if pno == 1 else txt,
    )
    assert res_par["total_pages"] == 3
    assert any(
        a["page_no"] == 1 and a["reason"] == "low_ocr_confidence_numeric_mismatch"
        for a in res_par["abstained_pages"]
    )

    client = TestClient(create_app())
    r_hp = client.post(
        "/ingest/heavy-pdf",
        json={
            "filename": "rfq_heavy.pdf",
            "content_base64": base64.b64encode(pdf_raw).decode("ascii"),
            "max_workers": 2,
            "chunk_pages": 2,
        },
    )
    assert r_hp.status_code == 200
    hp_data = r_hp.json()["result"]
    assert hp_data["total_pages"] == 3
    assert len(hp_data["verified_pages"]) == 3


def test_sprint6_block5_kms_vault_webauthn_sbom_and_mcp50(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path / "ehome"))
    repo_root = Path(__file__).resolve().parents[1]

    # 1. PKCS#11 HSM DSSE roundtrip
    hsm = PKCS11HSMBridge()
    env_hsm = hsm.sign_dsse({"artifact": "stress-note", "ms_min": "0.244"})
    assert hsm.verify_dsse(env_hsm) is True

    # 2. AWS KMS Adapter DSSE roundtrip
    kms = AWSKMSAdapter("arn:aws:kms:eu-central-1:123456789012:key/aeroregu-cve")
    env_kms = kms.sign_dsse({"artifact": "dossier", "rev": "B"})
    assert kms.verify_dsse(env_kms) is True

    # 3. HashiCorp Vault Transit mock transport roundtrip
    sigs_seen: dict[str, str] = {}

    def _vault_handler(req: httpx.Request) -> httpx.Response:
        if "/v1/transit/sign/" in req.url.path:
            inp = json.loads(req.content.decode("utf-8"))["input"]
            sig = "vault:v1:" + base64.b64encode(inp.encode("ascii")).decode("ascii")
            sigs_seen[inp] = sig
            return httpx.Response(200, json={"data": {"signature": sig}})
        if "/v1/transit/verify/" in req.url.path:
            body = json.loads(req.content.decode("utf-8"))
            ok = sigs_seen.get(body["input"]) == body["signature"]
            return httpx.Response(200, json={"data": {"valid": ok}})
        return httpx.Response(404)

    vault = VaultTransitSigner(
        "https://vault.internal:8200",
        "aeroregu-dsse",
        "hvs.mock-token",
        transport=httpx.MockTransport(_vault_handler),
    )
    env_v = vault.sign_dsse({"vault": "transit", "ok": True})
    assert vault.verify_dsse(env_v) is True

    # 4. CycloneDX 1.5 SBOM + offline CVE floor detection + HSM signature
    sbom_ok = generate_cyclonedx_sbom_from_uv_lock(repo_root, sign_backend=hsm)
    assert sbom_ok["bom_format"] == "CycloneDX"
    assert sbom_ok["component_count"] >= 40
    assert hsm.verify_dsse(sbom_ok["dsse_envelope"]) is True

    sbom_cve = generate_cyclonedx_sbom_from_uv_lock(
        repo_root, offline_cve_advisories={"fastapi": "999.0.0"}
    )
    assert sbom_cve["airgap_clean"] is False
    assert sbom_cve["cve_finding_count"] >= 1

    # 5. WebAuthn Step-Up Reauthentication (active user scoping + cross-user rejection)
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    client = TestClient(create_app())
    opts_r = client.post(
        "/auth/webauthn/reauth/options",
        json={
            "user_id": "cve.martinez",
            "register_credential": {
                "user_id": "cve.martinez",
                "credential_id": "cred-martinez-1",
                "public_key_pem": pub_pem.decode("utf-8"),
            },
        },
    )
    assert opts_r.status_code == 200
    opts_res = opts_r.json()["result"]
    challenge = opts_res["challenge"]
    assert opts_res["allowCredentials"][0]["id"] == "cred-martinez-1"

    sig_b64 = base64.b64encode(priv.sign(challenge.encode("utf-8"))).decode("ascii")
    ver_ok = client.post(
        "/auth/webauthn/reauth/verify",
        json={
            "user_id": "cve.martinez",
            "id": "cred-martinez-1",
            "challenge": challenge,
            "signature_b64": sig_b64,
        },
    )
    assert ver_ok.status_code == 200
    assert ver_ok.json()["result"]["verified"] is True

    # Cross-user credential replay rejected with 403
    priv2 = ed25519.Ed25519PrivateKey.generate()
    pub2 = priv2.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    opts2 = client.post(
        "/auth/webauthn/reauth/options",
        json={
            "user_id": "other.engineer",
            "register_credential": {
                "user_id": "other.engineer",
                "credential_id": "cred-other-2",
                "public_key_pem": pub2.decode("utf-8"),
            },
        },
    )
    ch2 = opts2.json()["result"]["challenge"]
    bad_replay = client.post(
        "/auth/webauthn/reauth/verify",
        json={
            "user_id": "other.engineer",
            "id": "cred-martinez-1",  # Belongs to cve.martinez, NOT other.engineer!
            "challenge": ch2,
            "signature_b64": sig_b64,
        },
    )
    assert bad_replay.status_code == 403

    # 6. Security Audit Endpoint + MCP 50 tools
    r_sec = client.post("/security/sbom-airgap-audit", json={"sign_with_hsm": True})
    assert r_sec.status_code == 200
    assert r_sec.json()["result"]["cluster_verified"] is True

    tools_list = handle_mcp_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert len(tools_list["result"]["tools"]) >= 50

    mcp_sec = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "audit_airgap_sbom_and_cluster_readiness", "arguments": {}},
        }
    )
    assert mcp_sec["result"]["isError"] is False
    assert mcp_sec["result"]["structuredContent"]["cluster_verified"] is True


def test_sprint6_block6_mmpds12_sn_nasgro_unitsafe_and_dronology_traces() -> None:
    mats = list_materials()
    assert len(mats) == 12
    for m in ("INCONEL-718", "17-4PH-H1025", "E-GLASS-8552", "NOMEX-HRH10-48"):
        assert m in mats

    sn_inc = lookup_sn_fatigue_allowable(
        "INCONEL-718", stress_ratio_r="0.1", target_cycles="1000000"
    )
    assert Decimal(sn_inc["reversed_fatigue_amp_mpa"]) >= Decimal("565")
    nas_al = lookup_nasgro_paris_params("AL-7075-T651")
    assert nas_al["k_ic_mpa_sqrt_m"] == "29"

    # UnitSafe Unicode & expanded aerospace/SI unit tokens parse cleanly
    for tok in ("m²", "m³", "N·m", "kJ/mol", "arcmin", "arcsec", "kvar", "Jy", "mG"):
        assert extended_dimension_exponents(tok) is not None
    # Regression guard: Pint native offset temperature symbol must stay intact
    assert dimension_exponents("°C") == {"Θ": 1}

    # Dronology-style trace recovery via predict_generic_traces
    targets = [
        ("DES-ROTOR-01", "Main rotor blade centrifugal root lug fatigue inspection interval"),
        ("DES-SKID-02", "CS 29 skid landing gear tubular crossbeam drop test absorption energy"),
        ("DES-AVIONICS-03", "DO-160 cockpit display dimmer backlight PWM controller"),
    ]
    links = predict_generic_traces(
        "REQ-LANDING-29725",
        (
            "Helicopter skid landing gear tubular crossbeam energy absorption "
            "drop test per DES-SKID-02"
        ),
        targets,
    )
    assert len(links) >= 1
    assert links[0]["target_id"] == "DES-SKID-02"
