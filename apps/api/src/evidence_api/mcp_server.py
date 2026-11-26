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
    inputs: dict[str, Any] | None = None,
    formal_bounds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run dual Z3+cvc5 formal proof matching any catalog method, plugin card, and bounds."""
    from evidence_api.formal_methods import (
        run_formal_proof_for_method as _dispatch_formal_proof,
    )

    return _dispatch_formal_proof(method_id, inputs or {}, formal_bounds=formal_bounds)


def get_mcp_inventory_counts(*, profile: str = "full") -> dict[str, int]:
    """Return live counts of exposed MCP tools, resources, prompts, and formal methods."""
    from evidence_api.formal_methods import METHOD_DEFAULT_INPUTS

    tools = _select_tools_for_profile(profile)
    return {
        "tools": len(tools),
        "full_tools": len(MCP_TOOLS),
        "compact_tools": len(MCP_COMPACT_TOOLS),
        "resources": len(MCP_RESOURCES),
        "prompts": len(MCP_PROMPTS),
        "formal_methods": len(METHOD_DEFAULT_INPUTS),
    }


def _select_tools_for_profile(profile: str | None = None) -> tuple[dict[str, Any], ...]:
    eff = (profile or os.environ.get("EVIDENCE_MCP_PROFILE") or "full").strip().lower()
    if eff == "compact":
        return MCP_COMPACT_TOOLS
    return MCP_TOOLS


def get_mcp_catalog(*, profile: str = "full") -> dict[str, Any]:
    """Return the live MCP catalog alongside certified method defaults and families."""
    from evidence_api.formal_methods import METHOD_DEFAULT_INPUTS, METHOD_FAMILIES

    eff = (profile or os.environ.get("EVIDENCE_MCP_PROFILE") or "full").strip().lower()
    selected = _select_tools_for_profile(eff)
    return {
        "server": SERVER_INFO,
        "profile": eff if eff == "compact" else "full",
        "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "counts": get_mcp_inventory_counts(profile=eff),
        "tools": [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            for t in selected
        ],
        "resources": list(MCP_RESOURCES),
        "prompts": list(MCP_PROMPTS),
        "method_families": dict(METHOD_FAMILIES),
        "method_default_inputs": dict(METHOD_DEFAULT_INPUTS),
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
            "interval bounds: flight_envelope, structural_margin, hover_power, or any certified "
            "method/plugin ID (kind='method' with method_id)."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {
                    "type": "string",
                    "description": (
                        "Proof kind: flight_envelope, structural_margin, hover_power, method, "
                        "or a direct calculation method_id."
                    ),
                    "default": "flight_envelope",
                },
                "method_id": {"type": "string"},
                "inputs": {"type": "object"},
                "formal_bounds": {"type": "object"},
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
    {
        "name": "evidence_cross_artifact_audit",
        "description": (
            "Cross-check Requirements, CAD, FEM (.bdf/.inp/.f06), and Report PDF/DOCX "
            "for mass, CG, and load-reaction mismatches."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "use_showcase": {"type": "boolean", "default": False},
                "requirements": {"type": "object"},
                "cad": {"type": "object"},
                "fem": {"type": "object"},
                "fem_f06": {"type": "object"},
                "report": {"type": "object"},
            },
        },
    },
    {
        "name": "evidence_nafems_audit",
        "description": (
            "Run NAFEMS V&V manifest, BDF-vs-Report table property drift, regulatory SUBCASE "
            "completeness, and SOL 103 rotor harmonic separation audit."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "bdf_text": {"type": "string"},
                "f06_text": {"type": "string"},
                "unit_system": {"type": "string"},
                "require_unit_system": {"type": "boolean", "default": False},
                "report_blocks": {"type": "array"},
                "report_claims": {"type": "object"},
                "required_load_families": {"type": "array"},
                "rotor_rpm": {"type": "string"},
                "blade_count": {"type": "integer", "default": 4},
                "guard_band_pct": {"type": "string", "default": "10.0"},
                "min_effective_mass_frac": {"type": "string", "default": "0"},
            },
            "required": ["bdf_text"],
        },
    },
    {
        "name": "evidence_nafems_bdf_diff",
        "description": (
            "Diff two Nastran BDF revisions (PSHELL/PCOMP/SUBCASE/CONM2) and invalidate affected "
            "Ledger cells."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "rev_a_bdf_text": {"type": "string"},
                "rev_b_bdf_text": {"type": "string"},
                "invalidate_cells": {"type": "boolean", "default": True},
            },
            "required": ["rev_a_bdf_text", "rev_b_bdf_text"],
        },
    },
    {
        "name": "evidence_adversarial_fuzz",
        "description": (
            "Run envelope_critic (Z3+cvc5) and bench_attacker red-team "
            "unit/sign/thermal/redundancy fuzzer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "method_ids": {"type": "array", "items": {"type": "string"}},
                "include_smt_critic": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "evidence_overnight_watch",
        "description": (
            "Trigger continuous verification cycle across persistent queue, "
            "cross-artifact auditor & red-team fuzzer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "use_showcase": {"type": "boolean", "default": True},
                "max_tokens_per_night": {"type": "integer", "default": 250000},
            },
        },
    },
    {
        "name": "evidence_morning_briefing",
        "description": (
            "Retrieve 08:00 AM risk-sorted Morning Briefing queue "
            "(MS<0, ABSTAIN, CAD<->FEM<->PDF, stale cells) & diffs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"tenant_id": {"type": "string", "default": "demo"}},
        },
    },
    {
        "name": "evidence_batch_signoff",
        "description": (
            "Execute audited batch human_signoff on reviewed briefing findings "
            "(enforcing CVE role and SoD)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["finding_ids"],
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "actor_id": {"type": "string", "default": "reviewer"},
                "actor_role": {"type": "string", "default": "cve"},
                "finding_ids": {"type": "array", "items": {"type": "string"}},
                "statement": {"type": "string"},
            },
        },
    },
    {
        "name": "evidence_observability_metrics",
        "description": (
            "Return OpenTelemetry/Prometheus runtime metrics "
            "(Z3/cvc5 p95 latency, abstain rate, edge vs cloud tokens, DLQ)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "evidence_webhooks_dlq_replay",
        "description": ("Replay dead-lettered webhook deliveries stored in the persistent DLQ."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant_id": {"type": "string", "default": "demo"},
                "delivery_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "generate_multiagent_quotation",
        "description": (
            "Run the 8-agent supervised quotation pipeline generating deterministic Decimal + Arb "
            "costing, 3-point PERT P50/P80/P90, exhaustive 7-dimension assumptions, Tornado "
            "sensitivity, and Z3 SMT formal margin proof sealed in the Ledger."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["rfq_text"],
            "properties": {
                "rfq_text": {"type": "string", "minLength": 1},
                "quotation_kind": {
                    "type": "string",
                    "enum": [
                        "hybrid_turnkey",
                        "aerospace_manufacturing",
                        "engineering_workpackage",
                    ],
                    "default": "hybrid_turnkey",
                },
                "tenant_id": {"type": "string", "default": "demo"},
                "actor_id": {"type": "string", "default": "author"},
                "currency": {"type": "string", "default": "EUR"},
                "target_margin_pct": {"type": "string", "default": "22.000"},
                "min_acceptable_margin_pct": {"type": "string", "default": "10.000"},
                "explicit_params": {"type": "object"},
                "assumption_overrides": {"type": "object"},
                "enable_formal_smt": {"type": "boolean", "default": True},
                "export_control_restricted": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "scrape_global_quotation_repos",
        "description": (
            "Scrape and compare global GitHub multi-agent RFQ/quotation repositories and "
            "commercial quoting web platforms against aeroregu across 8 capability axes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "live_network": {"type": "boolean", "default": False},
                "queries": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "generate_rotorcraft_archetype_quotation",
        "description": (
            "Generate a helicopter engineering design/stress quotation across 18 archetypes "
            "(Q-DES-01..Q-TST-02), 9 country rate profiles (EU_DEFAULT + 8 countries), "
            "6 academic costing models, 10 assumption dimensions, FLINT/Arb, and Z3 SMT proof."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["rfq_text"],
            "properties": {
                "rfq_text": {"type": "string"},
                "country_code": {"type": "string", "default": "EU_DEFAULT"},
                "archetype_id": {"type": "string"},
                "cert_basis": {"type": "string", "default": "CS-29"},
                "material_family": {"type": "string", "default": "HYBRID_AL_CFRP"},
                "cosysmo_complexity": {"type": "string", "default": "NOMINAL"},
                "idp_maturity": {"type": "string", "default": "COMPLETE"},
                "nearshore_country": {"type": "string", "default": "ES"},
                "target_margin_pct": {"type": "string", "default": "22.000"},
                "min_acceptable_margin_pct": {"type": "string", "default": "10.000"},
                "tenant_id": {"type": "string", "default": "demo"},
                "actor_id": {"type": "string", "default": "author"},
                "enable_formal_smt": {"type": "boolean", "default": True},
                "export_control_restricted": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "calibrate_and_match_historical_quotations",
        "description": (
            "Ingest 2,000+ historical rotorcraft quotations, inspect physical CAD/FEM IDP "
            "artifacts, compute Decimal + FLINT/Arb PERT calibration & 80/20 backtest MAPE, "
            "and retrieve top-k nearest past bids."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "archetype_id": {"type": "string", "default": "Q-STR-03"},
                "country_code": {"type": "string", "default": "EU_DEFAULT"},
                "cert_basis": {"type": "string", "default": "CS-29"},
                "material_family": {"type": "string", "default": "HYBRID_AL_CFRP"},
                "corpus_path": {"type": "string"},
                "records": {"type": "array", "items": {"type": "object"}},
                "synthetic_count": {"type": "integer", "default": 2160},
                "idp_attachments": {"type": "object"},
                "top_k": {"type": "integer", "default": 3},
            },
        },
    },
    {
        "name": "generate_composite_rotorcraft_quotation",
        "description": (
            "Generate a Composite Multi-Archetype WBS DAG quotation with deterministic Critical "
            "Path (CPM), engineering reuse synergy, multi-year Wright/Crawford learning curve, "
            "country inflation/cash-flow NPV, deep physical IDP inspection, contractual "
            "poison-clause audit, and formal Z3 SMT margin & NPV proofs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "rfq_text": {"type": "string"},
                "archetype_ids": {"type": "array", "items": {"type": "string"}},
                "country_code": {"type": "string", "default": "EU_DEFAULT"},
                "cert_basis": {"type": "string", "default": "CS-29"},
                "material_family": {"type": "string", "default": "HYBRID_AL_CFRP"},
                "unit_count": {"type": "integer", "default": 1},
                "program_years": {"type": "integer", "default": 3},
                "learning_rate_pct": {"type": "string", "default": "85.000"},
                "payment_terms_days": {"type": "integer", "default": 60},
                "target_margin_pct": {"type": "string", "default": "22.000"},
                "min_acceptable_margin_pct": {"type": "string", "default": "10.000"},
                "tenant_id": {"type": "string", "default": "demo"},
                "enable_formal_smt": {"type": "boolean", "default": True},
                "enforce_contract_gate": {"type": "boolean", "default": True},
                "idp_attachments": {"type": "object"},
            },
            "required": ["rfq_text"],
        },
    },
    {
        "name": "audit_rfq_contract_clauses",
        "description": (
            "Audit RFQ contractual clauses deterministically into SUPPORTED, "
            "PARTIALLY_SUPPORTED_WITH_ASSUMPTION, CHANGE_ORDER_REQUIRED, or REJECT_OR_ABSTAIN, "
            "detecting uncapped LDs, free redesign, background IP assignment, open-ended payment "
            "gates, excessive retention, and CVE waivers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "rfq_text": {"type": "string"},
                "clauses": {"type": "array", "items": {"type": "object"}},
                "filename": {"type": "string", "default": "rfq.txt"},
            },
        },
    },
    {
        "name": "inspect_deep_idp_package",
        "description": (
            "Inspect nested-INCLUDE Nastran .bdf models (DOFs, local coords, properties), binary "
            ".op2/.h5 files, .f06 audits, STEP B-Rep Buy-to-Fly & surface area, and "
            "PDF/XLSX/DOCX BOMs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "idp_attachments": {"type": "object"},
            },
        },
    },
    {
        "name": "export_quotation_oem_artifacts",
        "description": (
            "Export a live-formula 7-tab Excel (.xlsx) workbook and an Ed25519 DSSE + ISO QR "
            "signed PDF dossier for a composite rotorcraft quotation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "rfq_text": {"type": "string"},
                "archetype_ids": {"type": "array", "items": {"type": "string"}},
                "country_code": {"type": "string", "default": "EU_DEFAULT"},
                "tenant_id": {"type": "string", "default": "demo"},
                "xlsx_output_path": {"type": "string"},
                "pdf_output_path": {"type": "string"},
            },
            "required": ["rfq_text"],
        },
    },
    {
        "name": "run_advanced_quotation_calibration",
        "description": (
            "Run stratified K-fold cross-validation, IQR/MAD outlier filtering, temporal drift "
            "diagnostics, and P50..P90 Win-Rate calibration over historical quotation corpora."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "archetype_id": {"type": "string", "default": "Q-STR-03"},
                "country_code": {"type": "string", "default": "EU_DEFAULT"},
                "k_folds": {"type": "integer", "default": 5},
                "synthetic_count": {"type": "integer", "default": 2160},
                "exclude_outliers": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "compute_quotation_change_order",
        "description": (
            "Compute closed-loop Rev A -> Rev B Change-Order (CCN) delta pricing across WBS "
            "archetypes, CPM critical path, multi-year cash flow/NPV, contractual poison gates, "
            "triggered assumptions, and Z3 SMT amended margin/NPV proofs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "baseline_rfq_text": {"type": "string"},
                "baseline_archetypes": {"type": "array", "items": {"type": "string"}},
                "revised_rfq_text": {"type": "string"},
                "revised_archetypes": {"type": "array", "items": {"type": "string"}},
                "country_code": {"type": "string", "default": "EU_DEFAULT"},
                "baseline_units": {"type": "integer", "default": 1},
                "revised_units": {"type": "integer", "default": 2},
                "cr_id": {"type": "string", "default": "CCN-001"},
                "change_reason": {"type": "string", "default": "Scope change"},
                "tenant_id": {"type": "string", "default": "demo"},
            },
            "required": ["baseline_rfq_text", "revised_rfq_text"],
        },
    },
    {
        "name": "level_rotorcraft_portfolio_capacity",
        "description": (
            "Perform deterministic RCPSP capacity leveling across multiple queued helicopter "
            "RFQs and 7 Stress Office engineering roles, identifying LEAD_CVE/FDT_SPEC "
            "bottlenecks, schedule slip weeks, nearshore overflow hours, and combined peak CF."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "rfq_specs": {"type": "array", "items": {"type": "object"}},
                "team_headcount": {"type": "object"},
                "max_utilization_pct": {"type": "string", "default": "85.000"},
                "tenant_id": {"type": "string", "default": "demo"},
            },
        },
    },
    {
        "name": "evaluate_quotation_fx_hedging",
        "description": (
            "Evaluate multi-currency FX billing (EUR/USD/GBP/PLN/INR), forward hedge carry, "
            "5-point spot shock sensitivity, recommended minimum hedge ratio, and a continuous "
            "Z3 SMT proof guaranteeing hedged EUR net margin >= contractual floor."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "quoted_price_eur": {"type": "string", "default": "500000"},
                "cost_eur": {"type": "string", "default": "380000"},
                "billing_currency": {"type": "string", "default": "USD"},
                "cost_currency": {"type": "string", "default": "EUR"},
                "hedge_ratio_pct": {"type": "string", "default": "80.000"},
                "forward_carry_bps_per_year": {"type": "string", "default": "85.000"},
                "program_years": {"type": "integer", "default": 3},
                "fx_shock_band_pct": {"type": "string", "default": "10.000"},
                "cost_drift_band_pct": {"type": "string", "default": "5.000"},
                "min_acceptable_margin_pct": {"type": "string", "default": "10.000"},
            },
        },
    },
    {
        "name": "run_bid_actual_evm_postmortem",
        "description": (
            "Run closed-loop Bid-to-Actual ERP Earned Value Management (CPI/SPI/EAC/VAC/TCPI) "
            "against a baseline composite rotorcraft quotation, attribute overrun root causes "
            "to broken ROTORCRAFT_MASTER_ASSUMPTIONS, export calibration records, and seal "
            "an immutable Ledger event."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "baseline_rfq_text": {"type": "string"},
                "baseline_archetypes": {"type": "array", "items": {"type": "string"}},
                "actuals": {"type": "array", "items": {"type": "object"}},
                "actuals_csv": {"type": "string"},
                "project_id": {"type": "string", "default": "POST-001"},
                "country_code": {"type": "string", "default": "EU_DEFAULT"},
                "actual_ecn_iterations": {"type": "integer", "default": 0},
                "tenant_id": {"type": "string", "default": "demo"},
            },
        },
    },
    {
        "name": "export_evm_postmortem_oem_artifacts",
        "description": (
            "Export native live-formula Excel (.xlsx) and Ed25519 DSSE + ISO QR signed PDF "
            "files for a Bid-to-Actual EVM Post-Mortem & optional FX Hedging report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "default": "POST-001"},
                "baseline_rfq_text": {"type": "string"},
                "baseline_archetypes": {"type": "array", "items": {"type": "string"}},
                "actuals": {"type": "array", "items": {"type": "object"}},
                "billing_currency": {"type": "string", "default": "USD"},
                "hedge_ratio_pct": {"type": "string", "default": "85.000"},
                "tenant_id": {"type": "string", "default": "demo"},
                "xlsx_output_path": {"type": "string"},
                "pdf_output_path": {"type": "string"},
            },
        },
    },
    {
        "name": "audit_fem_sol105_gpforce_abaqus",
        "description": (
            "Audit Nastran .f06 SOL 105 linear buckling eigenvalues, GRID POINT FORCE BALANCE "
            "freebody equilibrium, and Abaqus .inp composite shell layups vs report claims."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "f06_text": {"type": "string"},
                "abaqus_text": {"type": "string"},
                "min_buckling_factor": {"type": "string", "default": "1.000"},
                "max_nodal_residual_n": {"type": "string", "default": "0.010"},
                "abaqus_report_claims": {"type": "object"},
            },
        },
    },
    {
        "name": "export_portfolio_capacity_oem_artifacts",
        "description": (
            "Level Stress Office RCPSP portfolio capacity across queued helicopter RFQs, "
            "optimize onshore-CVE + nearshore allocation, and export live-formula Excel (.xlsx) "
            "plus Ed25519 DSSE + ISO QR signed PDF plans."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "rfq_specs": {"type": "array", "items": {"type": "object"}},
                "team_headcount": {"type": "object"},
                "onshore_country": {"type": "string", "default": "DE"},
                "nearshore_country": {"type": "string", "default": "ES"},
                "max_utilization_pct": {"type": "string", "default": "85.000"},
                "tenant_id": {"type": "string", "default": "demo"},
                "xlsx_output_path": {"type": "string"},
                "pdf_output_path": {"type": "string"},
            },
        },
    },
    {
        "name": "run_batch_stress_summary_dossier",
        "description": (
            "Execute batch component stress checks across the 56-card catalog with 50-digit Arb "
            "intervals, MMPDS/CMH-17 material intervals, Z3 SMT formal proofs, Ledger sealing, "
            "and optional live-formula Excel (.xlsx) / DSSE signed PDF export."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dossier_id": {"type": "string", "default": "STRESS-NOTE-001"},
                "checks": {"type": "array", "items": {"type": "object"}},
                "record": {"type": "boolean", "default": True},
                "tenant_id": {"type": "string", "default": "demo"},
                "xlsx_output_path": {"type": "string"},
                "pdf_output_path": {"type": "string"},
            },
        },
    },
    {
        "name": "audit_airgap_sbom_and_cluster_readiness",
        "description": (
            "Generate a CycloneDX 1.5 SBOM from uv.lock with offline CVE checks and verify "
            "PostgreSQL 16 RLS/WORM DDL, Compose enterprise services, Helm HA/NetworkPolicy "
            "templates, and air-gapped pinned OCI digests."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "offline_cve_advisories": {"type": "object"},
                "sign_with_hsm": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "combine_structural_load_envelopes",
        "description": (
            "Run exact Decimal multi-subcase structural load-case superposition across "
            "components and MMPDS-16 / CMH-17 Arb allowables, identify governing CS-29 load "
            "combinations, and optionally export .xlsx/.pdf."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "envelope_id": {"type": "string", "default": "ENV-H145-CS29-001"},
                "basic_subcases": {"type": "object"},
                "combinations": {"type": "array", "items": {"type": "object"}},
                "component_allowables": {"type": "object"},
                "tenant_id": {"type": "string", "default": "demo"},
                "record": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "build_part21j_moc_compliance_matrix",
        "description": (
            "Build deterministic EASA Part 21J Means-of-Compliance (MoC 0..9) readiness "
            "matrix across CS-29 paragraphs with ECN staleness and negative-margin gap checks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "program_id": {"type": "string", "default": "PROG-H145-MOD"},
                "active_ecn_revision": {"type": "string", "default": "REV-A"},
                "requirements": {"type": "array", "items": {"type": "object"}},
                "stress_dossier": {"type": "object"},
                "load_envelope": {"type": "object"},
                "cve_signoffs": {"type": "object"},
                "tenant_id": {"type": "string", "default": "demo"},
                "record": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "optimize_quotation_risk_frontier",
        "description": (
            "Run deterministic Halton low-discrepancy cost risk simulation, Tornado sensitivity, "
            "Bid-Price Pareto EMV frontier optimization (ESTIMATE), and Z3 SMT margin floor proof."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_cost_eur": {"type": "string", "default": "375000"},
                "base_quote_price_eur": {"type": "string", "default": "480000"},
                "bid_prep_cost_eur": {"type": "string", "default": "25000"},
                "min_margin_floor_pct": {"type": "string", "default": "12.00"},
                "num_scenarios": {"type": "integer", "default": 500},
                "seed": {"type": "integer", "default": 20261126},
            },
        },
    },
)

MCP_COMPACT_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "aeroregu_calc_dispatch",
        "description": (
            "Domain hub for deterministic calculations & allowables: list_cards, run_method, "
            "allowables_lookup, run_batch_stress_dossier, combine_load_envelopes."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "list_cards",
                        "run_method",
                        "allowables_lookup",
                        "stress_dossier",
                        "load_envelope",
                    ],
                },
                "payload": {"type": "object"},
            },
        },
    },
    {
        "name": "aeroregu_ingest_cad_fem",
        "description": (
            "Domain hub for document/PDF/CAD/FEM ingestion: ingest_document, inspect_deep_idp, "
            "nafems_bdf_diff, audit_fem_sol105, inspect_step_cad."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "ingest_document",
                        "deep_idp",
                        "bdf_diff",
                        "fem_sol105",
                        "verify_case",
                    ],
                },
                "payload": {"type": "object"},
            },
        },
    },
    {
        "name": "aeroregu_certification_moc",
        "description": (
            "Domain hub for flight-envelope coverage, Z3/cvc5 formal proofs, "
            "and Part 21J MoC 0..9 readiness."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["coverage_status", "coverage_sweep", "formal_prove", "moc_matrix"],
                },
                "payload": {"type": "object"},
            },
        },
    },
    {
        "name": "aeroregu_quotation_commercial",
        "description": (
            "Domain hub for ESTIMATE/ASSUMPTION quotations: composite DAG, change order, "
            "FX hedging, EVM postmortem, RCPSP portfolio, calibration, and risk frontier."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "composite_quote",
                        "single_quote",
                        "multiagent_quote",
                        "change_order",
                        "fx_hedge",
                        "evm_postmortem",
                        "portfolio_level",
                        "risk_frontier",
                        "audit_contract",
                        "calibrate",
                    ],
                },
                "payload": {"type": "object"},
            },
        },
    },
    {
        "name": "aeroregu_ledger_attestation",
        "description": (
            "Domain hub for hash-chained SQLite ledger queries, human signoff, "
            "and DSSE Ed25519 ZIP/PDF bundles."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "ledger_query",
                        "bundle_export",
                        "bundle_verify",
                        "dossier_export",
                        "batch_signoff",
                    ],
                },
                "payload": {"type": "object"},
            },
        },
    },
    {
        "name": "aeroregu_security_ops",
        "description": (
            "Domain hub for safety guardrails, 46-probe Red-Team benchmark, "
            "SBOM/air-gap audit, and runtime health."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "safety_scan",
                        "redteam",
                        "airgap_sbom",
                        "agents_runtime",
                        "morning_briefing",
                    ],
                },
                "payload": {"type": "object"},
            },
        },
    },
)

_COMPACT_ACTION_MAP: dict[str, dict[str, str]] = {
    "aeroregu_calc_dispatch": {
        "list_cards": "evidence_calc_list",
        "run_method": "evidence_calc_run",
        "allowables_lookup": "evidence_calc_run",
        "stress_dossier": "run_batch_stress_summary_dossier",
        "load_envelope": "combine_structural_load_envelopes",
    },
    "aeroregu_ingest_cad_fem": {
        "ingest_document": "evidence_ingest_document",
        "deep_idp": "inspect_deep_idp_package",
        "bdf_diff": "evidence_nafems_bdf_diff",
        "fem_sol105": "audit_fem_sol105_gpforce_abaqus",
        "verify_case": "evidence_verify_case",
    },
    "aeroregu_certification_moc": {
        "coverage_status": "evidence_coverage_status",
        "coverage_sweep": "evidence_coverage_sweep",
        "formal_prove": "evidence_formal_prove",
        "moc_matrix": "build_part21j_moc_compliance_matrix",
    },
    "aeroregu_quotation_commercial": {
        "composite_quote": "generate_composite_rotorcraft_quotation",
        "single_quote": "generate_rotorcraft_archetype_quotation",
        "multiagent_quote": "generate_multiagent_quotation",
        "change_order": "compute_quotation_change_order",
        "fx_hedge": "evaluate_quotation_fx_hedging",
        "evm_postmortem": "run_bid_actual_evm_postmortem",
        "portfolio_level": "level_rotorcraft_portfolio_capacity",
        "risk_frontier": "optimize_quotation_risk_frontier",
        "audit_contract": "audit_rfq_contract_clauses",
        "calibrate": "run_advanced_quotation_calibration",
    },
    "aeroregu_ledger_attestation": {
        "ledger_query": "evidence_ledger_query",
        "bundle_export": "evidence_bundle_export",
        "bundle_verify": "evidence_bundle_verify",
        "dossier_export": "evidence_dossier_export",
        "batch_signoff": "evidence_batch_signoff",
    },
    "aeroregu_security_ops": {
        "safety_scan": "evidence_safety_scan",
        "redteam": "evidence_redteam_benchmark",
        "airgap_sbom": "audit_airgap_sbom_and_cluster_readiness",
        "agents_runtime": "evidence_agents_runtime",
        "morning_briefing": "evidence_morning_briefing",
    },
}

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

    if (
        name == "aeroregu_calc_dispatch"
        and str(arguments.get("action") or "") == "allowables_lookup"
    ):
        from evidence_calc.allowables import lookup_allowable

        inner_args = dict(arguments.get("payload") or {})
        if not inner_args:
            inner_args = {k: v for k, v in arguments.items() if k != "action"}
        return False, lookup_allowable(**inner_args)

    if name in _COMPACT_ACTION_MAP:
        action = str(arguments.get("action") or "")
        mapped = _COMPACT_ACTION_MAP[name].get(action)
        if not mapped:
            return True, {"error": f"unsupported compact action '{action}' for '{name}'"}
        inner_args = dict(arguments.get("payload") or {})
        if not inner_args:
            inner_args = {k: v for k, v in arguments.items() if k != "action"}
        return _call_tool(
            mapped,
            inner_args,
            require_auth_for_writes=require_auth_for_writes,
            is_authenticated=is_authenticated,
        )

    if require_auth_for_writes and not is_authenticated:
        mutating = (
            name
            in {
                "evidence_bundle_export",
                "evidence_bundle_verify",
                "evidence_verify_case",
                "evidence_ledger_signoff",
                "evidence_coverage_sweep",
                "evidence_formal_prove",
                "evidence_calc_register_plugin",
                "evidence_webhooks_register",
                "evidence_dossier_pdf_export",
                "evidence_cross_artifact_audit",
                "evidence_overnight_watch",
                "evidence_batch_signoff",
                "evidence_webhooks_dlq_replay",
                "generate_multiagent_quotation",
                "generate_rotorcraft_archetype_quotation",
                "generate_composite_rotorcraft_quotation",
                "compute_quotation_change_order",
                "run_bid_actual_evm_postmortem",
                "export_evm_postmortem_oem_artifacts",
                "export_portfolio_capacity_oem_artifacts",
                "run_batch_stress_summary_dossier",
            }
            or (
                name in {"evidence_calc_run", "evidence_ingest_document"}
                and bool(arguments.get("record"))
            )
            or (
                name == "evidence_nafems_bdf_diff" and bool(arguments.get("invalidate_cells", True))
            )
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
        target_method = str(arguments.get("method_id") or "")
        if kind == "method" or target_method:
            if not target_method:
                return True, {"error": "method_id is required when kind == 'method'"}
            res_dict = run_formal_proof_for_method(
                target_method,
                dict(arguments.get("inputs") or {}),
                formal_bounds=dict(arguments.get("formal_bounds") or bounds),
            )
            return res_dict.get("status") == "UNSUPPORTED_METHOD", res_dict
        if kind not in {"flight_envelope", "structural_margin", "hover_power"}:
            res_dict = run_formal_proof_for_method(
                kind,
                dict(arguments.get("inputs") or {}),
                formal_bounds=dict(arguments.get("formal_bounds") or bounds),
            )
            if res_dict.get("status") != "UNSUPPORTED_METHOD":
                return False, res_dict
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
        from evidence_coverage.collaboration_ecn import get_review_thread_store

        tenant_id = _validate_tenant(arguments.get("tenant_id"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        target = str(arguments.get("target_event_hash") or ledger.head_hash())
        known_hashes = {str(ev["event_hash"]) for ev in ledger.events()}
        if target not in known_hashes:
            return True, {"error": "target_event_not_found", "target_event_hash": target}
        review_store = get_review_thread_store()
        blocking = review_store.unresolved_blocking_threads(tenant_id, target_event_hash=target)
        if blocking:
            return True, {
                "error": "unresolved_review_threads",
                "target_event_hash": target,
                "blocking_threads": [b["thread_id"] for b in blocking],
            }
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
        locked_threads = review_store.lock_threads_on_signoff(
            tenant_id,
            target_event_hash=target,
            signoff_event_hash=ev_hash,
            signed_by=actor_id,
        )
        return False, {
            "event_hash": ev_hash,
            "target_event_hash": target,
            "merkle_root": ledger.merkle_root(),
            "locked_review_threads": [item["thread_id"] for item in locked_threads],
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
            exports_root = (evidence_home() / "exports").resolve()
            confined = _confine_path(
                str(out_path_raw),
                allowed_roots=(exports_root, evidence_home()),
                default_dir=exports_root,
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

    if name == "evidence_cross_artifact_audit":
        from evidence_coverage.cross_artifact import audit_cross_artifact_consistency
        from evidence_coverage.overnight import default_showcase_artifacts

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        src = default_showcase_artifacts() if arguments.get("use_showcase") else arguments
        res = audit_cross_artifact_consistency(
            ledger,
            requirements=src.get("requirements") or arguments.get("requirements"),
            cad=src.get("cad") or arguments.get("cad"),
            fem=src.get("fem") or arguments.get("fem"),
            fem_f06=src.get("fem_f06") or arguments.get("fem_f06"),
            report=src.get("report") or arguments.get("report"),
        )
        return False, res

    if name == "evidence_nafems_audit":
        import hashlib as _hl

        from evidence_coverage.nafems_audit import run_full_nafems_audit
        from evidence_ingest.blocks import IngestAbstain
        from evidence_ingest.fem_parsers import parse_nastran_bdf, parse_nastran_f06

        bdf_text = str(arguments.get("bdf_text") or "")
        if not bdf_text.strip():
            return True, {"error": "missing_bdf_text"}
        bdf_bytes = bdf_text.encode("utf-8")
        bdf_hash = _hl.sha256(bdf_bytes).hexdigest()
        try:
            bdf_parsed = parse_nastran_bdf(
                bdf_bytes, bdf_hash, unit_system=arguments.get("unit_system")
            )
            f06_parsed = None
            f06_hash = ""
            f06_text = str(arguments.get("f06_text") or "")
            if f06_text.strip():
                f06_bytes = f06_text.encode("utf-8")
                f06_hash = _hl.sha256(f06_bytes).hexdigest()
                f06_parsed = parse_nastran_f06(f06_bytes, f06_hash)
        except IngestAbstain as exc:
            return True, {"error": exc.reason}

        res = run_full_nafems_audit(
            bdf_parsed=bdf_parsed,
            bdf_hash=bdf_hash,
            f06_parsed=f06_parsed,
            f06_hash=f06_hash,
            report_blocks=arguments.get("report_blocks"),
            report_claims=arguments.get("report_claims"),
            required_load_families=arguments.get("required_load_families"),
            rotor_rpm=arguments.get("rotor_rpm"),
            blade_count=int(arguments.get("blade_count", 4)),
            guard_band_pct=str(arguments.get("guard_band_pct", "10.0")),
            min_effective_mass_frac=str(arguments.get("min_effective_mass_frac", "0")),
            require_unit_system=bool(arguments.get("require_unit_system", False)),
        )
        return bool(res.get("abstain")), res

    if name == "evidence_nafems_bdf_diff":
        import hashlib as _hl

        from evidence_coverage.nafems_audit import diff_bdf_revisions_and_invalidate
        from evidence_ingest.blocks import IngestAbstain
        from evidence_ingest.fem_parsers import parse_nastran_bdf

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        rev_a = str(arguments.get("rev_a_bdf_text") or "")
        rev_b = str(arguments.get("rev_b_bdf_text") or "")
        if not rev_a.strip() or not rev_b.strip():
            return True, {"error": "missing_bdf_text"}
        try:
            a_b = rev_a.encode("utf-8")
            b_b = rev_b.encode("utf-8")
            bdf_a = parse_nastran_bdf(a_b, _hl.sha256(a_b).hexdigest())
            bdf_b = parse_nastran_bdf(b_b, _hl.sha256(b_b).hexdigest())
        except IngestAbstain as exc:
            return True, {"error": exc.reason}
        ledger = open_ledger(tenant_id) if arguments.get("invalidate_cells", True) else None
        return False, diff_bdf_revisions_and_invalidate(
            rev_a_bdf=bdf_a, rev_b_bdf=bdf_b, ledger=ledger
        )

    if name == "evidence_adversarial_fuzz":
        from evidence_coverage.adversarial import run_bench_attacker, run_envelope_critic

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        qdir = evidence_home() / "tenants" / tenant_id / "quarantine"
        mids = arguments.get("method_ids")
        attacker = run_bench_attacker(
            quarantine_dir=qdir,
            method_ids=[str(m) for m in mids] if isinstance(mids, list) else None,
        )
        critic = run_envelope_critic() if arguments.get("include_smt_critic", True) else None
        return False, {"bench_attacker": attacker, "envelope_critic": critic}

    if name == "evidence_overnight_watch":
        from evidence_coverage.overnight import run_overnight_cycle
        from evidence_kernel.daemon import OvernightBudget

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        budget = OvernightBudget(
            max_tokens_per_night=int(arguments.get("max_tokens_per_night", 250_000))
        )
        summary = run_overnight_cycle(
            ledger,
            quarantine_dir=evidence_home() / "tenants" / tenant_id / "quarantine",
            budget=budget,
            use_showcase_if_empty=bool(arguments.get("use_showcase", True)),
        )
        return False, summary

    if name == "evidence_morning_briefing":
        from evidence_coverage.overnight import build_morning_briefing

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        return False, build_morning_briefing(open_ledger(tenant_id))

    if name == "evidence_batch_signoff":
        from evidence_coverage.overnight import batch_human_signoff

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        fids = [str(x) for x in (arguments.get("finding_ids") or []) if str(x).strip()]
        if not fids:
            return True, {"error": "missing_finding_ids"}
        actor_id = str(arguments.get("actor_id") or "reviewer")
        role = str(arguments.get("actor_role") or ledger.actor_role(actor_id) or "cve")
        try:
            out = batch_human_signoff(
                ledger,
                finding_ids=fids,
                actor_id=actor_id,
                actor_role=role,
                statement=str(arguments.get("statement") or SIGN_OFF_STATEMENT),
                enforce_distinct_reviewer=False,
            )
            return False, out
        except LedgerError as exc:
            return True, {"error": str(exc)}

    if name == "evidence_observability_metrics":
        from evidence_kernel.telemetry import get_telemetry

        return False, get_telemetry().snapshot()

    if name == "evidence_webhooks_dlq_replay":
        from evidence_kernel.webhooks import replay_dead_letters

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        dids = arguments.get("delivery_ids")
        res = replay_dead_letters(
            ledger,
            delivery_ids=[str(x) for x in dids] if isinstance(dids, list) else None,
        )
        return False, {"replayed_count": len(res), "results": res}

    if name == "generate_multiagent_quotation":
        from evidence_coverage.quotation_multiagent import (
            QuotationRequestSpec,
            run_multiagent_quotation,
        )

        tenant_id = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant_id)
        spec = QuotationRequestSpec(
            rfq_text=str(arguments.get("rfq_text") or ""),
            quotation_kind=str(arguments.get("quotation_kind") or "hybrid_turnkey"),  # type: ignore[arg-type]
            tenant_id=tenant_id,
            actor_id=str(arguments.get("actor_id") or "author"),
            created_at=_now(),
            currency=str(arguments.get("currency") or "EUR"),
            target_margin_pct=str(arguments.get("target_margin_pct") or "22.000"),
            min_acceptable_margin_pct=str(arguments.get("min_acceptable_margin_pct") or "10.000"),
            explicit_params=dict(arguments.get("explicit_params") or {}),
            assumption_overrides=dict(arguments.get("assumption_overrides") or {}),
            enable_formal_smt=bool(arguments.get("enable_formal_smt", True)),
            export_control_restricted=bool(arguments.get("export_control_restricted", False)),
        )
        dossier = run_multiagent_quotation(ledger, spec)
        return False, dossier.to_dict()

    if name == "scrape_global_quotation_repos":
        from evidence_coverage.repo_web_scraper import QuotationIntelligenceScraper

        live = bool(arguments.get("live_network", False))
        queries = arguments.get("queries")
        scraper = QuotationIntelligenceScraper()
        gh = scraper.scrape_github_repositories(
            queries=[str(q) for q in queries] if isinstance(queries, list) else None,
            live_network=live,
        )
        web = scraper.scrape_web_platforms(live_network=live)
        cmp = scraper.compare_against_aeroregu()
        return False, {
            "github": gh,
            "web_platforms": web,
            "comparison": cmp,
            "markdown_report": scraper.export_intelligence_report_markdown(
                github_res=gh, web_res=web, comparison=cmp
            ),
        }

    if name == "generate_rotorcraft_archetype_quotation":
        from evidence_coverage.rotorcraft_quotation_catalog import (
            RotorcraftQuotationSpec,
            run_rotorcraft_department_quotation,
        )

        tenant = _validate_tenant(arguments.get("tenant_id"))
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant)
        spec = RotorcraftQuotationSpec(
            rfq_text=str(arguments.get("rfq_text") or ""),
            country_code=str(arguments.get("country_code") or "EU_DEFAULT"),
            archetype_id=(
                str(arguments["archetype_id"]) if arguments.get("archetype_id") else None
            ),
            cert_basis=str(arguments.get("cert_basis") or "CS-29"),
            material_family=str(arguments.get("material_family") or "HYBRID_AL_CFRP"),
            cosysmo_complexity=str(arguments.get("cosysmo_complexity") or "NOMINAL"),
            idp_maturity=str(arguments.get("idp_maturity") or "COMPLETE"),
            nearshore_country=str(arguments.get("nearshore_country") or "ES"),
            target_margin_pct=str(arguments.get("target_margin_pct") or "22.000"),
            min_acceptable_margin_pct=str(arguments.get("min_acceptable_margin_pct") or "10.000"),
            tenant_id=tenant,
            actor_id=str(arguments.get("actor_id") or "author"),
            created_at=str(arguments.get("created_at") or _now()),
            enable_formal_smt=bool(arguments.get("enable_formal_smt", True)),
            export_control_restricted=bool(arguments.get("export_control_restricted", False)),
        )
        return False, run_rotorcraft_department_quotation(ledger, spec)

    if name == "calibrate_and_match_historical_quotations":
        from evidence_coverage.historical_quotation_calibrator import (
            run_historical_calibration_and_matching,
        )

        return False, run_historical_calibration_and_matching(
            archetype_id=str(arguments.get("archetype_id") or "Q-STR-03"),
            country_code=str(arguments.get("country_code") or "EU_DEFAULT"),
            cert_basis=str(arguments.get("cert_basis") or "CS-29"),
            material_family=str(arguments.get("material_family") or "HYBRID_AL_CFRP"),
            corpus_path=(str(arguments["corpus_path"]) if arguments.get("corpus_path") else None),
            records=(arguments["records"] if isinstance(arguments.get("records"), list) else None),
            synthetic_count=int(arguments.get("synthetic_count") or 2160),
            idp_attachments=arguments.get("idp_attachments"),
            top_k=int(arguments.get("top_k") or 3),
        )

    if name == "generate_composite_rotorcraft_quotation":
        from evidence_coverage.composite_dag_quotation import (
            CompositeRotorcraftQuotationSpec,
            run_composite_rotorcraft_quotation,
        )

        tenant = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant)
        raw_archs = arguments.get("archetype_ids") or ()
        spec = CompositeRotorcraftQuotationSpec(
            rfq_text=str(arguments.get("rfq_text") or ""),
            archetype_ids=tuple(str(a) for a in raw_archs if str(a).strip()),
            country_code=str(arguments.get("country_code") or "EU_DEFAULT"),
            cert_basis=str(arguments.get("cert_basis") or "CS-29"),
            material_family=str(arguments.get("material_family") or "HYBRID_AL_CFRP"),
            unit_count=int(arguments.get("unit_count") or 1),
            program_years=int(arguments.get("program_years") or 3),
            learning_rate_pct=str(arguments.get("learning_rate_pct") or "85.000"),
            payment_terms_days=(
                int(arguments["payment_terms_days"])
                if arguments.get("payment_terms_days") is not None
                else None
            ),
            target_margin_pct=str(arguments.get("target_margin_pct") or "22.000"),
            min_acceptable_margin_pct=str(arguments.get("min_acceptable_margin_pct") or "10.000"),
            tenant_id=tenant,
            created_at=str(arguments.get("created_at") or _now()),
            enable_formal_smt=bool(arguments.get("enable_formal_smt", True)),
            enforce_contract_gate=bool(arguments.get("enforce_contract_gate", True)),
            idp_attachments=dict(arguments.get("idp_attachments") or {}),
        )
        return False, run_composite_rotorcraft_quotation(ledger, spec)

    if name == "audit_rfq_contract_clauses":
        from evidence_coverage.contract_clause_auditor import audit_rfq_contract_clauses

        return False, audit_rfq_contract_clauses(
            str(arguments.get("rfq_text") or ""),
            clauses=(
                list(arguments["clauses"]) if isinstance(arguments.get("clauses"), list) else None
            ),
            filename=str(arguments.get("filename") or "rfq.txt"),
        )

    if name == "inspect_deep_idp_package":
        from evidence_coverage.deep_idp_quotation_extractor import (
            extract_deep_idp_engineering_package,
        )

        return False, extract_deep_idp_engineering_package(
            arguments.get("idp_attachments") or arguments
        )

    if name == "export_quotation_oem_artifacts":
        from evidence_coverage.composite_dag_quotation import (
            CompositeRotorcraftQuotationSpec,
            run_composite_rotorcraft_quotation,
        )
        from evidence_coverage.quotation_exporter import (
            export_quotation_signed_pdf,
            export_quotation_xlsx,
        )

        from evidence_api.app import _attestation_keypair

        tenant = _validate_tenant(arguments.get("tenant_id") or "demo")
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        raw_archs = arguments.get("archetype_ids") or ()
        spec = CompositeRotorcraftQuotationSpec(
            rfq_text=str(arguments.get("rfq_text") or ""),
            archetype_ids=tuple(str(a) for a in raw_archs if str(a).strip()),
            country_code=str(arguments.get("country_code") or "EU_DEFAULT"),
            tenant_id=tenant,
            created_at=_now(),
        )
        dossier = run_composite_rotorcraft_quotation(open_ledger(tenant), spec)
        if dossier.get("confidence") == "abstain":
            return True, {"error": dossier.get("abstain_reason") or "abstain"}
        xlsx_p = (
            _confine_path(
                str(arguments["xlsx_output_path"]),
                allowed_roots=(evidence_home(), Path.cwd()),
                default_dir=evidence_home(),
            )
            if arguments.get("xlsx_output_path")
            else None
        )
        pdf_p = (
            _confine_path(
                str(arguments["pdf_output_path"]),
                allowed_roots=(evidence_home(), Path.cwd()),
                default_dir=evidence_home(),
            )
            if arguments.get("pdf_output_path")
            else None
        )
        x_res = export_quotation_xlsx(dossier, output_path=xlsx_p)
        priv_pem, pub_pem = _attestation_keypair()
        p_res = export_quotation_signed_pdf(
            dossier, private_key_pem=priv_pem, public_key_pem=pub_pem, output_path=pdf_p
        )
        return False, {
            "rfq_id": dossier["rfq_id"],
            "xlsx_sha256": x_res["xlsx_sha256"],
            "xlsx_sheet_names": x_res["sheet_names"],
            "xlsx_formula_count": x_res["formula_count"],
            "xlsx_output_path": x_res["output_path"],
            "pdf_sha256": p_res["pdf_sha256"],
            "pdf_merkle_root": p_res["merkle_root"],
            "pdf_output_path": p_res["output_path"],
        }

    if name == "run_advanced_quotation_calibration":
        from evidence_coverage.advanced_quotation_calibration import run_advanced_calibration_suite
        from evidence_coverage.historical_quotation_calibrator import (
            generate_reference_historical_corpus,
        )

        corpus = generate_reference_historical_corpus(int(arguments.get("synthetic_count") or 2160))
        return False, run_advanced_calibration_suite(
            corpus=corpus,
            archetype_id=str(arguments.get("archetype_id") or "Q-STR-03"),
            country_code=str(arguments.get("country_code") or "EU_DEFAULT"),
            k_folds=int(arguments.get("k_folds") or 5),
            exclude_outliers=bool(arguments.get("exclude_outliers", True)),
        )

    if name == "compute_quotation_change_order":
        from evidence_coverage.composite_dag_quotation import (
            CompositeRotorcraftQuotationSpec,
            run_composite_rotorcraft_quotation,
        )
        from evidence_coverage.quotation_change_order import compute_quotation_change_order

        tenant = _validate_tenant(str(arguments.get("tenant_id") or "demo"))
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant)
        country = str(arguments.get("country_code") or "EU_DEFAULT")
        base_spec = CompositeRotorcraftQuotationSpec(
            rfq_id="MCP-REV-A",
            rfq_text=str(arguments.get("baseline_rfq_text") or ""),
            archetype_ids=tuple(
                str(a) for a in (arguments.get("baseline_archetypes") or ("Q-DES-02", "Q-STR-03"))
            ),
            country_code=country,
            unit_count=int(arguments.get("baseline_units") or 1),
            tenant_id=tenant,
        )
        baseline = run_composite_rotorcraft_quotation(ledger, base_spec)
        rev_spec = CompositeRotorcraftQuotationSpec(
            rfq_id="MCP-REV-B",
            rfq_text=str(arguments.get("revised_rfq_text") or ""),
            archetype_ids=tuple(
                str(a)
                for a in (
                    arguments.get("revised_archetypes")
                    or ("Q-DES-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02")
                )
            ),
            country_code=country,
            unit_count=int(arguments.get("revised_units") or 2),
            tenant_id=tenant,
        )
        return False, compute_quotation_change_order(
            ledger,
            baseline,
            rev_spec,
            cr_id=str(arguments.get("cr_id") or "CCN-001"),
            change_reason=str(arguments.get("change_reason") or "MCP Change Request"),
        )

    if name == "level_rotorcraft_portfolio_capacity":
        from evidence_coverage.composite_dag_quotation import (
            CompositeRotorcraftQuotationSpec,
            run_composite_rotorcraft_quotation,
        )
        from evidence_coverage.portfolio_capacity_leveler import level_portfolio_capacity

        tenant = _validate_tenant(str(arguments.get("tenant_id") or "demo"))
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant)
        specs = list(
            arguments.get("rfq_specs")
            or [
                {
                    "rfq_id": "PORT-01",
                    "rfq_text": "CS-29 frame static & FDT Net 60.",
                    "archetype_ids": ["Q-DES-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02"],
                },
                {
                    "rfq_id": "PORT-02",
                    "rfq_text": "CS-29 hoist STC & rig test Net 60.",
                    "archetype_ids": ["Q-STR-03", "Q-DOA-02", "Q-TST-01"],
                },
            ]
        )
        dossiers = []
        for idx, rs in enumerate(specs):
            d = run_composite_rotorcraft_quotation(
                ledger,
                CompositeRotorcraftQuotationSpec(
                    rfq_id=str(rs.get("rfq_id") or f"PORT-{idx + 1:02d}"),
                    rfq_text=str(rs.get("rfq_text") or "CS-29 structural analysis."),
                    archetype_ids=tuple(str(a) for a in (rs.get("archetype_ids") or ("Q-STR-03",))),
                    country_code=str(rs.get("country_code") or "ES"),
                    tenant_id=tenant,
                ),
            )
            if d.get("confidence") != "abstain":
                dossiers.append(d)
        headcount = (
            {str(k): int(v) for k, v in arguments["team_headcount"].items()}
            if isinstance(arguments.get("team_headcount"), dict)
            else None
        )
        return False, level_portfolio_capacity(
            dossiers,
            team_headcount=headcount,
            max_utilization_pct=str(arguments.get("max_utilization_pct") or "85.000"),
        )

    if name == "evaluate_quotation_fx_hedging":
        from evidence_coverage.quotation_fx_hedging import evaluate_quotation_fx_hedging

        return False, evaluate_quotation_fx_hedging(
            quoted_price_eur=arguments.get("quoted_price_eur") or "500000",
            cost_eur=arguments.get("cost_eur") or "380000",
            billing_currency=str(arguments.get("billing_currency") or "USD"),
            cost_currency=str(arguments.get("cost_currency") or "EUR"),
            hedge_ratio_pct=str(arguments.get("hedge_ratio_pct") or "80.000"),
            forward_carry_bps_per_year=str(arguments.get("forward_carry_bps_per_year") or "85.000"),
            program_years=int(arguments.get("program_years") or 3),
            fx_shock_band_pct=str(arguments.get("fx_shock_band_pct") or "10.000"),
            cost_drift_band_pct=str(arguments.get("cost_drift_band_pct") or "5.000"),
            min_acceptable_margin_pct=str(arguments.get("min_acceptable_margin_pct") or "10.000"),
        )

    if name == "run_bid_actual_evm_postmortem":
        from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
        from evidence_coverage.composite_dag_quotation import (
            CompositeRotorcraftQuotationSpec,
            run_composite_rotorcraft_quotation,
        )

        tenant = _validate_tenant(str(arguments.get("tenant_id") or "demo"))
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant)
        baseline = arguments.get("baseline_dossier")
        if not isinstance(baseline, dict) or not baseline.get("composite_wbs_dag"):
            b_archs = tuple(
                str(a)
                for a in (
                    arguments.get("baseline_archetypes") or ("Q-DES-02", "Q-STR-03", "Q-DOA-02")
                )
            )
            baseline = run_composite_rotorcraft_quotation(
                ledger,
                CompositeRotorcraftQuotationSpec(
                    rfq_id=str(arguments.get("project_id") or "POST-001"),
                    rfq_text=str(
                        arguments.get("baseline_rfq_text") or "CS-29 frame static analysis Net 60."
                    ),
                    archetype_ids=b_archs,
                    country_code=str(arguments.get("country_code") or "EU_DEFAULT"),
                    tenant_id=tenant,
                ),
            )
        return False, run_bid_actual_evm_postmortem(
            ledger,
            baseline,
            arguments.get("actuals"),
            actuals_csv=arguments.get("actuals_csv"),
            project_id=str(arguments.get("project_id") or "POST-001"),
            actual_ecn_iterations=int(arguments.get("actual_ecn_iterations") or 0),
            idp_rework_hours=str(arguments.get("idp_rework_hours") or "0"),
            unbilled_scope_hours=str(arguments.get("unbilled_scope_hours") or "0"),
            cve_rework_hours=str(arguments.get("cve_rework_hours") or "0"),
        )

    if name == "export_evm_postmortem_oem_artifacts":
        from evidence_coverage.bid_actual_postmortem import run_bid_actual_evm_postmortem
        from evidence_coverage.composite_dag_quotation import (
            CompositeRotorcraftQuotationSpec,
            run_composite_rotorcraft_quotation,
        )
        from evidence_coverage.quotation_exporter import (
            export_evm_postmortem_signed_pdf,
            export_evm_postmortem_xlsx,
        )
        from evidence_coverage.quotation_fx_hedging import evaluate_quotation_fx_hedging

        from evidence_api.app import _attestation_keypair

        tenant = _validate_tenant(str(arguments.get("tenant_id") or "demo"))
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant)
        b_archs = tuple(
            str(a)
            for a in (arguments.get("baseline_archetypes") or ("Q-DES-02", "Q-STR-03", "Q-DOA-02"))
        )
        baseline = run_composite_rotorcraft_quotation(
            ledger,
            CompositeRotorcraftQuotationSpec(
                rfq_id=str(arguments.get("project_id") or "POST-001"),
                rfq_text=str(
                    arguments.get("baseline_rfq_text") or "CS-29 frame static analysis Net 60."
                ),
                archetype_ids=b_archs,
                country_code=str(arguments.get("country_code") or "EU_DEFAULT"),
                tenant_id=tenant,
            ),
        )
        pm = run_bid_actual_evm_postmortem(
            ledger,
            baseline,
            arguments.get("actuals"),
            actuals_csv=arguments.get("actuals_csv"),
            project_id=str(arguments.get("project_id") or "POST-001"),
            actual_ecn_iterations=int(arguments.get("actual_ecn_iterations") or 0),
        )
        evm_s = pm.get("evm_summary") or {}
        fx_rep = evaluate_quotation_fx_hedging(
            quoted_price_eur=evm_s.get("quoted_selling_price_eur") or "500000",
            cost_eur=evm_s.get("bac_cost_eur") or "380000",
            billing_currency=str(arguments.get("billing_currency") or "USD"),
            hedge_ratio_pct=str(arguments.get("hedge_ratio_pct") or "85.000"),
        )
        x_res = export_evm_postmortem_xlsx(
            pm, fx_report=fx_rep, output_path=arguments.get("xlsx_output_path")
        )
        priv_pem, pub_pem = _attestation_keypair()
        p_res = export_evm_postmortem_signed_pdf(
            pm,
            fx_report=fx_rep,
            private_key_pem=priv_pem,
            public_key_pem=pub_pem,
            output_path=arguments.get("pdf_output_path"),
        )
        return False, {
            "project_id": pm["project_id"],
            "xlsx_sha256": x_res["xlsx_sha256"],
            "xlsx_sheet_names": x_res["sheet_names"],
            "xlsx_formula_count": x_res["formula_count"],
            "xlsx_output_path": x_res["output_path"],
            "pdf_sha256": p_res["pdf_sha256"],
            "merkle_root": p_res["merkle_root"],
            "pdf_output_path": p_res["output_path"],
        }

    if name == "audit_fem_sol105_gpforce_abaqus":
        import hashlib as _hs

        from evidence_coverage.nafems_audit import (
            audit_abaqus_composite_layup_vs_report,
            audit_gpforce_freebody_equilibrium,
            audit_sol105_buckling_margins,
        )
        from evidence_ingest.fem_parsers import parse_abaqus_inp, parse_nastran_f06

        f06_txt = str(arguments.get("f06_text") or "")
        abq_txt = str(arguments.get("abaqus_text") or "")
        sol105_res = None
        gpforce_res = None
        abaqus_res = None
        if f06_txt.strip():
            f06_b = f06_txt.encode("utf-8")
            f06_p = parse_nastran_f06(f06_b, _hs.sha256(f06_b).hexdigest())
            sol105_res = audit_sol105_buckling_margins(
                f06_p, min_buckling_factor=str(arguments.get("min_buckling_factor") or "1.000")
            )
            gpforce_res = audit_gpforce_freebody_equilibrium(
                f06_p, max_nodal_residual_n=str(arguments.get("max_nodal_residual_n") or "0.010")
            )
        if abq_txt.strip():
            abq_b = abq_txt.encode("utf-8")
            abq_p = parse_abaqus_inp(abq_b, _hs.sha256(abq_b).hexdigest())
            abaqus_res = audit_abaqus_composite_layup_vs_report(
                abq_p, report_claims=arguments.get("abaqus_report_claims")
            )
        return False, {
            "sol105_buckling": sol105_res,
            "gpforce_equilibrium": gpforce_res,
            "abaqus_composite_drift": abaqus_res,
        }

    if name == "export_portfolio_capacity_oem_artifacts":
        from evidence_coverage.composite_dag_quotation import (
            CompositeRotorcraftQuotationSpec,
            run_composite_rotorcraft_quotation,
        )
        from evidence_coverage.portfolio_capacity_leveler import (
            level_portfolio_capacity,
            optimize_portfolio_nearshore_allocation,
        )
        from evidence_coverage.quotation_exporter import (
            export_portfolio_capacity_signed_pdf,
            export_portfolio_capacity_xlsx,
        )

        from evidence_api.app import _attestation_keypair, _now, _validate_tenant, open_ledger

        tenant = _validate_tenant(str(arguments.get("tenant_id") or "demo"))
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant)
        now = _now()
        specs = list(
            arguments.get("rfq_specs")
            or [
                {
                    "rfq_id": "RFQ-PORT-01",
                    "rfq_text": "CS-29 frame static & F&DT Net 60.",
                    "archetype_ids": ["Q-DES-02", "Q-STR-03", "Q-FDT-01", "Q-DOA-02"],
                    "country_code": str(arguments.get("nearshore_country") or "ES"),
                },
                {
                    "rfq_id": "RFQ-PORT-02",
                    "rfq_text": "CS-29 hoist STC Net 60.",
                    "archetype_ids": ["Q-STR-03", "Q-FDT-01", "Q-DOA-02", "Q-TST-01"],
                    "country_code": str(arguments.get("nearshore_country") or "ES"),
                },
            ]
        )
        dossiers = []
        for idx, raw_s in enumerate(specs):
            spec = CompositeRotorcraftQuotationSpec(
                rfq_id=str(raw_s.get("rfq_id") or f"RFQ-PORT-{idx + 1:02d}"),
                rfq_text=str(raw_s.get("rfq_text") or "CS-29 helicopter stress package."),
                archetype_ids=tuple(raw_s.get("archetype_ids") or ("Q-STR-03", "Q-DOA-02")),
                country_code=str(raw_s.get("country_code") or "ES"),
                tenant_id=tenant,
                created_at=now,
            )
            dossiers.append(run_composite_rotorcraft_quotation(ledger, spec))
        raw_hc = arguments.get("team_headcount")
        headcount = (
            {str(k): int(v) for k, v in raw_hc.items()} if isinstance(raw_hc, dict) else None
        )
        port_res = level_portfolio_capacity(
            dossiers,
            team_headcount=headcount,
            max_utilization_pct=str(arguments.get("max_utilization_pct") or "85.000"),
        )
        ns_plan = optimize_portfolio_nearshore_allocation(
            port_res,
            onshore_country=str(arguments.get("onshore_country") or "DE"),
            nearshore_country=str(arguments.get("nearshore_country") or "ES"),
        )
        x_res = export_portfolio_capacity_xlsx(
            port_res, nearshore_plan=ns_plan, output_path=arguments.get("xlsx_output_path")
        )
        priv_pem, pub_pem = _attestation_keypair()
        p_res = export_portfolio_capacity_signed_pdf(
            port_res,
            nearshore_plan=ns_plan,
            private_key_pem=priv_pem,
            public_key_pem=pub_pem,
            output_path=arguments.get("pdf_output_path"),
        )
        return False, {
            "portfolio_rfq_count": port_res["portfolio_rfq_count"],
            "net_savings_eur": ns_plan["net_savings_eur"],
            "cve_governance_preserved": ns_plan["cve_governance_preserved"],
            "xlsx_sha256": x_res["xlsx_sha256"],
            "xlsx_sheet_names": x_res["sheet_names"],
            "xlsx_formula_count": x_res["formula_count"],
            "xlsx_output_path": x_res["output_path"],
            "pdf_sha256": p_res["pdf_sha256"],
            "merkle_root": p_res["merkle_root"],
            "pdf_output_path": p_res["output_path"],
        }

    if name == "run_batch_stress_summary_dossier":
        from evidence_coverage.stress_dossier_packager import (
            build_stress_summary_dossier,
            export_stress_dossier_signed_pdf,
            export_stress_dossier_xlsx,
        )

        from evidence_api.app import _attestation_keypair, _validate_tenant, open_ledger
        from evidence_api.formal_methods import METHOD_DEFAULT_INPUTS

        tenant = _validate_tenant(str(arguments.get("tenant_id") or "demo"))
        if tenant is None:
            return True, {"error": "invalid_tenant"}
        ledger = open_ledger(tenant) if bool(arguments.get("record", True)) else None
        checks = list(
            arguments.get("checks")
            or [
                {
                    "check_id": "SKID-01",
                    "component_name": "Skid Cross-Tube",
                    "method_id": "cs29_skid_landing_gear_drop_energy",
                    "inputs": dict(METHOD_DEFAULT_INPUTS["cs29_skid_landing_gear_drop_energy"]),
                },
                {
                    "check_id": "WHIRL-02",
                    "component_name": "Tail Rotor Drive Shaft",
                    "method_id": "shaft_whirl_critical_speed_screen",
                    "inputs": dict(METHOD_DEFAULT_INPUTS["shaft_whirl_critical_speed_screen"]),
                },
            ]
        )
        dos = build_stress_summary_dossier(
            str(arguments.get("dossier_id") or "STRESS-NOTE-001"),
            checks,
            ledger=ledger,
            tenant_id=tenant,
            include_formal_proofs=True,
        )
        out: dict[str, Any] = {
            "dossier_id": dos["dossier_id"],
            "check_count": dos["check_count"],
            "global_ms_min": dos["global_ms_min"],
            "governing_check_id": dos["governing_check_id"],
            "formal_proved_count": dos["formal_proved_count"],
            "overall_status": dos["overall_status"],
            "merkle_root": dos["merkle_root"],
        }
        if arguments.get("xlsx_output_path"):
            xr = export_stress_dossier_xlsx(dos, output_path=arguments["xlsx_output_path"])
            out["xlsx_sha256"] = xr["xlsx_sha256"]
            out["xlsx_output_path"] = xr["output_path"]
        if arguments.get("pdf_output_path"):
            priv_pem, pub_pem = _attestation_keypair()
            pr = export_stress_dossier_signed_pdf(
                dos,
                private_key_pem=priv_pem,
                public_key_pem=pub_pem,
                output_path=arguments["pdf_output_path"],
            )
            out["pdf_sha256"] = pr["pdf_sha256"]
            out["pdf_output_path"] = pr["output_path"]
        return False, out

    if name == "audit_airgap_sbom_and_cluster_readiness":
        from evidence_coverage.cluster_readiness import verify_cluster_infra_manifests
        from evidence_coverage.enterprise_kms_airgap import (
            PKCS11HSMBridge,
            generate_cyclonedx_sbom_from_uv_lock,
        )
        from evidence_kernel.paths import repo_root as _repo_root

        root = _repo_root()
        signer = PKCS11HSMBridge() if bool(arguments.get("sign_with_hsm", True)) else None
        sbom_res = generate_cyclonedx_sbom_from_uv_lock(
            root,
            offline_cve_advisories=arguments.get("offline_cve_advisories"),
            sign_backend=signer,
        )
        cluster_res = verify_cluster_infra_manifests(root)
        return False, {
            "bom_format": sbom_res["bom_format"],
            "spec_version": sbom_res["spec_version"],
            "component_count": sbom_res["component_count"],
            "cve_finding_count": sbom_res["cve_finding_count"],
            "airgap_clean": sbom_res["airgap_clean"],
            "sbom_sha256": sbom_res["sbom_sha256"],
            "dsse_signed": sbom_res["dsse_envelope"] is not None,
            "cluster_verified": cluster_res["verified"],
            "cluster_checks": cluster_res["checks"],
        }

    if name == "combine_structural_load_envelopes":
        from evidence_coverage.load_envelope_combiner import (
            combine_structural_load_envelopes,
            default_cs29_load_envelope_payload,
        )

        from evidence_api.app import _validate_tenant, open_ledger

        defaults = default_cs29_load_envelope_payload()
        tenant_id = _validate_tenant(str(arguments.get("tenant_id") or "demo"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger_obj = open_ledger(tenant_id) if bool(arguments.get("record", False)) else None
        res = combine_structural_load_envelopes(
            str(arguments.get("envelope_id") or defaults["envelope_id"]),
            arguments.get("basic_subcases") or defaults["basic_subcases"],
            arguments.get("combinations") or defaults["combinations"],
            arguments.get("component_allowables") or defaults["component_allowables"],
            ledger=ledger_obj,
            tenant_id=tenant_id,
        )
        return False, res

    if name == "build_part21j_moc_compliance_matrix":
        from evidence_coverage.certification_moc_matrix import build_part21j_moc_matrix

        from evidence_api.app import _validate_tenant, open_ledger

        tenant_id = _validate_tenant(str(arguments.get("tenant_id") or "demo"))
        if tenant_id is None:
            return True, {"error": "invalid_tenant"}
        ledger_obj = open_ledger(tenant_id) if bool(arguments.get("record", False)) else None
        res = build_part21j_moc_matrix(
            str(arguments.get("program_id") or "PROG-H145-MOD"),
            requirements=arguments.get("requirements"),
            stress_dossier=arguments.get("stress_dossier"),
            load_envelope=arguments.get("load_envelope"),
            cve_signoffs=arguments.get("cve_signoffs"),
            active_ecn_revision=str(arguments.get("active_ecn_revision") or "REV-A"),
            ledger=ledger_obj,
            tenant_id=tenant_id,
        )
        return False, res

    if name == "optimize_quotation_risk_frontier":
        from evidence_coverage.quotation_risk_frontier import run_quotation_risk_frontier

        res = run_quotation_risk_frontier(
            base_cost_eur=arguments.get("base_cost_eur", "375000"),
            base_quote_price_eur=arguments.get("base_quote_price_eur", "480000"),
            bid_prep_cost_eur=arguments.get("bid_prep_cost_eur", "25000"),
            min_margin_floor_pct=arguments.get("min_margin_floor_pct", "12.00"),
            num_scenarios=int(arguments.get("num_scenarios", 500)),
            seed=int(arguments.get("seed", 20261126)),
        )
        return False, res

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
    profile: str | None = None,
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
                    profile=profile,
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
        req_profile = params.get("profile") if isinstance(params, dict) else None
        selected = _select_tools_for_profile(
            str(req_profile) if req_profile is not None else profile
        )
        return _ok({"tools": list(selected)})
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
