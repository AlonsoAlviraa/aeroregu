"""Deterministic SHA-256 Merkle tree and O(log N) inclusion proofs for ledger events."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from typing import Any

EMPTY_ROOT = hashlib.sha256(b"").hexdigest()


def _hash_leaf(event_hash_hex: str) -> str:
    return hashlib.sha256(b"\x00" + event_hash_hex.encode("utf-8")).hexdigest()


def _hash_node(left_hex: str, right_hex: str) -> str:
    return hashlib.sha256(
        b"\x01" + left_hex.encode("ascii") + right_hex.encode("ascii")
    ).hexdigest()


def _next_level(nodes: list[str]) -> list[str]:
    level: list[str] = []
    for idx in range(0, len(nodes), 2):
        if idx + 1 < len(nodes):
            level.append(_hash_node(nodes[idx], nodes[idx + 1]))
        else:
            level.append(nodes[idx])
    return level


def merkle_root(event_hashes: Sequence[str]) -> str:
    """Compute the RFC-6962-style domain-separated SHA-256 Merkle root."""
    if not event_hashes:
        return EMPTY_ROOT
    nodes = [_hash_leaf(item) for item in event_hashes]
    while len(nodes) > 1:
        nodes = _next_level(nodes)
    return nodes[0]


def inclusion_proof(event_hashes: Sequence[str], target_hash: str) -> dict[str, Any]:
    """Build an O(log N) Merkle inclusion proof for target_hash."""
    if not event_hashes:
        raise ValueError("cannot build inclusion proof for an empty ledger")
    try:
        idx = list(event_hashes).index(target_hash)
    except ValueError as exc:
        raise ValueError(f"event_hash not found in ledger: {target_hash}") from exc

    nodes = [_hash_leaf(item) for item in event_hashes]
    audit_path: list[dict[str, str]] = []
    cur = idx
    while len(nodes) > 1:
        if cur % 2 == 0:
            if cur + 1 < len(nodes):
                audit_path.append({"side": "right", "hash": nodes[cur + 1]})
        else:
            audit_path.append({"side": "left", "hash": nodes[cur - 1]})
        nodes = _next_level(nodes)
        cur //= 2

    return {
        "target_hash": target_hash,
        "index": idx,
        "leaf_count": len(event_hashes),
        "merkle_root": nodes[0],
        "audit_path": audit_path,
    }


def verify_inclusion_proof(
    target_hash: str,
    audit_path: Sequence[dict[str, str]],
    expected_root: str,
) -> bool:
    """Verify an O(log N) Merkle inclusion proof against expected_root."""
    if not target_hash or not expected_root:
        return False
    current = _hash_leaf(target_hash)
    for step in audit_path:
        side = step.get("side")
        sibling = step.get("hash", "")
        if not isinstance(sibling, str) or len(sibling) != 64:
            return False
        if side == "left":
            current = _hash_node(sibling, current)
        elif side == "right":
            current = _hash_node(current, sibling)
        else:
            return False
    return hmac.compare_digest(current, expected_root)


def consistency_proof(event_hashes: Sequence[str], old_count: int) -> dict[str, Any]:
    """Build an append-only consistency snapshot between old_count and len(event_hashes)."""
    if old_count < 0 or old_count > len(event_hashes):
        raise ValueError("old_count must lie within [0, len(event_hashes)]")
    old_prefix = event_hashes[:old_count]
    old_root = merkle_root(old_prefix)
    new_root = merkle_root(event_hashes)
    if old_count == 0:
        return {
            "old_count": 0,
            "new_count": len(event_hashes),
            "old_root": old_root,
            "new_root": new_root,
            "boundary_hash": "",
            "boundary_proof": [],
            "consistent": True,
        }
    boundary_hash = event_hashes[old_count - 1]
    boundary = inclusion_proof(event_hashes, boundary_hash)
    return {
        "old_count": old_count,
        "new_count": len(event_hashes),
        "old_root": old_root,
        "new_root": new_root,
        "boundary_hash": boundary_hash,
        "boundary_proof": boundary["audit_path"],
        "consistent": verify_inclusion_proof(boundary_hash, boundary["audit_path"], new_root),
    }


def verify_consistency_proof(proof: dict[str, Any]) -> bool:
    """Verify an append-only Merkle consistency snapshot."""
    old_count = int(proof.get("old_count", -1))
    new_count = int(proof.get("new_count", -1))
    if old_count < 0 or new_count < old_count:
        return False
    old_root = str(proof.get("old_root", ""))
    new_root = str(proof.get("new_root", ""))
    if old_count == 0:
        return hmac.compare_digest(old_root, EMPTY_ROOT) and len(new_root) == 64
    boundary_hash = str(proof.get("boundary_hash", ""))
    boundary_proof = proof.get("boundary_proof", [])
    return len(old_root) == 64 and verify_inclusion_proof(boundary_hash, boundary_proof, new_root)
