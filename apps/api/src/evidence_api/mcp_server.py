"""Model Context Protocol (MCP) JSON-RPC 2.0 server (stdio + HTTP) for aeroregu / Evidence Layer.

Exposes deterministic calculation, document ingestion (with page_no + bbox), supervised
multi-agent verification, cryptographic DSSE Ed25519 export/verify, ledger queries, and
Red-Team safety tools to MCP clients (Claude Desktop, Cursor, VS Code, Antigravity IDE).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from evidence_kernel.paths import repo_root

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS = ("2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "aeroregu-evidence-layer", "version": "0.1.0"}


def _all_calc_cards() -> list[dict[str, Any]]:
    from evidence_calc.registry import list_cards

    try:
        return list_cards()
    except Exception as exc:
        logger.warning("Failed to load calculation cards: %s", exc)
        return []


def _pair_bounds(val: Any, fallback: tuple[str, str]) -> tuple[str, str]:
    if isinstance(val, (list, tuple)) and len(val) == 2:
        return (str(val[0]), str(val[1]))
    if val is not None:
        s = str(val)
        return (s, s)
    return fallback


def run_formal_proof_for_method(
    method_id: str,
    inputs: dict[str, Any],
    formal_bounds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run dual Z3+cvc5 formal proof matching the calculation method and inputs."""
    from evidence_coverage.formal_bounds import prove_continuous_flight_envelope
    from evidence_kernel.formal import SMTSolverProofEngine

    bounds = formal_bounds or {}
    if method_id == "rigid_body_point_mass":
        mass_range = _pair_bounds(
            bounds.get("mass_range_kg") or bounds.get("mass_bounds") or inputs.get("mass_kg"),
            ("800.000", "1200.000"),
        )
        cg_range = _pair_bounds(
            bounds.get("cg_range_m") or inputs.get("cg_x_m"),
            ("-0.200", "0.200"),
        )
        lf_range = _pair_bounds(
            bounds.get("load_factor_range")
            or bounds.get("load_factor_bounds")
            or inputs.get("load_factor"),
            ("-1.000", "2.500"),
        )
        stations_raw = bounds.get("station_positions_m") or inputs.get("unit_x_m")
        stations = [str(x) for x in stations_raw] if stations_raw else None
        max_thrust = str(
            bounds.get("max_station_thrust_n") or bounds.get("lift_capacity_n") or "15000.000"
        )
        gravity = str(inputs.get("gravity_m_s2") or bounds.get("gravity_m_s2") or "9.807")
        min_active = int(bounds.get("min_active_units", 3))
        return prove_continuous_flight_envelope(
            mass_range_kg=mass_range,
            cg_range_m=cg_range,
            load_factor_range=lf_range,
            station_positions_m=stations,
            max_station_thrust_n=max_thrust,
            gravity_m_s2=gravity,
            min_active_units=min_active,
        )

    engine = SMTSolverProofEngine()
    if method_id == "bolt_screen":
        proof = engine.prove_structural_margin(
            bounds={
                "area_mm2": _pair_bounds(
                    bounds.get("area_mm2") or inputs.get("area_mm2"), ("100.000", "120.000")
                ),
                "shear_force_n": _pair_bounds(
                    bounds.get("shear_force_n") or inputs.get("shear_force_n"),
                    ("1000.000", "2000.000"),
                ),
                "tensile_force_n": _pair_bounds(
                    bounds.get("tensile_force_n") or inputs.get("tensile_force_n"),
                    ("2000.000", "3000.000"),
                ),
            },
            allowables={
                "shear_allowable_mpa": str(inputs.get("shear_allowable_mpa") or "150.000"),
                "tensile_allowable_mpa": str(inputs.get("tensile_allowable_mpa") or "250.000"),
            },
            safety_factor=str(bounds.get("safety_factor") or "1.500"),
        )
        return proof.to_dict()

    if method_id == "hover_power_screen":
        proof = engine.prove_hover_power_envelope(
            thrust_bounds_n=_pair_bounds(
                bounds.get("thrust_n") or inputs.get("thrust_n"), ("2000.000", "10500.000")
            ),
            disk_area_m2=str(inputs.get("disk_area_m2") or "10.000"),
            air_density_kg_m3=str(inputs.get("air_density_kg_m3") or "1.225"),
            figure_of_merit=str(inputs.get("figure_of_merit") or "0.700"),
            max_power_available_kw=str(inputs.get("power_available_kw") or "350.000"),
        )
        return proof.to_dict()

    return {
        "property_name": f"{method_id}_formal_bounds",
        "proved": False,
        "status": "UNSUPPORTED_METHOD",
        "method_id": method_id,
    }


MCP_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "evidence_calc_list",
        "description": (
            "List certified deterministic engineering calculation methods, input schemas, "
            "required physical units, and formula cards."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    },
    {
        "name": "evidence_calc_run",
        "description": (
            "Execute a deterministic Decimal calculation method with exact python-flint "
            "interval bounds, optional unit normalization, Z3+cvc5 formal proof, and "
            "optional delta diagnosis against stated outputs."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["method_id", "inputs"],
            "properties": {
                "method_id": {"type": "string", "minLength": 1},
                "inputs": {"type": "object"},
                "stated_outputs": {"type": "object"},
                "normalize_units": {"type": "boolean", "default": False},
                "include_intervals": {"type": "boolean", "default": True},
                "formal_proof": {"type": "boolean", "default": False},
                "formal_bounds": {"type": "object"},
                "record": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string", "default": "demo"},
                "actor_id": {"type": "string", "default": "author"},
            },
        },
    },
    {
        "name": "evidence_ingest_document",
        "description": (
            "Ingest PDF, DOCX, XLSX, Markdown, or text documents into span-tracked blocks "
            "and requirement IDs (CS-27, CS-29, FAR, AMC, DO-178C, VTOL) with page_no and bbox."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["filename"],
            "properties": {
                "filename": {"type": "string", "minLength": 1},
                "content_text": {"type": "string"},
                "content_base64": {"type": "string"},
                "record": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string", "default": "demo"},
                "actor_id": {"type": "string", "default": "author"},
            },
        },
    },
    {
        "name": "evidence_verify_case",
        "description": (
            "Run the supervised multi-agent verification pipeline (reader, checker, refuter, "
            "scribe + deterministic math + Z3/cvc5 + guardrails) returning verified spans "
            "with page_no/bbox or failing closed with abstain."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string"},
                "blocks": {"type": "array", "items": {"type": "object"}},
                "method_id": {"type": "string"},
                "calc_inputs": {"type": "object"},
                "stated_outputs": {"type": "object"},
                "runtime_mode": {
                    "type": "string",
                    "enum": ["auto", "fixture", "edge", "api", "hybrid"],
                    "default": "auto",
                },
                "model": {"type": "string"},
                "edge_model": {"type": "string"},
                "edge_preset": {"type": "string", "default": "laptop-cpu-16gb"},
                "use_decision_gate": {"type": "boolean", "default": False},
                "formal_verification": {"type": "boolean", "default": False},
                "record_requirements": {"type": "boolean", "default": True},
                "compact_for_edge": {"type": "boolean", "default": False},
                "tenant_id": {"type": "string", "default": "demo"},
                "actor_id": {"type": "string", "default": "author"},
            },
        },
    },
    {
        "name": "evidence_ledger_query",
        "description": (
            "Inspect the tamper-evident SQLite hash chain ledger: status/Merkle root, "
            "recent events, Merkle inclusion proof, or human pilot signoff metrics."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "action": {
                    "type": "string",
                    "enum": ["summary", "events", "merkle_proof", "pilot_metrics"],
                    "default": "summary",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20},
                "event_hash": {"type": "string"},
            },
        },
    },
    {
        "name": "evidence_bundle_export",
        "description": (
            "Export a DSSE Ed25519 signed audit dossier ZIP (chain.json, merkle_root.txt, "
            "dossier.json, StrictDOC, OSCAL SAR, attestation_bundle.dsse.json) and verify it."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["output_path"],
            "properties": {
                "output_path": {"type": "string", "minLength": 1},
                "tenant_id": {"type": "string", "default": "demo"},
            },
        },
    },
    {
        "name": "evidence_bundle_verify",
        "description": (
            "Verify an exported dossier ZIP or chain.json off-line: hash chain integrity, "
            "Merkle root, and DSSE Ed25519 signature."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["bundle_path"],
            "properties": {
                "bundle_path": {"type": "string", "minLength": 1},
                "public_key_path": {"type": "string"},
            },
        },
    },
    {
        "name": "evidence_safety_scan",
        "description": (
            "Scan text through Evidence Layer Red-Team guardrails for prompt injection, "
            "obfuscated Base64/Hex/URL smuggling, bidi/control chars, secrets, and PII leaks."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {
                "text": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["both", "input", "output"],
                    "default": "both",
                },
            },
        },
    },
    {
        "name": "evidence_redteam_benchmark",
        "description": (
            "Run the built-in 46-probe adversarial Red-Team suite + 10 benign aerospace "
            "controls and return block rate, secret/PII leakage, and false positive metrics."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
    },
    {
        "name": "evidence_coverage_status",
        "description": (
            "Inspect the flight-envelope coverage matrix: gap summary, filtered cells "
            "(gap/covered/stale), and certification traceability gate readiness."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "action": {
                    "type": "string",
                    "enum": ["summary", "cells", "gate"],
                    "default": "summary",
                },
                "status": {"type": "string"},
                "stale_only": {"type": "boolean", "default": False},
                "require_signoff": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
        },
    },
    {
        "name": "evidence_coverage_sweep",
        "description": (
            "Mutate flight-envelope coverage state: run deterministic cell sweep, invalidate "
            "active calculations under a +5% aircraft mass shift, or set an explicit cell status."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "actor_id": {"type": "string", "default": "author"},
                "action": {
                    "type": "string",
                    "enum": ["sweep", "mass_shift", "set_cell_status"],
                    "default": "sweep",
                },
                "target_status": {"type": "string", "default": "gap"},
                "stale_only": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 15},
                "cell_id": {"type": "string"},
                "cell_status": {
                    "type": "string",
                    "enum": ["not_in_envelope", "justified_not_critical", "gap"],
                },
                "evidence_event_hash": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "evidence_dossier_export",
        "description": (
            "Build and export the enterprise certification dossier as structured JSON, "
            "StrictDOC (.sdoc) requirements markup, or NIST OSCAL 1.1.2 SAR JSON."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "format": {
                    "type": "string",
                    "enum": ["summary", "strictdoc", "oscal"],
                    "default": "summary",
                },
            },
        },
    },
    {
        "name": "evidence_formal_prove",
        "description": (
            "Run standalone dual-solver (Z3 + cvc5) continuous mathematical proofs across "
            "interval bounds: flight_envelope, structural_margin, or hover_power."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["flight_envelope", "structural_margin", "hover_power"],
                    "default": "flight_envelope",
                },
                "bounds": {"type": "object"},
                "allowables": {"type": "object"},
                "safety_factor": {"type": "string", "default": "1.500"},
                "stations_m": {"type": "array", "items": {"type": "string"}},
                "max_station_thrust_n": {"type": "string", "default": "15000.000"},
                "disk_area_m2": {"type": "string", "default": "10.000"},
                "air_density_kg_m3": {"type": "string", "default": "1.225"},
                "figure_of_merit": {"type": "string", "default": "0.700"},
                "max_power_available_kw": {"type": "string", "default": "350.000"},
            },
        },
    },
    {
        "name": "evidence_agents_runtime",
        "description": (
            "Inspect active agent gateways (fixture/edge/api/hybrid), hardware presets "
            "(Ollama/llama.cpp), edge token/chunk preflight screening, or live health probe."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "probe", "edge_preflight"],
                    "default": "status",
                },
                "target": {"type": "string", "enum": ["all", "api", "edge"], "default": "all"},
                "timeout_s": {"type": "number", "minimum": 0.5, "maximum": 10.0, "default": 3.0},
                "edge_preset": {"type": "string", "default": "laptop-cpu-16gb"},
                "text": {"type": "string"},
                "blocks": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
    {
        "name": "evidence_ledger_signoff",
        "description": (
            "Record an immutable human engineer certification sign-off in the SQLite hash "
            "chain ledger with optional review_duration_ms for pilot velocity metrics."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "actor_id": {"type": "string", "default": "reviewer"},
                "target_event_hash": {"type": "string"},
                "statement": {"type": "string"},
                "review_duration_ms": {"type": "integer", "minimum": 0},
            },
        },
    },
    {
        "name": "evidence_notes_check",
        "description": (
            "Validate a draft engineering calculation artifact against card limits/units to "
            "catch unit-scale, missing-input, or ungrounded numeric faults."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "example": {"type": "string", "enum": ["unit_scale", "missing_input"]},
                "artifact": {"type": "object"},
            },
        },
    },
    {
        "name": "evidence_bench_compare",
        "description": (
            "Run the B2 baseline single-pass LLM vs Evidence Layer comparison measuring exact "
            "page+bbox citation precision gain and numeric hallucination reduction."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {"type": "string", "enum": ["fixture"], "default": "fixture"},
            },
        },
    },
    {
        "name": "evidence_cad_cae_ingest",
        "description": (
            "Ingest and extract STEP AP242 (+ GD&T/PMI), IGES 5.3, CATIA XML/.CATPart/.CATProduct "
            "Knowledgeware trees, NASTRAN .bdf/.dat, or ABAQUS .inp FEM models and bind parameters "
            "to verified Decimal calculation cards."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["filename"],
            "properties": {
                "filename": {"type": "string"},
                "content_text": {"type": "string"},
                "content_base64": {"type": "string"},
                "auto_run": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "evidence_envelope_3d",
        "description": (
            "Build deterministic 3D V-n flight envelope surface, [X_cg, Y_cg, Z_cg] CG cloud, "
            "and SMT continuous bounds (with optional CAD/FEM CG overlay points)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "wing_area_m2": {"type": "string", "default": "12.000"},
                "v_c_mps": {"type": "string", "default": "65.000"},
                "v_d_mps": {"type": "string", "default": "82.000"},
                "nz_max": {"type": "string", "default": "2.500"},
                "nz_min": {"type": "string", "default": "-1.000"},
                "cad_cg_points": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
    {
        "name": "evidence_calc_register_plugin",
        "description": (
            "Validate and persist a custom declarative user calculation method card evaluated "
            "strictly via AST Decimal + Arb interval arithmetic (no float or code execution)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["card"],
            "properties": {
                "card": {
                    "type": "object",
                    "description": (
                        "Declarative card JSON containing method_id, title, "
                        "required, limits, and formulas."
                    ),
                }
            },
        },
    },
    {
        "name": "evidence_dossier_pdf_export",
        "description": (
            "Generate a DSSE Ed25519 signed PDF certification dossier containing cropped visual "
            "bbox page thumbnails from source PDFs and an offline verifiable ISO/IEC 18004 QR code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "output_path": {
                    "type": "string",
                    "description": "Optional .pdf output path under workspace/EVIDENCE_HOME.",
                },
                "enforce_distinct_reviewer": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "evidence_webhooks_list",
        "description": (
            "List registered CI/CD envelope-invalidation webhooks and recent delivery telemetry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"tenant_id": {"type": "string", "default": "demo"}},
        },
    },
    {
        "name": "evidence_webhooks_register",
        "description": (
            "Register an SSRF-safe HMAC-SHA256 CI/CD webhook triggered on envelope invalidation."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "url": {"type": "string"},
                "events": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
        },
    },
)

MCP_RESOURCES: tuple[dict[str, Any], ...] = (
    {
        "uri": "aeroregu://runtime/status",
        "name": "Runtime & Gateway Status",
        "description": "Active agent gateway mode, Edge/API availability, and solver runtime.",
        "mimeType": "application/json",
    },
    {
        "uri": "aeroregu://calc/catalog",
        "name": "Deterministic Calculation Catalog",
        "description": "Certified aerospace Decimal method cards and required units.",
        "mimeType": "application/json",
    },
    {
        "uri": "aeroregu://ledger/demo/summary",
        "name": "Demo Tenant Ledger Summary",
        "description": "Chain verification status, head hash, Merkle root, and pilot metrics.",
        "mimeType": "application/json",
    },
    {
        "uri": "aeroregu://attestation/public-key",
        "name": "DSSE Ed25519 Public Key",
        "description": "PEM public key used to verify exported DSSE attestation bundles.",
        "mimeType": "application/x-pem-file",
    },
    {
        "uri": "aeroregu://coverage/summary",
        "name": "Flight Envelope Coverage Summary",
        "description": "Gap report and traceability gate status for the demo tenant.",
        "mimeType": "application/json",
    },
    {
        "uri": "aeroregu://dossier/oscal",
        "name": "NIST OSCAL 1.1.2 SAR Export",
        "description": "Compliance assessment results document for the demo tenant.",
        "mimeType": "application/json",
    },
)

MCP_PROMPTS: tuple[dict[str, Any], ...] = (
    {
        "name": "audit-cs27-cs29-requirement",
        "description": (
            "Guided audit workflow for CS-27/CS-29/FAR/VTOL certification evidence with zero "
            "invented numbers and verified page_no + bbox citations."
        ),
        "arguments": [
            {
                "name": "requirement_id",
                "description": "Target clause identifier (e.g. CS-27.301 or VTOL.2210)",
                "required": False,
            }
        ],
    },
    {
        "name": "verify-offline-dossier",
        "description": "Step-by-step cryptographic audit of a signed ZIP dossier.",
        "arguments": [
            {
                "name": "bundle_path",
                "description": "Filesystem path to the exported .zip bundle",
                "required": True,
            }
        ],
    },
    {
        "name": "coverage-envelope-sweep",
        "description": (
            "Execute a flight-envelope sweep, verify continuous Z3+cvc5 bounds, check "
            "traceability gate, and export a signed DSSE dossier."
        ),
        "arguments": [
            {
                "name": "tenant_id",
                "description": "Target tenant ledger identifier",
                "required": False,
            }
        ],
    },
    {
        "name": "redteam-security-audit",
        "description": (
            "Run injection/PII guardrail scans and the 46-probe Red-Team adversarial suite."
        ),
        "arguments": [],
    },
)


MAX_BUNDLE_VERIFY_BYTES = 64 * 1024 * 1024


def _confine_path(
    raw_path: str,
    *,
    allowed_roots: tuple[Path, ...],
    default_dir: Path,
) -> Path | None:
    candidate = Path(raw_path).expanduser()
    resolved = (
        (default_dir / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    )
    for root in allowed_roots:
        if resolved.is_relative_to(root.resolve()):
            return resolved
    return None


def _ledger_summary(tenant_id: str) -> dict[str, Any]:
    from evidence_api.app import open_ledger

    ledger = open_ledger(tenant_id)
    events = ledger.events()
    signoffs = [ev for ev in events if ev["body"]["event_type"] == "human_signoff"]
    durations = [
        int(ev["body"]["payload"]["review_duration_ms"])
        for ev in signoffs
        if isinstance(ev["body"]["payload"].get("review_duration_ms"), (int, float))
    ]
    sorted_d = sorted(durations)
    return {
        "tenant_id": tenant_id,
        "chain_verified": ledger.verify(),
        "event_count": len(events),
        "head_hash": ledger.head_hash(),
        "merkle_root": ledger.merkle_root(),
        "signed_reviews": len(signoffs),
        "timed_reviews": len(durations),
        "avg_review_duration_ms": (sum(durations) // len(durations)) if durations else None,
        "median_review_duration_ms": sorted_d[len(sorted_d) // 2] if sorted_d else None,
    }


def _call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    require_auth_for_writes: bool = False,
    is_authenticated: bool = True,
) -> tuple[bool, dict[str, Any]]:
    from evidence_calc.cad_bindings import bind_parameters_to_cards
    from evidence_calc.diagnostics import classify_numeric_delta
    from evidence_calc.errors import AbstainError
    from evidence_calc.registry import run_method
    from evidence_coverage.dossier import (
        active_calc_records,
        build_enterprise_dossier,
        export_oscal_sar,
        export_strictdoc,
    )
    from evidence_coverage.envelope_3d import build_vn_cg_envelope_3d
    from evidence_coverage.formal_bounds import prove_continuous_flight_envelope
    from evidence_coverage.gate import evaluate_traceability_gate
    from evidence_coverage.grid import generate_cells
    from evidence_coverage.status import (
        gap_report,
        invalidate_mass_shift,
        list_cells_with_status,
        run_coverage_sweep,
        set_cell_status,
    )
    from evidence_eval.agent_live_bench import compare_baseline_vs_evidence_layer
    from evidence_eval.detect import assess
    from evidence_eval.faults import clean_artifact, inject
    from evidence_eval.redteam import run_redteam_suite
    from evidence_ingest.blocks import IngestAbstain
    from evidence_ingest.router import ingest_bytes
    from evidence_kernel.__main__ import verify_zip_bundle
    from evidence_kernel.edge import (
        EDGE_PRESETS,
        edge_deployment_recipe,
        preflight_edge_screening,
    )
    from evidence_kernel.envelope import make_envelope, project_source
    from evidence_kernel.formal import SMTSolverProofEngine
    from evidence_kernel.gateway import (
        BudgetedGateway,
        FixtureGateway,
        describe_agent_runtime,
        gateway_from_env,
        probe_gateway_health,
    )
    from evidence_kernel.guardrails import (
        check_output_safety,
        check_structure_safety,
        check_text_safety,
    )
    from evidence_kernel.ledger import SIGN_OFF_STATEMENT, LedgerError, verify_chain_document
    from evidence_kernel.merkle import inclusion_proof
    from evidence_kernel.orchestrator import record
    from evidence_kernel.supervisor import CaseSpec, run_case

    from evidence_api.app import (
        MAX_INGEST_BYTES,
        _bolt_inputs,
        _now,
        _validate_tenant,
        _zip_bytes,
        evidence_home,
        open_ledger,
    )

    if require_auth_for_writes and not is_authenticated:
        mutating = name in {
            "evidence_bundle_export",
            "evidence_bundle_verify",
            "evidence_verify_case",
            "evidence_ledger_signoff",
            "evidence_coverage_sweep",
            "evidence_formal_prove",
            "evidence_calc_register_plugin",
            "evidence_webhooks_register",
            "evidence_dossier_pdf_export",
        } or (
            name in {"evidence_calc_run", "evidence_ingest_document"}
            and bool(arguments.get("record"))
        )
        if mutating:
            return True, {
                "error": "auth_required",
                "message": "HTTP write operation requires login",
            }

    if name == "evidence_calc_list":
        cards = _all_calc_cards()
        return False, {"count": len(cards), "methods": cards}

    if name == "evidence_calc_run":
        method_id = str(arguments.get("method_id") or "")
        inputs = dict(arguments.get("inputs") or {})
        normalize_units = bool(arguments.get("normalize_units", False))
        include_intervals = bool(arguments.get("include_intervals", True))
        try:
            ran = run_method(
                method_id,
                inputs,
                normalize_units=normalize_units,
                include_intervals=include_intervals,
            )
        except AbstainError as exc:
            return False, {"confidence": "abstain", "abstain_reason": exc.reason}

        result_payload: dict[str, Any] = {
            "confidence": "deterministic",
            "method_version": ran["method_version"],
            "outputs": ran["outputs"],
        }
        if include_intervals and ran.get("exact_intervals"):
            result_payload["exact_intervals"] = ran["exact_intervals"]
        if normalize_units and ran.get("unit_conversions"):
            result_payload["unit_conversions"] = ran["unit_conversions"]
        if arguments.get("stated_outputs") is not None:
            raw_stated = arguments["stated_outputs"]
            if not isinstance(raw_stated, dict):
                return True, {"error": "invalid_stated_outputs"}
            stated = dict(raw_stated)
            effective_inputs = ran.get("normalized_inputs", inputs)
            result_payload["fault_kind"] = classify_numeric_delta(
                method_id,
                effective_inputs,
                stated,
                ran["outputs"],
            )
            result_payload["delta_vs_stated"] = {
                key: {
                    "stated": str(val),
                    "recomputed": str(ran["outputs"].get(key, "")),
                    "match": key in ran["outputs"] and str(val) == str(ran["outputs"][key]),
                }
                for key, val in stated.items()
            }
        if arguments.get("formal_proof"):
            result_payload["formal_proof"] = run_formal_proof_for_method(
                method_id,
                inputs,
                arguments.get("formal_bounds"),
            )
        if arguments.get("record"):
            tenant_id = _validate_tenant(arguments.get("tenant_id"))
            if tenant_id is None:
                return True, {"error": "invalid_tenant"}
            ledger = open_ledger(tenant_id)
            actor_id = str(arguments.get("actor_id") or "author")
            env = make_envelope(
                sources=ran["sources"],
                method_version=ran["method_version"],
                inputs=ran.get("normalized_inputs", inputs),
                confidence="deterministic",
                result=ran["outputs"],
            )
            ev_hash = record(
                ledger,
                {
                    "event_type": "calc",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": _now(),
                    "payload": {
                        "method_id": method_id,
                        "inputs": ran.get("normalized_inputs", inputs),
                        "outputs": ran["outputs"],
                    },
                    "envelope": env,
                },
            )
            result_payload["recorded_event_hash"] = ev_hash
        return False, result_payload

    if name == "evidence_ingest_document":
        filename = str(arguments.get("filename") or "document.txt")
        if arguments.get("content_base64") is not None:
            encoded = str(arguments["content_base64"])
            if len(encoded) > (MAX_INGEST_BYTES * 4) // 3 + 16:
                return False, {"confidence": "abstain", "abstain_reason": "payload_too_large"}
            try:
                raw = base64.b64decode(encoded, validate=True)
            except Exception:
                return True, {"error": "invalid_base64"}
        elif arguments.get("content_text") is not None:
            raw = str(arguments["content_text"]).encode("utf-8")
        else:
            return True, {"error": "missing_document_content"}

        if len(raw) > MAX_INGEST_BYTES:
            return False, {"confidence": "abstain", "abstain_reason": "payload_too_large"}
        try:
            parsed = ingest_bytes(raw, filename)
        except IngestAbstain as exc:
            return False, {"confidence": "abstain", "abstain_reason": exc.reason}

        safety = check_structure_safety(
            [str(b.get("text", "")) for b in parsed.get("blocks", [])],
            mode="input",
        )
        if safety is not None:
            return False, {"confidence": "abstain", "abstain_reason": safety}

        recorded_hashes: list[str] = []
        if arguments.get("record") and parsed.get("requirements"):
            tenant_id = _validate_tenant(arguments.get("tenant_id"))
            if tenant_id is None:
                return True, {"error": "invalid_tenant"}
            ledger = open_ledger(tenant_id)
            actor_id = str(arguments.get("actor_id") or "author")
            created_at = _now()
            for req in parsed["requirements"]:
                env = make_envelope(
                    sources=[
                        project_source("ingest", "https://aeroregu.local/ingest", "ASSUMPTION")
                    ],
                    method_version="ingest_requirements@1.0.0",
                    inputs={
                        "id": req["id"],
                        "source_file_hash": req["source_file_hash"],
                        "span_start": req["span_start"],
                    },
                    confidence="quoted",
                    result={"id": req["id"], "title_label": req["title_label"]},
                )
                recorded_hashes.append(
                    record(
                        ledger,
                        {
                            "event_type": "requirement_recorded",
                            "tenant_id": ledger.tenant_id,
                            "actor_id": actor_id,
                            "created_at": created_at,
                            "payload": req,
                            "envelope": env,
                        },
                    )
                )
        return False, {**parsed, "recorded_event_hashes": recorded_hashes}

    if name == "evidence_verify_case":
        tenant_id = _validate_tenant(arguments.get("tenant_id"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        raw_blocks = arguments.get("blocks")
        if isinstance(raw_blocks, list) and raw_blocks:
            blocks = list(raw_blocks)
        else:
            text = str(arguments.get("text") or "")
            if not text.strip():
                return False, {"confidence": "abstain", "abstain_reason": "no_text_layer"}
            blocks = [{"text": text, "span_start": 0, "span_end": len(text)}]

        ledger = open_ledger(tenant_id)
        actor_id = str(arguments.get("actor_id") or "author")
        case = CaseSpec(
            tenant_id=tenant_id,
            actor_id=actor_id,
            created_at=_now(),
            blocks=blocks,
            method_id=arguments.get("method_id"),
            calc_inputs=arguments.get("calc_inputs"),
            stated_outputs=arguments.get("stated_outputs"),
            use_decision_gate=bool(arguments.get("use_decision_gate", False)),
            formal_verification=bool(arguments.get("formal_verification", False)),
            record_requirements=bool(arguments.get("record_requirements", True)),
            compact_for_edge=bool(arguments.get("compact_for_edge", False)),
            edge_preset=str(arguments.get("edge_preset") or "laptop-cpu-16gb"),
        )
        gw = gateway_from_env(
            "happy",
            constrained=True,
            runtime_mode=str(arguments.get("runtime_mode") or "auto"),
            model=arguments.get("model"),
            edge_model=arguments.get("edge_model"),
            edge_preset=case.edge_preset,
        )
        outcome = run_case(ledger, gw, case)
        return False, {
            "envelope": outcome.envelope,
            "citations": outcome.citations,
            "paragraph": outcome.paragraph,
            "fault_kind": outcome.fault_kind,
            "formal_proof": outcome.formal_proof,
            "event_hashes": outcome.event_hashes,
            "agent_telemetry": outcome.agent_telemetry,
        }

    if name == "evidence_ledger_query":
        tenant_id = _validate_tenant(arguments.get("tenant_id"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        action = str(arguments.get("action") or "summary")
        ledger = open_ledger(tenant_id)
        if action in {"summary", "pilot_metrics"}:
            return False, _ledger_summary(tenant_id)
        events = ledger.events()
        if action == "events":
            limit = max(1, min(int(arguments.get("limit") or 20), 200))
            tail = [
                {
                    "event_hash": ev["event_hash"],
                    "prev_hash": ev["prev_hash"],
                    "event_type": ev["body"]["event_type"],
                    "actor_id": ev["body"]["actor_id"],
                    "created_at": ev["body"]["created_at"],
                    "confidence": ev["body"]["envelope"]["confidence"],
                }
                for ev in events[-limit:]
            ]
            return False, {
                "tenant_id": tenant_id,
                "total_events": len(events),
                "events": tail,
            }
        if action == "merkle_proof":
            ev_hash = str(arguments.get("event_hash") or ledger.head_hash())
            hashes = [str(ev["event_hash"]) for ev in events]
            try:
                proof = inclusion_proof(hashes, ev_hash)
            except ValueError as exc:
                return True, {"error": str(exc)}
            return False, proof
        return True, {"error": f"unsupported action: {action}"}

    if name == "evidence_bundle_export":
        tenant_id = _validate_tenant(arguments.get("tenant_id"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        raw_out = str(arguments.get("output_path") or "").strip()
        if not raw_out:
            return True, {"error": "missing_output_path"}
        exports_root = (evidence_home() / "exports").resolve()
        out_path = _confine_path(raw_out, allowed_roots=(exports_root,), default_dir=exports_root)
        if out_path is None:
            return True, {"error": "path_outside_allowed_root", "allowed_root": str(exports_root)}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ledger = open_ledger(tenant_id)
        blob = _zip_bytes(ledger.events())
        out_path.write_bytes(blob)
        ok, report = verify_zip_bundle(out_path)
        return not ok, {"output_path": str(out_path), "bytes": len(blob), "verified": ok, **report}

    if name == "evidence_bundle_verify":
        raw_bundle = str(arguments.get("bundle_path") or "").strip()
        if not raw_bundle:
            return True, {"error": "missing_bundle_path"}
        home_root = evidence_home().resolve()
        exports_root = (home_root / "exports").resolve()
        keys_root = (home_root / ".keys").resolve()
        target = _confine_path(raw_bundle, allowed_roots=(exports_root,), default_dir=exports_root)
        if target is None:
            return True, {
                "error": "path_outside_allowed_root",
                "allowed_root": str(exports_root),
            }
        if not target.is_file():
            return True, {"error": "file_not_found", "path": str(target)}
        if target.stat().st_size > MAX_BUNDLE_VERIFY_BYTES:
            return True, {"error": "bundle_too_large"}
        if target.suffix.lower() == ".zip":
            pub_pem = None
            if arguments.get("public_key_path"):
                key_path = _confine_path(
                    str(arguments["public_key_path"]),
                    allowed_roots=(keys_root,),
                    default_dir=keys_root,
                )
                if key_path is None:
                    return True, {
                        "error": "path_outside_allowed_root",
                        "allowed_root": str(keys_root),
                    }
                if key_path.name.endswith(".key.pem") or not key_path.name.endswith(".pem"):
                    return True, {"error": "invalid_public_key_path"}
                if not key_path.is_file():
                    return True, {"error": "public_key_not_found", "path": str(key_path)}
                if key_path.stat().st_size > 1024 * 64:
                    return True, {"error": "public_key_too_large"}
                pub_pem = key_path.read_bytes()
                if b"PRIVATE KEY" in pub_pem:
                    return True, {"error": "invalid_public_key_contents"}
            ok, report = verify_zip_bundle(target, public_key_pem=pub_pem)
            return not ok, report
        try:
            doc = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return True, {"error": "invalid_chain_json", "bundle": str(target)}
        ok = isinstance(doc, list) and verify_chain_document(doc)
        return not ok, {
            "bundle": str(target),
            "chain_ok": ok,
            "event_count": len(doc) if isinstance(doc, list) else 0,
        }

    if name == "evidence_safety_scan":
        text = str(arguments.get("text") or "")
        mode = str(arguments.get("mode") or "both")
        input_reason = check_text_safety(text) if mode in {"both", "input"} else None
        output_reason = check_output_safety(text) if mode in {"both", "output"} else None
        blocked = input_reason is not None or output_reason is not None
        return False, {
            "safe": not blocked,
            "input_reason": input_reason,
            "output_reason": output_reason,
        }

    if name == "evidence_redteam_benchmark":
        return False, run_redteam_suite()

    if name == "evidence_coverage_status":
        tenant_id = _validate_tenant(arguments.get("tenant_id"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        events = ledger.events()
        action = str(arguments.get("action") or "summary")
        if action == "summary":
            return False, {
                "tenant_id": tenant_id,
                "gaps": gap_report(events),
                "gate": evaluate_traceability_gate(
                    events,
                    chain_verified=ledger.verify(),
                    require_head_signoff=bool(arguments.get("require_signoff")),
                ),
            }
        if action == "cells":
            rows = list_cells_with_status(
                events,
                status_filter=arguments.get("status") or None,
                stale_only=bool(arguments.get("stale_only")),
            )
            limit = max(1, min(int(arguments.get("limit") or 50), 200))
            offset = max(0, int(arguments.get("offset") or 0))
            return False, {
                "tenant_id": tenant_id,
                "total": len(rows),
                "limit": limit,
                "offset": offset,
                "cells": rows[offset : offset + limit],
            }
        if action == "gate":
            return False, evaluate_traceability_gate(
                events,
                chain_verified=ledger.verify(),
                require_head_signoff=bool(arguments.get("require_signoff")),
            )
        return True, {"error": f"unsupported coverage action: {action}"}

    if name == "evidence_coverage_sweep":
        tenant_id = _validate_tenant(arguments.get("tenant_id"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        actor_id = str(arguments.get("actor_id") or "author")
        created_at = _now()
        ledger = open_ledger(tenant_id)
        action = str(arguments.get("action") or "sweep")
        if action == "sweep":
            summary = run_coverage_sweep(
                ledger,
                actor_id=actor_id,
                created_at=created_at,
                target_status=str(arguments.get("target_status") or "gap"),
                stale_only=bool(arguments.get("stale_only")),
                limit=max(1, min(int(arguments.get("limit") or 15), 200)),
            )
            return False, {**summary, "merkle_root": ledger.merkle_root()}
        if action == "mass_shift":
            records = active_calc_records(ledger.events())
            inv_hashes = invalidate_mass_shift(
                ledger, records, actor_id=actor_id, created_at=created_at
            )
            dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
            return False, {
                "invalidated_cells": [row["cell_id"] for row in records],
                "invalidated_event_hashes": inv_hashes,
                "delta_reverification_manifest": dossier["delta_reverification_manifest"],
                "dossier_hash": dossier["dossier_hash"],
            }
        if action == "set_cell_status":
            cell_id = str(arguments.get("cell_id") or "")
            status = str(arguments.get("cell_status") or "")
            if status not in {"not_in_envelope", "justified_not_critical", "gap"}:
                return True, {"error": "invalid_status"}
            cell = next((item for item in generate_cells() if item.cell_id == cell_id), None)
            if cell is None:
                return True, {"error": "unknown_cell", "cell_id": cell_id}
            ev_hash = set_cell_status(
                ledger,
                cell=cell,
                status=status,
                actor_id=actor_id,
                actor_role="human",
                created_at=created_at,
                evidence_event_hash=str(arguments.get("evidence_event_hash") or ""),
            )
            return False, {"event_hash": ev_hash, "cell_id": cell_id, "status": status}
        return True, {"error": f"unsupported sweep action: {action}"}

    if name == "evidence_dossier_export":
        tenant_id = _validate_tenant(arguments.get("tenant_id"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        fmt = str(arguments.get("format") or "summary")
        ledger = open_ledger(tenant_id)
        dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
        if fmt == "summary":
            return False, dossier
        if fmt == "strictdoc":
            return False, {"format": "strictdoc", "content": export_strictdoc(dossier)}
        if fmt == "oscal":
            return False, export_oscal_sar(dossier)
        return True, {"error": f"unsupported dossier format: {fmt}"}

    if name == "evidence_formal_prove":
        kind = str(arguments.get("kind") or "flight_envelope")
        bounds = dict(arguments.get("bounds") or {})
        if kind == "flight_envelope":
            return False, prove_continuous_flight_envelope(
                mass_range_kg=_pair_bounds(bounds.get("mass_kg"), ("800.000", "1200.000")),
                cg_range_m=_pair_bounds(bounds.get("cg_x_m"), ("-0.200", "0.200")),
                load_factor_range=_pair_bounds(bounds.get("load_factor"), ("-1.000", "2.500")),
                station_positions_m=arguments.get("stations_m"),
                max_station_thrust_n=str(arguments.get("max_station_thrust_n") or "15000.000"),
            )
        engine = SMTSolverProofEngine()
        if kind == "structural_margin":
            allowables = dict(
                arguments.get("allowables")
                or {"shear_allowable_mpa": "150.000", "tensile_allowable_mpa": "250.000"}
            )
            res = engine.prove_structural_margin(
                bounds={
                    "area_mm2": _pair_bounds(bounds.get("area_mm2"), ("100.000", "120.000")),
                    "shear_force_n": _pair_bounds(
                        bounds.get("shear_force_n"), ("1000.000", "2000.000")
                    ),
                    "tensile_force_n": _pair_bounds(
                        bounds.get("tensile_force_n"), ("2000.000", "3000.000")
                    ),
                },
                allowables={k: str(v) for k, v in allowables.items()},
                safety_factor=str(arguments.get("safety_factor") or "1.500"),
            )
            return False, res.to_dict()
        if kind == "hover_power":
            res = engine.prove_hover_power_envelope(
                thrust_bounds_n=_pair_bounds(bounds.get("thrust_n"), ("2000.000", "10500.000")),
                disk_area_m2=str(arguments.get("disk_area_m2") or "10.000"),
                air_density_kg_m3=str(arguments.get("air_density_kg_m3") or "1.225"),
                figure_of_merit=str(arguments.get("figure_of_merit") or "0.700"),
                max_power_available_kw=str(arguments.get("max_power_available_kw") or "350.000"),
            )
            return False, res.to_dict()
        return True, {"error": f"unsupported formal proof kind: {kind}"}

    if name == "evidence_agents_runtime":
        action = str(arguments.get("action") or "status")
        if action == "status":
            return False, {
                **describe_agent_runtime(),
                "edge_presets": EDGE_PRESETS,
                "edge_recipes": {
                    "ollama": edge_deployment_recipe(runtime_kind="ollama"),
                    "llamacpp": edge_deployment_recipe(runtime_kind="llamacpp"),
                },
            }
        if action == "probe":
            target = str(arguments.get("target") or "all")
            timeout_s = max(0.5, min(float(arguments.get("timeout_s") or 3.0), 10.0))
            return False, probe_gateway_health(target=target, timeout_s=timeout_s)
        if action == "edge_preflight":
            preset_id = str(arguments.get("edge_preset") or "laptop-cpu-16gb")
            raw_blocks = arguments.get("blocks")
            if isinstance(raw_blocks, list) and raw_blocks:
                blocks = list(raw_blocks)
            else:
                text = str(arguments.get("text") or "")
                if not text.strip():
                    return True, {"error": "empty_document"}
                blocks = [
                    {"text": line, "span_start": 0, "span_end": len(line)}
                    for line in text.splitlines()
                    if line.strip()
                ]
            return False, preflight_edge_screening(blocks, preset_id=preset_id)
        return True, {"error": f"unsupported agents action: {action}"}

    if name == "evidence_ledger_signoff":
        tenant_id = _validate_tenant(arguments.get("tenant_id"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        target = str(arguments.get("target_event_hash") or ledger.head_hash())
        known_hashes = {str(ev["event_hash"]) for ev in ledger.events()}
        if target not in known_hashes:
            return True, {"error": "target_event_not_found", "target_event_hash": target}
        actor_id = str(arguments.get("actor_id") or "reviewer")
        statement = str(arguments.get("statement") or SIGN_OFF_STATEMENT)
        duration_ms = arguments.get("review_duration_ms")
        payload: dict[str, Any] = {
            "actor_id": actor_id,
            "target_event_hash": target,
            "statement": statement,
        }
        if duration_ms is not None:
            payload["review_duration_ms"] = int(duration_ms)
        env = make_envelope(
            sources=[
                project_source("human-review", "https://aeroregu.local/signoff", "ASSUMPTION")
            ],
            method_version="human_signoff@1.0.0",
            inputs={"target_event_hash": target, "statement": statement},
            confidence="deterministic",
            result=payload,
        )
        try:
            ev_hash = record(
                ledger,
                {
                    "event_type": "human_signoff",
                    "tenant_id": ledger.tenant_id,
                    "actor_id": actor_id,
                    "created_at": _now(),
                    "payload": payload,
                    "envelope": env,
                },
            )
        except LedgerError as exc:
            return True, {"error": str(exc)}
        return False, {
            "event_hash": ev_hash,
            "target_event_hash": target,
            "merkle_root": ledger.merkle_root(),
        }

    if name == "evidence_notes_check":
        example = arguments.get("example")
        if example == "unit_scale":
            artifact = inject("unit_scale", clean_artifact("bolt_screen", _bolt_inputs("3.000")), 0)
        elif example == "missing_input":
            artifact = inject(
                "missing_input", clean_artifact("bolt_screen", _bolt_inputs("3000.000")), 0
            )
            artifact["inputs"].pop("area_mm2", None)
        elif isinstance(arguments.get("artifact"), dict):
            artifact = dict(arguments["artifact"])
        else:
            return True, {"error": "provide example or artifact"}
        return False, assess(artifact)["envelope"]

    if name == "evidence_bench_compare":
        return False, compare_baseline_vs_evidence_layer(
            lambda: BudgetedGateway(FixtureGateway("happy"), max_turns=5),
            is_live=False,
        )

    if name == "evidence_cad_cae_ingest":
        filename = str(arguments.get("filename") or "model.stp")
        if arguments.get("content_base64") is not None:
            try:
                raw = base64.b64decode(str(arguments["content_base64"]), validate=True)
            except Exception:
                return True, {"error": "invalid_base64"}
        elif arguments.get("content_text") is not None:
            raw = str(arguments["content_text"]).encode("utf-8")
        else:
            return True, {"error": "provide content_text or content_base64"}
        try:
            parsed = ingest_bytes(raw, filename)
        except IngestAbstain as exc:
            return True, {"error": exc.reason}
        cad_cae = parsed.get("cad_cae")
        if not isinstance(cad_cae, dict):
            return True, {"error": "not_cad_cae_media"}
        bindings = bind_parameters_to_cards(
            list(cad_cae.get("parameters") or []),
            formulas=list(cad_cae.get("formulas") or []),
            auto_run=bool(arguments.get("auto_run", True)),
        )
        return False, {
            "filename": parsed["filename"],
            "media_type": parsed["media_type"],
            "source_hash": parsed["source_hash"],
            "cad_cae": cad_cae,
            "bindings": bindings,
        }

    if name == "evidence_envelope_3d":
        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        payload = build_vn_cg_envelope_3d(
            ledger.events(),
            cad_cg_points=arguments.get("cad_cg_points"),
            wing_area_m2=str(arguments.get("wing_area_m2") or "12.000"),
            v_c_mps=str(arguments.get("v_c_mps") or "65.000"),
            v_d_mps=str(arguments.get("v_d_mps") or "82.000"),
            nz_max=str(arguments.get("nz_max") or "2.500"),
            nz_min=str(arguments.get("nz_min") or "-1.000"),
        )
        return False, payload

    if name == "evidence_calc_register_plugin":
        from evidence_calc.registry import register_custom_card

        card_raw = (
            arguments.get("card")
            if isinstance(arguments.get("card"), dict)
            else (arguments if isinstance(arguments, dict) and "method_id" in arguments else None)
        )
        if not isinstance(card_raw, dict):
            return True, {"error": "card object is required"}
        try:
            saved = register_custom_card(card_raw)
        except AbstainError as exc:
            return True, {"error": exc.reason}
        return False, {"card": saved, "card_sha256": saved["card_sha256"]}

    if name == "evidence_dossier_pdf_export":
        from evidence_coverage.pdf_report import build_signed_pdf_report
        from evidence_kernel.storage import open_blob_store

        from evidence_api.app import _attestation_keypair

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        events = ledger.events()
        priv_pem, pub_pem = _attestation_keypair()
        store = open_blob_store(evidence_home())
        pdf_sources: dict[str, bytes] = {}
        for ev in events:
            p = (ev.get("body") or {}).get("payload") or {}
            sh = str(p.get("source_hash") or p.get("source_file_hash") or "")
            if len(sh) == 64 and sh not in pdf_sources:
                try:
                    raw_b = store.get_blob(sh)
                    if raw_b.startswith(b"%PDF"):
                        pdf_sources[sh] = raw_b
                except Exception:
                    pass
        report = build_signed_pdf_report(
            events,
            tenant_id=tenant_id,
            chain_verified=ledger.verify(),
            private_key_pem=priv_pem,
            public_key_pem=pub_pem,
            pdf_sources=pdf_sources or None,
            enforce_distinct_reviewer=bool(arguments.get("enforce_distinct_reviewer")),
        )
        out_path_raw = arguments.get("output_path")
        saved_path = None
        if out_path_raw:
            confined = _confine_path(
                str(out_path_raw),
                allowed_roots=(repo_root(), evidence_home()),
                default_dir=evidence_home(),
            )
            if confined is None:
                return True, {"error": "output_path_outside_workspace"}
            confined.parent.mkdir(parents=True, exist_ok=True)
            confined.write_bytes(report["pdf_bytes"])
            saved_path = str(confined)
        return False, {
            "tenant_id": tenant_id,
            "pdf_sha256": report["pdf_sha256"],
            "merkle_root": report["merkle_root"],
            "qr_payload": report["qr_payload"],
            "bbox_thumbnails_count": report["bbox_thumbnails_count"],
            "gate_status": report["gate_status"],
            "output_path": saved_path,
            "pdf_base64": base64.b64encode(report["pdf_bytes"]).decode("ascii")
            if not saved_path
            else None,
        }

    if name == "evidence_webhooks_list":
        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        return False, {
            "tenant_id": tenant_id,
            "webhooks": ledger.list_webhooks(),
            "deliveries": ledger.list_webhook_deliveries(),
        }

    if name == "evidence_webhooks_register":
        from evidence_kernel.webhooks import WebhookError, new_webhook_record

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        try:
            rec = new_webhook_record(
                url=str(arguments.get("url") or ""),
                events=arguments.get("events"),
                description=str(arguments.get("description") or ""),
            )
        except WebhookError as exc:
            return True, {"error": str(exc)}
        saved = ledger.register_webhook(rec)
        return False, saved

    return True, {"error": f"unknown_tool: {name}"}


def _read_resource(uri: str) -> tuple[str, str]:
    from evidence_coverage.dossier import build_enterprise_dossier, export_oscal_sar
    from evidence_coverage.gate import evaluate_traceability_gate
    from evidence_coverage.status import gap_report
    from evidence_kernel.gateway import describe_agent_runtime

    from evidence_api.app import _attestation_keypair, _validate_tenant, open_ledger

    if uri == "aeroregu://runtime/status":
        return "application/json", json.dumps(describe_agent_runtime(), indent=2)
    if uri == "aeroregu://calc/catalog":
        return "application/json", json.dumps(_all_calc_cards(), indent=2)
    if uri == "aeroregu://attestation/public-key":
        _, pub_pem = _attestation_keypair()
        return "application/x-pem-file", pub_pem.decode("utf-8")
    if uri == "aeroregu://coverage/summary":
        ledger = open_ledger("demo")
        events = ledger.events()
        payload = {
            "tenant_id": "demo",
            "gaps": gap_report(events),
            "gate": evaluate_traceability_gate(events, chain_verified=ledger.verify()),
        }
        return "application/json", json.dumps(payload, indent=2)
    if uri == "aeroregu://dossier/oscal":
        ledger = open_ledger("demo")
        dossier = build_enterprise_dossier(ledger.events(), chain_verified=ledger.verify())
        return "application/json", json.dumps(export_oscal_sar(dossier), indent=2)
    if uri.startswith("aeroregu://ledger/") and uri.endswith("/summary"):
        tenant = uri.removeprefix("aeroregu://ledger/").removesuffix("/summary")
        checked = _validate_tenant(tenant) or "demo"
        return "application/json", json.dumps(_ledger_summary(checked), indent=2)
    raise KeyError(uri)


def _get_prompt(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    if name == "audit-cs27-cs29-requirement":
        req_id = str(args.get("requirement_id") or "CS-27.301")
        text = (
            f"Audit requirement {req_id} using Evidence Layer MCP tools:\n"
            "1. Call evidence_ingest_document to extract clause slices, page_no, and bbox.\n"
            "2. Call evidence_calc_run for all engineering formulas (never compute numbers "
            "manually).\n"
            "3. Call evidence_verify_case to verify spans, Z3+cvc5 bounds, and guardrails.\n"
            "4. Never output any physical number absent from evidence_calc_run outputs, and remind "
            "the user that this tool assists a human reviewer and does not determine compliance."
        )
        return {
            "description": f"Grounded verification workflow for {req_id}",
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }
    if name == "verify-offline-dossier":
        bundle_path = str(args.get("bundle_path") or "bundle.zip")
        text = (
            f"Verify exported audit dossier '{bundle_path}' off-line:\n"
            "1. Read resource aeroregu://attestation/public-key if comparing against server key.\n"
            "2. Call evidence_bundle_verify with bundle_path.\n"
            "3. Summarize chain_ok, merkle_ok, dsse_signature_ok, and dsse_digest_ok."
        )
        return {
            "description": "Offline DSSE Ed25519 + Merkle verification workflow",
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }
    if name == "coverage-envelope-sweep":
        tenant_id = str(args.get("tenant_id") or "demo")
        text = (
            f"Sweep and verify flight-envelope coverage for tenant '{tenant_id}':\n"
            "1. Call evidence_coverage_status to inspect current gaps and gate status.\n"
            "2. Call evidence_coverage_sweep (action='sweep') to compute unverified cells.\n"
            "3. Call evidence_formal_prove (kind='flight_envelope') for Z3+cvc5 bounds.\n"
            "4. Call evidence_bundle_export to seal the DSSE Ed25519 audit dossier."
        )
        return {
            "description": "Flight-envelope coverage sweep & DSSE export workflow",
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }
    if name == "redteam-security-audit":
        text = (
            "Audit Evidence Layer security posture:\n"
            "1. Call evidence_redteam_benchmark to run the 46-probe adversarial suite.\n"
            "2. Call evidence_notes_check with example='unit_scale' and 'missing_input'.\n"
            "3. Verify block_rate >= 0.95 and secret_pii_leaked == 0."
        )
        return {
            "description": "Red-Team & numeric fault sentinel verification workflow",
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
        }
    raise KeyError(name)


def handle_mcp_message(
    message: Any,
    *,
    require_auth_for_writes: bool = False,
    is_authenticated: bool = True,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Dispatch an MCP JSON-RPC 2.0 request, batch, or notification."""
    if isinstance(message, list):
        replies = [
            reply
            for item in message
            if (
                reply := handle_mcp_message(
                    item,
                    require_auth_for_writes=require_auth_for_writes,
                    is_authenticated=is_authenticated,
                )
            )
            is not None
        ]
        return replies or None

    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": message.get("id") if isinstance(message, dict) else None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    req_id = message.get("id")
    method = str(message.get("method") or "")
    params = message.get("params") or {}

    # Notifications (no id) produce no JSON-RPC response per MCP spec.
    if req_id is None and method.startswith("notifications/"):
        return None

    def _ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _err(code: int, msg: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}

    if method == "initialize":
        req_proto = str(params.get("protocolVersion") or SUPPORTED_PROTOCOL_VERSIONS[0])
        proto = (
            req_proto
            if req_proto in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return _ok(
            {
                "protocolVersion": proto,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": SERVER_INFO,
            }
        )
    if method == "ping":
        return _ok({})
    if method == "tools/list":
        return _ok({"tools": list(MCP_TOOLS)})
    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        if not tool_name:
            return _err(-32602, "Missing tool name")
        args = dict(params.get("arguments") or {})
        try:
            is_err, payload = _call_tool(
                tool_name,
                args,
                require_auth_for_writes=require_auth_for_writes,
                is_authenticated=is_authenticated,
            )
        except Exception as exc:
            return _ok(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": f"{type(exc).__name__}: {exc}"}),
                        }
                    ],
                    "isError": True,
                }
            )
        return _ok(
            {
                "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                "structuredContent": payload,
                "isError": is_err,
            }
        )
    if method == "resources/list":
        return _ok({"resources": list(MCP_RESOURCES)})
    if method == "resources/read":
        uri = str(params.get("uri") or "")
        try:
            mime_type, body = _read_resource(uri)
        except KeyError:
            return _err(-32002, f"Resource not found: {uri}")
        return _ok({"contents": [{"uri": uri, "mimeType": mime_type, "text": body}]})
    if method == "prompts/list":
        return _ok({"prompts": list(MCP_PROMPTS)})
    if method == "prompts/get":
        p_name = str(params.get("name") or "")
        try:
            prompt_data = _get_prompt(p_name, params.get("arguments"))
        except KeyError:
            return _err(-32602, f"Unknown prompt: {p_name}")
        return _ok(prompt_data)

    if req_id is None:
        return None
    return _err(-32601, f"Method not found: {method}")


def build_mcp_client_config(
    client: str = "generic",
    *,
    repo_path: Path | None = None,
    server_url: str | None = None,
) -> dict[str, Any]:
    """Generate ready-to-paste MCP client configuration snippets."""
    root = (repo_path or repo_root()).resolve()
    python_exe = sys.executable
    stdio_entry: dict[str, Any] = {
        "command": python_exe,
        "args": ["-m", "evidence_api.mcp_server"],
        "env": {
            "EVIDENCE_HOME": str(root / "data"),
            "EVIDENCE_GATEWAY": os.environ.get("EVIDENCE_GATEWAY", "auto"),
        },
    }
    if server_url:
        http_entry = {"url": server_url.rstrip("/") + "/mcp"}
        server_cfg = http_entry
    else:
        server_cfg = stdio_entry

    if client in {"claude", "antigravity"}:
        return {"mcpServers": {"aeroregu": server_cfg}}
    if client == "cursor":
        return {"mcpServers": {"aeroregu": server_cfg}}
    if client == "vscode":
        if server_url:
            return {"servers": {"aeroregu": {"type": "http", "url": server_cfg["url"]}}}
        return {
            "servers": {
                "aeroregu": {
                    "type": "stdio",
                    "command": python_exe,
                    "args": ["-m", "evidence_api.mcp_server"],
                    "env": stdio_entry["env"],
                }
            }
        }
    return {"mcpServers": {"aeroregu": server_cfg}}


def serve_stdio() -> int:
    """Run the newline-delimited JSON-RPC 2.0 MCP server over stdin/stdout."""
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            err_reply = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            sys.stdout.write(json.dumps(err_reply) + "\n")
            sys.stdout.flush()
            continue

        reply = handle_mcp_message(msg, require_auth_for_writes=False, is_authenticated=True)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


def main() -> None:
    raise SystemExit(serve_stdio())


if __name__ == "__main__":
    main()
