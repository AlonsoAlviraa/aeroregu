from __future__ import annotations

import base64
import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from evidence_kernel.pg_ledger import PostgresLedger, open_ledger_backend
from evidence_kernel.qrcode_iso import render_qr_png
from evidence_kernel.sso import (
    OIDCConfig,
    OIDCVerifier,
    SAML2Verifier,
    SAMLConfig,
    SSOValidationError,
    sign_saml_assertion_for_test,
)
from evidence_kernel.storage import (
    BlobStoreError,
    LocalFilesystemBlobStore,
    S3CompatibleBlobStore,
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_b64(n: int) -> str:
    length = max(1, (n.bit_length() + 7) // 8)
    return _b64url(n.to_bytes(length, "big"))


class _PgSQLiteCursor:
    """In-process DB-API cursor shim translating PostgresLedger SQL DDL/DML to SQLite."""

    def __init__(self, sqlite_conn: sqlite3.Connection) -> None:
        self._conn = sqlite_conn
        self._cur = sqlite_conn.cursor()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _PgSQLiteCursor:
        stripped = sql.strip()
        if stripped.startswith("SELECT pg_advisory_xact_lock"):
            return self
        if "CREATE OR REPLACE FUNCTION" in stripped:
            return self
        if "CREATE TRIGGER events_no_mutation" in stripped:
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events
                BEGIN
                    SELECT RAISE(ABORT, 'append-only: update rejected');
                END
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events
                BEGIN
                    SELECT RAISE(ABORT, 'append-only: delete rejected');
                END
                """
            )
            return self
        translated = sql.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        translated = translated.replace("%s", "?")
        if "ON CONFLICT (token_hash) DO UPDATE SET" in translated:
            translated = (
                "INSERT OR REPLACE INTO revoked_tokens (token_hash, revoked_at, expires_at) "
                "VALUES (?, ?, ?)"
            )
        if "ON CONFLICT (tenant_id, webhook_id) DO UPDATE SET" in translated:
            translated = (
                "INSERT OR REPLACE INTO webhooks "
                "(tenant_id, webhook_id, url, events_json, secret, "
                "description, created_at, active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            )
        self._cur.execute(translated, params)
        return self

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        return self._cur.fetchall()

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount


class _PgSQLiteConn:
    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path)

    def cursor(self) -> _PgSQLiteCursor:
        return _PgSQLiteCursor(self._conn)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _sample_event_body(tenant: str, actor: str, prompt_hash: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "actor_id": actor,
        "created_at": "2026-11-14T10:00:00Z",
        "event_type": "calc",
        "payload": {"calc_id": "c1", "prompt_hash": prompt_hash},
        "envelope": {
            "sources": [
                {
                    "source_id": "src-1",
                    "uri": "https://example.org/spec.pdf",
                    "content_hash": "a" * 64,
                    "label": "VERIFIED",
                }
            ],
            "method_version": "margin_of_safety@1.0.0",
            "inputs_hash": "b" * 64,
            "confidence": "deterministic",
            "result": {"margin_of_safety": "0.450"},
            "abstain": None,
        },
    }


def test_local_and_s3_blob_stores_with_sigv4(tmp_path: Path) -> None:
    local_store = LocalFilesystemBlobStore(tmp_path / "blobs")
    data = b"STEP-AP242-WINGBOX-CAD-PAYLOAD-001"
    meta = local_store.put_blob(data, content_type="application/step", filename="rib/../rib.step")
    assert meta["backend"] == "local_fs"
    assert meta["size_bytes"] == len(data)
    assert meta["filename"] == "rib.step"
    assert local_store.get_blob(meta["sha256"]) == data
    assert local_store.head_blob(meta["sha256"]) is not None
    assert len(local_store.list_blobs()) == 1

    with pytest.raises(BlobStoreError, match="invalid_sha256_digest"):
        local_store.get_blob("../../etc/passwd")

    # Mock S3 server verifying AWS4-HMAC-SHA256 SigV4 Authorization headers
    bucket_objects: dict[str, tuple[bytes, dict[str, str]]] = {}
    seen_auth_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        assert auth.startswith("AWS4-HMAC-SHA256 Credential=test-ak/")
        assert "x-amz-content-sha256" in request.headers
        seen_auth_headers.append(auth)
        key = str(request.url.path)
        if request.method == "PUT":
            bucket_objects[key] = (
                request.content,
                {
                    "content-type": request.headers.get("content-type", "application/octet-stream"),
                    "x-amz-meta-filename": request.headers.get("x-amz-meta-filename", "file.bin"),
                },
            )
            return httpx.Response(200)
        if request.method == "GET":
            if key not in bucket_objects:
                return httpx.Response(404)
            return httpx.Response(200, content=bucket_objects[key][0])
        if request.method == "HEAD":
            if key not in bucket_objects:
                return httpx.Response(404)
            raw_obj, hdrs = bucket_objects[key]
            return httpx.Response(200, headers={"content-length": str(len(raw_obj)), **hdrs})
        return httpx.Response(405)

    s3 = S3CompatibleBlobStore(
        endpoint="https://s3.eu-west-1.example.com",
        bucket="engineering-artifacts",
        access_key="test-ak",
        secret_key="test-secret-key",
        transport=httpx.MockTransport(handler),
    )
    s3_meta = s3.put_blob(data, content_type="model/step", filename="rib.step")
    assert s3_meta["backend"] == "s3"
    assert s3_meta["uri"].startswith("s3://engineering-artifacts/")
    assert s3.get_blob(s3_meta["sha256"]) == data
    head = s3.head_blob(s3_meta["sha256"])
    assert head is not None and head["filename"] == "rib.step"
    assert len(seen_auth_headers) == 3


def test_postgres_ledger_multi_tenant_append_immutability_and_roles(tmp_path: Path) -> None:
    db_file = tmp_path / "pg_sim.sqlite"

    def connect_fn(_dsn: str) -> _PgSQLiteConn:
        return _PgSQLiteConn(db_file)

    ledger_a = PostgresLedger("postgresql://local/test", "tenant-alpha", connect_fn=connect_fn)
    ledger_b = open_ledger_backend(
        tmp_path / "unused.db",
        "tenant-beta",
        pg_dsn="postgresql://local/test",
        pg_connect_fn=connect_fn,
    )
    assert isinstance(ledger_b, PostgresLedger)

    h1 = ledger_a.append(_sample_event_body("tenant-alpha", "alice", "1" * 64))
    h2 = ledger_b.append(_sample_event_body("tenant-beta", "bob", "2" * 64))
    assert len(h1) == 64 and len(h2) == 64
    assert len(ledger_a.events()) == 1
    assert len(ledger_b.events()) == 1
    assert ledger_a.verify_chain() is True
    assert ledger_b.verify_chain() is True

    # RBAC role assignment & password check
    ledger_a.ensure_sso_actor("alice@corp.example", "author")
    ledger_a.ensure_sso_actor("cve.reviewer@corp.example", "cve")
    assert ledger_a.actor_role("alice@corp.example") == "author"
    assert ledger_a.actor_role("cve.reviewer@corp.example") == "cve"
    ledger_a.set_actor_role("alice@corp.example", "admin")
    assert ledger_a.actor_role("alice@corp.example") == "admin"

    # Immutability trigger blocks direct DELETE/UPDATE
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn = connect_fn("")
        conn.cursor().execute("DELETE FROM events WHERE tenant_id = ?", ("tenant-alpha",))


def test_oidc_rs256_es256_and_saml2_xxe_safe_verification() -> None:
    # 1) OIDC RS256 (Entra ID style) + ES256 (Okta style)
    priv_rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_nums = priv_rsa.public_key().public_numbers()
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "kid": "entra-key-1"}).encode("utf-8"))
    claims = _b64url(
        json.dumps(
            {
                "iss": "https://login.microsoftonline.com/tenant-1/v2.0",
                "aud": "evidence-api-client",
                "sub": "oid-user-42",
                "preferred_username": "cve.garcia@corp.example",
                "roles": ["evidence-cve"],
                "nonce": "n-123",
                "exp": now + 300,
                "iat": now,
            }
        ).encode("utf-8")
    )
    signing_input = f"{header}.{claims}".encode("ascii")
    sig = priv_rsa.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    id_token = f"{header}.{claims}.{_b64url(sig)}"

    verifier = OIDCVerifier(
        OIDCConfig(
            provider_name="entra_id",
            issuer="https://login.microsoftonline.com/tenant-1/v2.0",
            audience="evidence-api-client",
            jwks={
                "keys": [
                    {
                        "kty": "RSA",
                        "kid": "entra-key-1",
                        "n": _int_b64(pub_nums.n),
                        "e": _int_b64(pub_nums.e),
                    }
                ]
            },
        )
    )
    identity = verifier.verify_id_token(id_token, expected_nonce="n-123")
    assert identity["actor_id"] == "cve.garcia@corp.example"
    assert identity["role"] == "cve"

    # Reject wrong audience / alg=none
    bad_none = f"{_b64url(b'{"alg":"none"}')}.{claims}."
    with pytest.raises(SSOValidationError, match="unsigned_jwt_rejected"):
        verifier.verify_id_token(bad_none)

    # 2) SAML 2.0 X.509 RSA-SHA256 signed Assertion & XXE protection
    priv_saml = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "okta.corp.example")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(priv_saml.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=30))
        .sign(priv_saml, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    saml_b64 = sign_saml_assertion_for_test(
        idp_entity_id="https://okta.corp.example/idp",
        sp_entity_id="https://evidence.corp.example/sp",
        name_id="admin.lopez@corp.example",
        roles=["evidence-admin"],
        private_key=priv_saml,
    )
    saml_verifier = SAML2Verifier(
        SAMLConfig(
            provider_name="okta_saml",
            idp_entity_id="https://okta.corp.example/idp",
            sp_entity_id="https://evidence.corp.example/sp",
            idp_certificate_pem=cert_pem,
        )
    )
    saml_id = saml_verifier.verify_saml_response(saml_b64, now_dt=datetime(2026, 6, 1, tzinfo=UTC))
    assert saml_id["actor_id"] == "admin.lopez@corp.example"
    assert saml_id["role"] == "admin"

    # Block XXE injection payload cleanly
    xxe_xml = b'<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'
    with pytest.raises(SSOValidationError, match="invalid_saml_xml"):
        saml_verifier.verify_saml_response(base64.b64encode(xxe_xml).decode("ascii"))


def test_iso_qr_code_roundtrip_via_cv2_detector() -> None:
    payload = (
        'aeroregu-verify:{"g":"verified","h":"deadbeef12345678",'
        '"m":"cafebabe87654321","n":12,"s":"1122334455667788","v":1}'
    )
    png_bytes = render_qr_png(payload, scale=6, border=4)
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    assert img is not None
    decoded, bbox, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert bbox is not None
    assert decoded == payload
