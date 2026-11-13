from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evidence_kernel.__main__ import main as cli_main
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.ledger import Ledger
from evidence_kernel.merkle import (
    EMPTY_ROOT,
    consistency_proof,
    inclusion_proof,
    merkle_root,
    verify_consistency_proof,
    verify_inclusion_proof,
)
from evidence_kernel.orchestrator import record
from hypothesis import given
from hypothesis import strategies as st


def _sample_body(tenant_id: str, seq_label: str) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "actor_id": "author-1",
        "event_type": "abstain",
        "created_at": "2026-11-12T10:00:00Z",
        "envelope": make_envelope(
            sources=[project_source("src-1", "https://aeroregu.local/src", "ASSUMPTION")],
            method_version="screen@1.0.0",
            inputs={"case": seq_label},
            confidence="abstain",
            abstain_reason="unspecified",
        ),
        "payload": {"reason": "unspecified"},
    }


def test_empty_merkle_root_and_empty_proof_rejected() -> None:
    assert merkle_root([]) == EMPTY_ROOT
    with pytest.raises(ValueError):
        inclusion_proof([], "a" * 64)


def test_ledger_merkle_proof_and_tamper_rejection(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db", "t1")
    hashes = [record(ledger, _sample_body("t1", f"item-{idx}")) for idx in range(5)]

    root = ledger.merkle_root()
    assert len(root) == 64

    for idx, target in enumerate(hashes):
        proof = ledger.inclusion_proof(target)
        assert proof["index"] == idx
        assert proof["leaf_count"] == 5
        assert proof["merkle_root"] == root
        assert len(proof["audit_path"]) <= 3
        assert verify_inclusion_proof(target, proof["audit_path"], root) is True
        assert verify_inclusion_proof("f" * 64, proof["audit_path"], root) is False
        assert verify_inclusion_proof(target, proof["audit_path"], "0" * 64) is False

    # CLI prove & verify-proof roundtrip
    chain_file = tmp_path / "chain.json"
    chain_file.write_text(json.dumps(ledger.events()), encoding="utf-8")
    assert cli_main(["merkle-root", str(chain_file)]) == 0
    assert cli_main(["prove", str(chain_file), hashes[2]]) == 0

    proof_file = tmp_path / "proof.json"
    proof_file.write_text(json.dumps(ledger.inclusion_proof(hashes[2])), encoding="utf-8")
    assert cli_main(["verify-proof", str(proof_file)]) == 0


@given(
    st.lists(
        st.integers(min_value=1, max_value=10_000).map(
            lambda n: hashlib.sha256(str(n).encode("utf-8")).hexdigest()
        ),
        min_size=1,
        max_size=25,
        unique=True,
    )
)
def test_property_all_leaves_verify_in_log_n_steps(leaves: list[str]) -> None:
    root = merkle_root(leaves)
    max_steps = (len(leaves) - 1).bit_length()
    for target in leaves:
        proof = inclusion_proof(leaves, target)
        assert len(proof["audit_path"]) <= max_steps
        assert verify_inclusion_proof(target, proof["audit_path"], root) is True


def test_consistency_proof_and_ledger_query_events(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "consistency.db", "t-cons")
    for idx in range(5):
        record(ledger, _sample_body("t-cons", f"ev-{idx}"))

    snap = ledger.consistency_snapshot(2)
    assert snap["old_count"] == 2
    assert snap["new_count"] == 5
    assert snap["consistent"] is True
    assert verify_consistency_proof(snap) is True

    hashes = [ev["event_hash"] for ev in ledger.events()]
    snap0 = consistency_proof(hashes, 0)
    assert verify_consistency_proof(snap0) is True

    bad_snap = dict(snap)
    bad_snap["new_root"] = "0" * 64
    assert verify_consistency_proof(bad_snap) is False

    page1 = ledger.query_events(event_type="abstain", actor_id="author-1", limit=2, offset=0)
    page2 = ledger.query_events(event_type="abstain", actor_id="author-1", limit=2, offset=2)
    assert page1["total"] == 5
    assert len(page1["events"]) == 2
    assert len(page2["events"]) == 2
    assert page1["events"][0]["event_hash"] != page2["events"][0]["event_hash"]
    assert ledger.query_events(actor_id="nobody", limit=10)["total"] == 0
