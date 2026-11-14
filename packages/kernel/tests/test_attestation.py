from __future__ import annotations

from pathlib import Path

from evidence_kernel.__main__ import verify_zip_bundle
from evidence_kernel.attestation import build_pipeline_attestation
from evidence_kernel.gateway import FixtureGateway
from evidence_kernel.ledger import Ledger
from evidence_kernel.supervisor import CaseSpec, run_case


def test_build_pipeline_attestation_in_toto_structure(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "attest.sqlite3", "demo")
    text = "SL-1.REQ-01 Structural load point mass equilibrium check."
    case = CaseSpec(
        tenant_id="demo",
        actor_id="author",
        created_at="2026-11-12T10:00:00Z",
        blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
        method_id="rigid_body_point_mass",
        calc_inputs={
            "mass_kg": "800.000",
            "gravity_m_s2": "9.810",
            "load_factor": "1.000",
            "cg_x_m": "-0.200",
            "unit_x_m": ["-1.000", "-0.300", "0.300", "1.000"],
            "unit_operative": [True, True, True, True],
        },
    )
    outcome = run_case(ledger, FixtureGateway("happy"), case)
    assert outcome.envelope["confidence"] == "deterministic"

    events = ledger.events()
    bundle = build_pipeline_attestation(events)
    assert bundle["_type"] == "https://in-toto.io/Statement/v1"
    assert len(bundle["attestation_digest"]) == 64
    assert bundle["subject"][0]["digest"]["sha256"] == ledger.head_hash()
    assert bundle["subject"][0]["digest"]["merkle_root"] == ledger.merkle_root()
    assert bundle["predicate"]["event_count"] == str(len(events))
    assert any(step["step_type"] == "agent_turn" for step in bundle["predicate"]["steps"])
    # Deterministic on identical events
    assert build_pipeline_attestation(events) == bundle


def test_verify_zip_bundle_rejects_decompression_bomb(tmp_path: Path) -> None:
    import zipfile

    bomb_ratio_path = tmp_path / "bomb_ratio.zip"
    with zipfile.ZipFile(bomb_ratio_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 200,000 bytes of zeros compresses to ~200 bytes -> ratio ~1000 > 100
        zf.writestr("chain.json", b"0" * 200_000)

    ok, report = verify_zip_bundle(bomb_ratio_path)
    assert ok is False
    assert report["error"] == "zip_bomb_detected"

    bomb_size_path = tmp_path / "bomb_cumulative.zip"
    with zipfile.ZipFile(bomb_size_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Cumulative size > 64 MB
        zf.writestr("huge.dat", b"0" * (70 * 1024 * 1024))

    ok2, report2 = verify_zip_bundle(bomb_size_path)
    assert ok2 is False
    assert report2["error"] == "zip_bomb_detected"
