from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import pymupdf
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from evidence_api.app import create_app
from evidence_api.cli import app as cli_app
from evidence_api.mcp_server import handle_mcp_message
from evidence_kernel.sso import sign_saml_assertion_for_test
from fastapi.testclient import TestClient
from typer.testing import CliRunner


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_b64(n: int) -> str:
    length = max(1, (n.bit_length() + 7) // 8)
    return _b64url(n.to_bytes(length, "big"))


def _make_sample_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 120), "CS-27.625 Fitting Factor MS shall remain positive.")
    page.insert_text((72, 180), "CS-27.571 Fatigue damage spectrum limit verification.")
    data = doc.tobytes()
    doc.close()
    return data


def test_declarative_plugins_and_four_sizing_methods_e2e(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")
    client = TestClient(create_app())

    cards_resp = client.get("/calc/cards")
    assert cards_resp.status_code == 200
    ids = {c["method_id"] for c in cards_resp.json()["result"]["methods"]}
    assert {
        "margin_of_safety",
        "column_plate_buckling",
        "palmgren_miner_fatigue",
        "composite_failure_criteria",
    }.issubset(ids)

    # Run each of the 4 classical methods cleanly through POST /calc/run
    run_payloads = [
        (
            "margin_of_safety",
            {
                "applied_load_n": "18000.000",
                "allowable_load_n": "42000.000",
                "reserve_factor": "1.500",
                "fitting_factor": "1.150",
            },
            "margin_of_safety",
        ),
        (
            "column_plate_buckling",
            {
                "applied_compression_n": "28000.000",
                "column_length_mm": "420.000",
                "end_fixity_k": "1.000",
                "area_mm2": "240.000",
                "inertia_mm4": "34560.000",
                "youngs_modulus_mpa": "71700.000",
                "yield_strength_mpa": "460.000",
                "poissons_ratio": "0.330",
                "plate_width_b_mm": "60.000",
                "plate_thickness_t_mm": "3.200",
                "plate_buckling_coeff_kc": "4.000",
                "crippling_cutoff_mpa": "420.000",
            },
            "buckling_ms",
        ),
        (
            "palmgren_miner_fatigue",
            {
                "cycles_applied": ["45000", "8500", "450"],
                "cycles_to_failure": ["900000", "250000", "18000"],
                "scatter_factor": "4.000",
                "damage_limit": "1.000",
            },
            "fatigue_ms",
        ),
        (
            "composite_failure_criteria",
            {
                "sigma_1_mpa": "420.000",
                "sigma_2_mpa": "18.000",
                "tau_12_mpa": "32.000",
                "xt_mpa": "1550.000",
                "xc_mpa": "1200.000",
                "yt_mpa": "55.000",
                "yc_mpa": "220.000",
                "s12_mpa": "85.000",
                "f12_star": "-0.500",
            },
            "hashin_ms",
        ),
    ]
    for method_id, inputs, key_out in run_payloads:
        r = client.post("/calc/run", json={"method_id": method_id, "inputs": inputs})
        assert r.status_code == 200
        body = r.json()
        assert body["confidence"] == "deterministic"
        assert key_out in body["result"]
        assert key_out in body["result"]["exact_intervals"]

    # Register declarative plugin card and execute it end-to-end
    client.post("/auth/login", json={"actor_id": "author", "password": "author-local"})
    plugin_card = {
        "method_id": "shear_lug_tearout",
        "title": "Lug shear tearout margin",
        "quantum": "0.001",
        "required": ["load_n", "area_mm2", "allowable_mpa"],
        "limits": {
            "load_n": {"min": "0", "max": "500000"},
            "area_mm2": {"min_exclusive": "0", "max": "50000"},
            "allowable_mpa": {"min": "1", "max": "5000"},
        },
        "input_units": {
            "load_n": "newton",
            "area_mm2": "millimeter ** 2",
            "allowable_mpa": "megapascal",
        },
        "formulas": [
            {"output": "stress_mpa", "expr": "load_n / area_mm2"},
            {"output": "margin_of_safety", "expr": "(allowable_mpa / stress_mpa) - 1"},
        ],
    }
    reg = client.post("/calc/cards", json=plugin_card)
    assert reg.status_code == 200
    assert reg.json()["result"]["card"]["method_id"] == "shear_lug_tearout"

    run_p = client.post(
        "/calc/run",
        json={
            "method_id": "shear_lug_tearout",
            "inputs": {"load_n": "12000.000", "area_mm2": "160.000", "allowable_mpa": "240.000"},
            "record": True,
        },
    )
    assert run_p.status_code == 200
    p_res = run_p.json()["result"]
    assert p_res["stress_mpa"] == "75.000"
    assert p_res["margin_of_safety"] == "2.200"
    assert "margin_of_safety" in p_res["exact_intervals"]

    dele = client.delete("/calc/cards/shear_lug_tearout")
    assert dele.status_code == 200
    assert dele.json()["result"]["deleted"] is True


def test_sso_rbac_distinct_signoff_blobs_webhooks_and_signed_pdf_e2e(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")
    monkeypatch.setenv("EVIDENCE_SESSION_SECRET", "enterprise-secret-key-24-plus-chars")

    # Configure OIDC (RS256) and SAML (RSA-SHA256) IdPs via env
    priv_oidc = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_nums = priv_oidc.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "k1",
                "n": _int_b64(pub_nums.n),
                "e": _int_b64(pub_nums.e),
            }
        ]
    }
    now = int(time.time())
    hdr = _b64url(json.dumps({"alg": "RS256", "kid": "k1"}).encode("utf-8"))
    clm = _b64url(
        json.dumps(
            {
                "iss": "https://login.microsoftonline.com/t1/v2.0",
                "aud": "aeroregu-api",
                "sub": "oid-cve-1",
                "preferred_username": "cve.martinez@corp.example",
                "roles": ["evidence-cve"],
                "exp": now + 600,
                "iat": now,
            }
        ).encode("utf-8")
    )
    sig = priv_oidc.sign(f"{hdr}.{clm}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    oidc_jwt = f"{hdr}.{clm}.{_b64url(sig)}"

    priv_saml = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "okta.corp.example")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subj)
        .issuer_name(subj)
        .public_key(priv_saml.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=30))
        .sign(priv_saml, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    dt_now = datetime.now(UTC)
    saml_b64 = sign_saml_assertion_for_test(
        idp_entity_id="https://okta.corp.example/idp",
        sp_entity_id="https://aeroregu.corp.example/sp",
        name_id="admin.lopez@corp.example",
        roles=["evidence-admin"],
        private_key=priv_saml,
        not_before=(dt_now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        not_on_or_after=(dt_now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    monkeypatch.setenv("EVIDENCE_OIDC_ISSUER", "https://login.microsoftonline.com/t1/v2.0")
    monkeypatch.setenv("EVIDENCE_OIDC_AUDIENCE", "aeroregu-api")
    monkeypatch.setenv("EVIDENCE_OIDC_JWKS_JSON", json.dumps(jwks))
    monkeypatch.setenv("EVIDENCE_SAML_IDP_ENTITY_ID", "https://okta.corp.example/idp")
    monkeypatch.setenv("EVIDENCE_SAML_SP_ENTITY_ID", "https://aeroregu.corp.example/sp")
    monkeypatch.setenv("EVIDENCE_SAML_CERT_PEM", cert_pem)

    client = TestClient(create_app())

    # 1) Author logs in, ingests real PDF, records calculation, tries sign-off -> 403!
    client.post("/auth/login", json={"actor_id": "author", "password": "author-local"})
    pdf_bytes = _make_sample_pdf_bytes()
    ing = client.post(
        "/ingest/document",
        json={
            "filename": "cs27_extract.pdf",
            "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "record": True,
        },
    )
    assert ing.status_code == 200
    assert ing.json()["confidence"] == "deterministic"
    src_hash = ing.json()["result"]["source_hash"]

    # Blob store now holds ingested PDF
    blobs_resp = client.get("/blobs")
    assert blobs_resp.status_code == 200
    assert any(b["sha256"] == src_hash for b in blobs_resp.json()["result"]["blobs"])

    # Direct blob PUT + GET roundtrip
    put_b = client.post(
        "/blobs",
        json={
            "filename": "wingbox.stp",
            "content_base64": base64.b64encode(b"ISO-10303-21;STEP;").decode("ascii"),
            "content_type": "application/step",
        },
    )
    assert put_b.status_code == 200
    sha_cad = put_b.json()["result"]["sha256"]
    assert client.get(f"/blobs/{sha_cad}").content == b"ISO-10303-21;STEP;"

    # Author cannot sign off as CVE
    denied_sign = client.post("/ledger/signoff", json={"review_duration_ms": 2000})
    assert denied_sign.status_code == 403
    assert denied_sign.json()["abstain"]["reason"] == "cve_role_required"

    # 2) SAML admin login -> inspect/set roles & register CI/CD webhook
    saml_login = client.post("/sso/saml/acs", json={"saml_response": saml_b64})
    assert saml_login.status_code == 200
    assert saml_login.json()["result"]["role"] == "admin"

    roles_list = client.get("/admin/roles")
    assert roles_list.status_code == 200
    set_role = client.post("/admin/roles", json={"target_actor_id": "author", "role": "author"})
    assert set_role.status_code == 200

    # Mock outgoing webhook HTTP delivery & register HTTPS webhook
    captured_webhooks: list[dict[str, Any]] = []
    orig_client_post = httpx.Client.post

    def _fake_webhook_post(self, url: str, *args: Any, **kwargs: Any):
        if str(url).startswith("https://ci.corp.example"):
            captured_webhooks.append(
                {
                    "url": str(url),
                    "content": kwargs.get("content", b""),
                    "headers": dict(kwargs.get("headers") or {}),
                }
            )

            class _Resp:
                status_code = 202

            return _Resp()
        return orig_client_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "post", _fake_webhook_post)
    wh_reg = client.post(
        "/webhooks",
        json={
            "url": "https://ci.corp.example/hooks/aeroregu",
            "secret": "enterprise-ci-hmac-key",
            "events": ["envelope_invalidated"],
            "allow_private_targets": False,
        },
    )
    assert wh_reg.status_code == 200

    # Trigger envelope invalidation via mass-shift -> fires HMAC webhook!
    shift = client.post("/coverage/mass-shift", json={"tenant_id": "demo"})
    assert shift.status_code == 200
    assert len(captured_webhooks) == 1
    sent = captured_webhooks[0]
    ts = sent["headers"]["X-Evidence-Timestamp"]
    mac_input = f"{ts}.".encode() + sent["content"]
    expected_sig = hmac.new(b"enterprise-ci-hmac-key", mac_input, hashlib.sha256).hexdigest()
    assert sent["headers"]["X-Evidence-Signature-256"] == f"sha256={expected_sig}"
    assert sent["headers"]["X-Evidence-Event"] == "envelope_invalidated"

    wh_list = client.get("/webhooks").json()["result"]
    assert len(wh_list["deliveries"]) >= 1
    assert wh_list["deliveries"][0]["status_code"] == 202

    # 3) Distinct CVE signs in via OIDC and signs off head -> gate passes (enforce_distinct=true)
    oidc_login = client.post("/sso/oidc/callback", json={"id_token": oidc_jwt})
    assert oidc_login.status_code == 200
    assert oidc_login.json()["result"]["role"] == "cve"

    ok_sign = client.post("/ledger/signoff", json={"review_duration_ms": 2500})
    assert ok_sign.status_code == 200
    assert ok_sign.json()["result"]["role"] == "cve"
    assert ok_sign.json()["result"]["distinct_reviewer"] is True

    gate = client.get("/coverage/gate?enforce_distinct=true").json()["result"]
    assert gate["head_signed_off"] is True
    assert gate["self_signoff_detected"] is False

    # 4) Export signed PDF audit report with embedded bbox thumbnails + offline QR code
    pdf_resp = client.get("/dossier/pdf?enforce_distinct=true")
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF-")

    doc = pymupdf.open(stream=pdf_resp.content, filetype="pdf")
    total_imgs = sum(len(doc[i].get_images(full=True)) for i in range(len(doc)))
    assert total_imgs >= 2  # QR code + >=1 cropped bbox visual thumbnail
    pix = doc[0].get_pixmap(dpi=220)
    arr = np.frombuffer(pix.tobytes("png"), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    detector = cv2.QRCodeDetector()
    decoded_qr, _, _ = detector.detectAndDecode(img)
    if "aeroregu-verify:" not in decoded_qr:
        # Top-right QR crop fallback if whole-page detector hits border whitespace
        h, w = img.shape[:2]
        crop = img[: int(h * 0.45), int(w * 0.5) :]
        decoded_qr, _, _ = detector.detectAndDecode(crop)
    if "aeroregu-verify:" not in decoded_qr:
        # Lossless embedded image extraction fallback (avoids page rasterization anti-aliasing)
        for info in doc[0].get_images(full=True):
            raw_img = doc.extract_image(info[0])
            emb_arr = np.frombuffer(raw_img["image"], dtype=np.uint8)
            emb_img = cv2.imdecode(emb_arr, cv2.IMREAD_COLOR)
            if emb_img is not None:
                cand, _, _ = detector.detectAndDecode(emb_img)
                if "aeroregu-verify:" in cand:
                    decoded_qr = cand
                    break
    doc.close()
    assert "aeroregu-verify:" in decoded_qr

    verify_resp = client.post(
        "/dossier/pdf/verify",
        json={"content_base64": base64.b64encode(pdf_resp.content).decode("ascii")},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["result"]["valid"] is True


def test_enterprise_mcp_tools_and_cli_commands(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVIDENCE_HOME", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_GATEWAY", "fixture")

    # MCP plugin register + webhooks list + PDF dossier export
    r_plug = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "evidence_calc_register_plugin",
                "arguments": {
                    "card": {
                        "method_id": "mcp_beam_stress",
                        "title": "Bending stress My/I",
                        "quantum": "0.001",
                        "required": ["moment_n_mm", "section_mod_mm3"],
                        "limits": {
                            "moment_n_mm": {"min": "0", "max": "5000000"},
                            "section_mod_mm3": {"min_exclusive": "0", "max": "100000"},
                        },
                        "input_units": {
                            "moment_n_mm": "newton * millimeter",
                            "section_mod_mm3": "millimeter ** 3",
                        },
                        "formulas": [
                            {"output": "sigma_mpa", "expr": "moment_n_mm / section_mod_mm3"}
                        ],
                    }
                },
            },
        },
        require_auth_for_writes=False,
    )
    assert r_plug["result"]["isError"] is False
    assert r_plug["result"]["structuredContent"]["card"]["method_id"] == "mcp_beam_stress"

    pdf_out = tmp_path / "mcp_dossier.pdf"
    r_pdf = handle_mcp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "evidence_dossier_pdf_export",
                "arguments": {"tenant_id": "demo", "output_path": str(pdf_out)},
            },
        },
        require_auth_for_writes=False,
    )
    assert r_pdf["result"]["isError"] is False
    assert pdf_out.read_bytes().startswith(b"%PDF-")

    # CLI commands
    runner = CliRunner()
    res_list = runner.invoke(cli_app, ["calc", "list"])
    assert res_list.exit_code == 0
    assert "margin_of_safety" in res_list.stdout
    assert "composite_failure_criteria" in res_list.stdout

    card_file = tmp_path / "cli_card.json"
    card_file.write_text(
        json.dumps(
            {
                "method_id": "cli_axial_stress",
                "title": "Axial P/A",
                "quantum": "0.001",
                "required": ["force_n", "area_mm2"],
                "limits": {
                    "force_n": {"min": "0", "max": "500000"},
                    "area_mm2": {"min_exclusive": "0", "max": "50000"},
                },
                "input_units": {
                    "force_n": "newton",
                    "area_mm2": "millimeter ** 2",
                },
                "formulas": [{"output": "sigma_mpa", "expr": "force_n / area_mm2"}],
            }
        ),
        encoding="utf-8",
    )
    res_reg = runner.invoke(cli_app, ["calc", "register", str(card_file)])
    assert res_reg.exit_code == 0
    assert "cli_axial_stress" in res_reg.stdout

    cli_pdf = tmp_path / "cli_dossier.pdf"
    res_pdf = runner.invoke(cli_app, ["dossier", "pdf", "--write", str(cli_pdf)])
    assert res_pdf.exit_code == 0
    assert cli_pdf.read_bytes().startswith(b"%PDF-")

    res_role = runner.invoke(cli_app, ["ledger", "role-set", "cve.cli@corp.example", "cve"])
    assert res_role.exit_code == 0
    assert "cve.cli@corp.example" in res_role.stdout
