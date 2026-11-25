from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import cv2
import httpx
import numpy as np
import pymupdf
import pytest
from evidence_coverage.pdf_report import build_signed_pdf_report, verify_signed_pdf_report
from evidence_kernel.attestation import generate_ed25519_keypair
from evidence_kernel.canonical import inputs_hash
from evidence_kernel.webhooks import (
    WebhookError,
    dispatch_webhook_event,
    new_webhook_record,
    sign_webhook_payload,
    validate_webhook_url,
)


def _build_sample_source_pdf() -> tuple[bytes, list[float], str]:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    req_rect = pymupdf.Rect(60, 120, 500, 165)
    page.insert_text(
        (70, 145), "REQ-CS27-625: Fitting factor FF >= 1.15 on critical fittings.", fontsize=11
    )
    pdf_bytes = doc.tobytes()
    doc.close()
    src_hash = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, [req_rect.x0, req_rect.y0, req_rect.x1, req_rect.y1], src_hash


def _sample_events_with_bbox(bbox: list[float], src_hash: str) -> list[dict[str, Any]]:
    body_req = {
        "schema_version": "1.0.0",
        "tenant_id": "airbus-cert-demo",
        "actor_id": "author",
        "created_at": "2026-11-14T10:00:00Z",
        "event_type": "requirement_recorded",
        "payload": {
            "doc_id": "cs27-spec",
            "source_hash": src_hash,
            "requirements": [
                {
                    "req_id": "REQ-CS27-625",
                    "text": "Fitting factor FF >= 1.15 on critical fittings.",
                    "page_no": 1,
                    "bbox": bbox,
                    "source_hash": src_hash,
                }
            ],
        },
        "envelope": {
            "sources": [
                {
                    "source_id": "cs27-spec",
                    "uri": "file:///cs27.pdf",
                    "content_hash": src_hash,
                    "page_no": 1,
                    "bbox": bbox,
                    "label": "VERIFIED",
                }
            ],
            "method_version": "doc_ingest@1.0.0",
            "inputs_hash": inputs_hash({"doc_id": "cs27-spec"}),
            "confidence": "quoted",
            "result": {"count": 1},
            "abstain": None,
        },
    }
    ev1_hash = hashlib.sha256(json.dumps(body_req, sort_keys=True).encode()).hexdigest()

    body_sign = {
        "schema_version": "1.0.0",
        "tenant_id": "airbus-cert-demo",
        "actor_id": "cve.reviewer",
        "created_at": "2026-11-14T10:05:00Z",
        "event_type": "human_signoff",
        "payload": {
            "target_event_hash": ev1_hash,
            "actor_id": "cve.reviewer",
            "statement": "reviewed this event",
        },
        "envelope": {
            "sources": [
                {
                    "source_id": "signoff",
                    "uri": "https://aeroregu.local/signoff",
                    "content_hash": src_hash,
                    "label": "VERIFIED",
                }
            ],
            "method_version": "human_signoff@1.0.0",
            "inputs_hash": inputs_hash({"target": ev1_hash}),
            "confidence": "deterministic",
            "result": {"signed": True},
            "abstain": None,
        },
    }
    ev2_hash = hashlib.sha256(json.dumps(body_sign, sort_keys=True).encode()).hexdigest()
    return [
        {"event_hash": ev1_hash, "prev_hash": "0" * 64, "body": body_req},
        {"event_hash": ev2_hash, "prev_hash": ev1_hash, "body": body_sign},
    ]


def test_signed_pdf_report_bbox_thumbnails_qr_and_dsse() -> None:
    src_pdf, bbox, src_hash = _build_sample_source_pdf()
    events = _sample_events_with_bbox(bbox, src_hash)
    priv_pem, pub_pem = generate_ed25519_keypair()

    report = build_signed_pdf_report(
        events,
        tenant_id="airbus-cert-demo",
        chain_verified=True,
        private_key_pem=priv_pem,
        public_key_pem=pub_pem,
        pdf_sources={src_hash: src_pdf},
        enforce_distinct_reviewer=True,
    )
    assert report["bbox_thumbnails_count"] == 1
    assert report["pdf_bytes"].startswith(b"%PDF-")

    # 1) Offline verify embedded DSSE Ed25519 signature + attachment
    verified = verify_signed_pdf_report(report["pdf_bytes"], expected_public_key_pem=pub_pem)
    assert verified["valid"] is True
    assert verified["attestation"]["merkle_root"] == report["merkle_root"]
    assert verified["embedded_image_count"] >= 2  # QR code + bbox visual crop thumbnail

    # 2) Render page 0 of generated PDF and scan embedded QR code via OpenCV QRCodeDetector
    with pymupdf.open(stream=report["pdf_bytes"], filetype="pdf") as out_doc:
        pix = out_doc.load_page(0).get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        detector = cv2.QRCodeDetector()
        decoded, _, _ = detector.detectAndDecode(img)
        if decoded != report["qr_payload"]:
            h, w = img.shape[:2]
            crop = img[: int(h * 0.45), int(w * 0.5) :]
            decoded, _, _ = detector.detectAndDecode(crop)
        if decoded != report["qr_payload"]:
            for info in out_doc[0].get_images(full=True):
                raw_img = out_doc.extract_image(info[0])
                emb_arr = np.frombuffer(raw_img["image"], dtype=np.uint8)
                emb_img = cv2.imdecode(emb_arr, cv2.IMREAD_COLOR)
                if emb_img is not None:
                    cand, _, _ = detector.detectAndDecode(emb_img)
                    if cand == report["qr_payload"]:
                        decoded = cand
                        break
        assert decoded == report["qr_payload"]
        assert '"m":"' + report["merkle_root"][:16] + '"' in decoded

    # 3) Wrong public key rejects offline signature verification
    _, wrong_pub = generate_ed25519_keypair()
    assert (
        verify_signed_pdf_report(report["pdf_bytes"], expected_public_key_pem=wrong_pub)["valid"]
        is False
    )


def test_webhook_hmac_signing_dispatch_and_ssrf_blocking() -> None:
    with pytest.raises(WebhookError, match="ssrf_private_webhook_blocked"):
        validate_webhook_url("http://127.0.0.1:8080/hook")
    with pytest.raises(WebhookError, match="ssrf_private_webhook_blocked"):
        validate_webhook_url("http://169.254.169.254/latest/meta-data/")

    sub = new_webhook_record(
        url="https://ci.airbus.example/hooks/evidence",
        events=["envelope_invalidated"],
        secret="whsec_super_secret",
    )
    received: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sig = request.headers["X-Evidence-Signature-256"]
        ts = request.headers["X-Evidence-Timestamp"]
        expected = sign_webhook_payload("whsec_super_secret", ts, request.content)
        assert hmac.compare_digest(sig, expected)
        received.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(202, json={"accepted": True})

    deliveries = dispatch_webhook_event(
        [sub],
        event_name="envelope_invalidated",
        payload={"mass_delta_kg": "25.000", "invalidated_cells": ["C-01"]},
        transport=httpx.MockTransport(handler),
    )
    assert len(deliveries) == 1
    assert deliveries[0]["ok"] is True
    assert deliveries[0]["status_code"] == 202
    assert received[0]["payload"]["invalidated_cells"] == ["C-01"]
