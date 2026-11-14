"""LATER_AGENTS Red-Team solver orchestration (`envelope_critic` & `bench_attacker`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evidence_calc.adversarial_fuzzer import fuzz_all_methods, fuzz_method
from evidence_kernel.agents import require_active_agent
from evidence_kernel.formal import SMTSolverProofEngine
from evidence_kernel.telemetry import get_telemetry


def run_envelope_critic(
    *,
    mass_bounds_kg: tuple[str, str] = ("800.000", "1050.000"),
    cg_bounds_m: tuple[str, str] = ("-0.250", "0.265"),
    load_factor_bounds: tuple[str, str] = ("-1.000", "3.000"),
    max_station_force_n: str = "4200.000",
    stations_m: list[str] | None = None,
    min_active_units: int = 3,
    structural_bounds: dict[str, tuple[str, str]] | None = None,
    structural_allowables: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Activate `envelope_critic`: search continuous intervals via Z3+cvc5 for counterexamples.

    Follows ADR-016: proposes `not_in_envelope` candidates for human review without mutating
    certified coverage status directly.
    """
    require_active_agent("envelope_critic")
    engine = SMTSolverProofEngine(timeout_ms=3000, cross_check=True)
    station_list = stations_m or ["-1.200", "-1.200", "1.200", "1.200"]

    eq_proof = engine.prove_station_equilibrium(
        bounds={
            "mass_kg": mass_bounds_kg,
            "cg_x_m": cg_bounds_m,
            "load_factor": load_factor_bounds,
        },
        stations=station_list,
        max_station_force_n=max_station_force_n,
        active_stations_min=min_active_units,
        enforce_moment_equilibrium=True,
    )

    s_bounds = structural_bounds or {
        "area_mm2": ("65.000", "85.000"),
        "shear_force_n": ("4000.000", "9500.000"),
        "tensile_force_n": ("3000.000", "9000.000"),
    }
    s_allow = structural_allowables or {
        "shear_allowable_mpa": "180.000",
        "tensile_allowable_mpa": "260.000",
    }
    struct_proof = engine.prove_structural_margin(
        bounds=s_bounds,
        allowables=s_allow,
        safety_factor="1.500",
    )

    proposals: list[dict[str, Any]] = []
    for label, proof in (
        ("station_equilibrium_oei", eq_proof),
        ("combined_bolt_margin", struct_proof),
    ):
        if not proof.proved and proof.counterexample:
            proposals.append(
                {
                    "proposal_id": f"critic_{proof.proof_hash[:12]}",
                    "agent_id": "envelope_critic",
                    "proposed_status": "not_in_envelope",
                    "human_approval_required": True,
                    "property": label,
                    "proof_status": proof.status,
                    "proof_hash": proof.proof_hash,
                    "counterexample": proof.counterexample,
                    "solver_stats": proof.solver_stats,
                    "reason": proof.solver_stats.get("reason") or "SMT counterexample found",
                }
            )
            get_telemetry().record_verification(
                stage="envelope_critic",
                abstained=True,
                reason=f"counterexample:{label}",
            )
        else:
            get_telemetry().record_verification(stage="envelope_critic", abstained=False)

    return {
        "agent_id": "envelope_critic",
        "human_status_mutated": False,
        "station_equilibrium_proof": eq_proof.to_dict(),
        "structural_margin_proof": struct_proof.to_dict(),
        "proposals": proposals,
        "counterexample_count": len(proposals),
    }


def run_bench_attacker(
    *,
    quarantine_dir: Path | None = None,
    method_ids: list[str] | None = None,
    custom_inputs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Activate `bench_attacker`: quarantine adversarial fault candidates cleanly."""
    require_active_agent("bench_attacker")
    if custom_inputs:
        reports = [fuzz_method(mid, inp) for mid, inp in custom_inputs.items()]
        ranked = [
            {"method_id": rep["method_id"], **item} for rep in reports for item in rep["findings"]
        ]
        summary: dict[str, Any] = {
            "methods_fuzzed": len(reports),
            "total_findings": len(ranked),
            "critical_findings": sum(1 for r in ranked if r["severity"] == "CRITICAL"),
            "per_method": reports,
            "ranked_findings": ranked,
        }
    else:
        summary = fuzz_all_methods(method_ids)

    written_files: list[str] = []
    if quarantine_dir is not None:
        qdir = Path(quarantine_dir)
        qdir.mkdir(parents=True, exist_ok=True)
        for item in summary["ranked_findings"]:
            cid = hashlib.sha256(
                json.dumps(item, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:16]
            qfile = qdir / f"candidate_{cid}.json"
            qfile.write_text(
                json.dumps(
                    {
                        "candidate_id": cid,
                        "agent_id": "bench_attacker",
                        "gold_label_untouched": True,
                        "quarantined": True,
                        **item,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            written_files.append(str(qfile))

    return {
        "agent_id": "bench_attacker",
        "gold_labels_modified": False,
        "quarantine_files_written": len(written_files),
        "quarantine_paths": written_files[:20],
        **summary,
    }
