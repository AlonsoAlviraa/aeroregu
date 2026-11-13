"""Deterministic in-toto-style pipeline attestation bundle and DSSE Ed25519 signing."""

from __future__ import annotations

import base64
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from evidence_kernel.canonical import canonicalize, inputs_hash, sha256_text
from evidence_kernel.ledger import GENESIS
from evidence_kernel.merkle import merkle_root

DSSE_PAYLOAD_TYPE = "application/vnd.in-toto+json"


def _dsse_pae(payload_type: str, payload_bytes: bytes) -> bytes:
    """Dead Simple Signing Envelope (DSSE) v1 Pre-Authentication Encoding."""
    header = f"DSSEv1 {len(payload_type)} {payload_type} {len(payload_bytes)} ".encode("ascii")
    return header + payload_bytes


def generate_ed25519_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_pem, public_key_pem) for air-gapped DSSE Ed25519 signing."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def sign_attestation_dsse(
    bundle: dict[str, Any],
    private_key_pem: bytes,
    *,
    key_id: str | None = None,
) -> dict[str, Any]:
    """Wrap an attestation bundle in a signed DSSE v1 envelope using Ed25519."""
    priv = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise TypeError("private_key_pem must be an Ed25519 private key")

    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    resolved_key_id = key_id or sha256_text(pub_pem.decode("ascii"))[:16]
    payload_bytes = canonicalize(bundle).encode("utf-8")
    pae = _dsse_pae(DSSE_PAYLOAD_TYPE, payload_bytes)
    sig_b64 = base64.b64encode(priv.sign(pae)).decode("ascii")

    return {
        "payload": base64.b64encode(payload_bytes).decode("ascii"),
        "payloadType": DSSE_PAYLOAD_TYPE,
        "signatures": [
            {
                "keyid": resolved_key_id,
                "alg": "ed25519",
                "sig": sig_b64,
            }
        ],
    }


def verify_attestation_dsse(
    dsse_envelope: dict[str, Any],
    public_key_pem: bytes,
) -> tuple[bool, dict[str, Any] | None]:
    """Verify DSSE v1 Ed25519 signature against the canonical payload bytes."""
    pub = serialization.load_pem_public_key(public_key_pem)
    if not isinstance(pub, Ed25519PublicKey):
        raise TypeError("public_key_pem must be an Ed25519 public key")

    payload_type = str(dsse_envelope.get("payloadType", ""))
    payload_b64 = str(dsse_envelope.get("payload", ""))
    signatures = dsse_envelope.get("signatures") or []
    if payload_type != DSSE_PAYLOAD_TYPE or not payload_b64 or not isinstance(signatures, list):
        return False, None
    try:
        payload_bytes = base64.b64decode(payload_b64, validate=True)
    except Exception:
        return False, None

    pae = _dsse_pae(payload_type, payload_bytes)
    for entry in signatures:
        if not isinstance(entry, dict):
            continue
        sig_b64 = str(entry.get("sig", ""))
        try:
            sig_bytes = base64.b64decode(sig_b64, validate=True)
            pub.verify(sig_bytes, pae)
        except (InvalidSignature, Exception):
            continue
        import json

        return True, json.loads(payload_bytes.decode("utf-8"))
    return False, None


def build_pipeline_attestation(
    events: list[dict[str, Any]],
    *,
    predicate_type: str = "https://aeroregu.local/attestation/v1",
) -> dict[str, Any]:
    """Build a deterministic provenance bundle across calc, agent_turn, and signoff steps."""
    steps: list[dict[str, Any]] = []
    for seq, event in enumerate(events, start=1):
        body = event["body"]
        envelope = body["envelope"]
        payload = body["payload"]
        step = {
            "step_index": str(seq),
            "step_type": str(body["event_type"]),
            "actor_id": str(body["actor_id"]),
            "created_at": str(body["created_at"]),
            "event_hash": str(event["event_hash"]),
            "prev_hash": str(event["prev_hash"]),
            "method_version": str(envelope["method_version"]),
            "inputs_hash": str(envelope["inputs_hash"]),
            "confidence": str(envelope["confidence"]),
            "payload_digest": inputs_hash(payload),
        }
        if body["event_type"] == "agent_turn":
            step["agent_id"] = str(payload.get("agent_id", ""))
            step["prompt_hash"] = str(payload.get("prompt_hash", ""))
            step["materials"] = list(payload.get("input_event_hashes") or [])
        steps.append(step)

    head_hash = str(events[-1]["event_hash"]) if events else GENESIS
    m_root = merkle_root([str(event["event_hash"]) for event in events])
    core = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": predicate_type,
        "subject": [
            {
                "name": "evidence_ledger_head",
                "digest": {"sha256": head_hash, "merkle_root": m_root},
            }
        ],
        "predicate": {
            "event_count": str(len(events)),
            "steps": steps,
        },
    }
    return {"attestation_digest": inputs_hash(core), **core}
