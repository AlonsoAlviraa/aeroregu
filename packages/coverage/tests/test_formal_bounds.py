from __future__ import annotations

from evidence_coverage.dossier import build_enterprise_dossier, export_oscal_sar, export_strictdoc
from evidence_coverage.formal_bounds import prove_continuous_flight_envelope


def test_prove_continuous_flight_envelope_safe() -> None:
    result = prove_continuous_flight_envelope()
    assert result["envelope_proved"] is True
    assert result["status"] == "PROVED_UNSAT"
    assert result["counterexample"] is None
    assert len(result["proof_hash"]) == 64
    assert "Cliff-edge risk: 0.000%" in result["summary"]


def test_prove_continuous_flight_envelope_counterexample() -> None:
    # Insufficient thrust per unit: max load cannot be sustained
    result = prove_continuous_flight_envelope(max_station_thrust_n="5000.000")
    assert result["envelope_proved"] is False
    assert result["status"] == "COUNTEREXAMPLE_FOUND"
    assert result["counterexample"] is not None
    assert "mass_kg" in result["counterexample"]


def test_dossier_includes_formal_proof_in_strictdoc_and_oscal() -> None:
    events = [
        {
            "event_hash": "a" * 64,
            "body": {
                "event_type": "cell_status_set",
                "actor_id": "test_runner",
                "payload": {
                    "cell_id": "m800.000-cg-0.200-lf1.000-unone",
                    "status": "calc",
                    "evidence_event_hash": "e" * 64,
                    "inputs_hash": "i" * 64,
                    "axes": {
                        "mass_kg": "800.000",
                        "cg_x_m": "-0.200",
                        "load_factor": "1.000",
                        "failed_unit": "none",
                    },
                },
            },
        }
    ]
    dossier = build_enterprise_dossier(events, chain_verified=True)
    assert "formal_envelope_proof" in dossier
    assert dossier["formal_envelope_proof"]["envelope_proved"] is True

    sdoc = export_strictdoc(dossier)
    assert "TITLE: Formal SMT Mathematical Bounds & Continuous Envelope Proof" in sdoc
    assert "UID: REQ-FORMAL-SMT-001" in sdoc
    assert "STATUS: Validated" in sdoc

    sar = export_oscal_sar(dossier)
    results = sar["assessment-results"]["results"][0]
    observations = results["observations"]
    formal_obs = [obs for obs in observations if obs.get("types") == ["formal-smt-proof"]]
    assert len(formal_obs) == 1
    assert formal_obs[0]["title"] == "Continuous Flight Envelope SMT Formal Proof"

    findings = results["findings"]
    formal_findings = [
        f for f in findings if f["target"]["target-id"] == "continuous-envelope-formal-bounds"
    ]
    assert len(formal_findings) == 1
    assert formal_findings[0]["target"]["status"]["state"] == "satisfied"
