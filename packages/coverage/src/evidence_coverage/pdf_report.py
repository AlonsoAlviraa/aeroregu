"""Signed PDF certification dossier with visual bbox evidence thumbnails and offline QR."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pymupdf
from evidence_kernel.attestation import (
    generate_ed25519_keypair,
    sign_attestation_dsse,
    verify_attestation_dsse,
)
from evidence_kernel.merkle import merkle_root
from evidence_kernel.qrcode_iso import render_qr_png
from PIL import Image, ImageDraw

from evidence_coverage.dossier import build_enterprise_dossier
from evidence_coverage.gate import evaluate_traceability_gate

_DSSE_ATTACHMENT_NAME = "dsse_attestation.json"
_PUBKEY_ATTACHMENT_NAME = "public_key.pem"
_QR_PREFIX = "aeroregu-verify:"


def _extract_bbox_citations(
    events: list[dict[str, Any]], max_items: int = 12
) -> list[dict[str, Any]]:
    """Collect distinct cited blocks/requirements carrying page_no and bbox coordinates."""
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()

    for event in reversed(events):
        body = event.get("body") or {}
        payload = body.get("payload") or {}
        envelope = body.get("envelope") or {}

        candidates: list[dict[str, Any]] = []
        for s in envelope.get("sources") or []:
            if isinstance(s, dict):
                candidates.append(
                    {
                        "source_hash": str(s.get("content_hash") or ""),
                        "source_id": str(s.get("source_id") or s.get("uri") or "source"),
                        "page_no": s.get("page_no"),
                        "bbox": s.get("bbox"),
                        "text": str(
                            s.get("quote") or s.get("label") or body.get("event_type") or ""
                        ),
                        "event_hash": str(event.get("event_hash") or ""),
                    }
                )
        for req in payload.get("requirements") or []:
            if isinstance(req, dict):
                candidates.append(
                    {
                        "source_hash": str(
                            req.get("source_hash") or payload.get("source_hash") or ""
                        ),
                        "source_id": str(req.get("req_id") or payload.get("doc_id") or "req"),
                        "page_no": req.get("page_no"),
                        "bbox": req.get("bbox"),
                        "text": str(req.get("text") or ""),
                        "event_hash": str(event.get("event_hash") or ""),
                    }
                )
        if payload.get("page_no") is not None and payload.get("bbox"):
            candidates.append(
                {
                    "source_hash": str(payload.get("source_hash") or ""),
                    "source_id": str(payload.get("doc_id") or body.get("event_type") or "block"),
                    "page_no": payload.get("page_no"),
                    "bbox": payload.get("bbox"),
                    "text": str(payload.get("text") or payload.get("quote") or ""),
                    "event_hash": str(event.get("event_hash") or ""),
                }
            )

        for item in candidates:
            bbox = item.get("bbox")
            page_no = item.get("page_no")
            if page_no is None or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            try:
                coords = [float(c) for c in bbox]
                pno = int(page_no)
            except (TypeError, ValueError):
                continue
            dedup_key = (item["source_hash"], pno, ",".join(f"{c:.1f}" for c in coords))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            citations.append({**item, "page_no": pno, "bbox": coords})
            if len(citations) >= max_items:
                return citations
    return citations


def _render_bbox_thumbnail(
    *,
    citation: dict[str, Any],
    pdf_sources: dict[str, bytes | Path] | None = None,
) -> bytes:
    """Crop the cited bbox (with highlight & margin context) or render a schematic thumbnail."""
    pno = int(citation["page_no"])
    x0, y0, x1, y1 = [float(v) for v in citation["bbox"]]
    src_hash = str(citation.get("source_hash") or "")
    src_id = str(citation.get("source_id") or "")

    raw_pdf: bytes | Path | None = None
    if pdf_sources:
        raw_pdf = pdf_sources.get(src_hash) or pdf_sources.get(src_id)
        if raw_pdf is None and len(pdf_sources) == 1:
            raw_pdf = next(iter(pdf_sources.values()))

    if raw_pdf is not None:
        try:
            doc = (
                pymupdf.open(str(raw_pdf))
                if isinstance(raw_pdf, Path)
                else pymupdf.open(stream=bytes(raw_pdf), filetype="pdf")
            )
            with doc:
                if 1 <= pno <= len(doc):
                    page = doc.load_page(pno - 1)
                    pad = 26.0
                    page_rect = page.rect
                    clip = pymupdf.Rect(
                        max(page_rect.x0, min(x0, x1) - pad),
                        max(page_rect.y0, min(y0, y1) - pad),
                        min(page_rect.x1, max(x0, x1) + pad),
                        min(page_rect.y1, max(y0, y1) + pad),
                    )
                    if clip.width < 10 or clip.height < 10:
                        clip = page_rect
                    zoom = 2.0
                    pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    draw = ImageDraw.Draw(img)
                    rx0 = max(1, int((min(x0, x1) - clip.x0) * zoom))
                    ry0 = max(1, int((min(y0, y1) - clip.y0) * zoom))
                    rx1 = min(pix.width - 2, int((max(x0, x1) - clip.x0) * zoom))
                    ry1 = min(pix.height - 2, int((max(y0, y1) - clip.y0) * zoom))
                    draw.rectangle([rx0, ry0, rx1, ry1], outline=(220, 38, 38), width=3)
                    out_buf = io.BytesIO()
                    img.save(out_buf, format="PNG")
                    return out_buf.getvalue()
        except Exception:
            pass

    # Fallback schematic page bbox diagram when raw source PDF binary is omitted
    w, h = 240, 140
    img = Image.new("RGB", (w, h), (248, 250, 252))
    draw = ImageDraw.Draw(img)
    draw.rectangle([4, 4, w - 5, h - 5], outline=(100, 116, 139), width=2)
    sx0 = max(10, min(w - 30, int((x0 / 612.0) * (w - 20)) + 10))
    sy0 = max(24, min(h - 30, int((y0 / 792.0) * (h - 32)) + 24))
    sx1 = max(sx0 + 18, min(w - 10, int((x1 / 612.0) * (w - 20)) + 10))
    sy1 = max(sy0 + 14, min(h - 10, int((y1 / 792.0) * (h - 32)) + 24))
    draw.rectangle([sx0, sy0, sx1, sy1], fill=(254, 226, 226), outline=(220, 38, 38), width=2)
    draw.text((10, 8), f"p.{pno} [{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}]", fill=(15, 23, 42))
    out_buf = io.BytesIO()
    img.save(out_buf, format="PNG")
    return out_buf.getvalue()


def _compact_qr_payload(
    *,
    merkle: str,
    head_hash: str,
    sig_sha256: str,
    gate_status: str,
    event_count: int,
) -> str:
    compact = {
        "v": 1,
        "m": merkle[:16],
        "h": head_hash[:16],
        "s": sig_sha256[:16],
        "g": gate_status[:16],
        "n": event_count,
    }
    return _QR_PREFIX + json.dumps(compact, sort_keys=True, separators=(",", ":"))


def build_signed_pdf_report(
    events: list[dict[str, Any]],
    *,
    tenant_id: str = "default",
    chain_verified: bool = True,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    pdf_sources: dict[str, bytes | Path] | None = None,
    enforce_distinct_reviewer: bool = False,
    require_head_signoff: bool = False,
) -> dict[str, Any]:
    """Generate an Ed25519 DSSE-signed PDF dossier with bbox thumbnails & offline QR code."""
    dossier = build_enterprise_dossier(events, chain_verified=chain_verified)
    gate = evaluate_traceability_gate(
        events,
        chain_verified=chain_verified,
        dossier=dossier,
        require_head_signoff=require_head_signoff,
        enforce_distinct_reviewer=enforce_distinct_reviewer,
    )
    event_hashes = [str(ev.get("event_hash") or "") for ev in events]
    root = merkle_root(event_hashes) if event_hashes else ("0" * 64)
    head_hash = str(dossier.get("head_hash") or ("0" * 64))

    if private_key_pem is None:
        priv_pem, pub_pem = generate_ed25519_keypair()
    else:
        priv_pem = private_key_pem
        if public_key_pem is None:
            from cryptography.hazmat.primitives import serialization

            priv_obj = serialization.load_pem_private_key(priv_pem, password=None)
            pub_pem = priv_obj.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        else:
            pub_pem = public_key_pem

    citations = _extract_bbox_citations(events)
    signoffs = list(dossier.get("human_signoffs") or [])
    attestation_payload = {
        "schema": "evidence-layer/pdf-dossier-attestation@1.0.0",
        "tenant_id": tenant_id,
        "merkle_root": root,
        "head_hash": head_hash,
        "dossier_hash": dossier["dossier_hash"],
        "event_count": len(events),
        "chain_verified": chain_verified,
        "gate_status": gate["gate_status"],
        "blockers": gate["blockers"],
        "bbox_citation_count": len(citations),
        "human_signoffs": signoffs,
    }
    dsse_envelope = sign_attestation_dsse(attestation_payload, priv_pem)
    dsse_bytes = json.dumps(dsse_envelope, sort_keys=True, indent=2).encode("utf-8")
    sig_raw = base64.b64decode(dsse_envelope["signatures"][0]["sig"])
    sig_sha256 = hashlib.sha256(sig_raw).hexdigest()

    qr_text = _compact_qr_payload(
        merkle=root,
        head_hash=head_hash,
        sig_sha256=sig_sha256,
        gate_status=str(gate["gate_status"]),
        event_count=len(events),
    )
    qr_png = render_qr_png(qr_text, scale=8, border=6)

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 portrait

    # Title banner
    banner_rgb = (15 / 255, 23 / 255, 42 / 255)
    page.draw_rect(pymupdf.Rect(32, 28, 563, 94), color=banner_rgb, fill=banner_rgb)
    page.insert_text(
        (44, 54),
        "AeroRegu - Signed Certification Evidence Dossier",
        fontsize=15,
        color=(1, 1, 1),
    )
    page.insert_text(
        (44, 74),
        "Assists human engineers & CVE reviewers. Does NOT determine regulatory compliance.",
        fontsize=8.5,
        color=(0.82, 0.88, 0.96),
    )

    # QR code top-right (high contrast for physical/camera scanning with clean quiet zone)
    qr_rect = pymupdf.Rect(366, 102, 566, 302)
    page.draw_rect(
        pymupdf.Rect(362, 98, 570, 306), color=(0.85, 0.88, 0.92), fill=(1, 1, 1), width=0.6
    )
    page.insert_image(qr_rect, stream=qr_png)
    page.insert_text(
        (402, 316), "Scan to verify Merkle + DSSE", fontsize=7.5, color=(0.2, 0.25, 0.35)
    )

    # Cryptographic ledger metadata (left of QR)
    counts = gate["counts"]
    meta_lines = [
        f"Tenant: {tenant_id}",
        f"Gate Status: {gate['gate_status']}  |  Chain Verified: {chain_verified}",
        f"Head Hash: {head_hash[:32]}...",
        f"Merkle Root: {root[:32]}...",
        f"DSSE KeyID: {dsse_envelope['signatures'][0]['keyid']} (Ed25519)",
        f"Sig SHA-256: {sig_sha256[:32]}...",
        f"Events: {len(events)}  |  Cells: {counts['calc_cells']}/{counts['total_cells']}"
        f"  |  Gaps: {counts['gap_cells']}",
        f"Distinct Reviewer Enforced: {enforce_distinct_reviewer}"
        f"  |  Signed: {gate['head_signed_off']}",
    ]
    y_cursor = 122
    for line in meta_lines:
        page.insert_text((36, y_cursor), line, fontsize=9, color=(0.1, 0.14, 0.22))
        y_cursor += 15

    # Human Sign-Offs & Blockers
    y_cursor = max(y_cursor + 12, 332)
    page.insert_text(
        (36, y_cursor), "Human Review & Separation of Duties", fontsize=11, color=(0.06, 0.1, 0.18)
    )
    y_cursor += 16
    if signoffs:
        for so in signoffs[:6]:
            role_label = so.get("actor_role") or so.get("role") or "reviewer"
            line = (
                f"- {so.get('actor_id')} ({role_label}) -> "
                f"{str(so.get('target_event_hash', ''))[:16]}... [{so.get('status')}]"
            )
            page.insert_text((42, y_cursor), line, fontsize=8.5, color=(0.15, 0.2, 0.3))
            y_cursor += 13
    else:
        page.insert_text(
            (42, y_cursor),
            "- No active human sign-off recorded.",
            fontsize=8.5,
            color=(0.45, 0.2, 0.2),
        )
        y_cursor += 13

    if gate["blockers"]:
        page.insert_text(
            (42, y_cursor + 4),
            f"Blockers: {', '.join(gate['blockers'])}",
            fontsize=8.5,
            color=(0.75, 0.12, 0.12),
        )
        y_cursor += 18

    # Cited visual bbox thumbnails section
    y_cursor += 14
    page.insert_text(
        (36, y_cursor),
        f"Visual Document Evidence Thumbnails ({len(citations)} cited bbox regions)",
        fontsize=11,
        color=(0.06, 0.1, 0.18),
    )
    y_cursor += 14

    if not citations:
        page.insert_text(
            (42, y_cursor + 8),
            "No page_no + bbox citations found in current ledger stream.",
            fontsize=8.5,
            color=(0.35, 0.4, 0.5),
        )
    else:
        for idx, cit in enumerate(citations, start=1):
            if y_cursor > 685:
                page = doc.new_page(width=595, height=842)
                page.insert_text(
                    (36, 42), "Visual Document Evidence Thumbnails (cont.)", fontsize=11
                )
                y_cursor = 64

            thumb_png = _render_bbox_thumbnail(citation=cit, pdf_sources=pdf_sources)
            card_rect = pymupdf.Rect(36, y_cursor, 558, y_cursor + 112)
            page.draw_rect(card_rect, color=(0.82, 0.85, 0.9), width=0.8)
            img_rect = pymupdf.Rect(42, y_cursor + 6, 222, y_cursor + 106)
            page.insert_image(img_rect, stream=thumb_png)

            bbox_str = ", ".join(f"{float(c):.1f}" for c in cit["bbox"])
            quote = " ".join(str(cit.get("text") or "").split())[:130]
            page.insert_text(
                (234, y_cursor + 20),
                f"#{idx}  Source: {cit['source_id']}  (Page {cit['page_no']})",
                fontsize=9,
                color=(0.06, 0.1, 0.2),
            )
            page.insert_text(
                (234, y_cursor + 35),
                f"BBox [pt]: [{bbox_str}]",
                fontsize=8,
                color=(0.75, 0.12, 0.12),
            )
            page.insert_text(
                (234, y_cursor + 49),
                f"SHA-256: {str(cit['source_hash'])[:28]}...",
                fontsize=8,
                color=(0.3, 0.35, 0.45),
            )
            if quote:
                page.insert_text(
                    (234, y_cursor + 66), quote[:54], fontsize=8, color=(0.15, 0.2, 0.28)
                )
                if len(quote) > 54:
                    page.insert_text(
                        (234, y_cursor + 78), quote[54:108], fontsize=8, color=(0.15, 0.2, 0.28)
                    )
            y_cursor += 122

    # Embed cryptographic DSSE envelope & Ed25519 public key right inside PDF container
    doc.embfile_add(
        _DSSE_ATTACHMENT_NAME,
        dsse_bytes,
        filename=_DSSE_ATTACHMENT_NAME,
        desc="DSSE v1 Ed25519 Attestation Envelope",
    )
    doc.embfile_add(
        _PUBKEY_ATTACHMENT_NAME,
        pub_pem,
        filename=_PUBKEY_ATTACHMENT_NAME,
        desc="Ed25519 Verification Public Key (PEM)",
    )
    doc.set_metadata(
        {
            "title": f"AeroRegu Signed Evidence Dossier ({tenant_id})",
            "subject": f"merkle={root} head={head_hash}",
            "keywords": qr_text,
            "creator": "aeroregu-evidence-layer",
        }
    )

    pdf_bytes = doc.tobytes(deflate=True)
    doc.close()

    return {
        "pdf_bytes": pdf_bytes,
        "pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "merkle_root": root,
        "head_hash": head_hash,
        "qr_payload": qr_text,
        "dsse_envelope": dsse_envelope,
        "public_key_pem": pub_pem.decode("ascii"),
        "bbox_thumbnails_count": len(citations),
        "gate_status": gate["gate_status"],
    }


def verify_signed_pdf_report(
    pdf_bytes: bytes,
    *,
    expected_public_key_pem: bytes | None = None,
) -> dict[str, Any]:
    """Offline verify embedded DSSE Ed25519 signature, PDF QR code payload, and metadata."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        names = doc.embfile_names()
        if _DSSE_ATTACHMENT_NAME not in names:
            return {"valid": False, "reason": "missing_dsse_attachment"}
        dsse_raw = doc.embfile_get(_DSSE_ATTACHMENT_NAME)
        dsse = json.loads(dsse_raw.decode("utf-8"))
        pub_pem = expected_public_key_pem
        if pub_pem is None:
            if _PUBKEY_ATTACHMENT_NAME not in names:
                return {"valid": False, "reason": "missing_public_key_attachment"}
            pub_pem = doc.embfile_get(_PUBKEY_ATTACHMENT_NAME)
        page0_images = doc.load_page(0).get_images(full=True)
        image_count = sum(len(doc.load_page(i).get_images(full=True)) for i in range(len(doc)))

    valid, payload = verify_attestation_dsse(dsse, pub_pem)
    if not valid or payload is None:
        return {"valid": False, "reason": "invalid_dsse_signature"}
    if not page0_images:
        return {"valid": False, "reason": "missing_qr_image"}
    return {
        "valid": True,
        "attestation": payload,
        "keyid": dsse["signatures"][0]["keyid"],
        "embedded_image_count": image_count,
    }
