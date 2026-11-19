"""Qualification Aid Pack (ADR-018) IQ/OQ verification suite & standalone offline verifier."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import rfc8785
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ASSISTANCE_DISCLAIMER = "This tool assists a human reviewer. It does not determine compliance."
_GENESIS = "0" * 64
_EMPTY_MERKLE_ROOT = hashlib.sha256(b"").hexdigest()


def _canonical_json_text(value: Any) -> str:
    return rfc8785.dumps(value).decode("utf-8")


def _compute_event_hash_standalone(prev_hash: str, body: dict[str, Any]) -> str:
    inner = hashlib.sha256(_canonical_json_text(body).encode("utf-8")).hexdigest()
    return hashlib.sha256((prev_hash + inner).encode("ascii")).hexdigest()


def _hash_leaf_rfc6962(event_hash_hex: str) -> str:
    return hashlib.sha256(b"\x00" + event_hash_hex.encode("utf-8")).hexdigest()


def _hash_node_rfc6962(left_hex: str, right_hex: str) -> str:
    return hashlib.sha256(
        b"\x01" + left_hex.encode("ascii") + right_hex.encode("ascii")
    ).hexdigest()


def _compute_merkle_root_and_proofs(
    event_hashes: list[str],
) -> tuple[str, dict[str, list[dict[str, str]]]]:
    if not event_hashes:
        return _EMPTY_MERKLE_ROOT, {}
    nodes = [_hash_leaf_rfc6962(item) for item in event_hashes]
    # Track inclusion paths per initial leaf index cleanly using standard level ascent
    paths: dict[int, list[dict[str, str]]] = {i: [] for i in range(len(event_hashes))}
    tracked_groups: list[list[int]] = [[i] for i in range(len(event_hashes))]

    level_nodes = list(nodes)
    while len(level_nodes) > 1:
        next_nodes: list[str] = []
        next_groups: list[list[int]] = []
        for idx in range(0, len(level_nodes), 2):
            if idx + 1 < len(level_nodes):
                left_h = level_nodes[idx]
                right_h = level_nodes[idx + 1]
                for leaf_idx in tracked_groups[idx]:
                    paths[leaf_idx].append({"side": "right", "hash": right_h})
                for leaf_idx in tracked_groups[idx + 1]:
                    paths[leaf_idx].append({"side": "left", "hash": left_h})
                next_nodes.append(_hash_node_rfc6962(left_h, right_h))
                next_groups.append(tracked_groups[idx] + tracked_groups[idx + 1])
            else:
                next_nodes.append(level_nodes[idx])
                next_groups.append(tracked_groups[idx])
        level_nodes = next_nodes
        tracked_groups = next_groups

    proofs_by_hash = {event_hashes[i]: paths[i] for i in range(len(event_hashes))}
    return level_nodes[0], proofs_by_hash


def _verify_inclusion_standalone(
    target_hash: str,
    audit_path: list[dict[str, str]],
    expected_root: str,
) -> bool:
    current = _hash_leaf_rfc6962(target_hash)
    for step in audit_path:
        sibling = step.get("hash", "")
        side = step.get("side")
        if not isinstance(sibling, str) or len(sibling) != 64:
            return False
        if side == "left":
            current = _hash_node_rfc6962(sibling, current)
        elif side == "right":
            current = _hash_node_rfc6962(current, sibling)
        else:
            return False
    return hmac.compare_digest(current, expected_root)


def verify_standalone_dossier_offline(
    bundle_or_events: bytes | dict[str, Any] | list[dict[str, Any]],
    *,
    expected_merkle_root: str | None = None,
    public_key_pem: str | bytes | None = None,
    signature_b64: str | None = None,
) -> dict[str, Any]:
    """Independently verify exported zip, event chain, RFC 6962 Merkle root, and DSSE."""
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    dsse_sig_b64: str | None = signature_b64
    dsse_payload_bytes: bytes | None = None
    pub_pem_bytes: bytes | None = (
        public_key_pem.encode("utf-8") if isinstance(public_key_pem, str) else public_key_pem
    )
    zip_merkle_root: str | None = expected_merkle_root

    if isinstance(bundle_or_events, (bytes, bytearray)):
        raw = bytes(bundle_or_events)
        if raw.startswith(b"PK"):
            with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
                names = set(zf.namelist())
                if "chain.json" not in names:
                    return {
                        "verified": False,
                        "chain_verified": False,
                        "merkle_verified": False,
                        "inclusion_proofs_verified": False,
                        "signature_verified": None,
                        "event_count": 0,
                        "computed_head_hash": _GENESIS,
                        "computed_merkle_root": _EMPTY_MERKLE_ROOT,
                        "errors": ["missing_chain_json_in_zip"],
                    }
                events = json.loads(zf.read("chain.json").decode("utf-8"))
                if "merkle_root.txt" in names and zip_merkle_root is None:
                    zip_merkle_root = zf.read("merkle_root.txt").decode("utf-8").strip()
                if "attestation_public_key.pem" in names and pub_pem_bytes is None:
                    pub_pem_bytes = zf.read("attestation_public_key.pem")
                if "attestation_bundle.dsse.json" in names and dsse_sig_b64 is None:
                    dsse = json.loads(zf.read("attestation_bundle.dsse.json").decode("utf-8"))
                    sigs = dsse.get("signatures") or []
                    if sigs:
                        dsse_sig_b64 = str(sigs[0].get("sig") or "")
                        payload_type = str(dsse.get("payloadType") or "")
                        payload_raw = base64.b64decode(str(dsse.get("payload") or ""))
                        # DSSE PAE encoding: "DSSEv1 <len(type)> <type> <len(body)> <body>"
                        pae_header = (
                            f"DSSEv1 {len(payload_type)} {payload_type} {len(payload_raw)} ".encode(
                                "ascii"
                            )
                        )
                        dsse_payload_bytes = pae_header + payload_raw
        else:
            parsed = json.loads(raw.decode("utf-8"))
            events = parsed if isinstance(parsed, list) else list(parsed.get("events") or [])
    elif isinstance(bundle_or_events, dict):
        events = list(bundle_or_events.get("events") or bundle_or_events.get("chain") or [])
    elif isinstance(bundle_or_events, list):
        events = list(bundle_or_events)
    else:
        errors.append("unsupported_bundle_type")

    chain_ok = True
    prev_hash = _GENESIS
    event_hashes: list[str] = []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            chain_ok = False
            errors.append(f"malformed_event_at_{idx}")
            break
        body = ev.get("body")
        recorded_prev = str(ev.get("prev_hash", ""))
        recorded_hash = str(ev.get("event_hash", ""))
        if not isinstance(body, dict) or recorded_prev != prev_hash:
            chain_ok = False
            errors.append(f"broken_prev_hash_at_{idx}")
            break
        computed = _compute_event_hash_standalone(prev_hash, body)
        if not hmac.compare_digest(computed, recorded_hash):
            chain_ok = False
            errors.append(f"hash_mismatch_at_{idx}")
            break
        event_hashes.append(recorded_hash)
        prev_hash = recorded_hash

    computed_root, proofs = _compute_merkle_root_and_proofs(event_hashes)
    merkle_ok = True
    if zip_merkle_root is not None and not hmac.compare_digest(computed_root, zip_merkle_root):
        merkle_ok = False
        errors.append("merkle_root_mismatch")

    proofs_ok = True
    for ev_h, path in proofs.items():
        if not _verify_inclusion_standalone(ev_h, path, computed_root):
            proofs_ok = False
            errors.append(f"inclusion_proof_failed_{ev_h[:12]}")
            break

    sig_ok: bool | None = None
    if pub_pem_bytes and dsse_sig_b64:
        try:
            pub = serialization.load_pem_public_key(pub_pem_bytes)
            if not isinstance(pub, Ed25519PublicKey):
                raise ValueError("unsupported_public_key_type")
            msg = (
                dsse_payload_bytes
                if dsse_payload_bytes is not None
                else computed_root.encode("utf-8")
            )
            pub.verify(base64.b64decode(dsse_sig_b64), msg)
            sig_ok = True
        except Exception as exc:
            sig_ok = False
            errors.append(f"signature_verification_failed:{exc}")

    overall = (
        chain_ok
        and merkle_ok
        and proofs_ok
        and (sig_ok is None or sig_ok is True)
        and len(errors) == 0
    )
    return {
        "verified": overall,
        "chain_verified": chain_ok,
        "merkle_verified": merkle_ok,
        "inclusion_proofs_verified": proofs_ok,
        "signature_verified": sig_ok,
        "event_count": len(events),
        "computed_head_hash": prev_hash,
        "computed_merkle_root": computed_root,
        "errors": errors,
        "assistance_disclaimer": ASSISTANCE_DISCLAIMER,
    }


def run_iq_oq_qualification_suite(repo_root: Path | None = None) -> dict[str, Any]:
    """Execute deterministic IQ and OQ verification checks for the Qualification Aid Pack."""
    from evidence_calc.registry import list_method_ids, run_method
    from evidence_calc.units import check_expression_dimensional_homogeneity
    from evidence_kernel.canonical import event_hash
    from evidence_kernel.hsm_eidas_scim import EidasQESEnvelope, HSMKMSSigner

    checks: list[dict[str, Any]] = []

    # IQ checks: Python environment, pinned libraries, card inventory, docs presence
    iq_py_ok = sys.version_info >= (3, 12)
    checks.append(
        {
            "id": "IQ-01",
            "phase": "IQ",
            "name": "python_runtime_version",
            "passed": iq_py_ok,
            "detail": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        }
    )

    req_pkgs = ["cryptography", "flint", "pint", "pydantic", "fastapi", "rfc8785"]
    missing_pkgs = [p for p in req_pkgs if importlib.util.find_spec(p) is None]
    checks.append(
        {
            "id": "IQ-02",
            "phase": "IQ",
            "name": "critical_packages_present",
            "passed": len(missing_pkgs) == 0,
            "detail": f"missing={missing_pkgs}",
        }
    )

    method_ids = list_method_ids(include_plugins=False)
    checks.append(
        {
            "id": "IQ-03",
            "phase": "IQ",
            "name": "builtin_method_card_count",
            "passed": len(method_ids) >= 32,
            "detail": f"cards={len(method_ids)}",
        }
    )

    qual_docs_ok = True
    if repo_root is not None:
        qdir = Path(repo_root) / "docs" / "qualification"
        qual_docs_ok = all(
            (qdir / name).is_file()
            for name in (
                "tool_operational_requirements_tor.md",
                "tool_qualification_plan_tqp.md",
                "requirement_trace_matrix_rtm.json",
            )
        )
    checks.append(
        {
            "id": "IQ-04",
            "phase": "IQ",
            "name": "qualification_aid_documentation_present",
            "passed": qual_docs_ok,
            "detail": "TOR, TQP, and RTM verified"
            if repo_root is not None
            else "runtime-only check",
        }
    )

    # OQ checks: Deterministic calculation, AST units check, Merkle/offline verify, HSM QES
    calc_out = run_method(
        "margin_of_safety",
        {
            "applied_load_n": "10000",
            "allowable_load_n": "15000",
            "reserve_factor": "1.0",
            "fitting_factor": "1.15",
        },
        include_intervals=True,
    )
    oq_calc_ok = (
        calc_out["outputs"]["margin_of_safety"] == "0.304"
        and "margin_of_safety" in calc_out["exact_intervals"]
    )
    checks.append(
        {"id": "OQ-01", "phase": "OQ", "name": "deterministic_calc_arb", "passed": oq_calc_ok}
    )

    dim_rejected = False
    try:
        check_expression_dimensional_homogeneity(
            "force + length", {"force": "newton", "length": "millimeter"}
        )
    except Exception:
        dim_rejected = True
    checks.append(
        {
            "id": "OQ-02",
            "phase": "OQ",
            "name": "ast_dimensional_inhomogeneity_reject",
            "passed": dim_rejected,
        }
    )

    sample_body = {"event_type": "oq_probe", "seq": 1}
    h1 = event_hash(_GENESIS, sample_body)
    synthetic_events = [{"prev_hash": _GENESIS, "event_hash": h1, "body": sample_body}]
    offline_res = verify_standalone_dossier_offline(synthetic_events)
    checks.append(
        {
            "id": "OQ-03",
            "phase": "OQ",
            "name": "standalone_offline_chain_and_merkle",
            "passed": bool(offline_res["verified"]),
        }
    )

    hsm = HSMKMSSigner()
    qes_svc = EidasQESEnvelope(hsm)
    env = qes_svc.build_envelope(b"oq-probe-bytes", signer_id="oq-verifier", profile="CAdES-B-LT")
    qes_v = EidasQESEnvelope.verify_envelope(env, b"oq-probe-bytes")
    checks.append(
        {
            "id": "OQ-04",
            "phase": "OQ",
            "name": "hsm_eidas_qes_ltv_roundtrip",
            "passed": bool(qes_v["verified"] and qes_v["tsa_rfc3161_valid"]),
        }
    )

    iq_passed = all(c["passed"] for c in checks if c["phase"] == "IQ")
    oq_passed = all(c["passed"] for c in checks if c["phase"] == "OQ")
    overall = iq_passed and oq_passed
    payload_for_hash = {"iq_passed": iq_passed, "oq_passed": oq_passed, "checks": checks}
    return {
        "status": "PASS" if overall else "FAIL",
        "iq_passed": iq_passed,
        "oq_passed": oq_passed,
        "aid_pack_standard": "DO-178C / DO-330 reference aid (human-in-the-loop)",
        "assistance_disclaimer": ASSISTANCE_DISCLAIMER,
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checks": checks,
        "report_sha256": hashlib.sha256(
            json.dumps(payload_for_hash, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
