"""Declarative MCP Tool, Resource, and Prompt JSON Schemas for aeroregu."""

from __future__ import annotations

from typing import Any

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
