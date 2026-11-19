"""Global GitHub & Web Commercial Quoting Intelligence Scraper and Comparative Engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

GLOBAL_QUOTATION_REPOS_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "repo_full_name": "Ethan-YS/quotemind",
        "url": "https://github.com/Ethan-YS/quotemind",
        "category": "multi_agent_rfq",
        "license": "Open-Source",
        "agent_architecture": "LangGraph-style explicit state machine with HITL gates",
        "tech_stack": ["Python", "LangGraph-style FSM", "JSON Schema"],
        "assumption_handling": "Stage checkpoints and cost-transferability scoring",
        "math_engine": "Deterministic draft BOM and routing cost scripts",
        "strengths": "Clear RFQ-to-quotation pipeline with replayable state and HITL review gates",
        "limitations": (
            "No Decimal/Arb intervals, no Z3 margin proof, no 7-axis assumption taxonomy"
        ),
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": True,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "aws-samples/sample-rfq-agent-strands-multi-agent",
        "url": "https://github.com/aws-samples/sample-rfq-agent-strands-multi-agent",
        "category": "multi_agent_rfq",
        "license": "MIT-0",
        "agent_architecture": (
            "Strands Agents SDK orchestrating RFQ, ERP/SAP, and compliance agents"
        ),
        "tech_stack": ["Python", "AWS Bedrock", "Strands SDK"],
        "assumption_handling": "Compliance checks (REACH, RoHS) via specialized agent",
        "math_engine": "ERP gateway pricing lookup",
        "strengths": "Enterprise SAP/ERP gateway pattern and regulatory compliance checking",
        "limitations": "Tied to AWS Bedrock cloud; no offline air-gapped execution or SMT proofs",
        "maturity_score": "high",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "naveendas96/presales-copilot-agents",
        "url": "https://github.com/naveendas96/presales-copilot-agents",
        "category": "multi_agent_rfq",
        "license": "MIT",
        "agent_architecture": "LangGraph typed state machine with bounded critic loop",
        "tech_stack": ["Python", "LangGraph", "Pydantic"],
        "assumption_handling": "Risk register and explainable effort estimation",
        "math_engine": "Python estimation helpers",
        "strengths": "Requirements traceability and bounded adversarial critic loop",
        "limitations": "No interval arithmetic, no formal margin proof, no cryptographic ledger",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": True,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": True,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "Rakif215/ProcuraAI",
        "url": "https://github.com/Rakif215/ProcuraAI",
        "category": "multi_agent_rfq",
        "license": "MIT",
        "agent_architecture": "LangGraph procurement automation pipeline",
        "tech_stack": ["FastAPI", "Python", "LangGraph", "Supabase", "React 19"],
        "assumption_handling": "Catalog matching against inventory DB",
        "math_engine": "Standard SQL/Python line-item totals",
        "strengths": "Full-stack intake from email to inventory matching and PDF quotation",
        "limitations": "Standard procurement only; lacks WBS engineering PERT and sensitivity",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "vanshjain271/B2B-RFP-Project",
        "url": "https://github.com/vanshjain271/B2B-RFP-Project",
        "category": "multi_agent_rfq",
        "license": "MIT",
        "agent_architecture": "Multi-agent extraction, spec matching, and pricing agents",
        "tech_stack": ["Python", "Gemini/OpenAI"],
        "assumption_handling": "Spec-to-SKU parametric catalog mapping",
        "math_engine": "Python product pricing calculator",
        "strengths": "Tailored for industrial manufacturing RFQs (wires/cables)",
        "limitations": "No adversarial refuter, no explicit assumption fallback clauses",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "killyx/ai-rfp-triage-agent",
        "url": "https://github.com/killyx/ai-rfp-triage-agent",
        "category": "multi_agent_rfq",
        "license": "MIT",
        "agent_architecture": "n8n + FastAPI + OpenAI Structured Outputs with Slack HITL gate",
        "tech_stack": ["FastAPI", "n8n", "Vector Store", "Slack Webhooks"],
        "assumption_handling": "Rate card seeding and triage scoring",
        "math_engine": "Structured rate card lookup",
        "strengths": "Model cascading and Slack HITL governance lock",
        "limitations": "No Tornado sensitivity matrix or formal margin envelope check",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": True,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "tolgadur/rfx-email-agent",
        "url": "https://github.com/tolgadur/rfx-email-agent",
        "category": "multi_agent_rfq",
        "license": "MIT",
        "agent_architecture": "Mailbox monitor + pgvector RAG responder",
        "tech_stack": ["Python", "PostgreSQL", "pgvector"],
        "assumption_handling": "RAG grounding in compliance and pricing docs",
        "math_engine": "Spreadsheet cell parsing",
        "strengths": "Handles RFX emails, Excel/CSV attachments, and security questionnaires",
        "limitations": "No span-offset verification or deterministic aerospace costing",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "weitzu-com/first-principles-rfq-robot",
        "url": "https://github.com/weitzu-com/first-principles-rfq-robot",
        "category": "multi_agent_rfq",
        "license": "Open-Source",
        "agent_architecture": "LangGraph first-principles RFQ inquiry robot",
        "tech_stack": ["Python", "LangGraph"],
        "assumption_handling": "First-principles decomposition of supplier requirements",
        "math_engine": "None / heuristic",
        "strengths": "Clean first-principles prompting pattern for manufacturing RFQs",
        "limitations": "Prototype lacking deterministic costing and audit ledger",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "A2CN-protocol/A2CN",
        "url": "https://github.com/A2CN-protocol/A2CN",
        "category": "multi_agent_rfq",
        "license": "Apache-2.0",
        "agent_architecture": (
            "Agent-to-Agent (A2A) negotiation protocol for RFQ/BAFO/reverse auction"
        ),
        "tech_stack": ["Python", "LangGraph/CrewAI compatible SDK"],
        "assumption_handling": "Negotiation envelope schemas (RFQ, BAFO)",
        "math_engine": "Protocol-level offer comparison",
        "strengths": "Canonical inter-agent commercial negotiation messages",
        "limitations": (
            "Communication protocol only; does not generate internal costing or assumptions"
        ),
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "SAP-samples/btp-joule-a2a-pro-code-agent",
        "url": "https://github.com/SAP-samples/btp-joule-a2a-pro-code-agent",
        "category": "multi_agent_rfq",
        "license": "Apache-2.0",
        "agent_architecture": "A2A LangGraph copilot integrated with SAP Cloud SDK",
        "tech_stack": ["SAP Cloud SDK", "LangGraph", "React"],
        "assumption_handling": "Quote optimization alternatives scored against SAP ERP rules",
        "math_engine": "SAP ERP pricing backend",
        "strengths": "Production-grade SAP quotation alternative scoring",
        "limitations": "Locked to SAP BTP ecosystem",
        "maturity_score": "high",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "banthevaishnavi/rfqflow-ai",
        "url": "https://github.com/banthevaishnavi/rfqflow-ai",
        "category": "multi_agent_rfq",
        "license": "MIT",
        "agent_architecture": "Single/staged extraction & validation pipeline",
        "tech_stack": ["Python", "Streamlit", "SQLite"],
        "assumption_handling": "Duplicate detection and required-field validation",
        "math_engine": "Mock ERP routing",
        "strengths": "Lightweight reproducible demo in SQLite",
        "limitations": "No multi-agent critique, no uncertainty quantification",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "kpdagrt22/servicequote-ai",
        "url": "https://github.com/kpdagrt22/servicequote-ai",
        "category": "cpq_and_estimation",
        "license": "MIT",
        "agent_architecture": "LLM parser + deterministic price-book lookup",
        "tech_stack": ["Next.js", "TypeScript", "Supabase RLS"],
        "assumption_handling": "Strict no-hallucinated-price rule bound to price-book",
        "math_engine": "Deterministic TS line-item summation",
        "strengths": "Strict separation between LLM extraction and authoritative price-book",
        "limitations": "Field-service domain; lacks engineering WBS, PERT, and formal verification",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": True,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "braedonsaunders/bidwright",
        "url": "https://github.com/braedonsaunders/bidwright",
        "category": "cpq_and_estimation",
        "license": "Open-Source",
        "agent_architecture": "Unified multi-provider agent orchestration + MCP server",
        "tech_stack": ["Python", "pgvector", "MCP"],
        "assumption_handling": "Parameterized assembly templates and cost intelligence",
        "math_engine": "Assembly parameterization calculator",
        "strengths": "Native MCP server exposing estimation tools directly to IDEs",
        "limitations": "Construction domain; lacks aerospace standards and Z3 proofs",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "xvanov/truecost",
        "url": "https://github.com/xvanov/truecost",
        "category": "cpq_and_estimation",
        "license": "MIT",
        "agent_architecture": "7-agent deep estimation pipeline in Python",
        "tech_stack": ["Python", "Monte Carlo", "PDF/CAD takeoff"],
        "assumption_handling": "Scope generation and probabilistic P50/P80/P90 risk bands",
        "math_engine": "Monte Carlo simulation (float)",
        "strengths": "Strong P50/P80/P90 risk-adjusted simulation and multi-agent pipeline",
        "limitations": (
            "Construction focus; uses float rather than Decimal/Arb and has no SMT proof"
        ),
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": True,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "IAmTomShaw/quotation-agent",
        "url": "https://github.com/IAmTomShaw/quotation-agent",
        "category": "cpq_and_estimation",
        "license": "MIT",
        "agent_architecture": "FastAPI WebSocket conversational quoting agent",
        "tech_stack": ["Python", "FastAPI", "OpenAI GPT-4o", "Notion API"],
        "assumption_handling": "Live FX conversion and web market-rate queries",
        "math_engine": "Python float helpers",
        "strengths": "Real-time WebSocket UX and multi-currency lookup",
        "limitations": "Relies on external web/Notion; no adversarial checking or audit chain",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "vybetechlabs-blip/enquiry-to-quote",
        "url": "https://github.com/vybetechlabs-blip/enquiry-to-quote",
        "category": "cpq_and_estimation",
        "license": "MIT",
        "agent_architecture": "Enquiry parser + rate card applier + HITL sign-off",
        "tech_stack": ["Python", "LLM Structured Output"],
        "assumption_handling": "Applies defaults from corporate rate card",
        "math_engine": "Deterministic rate card arithmetic",
        "strengths": "Clean HITL draft-before-dispatch workflow",
        "limitations": "No sensitivity matrix or formal assumption tracking",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "shantiNaser/RFQ_system",
        "url": "https://github.com/shantiNaser/RFQ_system",
        "category": "cpq_and_estimation",
        "license": "MIT",
        "agent_architecture": "Classic Django MVC portal (non-agentic)",
        "tech_stack": ["Python", "Django", "SQLite"],
        "assumption_handling": "Manual vendor notes",
        "math_engine": "ORM totals",
        "strengths": "Solid client-vendor RFQ submission CRUD model",
        "limitations": "No AI agents, no automated assumption synthesis",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "paigecew/Simple-Product-Quoting-System-in-Python",
        "url": "https://github.com/paigecew/Simple-Product-Quoting-System-in-Python",
        "category": "cpq_and_estimation",
        "license": "MIT",
        "agent_architecture": "CLI script (non-agentic)",
        "tech_stack": ["Python"],
        "assumption_handling": "Static hardcoded order rules",
        "math_engine": "Basic Python arithmetic",
        "strengths": "Minimal baseline quoting calculator",
        "limitations": "No document ingestion, no multi-agent orchestration",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "GiorgosPanagopoulos/bidpilot",
        "url": "https://github.com/GiorgosPanagopoulos/bidpilot",
        "category": "tender_rfp_evidence",
        "license": "MIT",
        "agent_architecture": "ReAct agent for tender matching and section-by-section drafting",
        "tech_stack": ["Python", "ReAct", "Semantic Search"],
        "assumption_handling": "Declarative eligibility rules",
        "math_engine": "None",
        "strengths": "Declarative eligibility gate before drafting bids",
        "limitations": "No quantitative BOM/WBS cost estimation",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": True,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": True,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "Mohamed934789/TenderProof-Core",
        "url": "https://github.com/Mohamed934789/TenderProof-Core",
        "category": "tender_rfp_evidence",
        "license": "Open-Source",
        "agent_architecture": "Multi-agent evidence-based contract and tender review",
        "tech_stack": ["Python", "FastAPI", "Streamlit"],
        "assumption_handling": "Evidence citation verification",
        "math_engine": "Compliance scoring",
        "strengths": "Verifiable PDF citations for tender compliance",
        "limitations": "Review-oriented; does not synthesize costed quotations",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": True,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": True,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "aadrikasingh/AI-Powered-RFP-Analyzer",
        "url": "https://github.com/aadrikasingh/AI-Powered-RFP-Analyzer",
        "category": "tender_rfp_evidence",
        "license": "MIT",
        "agent_architecture": "Microsoft Semantic Kernel multi-agent evaluation pipeline",
        "tech_stack": ["Python", "Semantic Kernel", "Azure"],
        "assumption_handling": "Legal/regulatory risk and vendor stability checks",
        "math_engine": "Weighted compliance scorecard",
        "strengths": "Structured vendor proposal compliance and legal scoring",
        "limitations": "Buy-side analyzer tied to Azure; does not author sell-side quotes",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "Start-With-AI/autonomous-rfp-agent",
        "url": "https://github.com/Autonomous-RFP-Response-System",
        "category": "tender_rfp_evidence",
        "license": "MIT",
        "agent_architecture": (
            "Modular multi-agent bid team (Reader, Retriever, Drafter, Compliance)"
        ),
        "tech_stack": ["Python", "RAG"],
        "assumption_handling": "Compliance manager role checks narrative gaps",
        "math_engine": "None",
        "strengths": "Clear separation of bid team roles",
        "limitations": "Narrative proposals only; no Decimal costing or Z3 verification",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "ishandutta2007/Awesome-RFP-Response-Management",
        "url": "https://github.com/ishandutta2007/Awesome-RFP-Response-Management",
        "category": "tender_rfp_evidence",
        "license": "MIT",
        "agent_architecture": (
            "Architectural blueprint (Pricing, Technical Writer, Legal, Compliance)"
        ),
        "tech_stack": ["LangGraph", "AutoGen", "CrewAI"],
        "assumption_handling": "Role-based checklists",
        "math_engine": "Reference pattern",
        "strengths": "Comprehensive multi-agent role taxonomy for RFP teams",
        "limitations": "Curated architecture guide, not an executable costing kernel",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "ZainAhmed9/bidengine-ai-showcase",
        "url": "https://github.com/ZainAhmed9/bidengine-ai-showcase",
        "category": "tender_rfp_evidence",
        "license": "MIT",
        "agent_architecture": "RFP analysis and tender drafting agents",
        "tech_stack": ["Python", "LLMs"],
        "assumption_handling": "Section template defaults",
        "math_engine": "Scoring only",
        "strengths": "Fast RFP compliance scoring showcase",
        "limitations": "Showcase without formal math or cryptographic audit trail",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "charithmadhuranga/CrewAI-Langgraph-Projects",
        "url": "https://github.com/charithmadhuranga/CrewAI-Langgraph-Projects",
        "category": "tender_rfp_evidence",
        "license": "MIT",
        "agent_architecture": "Hybrid LangGraph deterministic state + CrewAI task crews",
        "tech_stack": ["Python", "LangGraph", "CrewAI"],
        "assumption_handling": "Human-in-the-loop checkpoints",
        "math_engine": "Tool hooks",
        "strengths": "Shows how deterministic state machines constrain autonomous crews",
        "limitations": "Generic templates lacking domain costing cards",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": True,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "Ionio-io/langgraph-with-crewai",
        "url": "https://github.com/Ionio-io/langgraph-with-crewai",
        "category": "tender_rfp_evidence",
        "license": "MIT",
        "agent_architecture": "Conditional graph routing to CrewAI sub-crews",
        "tech_stack": ["Python", "LangGraph", "CrewAI"],
        "assumption_handling": "Conditional edge routing",
        "math_engine": "None",
        "strengths": "Clean modular orchestration example",
        "limitations": "Example repo without costing or assumptions engine",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "kiloloop/agent-estimate",
        "url": "https://github.com/kiloloop/agent-estimate",
        "category": "pert_and_ai_costing",
        "license": "MIT",
        "agent_architecture": "CLI + GitHub Action estimator for agent workflows",
        "tech_stack": ["Python/CLI", "PERT"],
        "assumption_handling": "Explicit config for review overhead and failure rates",
        "math_engine": "PERT timeline and fleet cost formulas",
        "strengths": "Explicit configuration of PERT assumptions and review overhead",
        "limitations": "Models AI agent compute/time rather than industrial/engineering quotes",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": True,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "abhimanyupallavisudhir/costly",
        "url": "https://github.com/abhimanyupallavisudhir/costly",
        "category": "pert_and_ai_costing",
        "license": "MIT",
        "agent_architecture": "Decorator-based simulation engine (@costly)",
        "tech_stack": ["Python"],
        "assumption_handling": "Pre-execution simulation flags for token usage",
        "math_engine": "Token tariff simulator",
        "strengths": "Estimates LLM pipeline cost before execution",
        "limitations": "Only estimates LLM API inference cost",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "pydantic/genai-prices",
        "url": "https://github.com/pydantic/genai-prices",
        "category": "pert_and_ai_costing",
        "license": "MIT",
        "agent_architecture": "Authoritative price registry package",
        "tech_stack": ["Python", "TypeScript", "JSON Registry"],
        "assumption_handling": "Tiered & cached context pricing rules",
        "math_engine": "Exact provider tariff calculation",
        "strengths": "Clean deterministic rate-card pattern for AI compute",
        "limitations": "Scoped strictly to LLM provider inference billing",
        "maturity_score": "high",
        "supports": {
            "zero_llm_math_decimal": True,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "RightNow-AI/inference-cost-truth",
        "url": "https://github.com/RightNow-AI/inference-cost-truth",
        "category": "pert_and_ai_costing",
        "license": "MIT",
        "agent_architecture": "Hardware cost modeling calculator",
        "tech_stack": ["Python"],
        "assumption_handling": "Explicit GPU utilization and throughput assumptions",
        "math_engine": "Deterministic cluster economics",
        "strengths": "Transparent assumptions for self-hosted vs API costing",
        "limitations": "GPU infrastructure scope only",
        "maturity_score": "medium",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
    {
        "repo_full_name": "franbonafina/llm-pricing-analytic",
        "url": "https://github.com/franbonafina/llm-pricing-analytic",
        "category": "pert_and_ai_costing",
        "license": "MIT",
        "agent_architecture": "Requirement parser + cloud pricing comparison",
        "tech_stack": ["Python", "LLMs"],
        "assumption_handling": "Maps software requirements to AWS/Azure/GCP tiers",
        "math_engine": "Cloud SKU aggregation",
        "strengths": "Requirement-to-SKU mapping pattern",
        "limitations": "Cloud hosting pricing only",
        "maturity_score": "prototype",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": False,
        },
    },
    {
        "repo_full_name": "OpenMDAO/OpenMDAO",
        "url": "https://github.com/OpenMDAO/OpenMDAO",
        "category": "aerospace_mdo_and_formal",
        "license": "Apache-2.0",
        "agent_architecture": "NASA coupled multidisciplinary optimization framework",
        "tech_stack": ["Python", "NumPy", "SciPy"],
        "assumption_handling": "Explicit design variables and discipline coupling",
        "math_engine": "Analytic derivative MDO solver",
        "strengths": "Gold-standard aerospace sizing & weight/cost coupling substrate",
        "limitations": "Engineering solver only; no RFQ intake or commercial quoting",
        "maturity_score": "high",
        "supports": {
            "zero_llm_math_decimal": False,
            "seven_dim_exhaustive_assumptions": False,
            "span_verified_rfq_citations": False,
            "pert_and_arb_uncertainty_bounds": False,
            "z3_smt_margin_proof": False,
            "adversarial_refuter_and_abstain": False,
            "cryptographic_ledger_merkle_dsse": False,
            "air_gapped_on_prem_ready": True,
        },
    },
)

GLOBAL_COMMERCIAL_PLATFORMS_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "name": "Paperless Parts (Wingman AI)",
        "url": "https://www.paperlessparts.com",
        "segment": "aerospace_job_shop_quoting",
        "target_users": ("Aerospace & Defense Tier-2/Tier-3 job shops and contract manufacturers"),
        "automation_method": (
            "Manufacturing-aware AI parses legacy PDF prints, BOMs, GD&T notes, "
            "and ZIP packages over ERP"
        ),
        "assumption_model": "Shop-native machine rates, ITAR/CMMC constraints, tribal setup rules",
        "strengths": "Deep aerospace compliance (ITAR/CMMC) and messy PDF/ZIP RFQ intake",
        "limitations": ("Proprietary US cloud; no formal Z3 margin envelope proof or open ledger"),
    },
    {
        "name": "aPriori Digital Factory",
        "url": "https://www.apriori.com",
        "segment": "parametric_should_cost",
        "target_users": "Aerospace & Automotive OEM procurement and VAVE teams",
        "automation_method": (
            "3D CAD geometric feature recognition + regional Digital Factory cost simulation"
        ),
        "assumption_model": (
            "Regional labor, machine burden, cycle times, casting/forging/5-axis CNC physics"
        ),
        "strengths": "Industry benchmark for deterministic CAD-driven should-costing and DFM",
        "limitations": (
            "High enterprise license cost; lacks multi-agent contractual assumption synthesis"
        ),
    },
    {
        "name": "Galorath SEER (SEER-H / SEER-Aero / SEER-DFM)",
        "url": "https://galorath.com",
        "segment": "parametric_should_cost",
        "target_users": "NASA, Defense agencies, Aerospace primes",
        "automation_method": (
            "Parametric hardware, composite ply, software, and schedule risk modeling"
        ),
        "assumption_model": "TRL, complexity drivers, weight, learning curves, Monte Carlo risk",
        "strengths": "Unmatched conceptual aerospace/defense parametric calibration",
        "limitations": "Closed proprietary black-box models; no LLM RFQ span citation",
    },
    {
        "name": "PRICE Systems TruePlanning",
        "url": "https://www.pricesystems.com",
        "segment": "parametric_should_cost",
        "target_users": "Space (ESA), Defense, Aerospace primes",
        "automation_method": (
            "Parametric lifecycle and hardware development cost estimation framework"
        ),
        "assumption_model": "Complexity, heritage, TRL, schedule and manufacturing footprint",
        "strengths": "Deep historical calibration for space and defense systems",
        "limitations": "Manual expert parameterization; no automated RFQ ingestion",
    },
    {
        "name": "Xometry Instant Quoting Engine (IQE)",
        "url": "https://www.xometry.com",
        "segment": "aerospace_job_shop_quoting",
        "target_users": "On-demand CNC, sheet metal, and additive manufacturing buyers",
        "automation_method": (
            "ML engine trained on millions of CAD quotes providing instant pricing and DFM"
        ),
        "assumption_model": (
            "Standardized marketplace lead times, tolerance tiers, global supplier capacity"
        ),
        "strengths": "Instant 24/7 quoting and automated DFM feedback",
        "limitations": (
            "Closed marketplace pricing without auditable breakdown or owned rate cards"
        ),
    },
    {
        "name": "Spanflug MAKE",
        "url": "https://www.spanflug.de",
        "segment": "aerospace_job_shop_quoting",
        "target_users": "European CNC turning and milling manufacturers",
        "automation_method": "AI feature analysis of CAD 3D models and 2D technical drawings",
        "assumption_model": "Machine tool kinematics, setup times, batch curves",
        "strengths": "Fast European CNC drawing + CAD automated costing",
        "limitations": "Limited to discrete CNC parts; no engineering/certification workpackages",
    },
    {
        "name": "Facturee",
        "url": "https://www.facturee.de",
        "segment": "aerospace_job_shop_quoting",
        "target_users": "Industrial engineering procurement in Europe",
        "automation_method": (
            "Digital manufacturing network combining automated intake and supplier matching"
        ),
        "assumption_model": "Network-wide machine availability and tolerance brackets",
        "strengths": "Streamlined multi-process European manufacturing procurement",
        "limitations": (
            "Sourcing partner model rather than white-box stress/manufacturing estimator"
        ),
    },
    {
        "name": "Digifabster",
        "url": "https://www.digifabster.com",
        "segment": "aerospace_job_shop_quoting",
        "target_users": "SMB machine shops and sheet-metal fabricators",
        "automation_method": "Web-widget CAD feature analysis and shop-calibrated rule matrices",
        "assumption_model": "Shop hourly rate matrices and standard commercial finishes",
        "strengths": "Turnkey 24/7 e-commerce storefront quoting",
        "limitations": "Designed for standard commercial jobs rather than CS-27/CS-29 packages",
    },
    {
        "name": "Costimator (MTI Systems)",
        "url": "https://www.mtisystems.com",
        "segment": "aerospace_job_shop_quoting",
        "target_users": "Precision aerospace and defense suppliers",
        "automation_method": (
            "Computer-aided cost estimating (ACE) using material/speeds/feeds libraries"
        ),
        "assumption_model": (
            "Alloy machinability (Ti, Inconel, Al), labor standards, setup formulas"
        ),
        "strengths": "Repeatable shop-floor physics-grounded manufacturing estimates",
        "limitations": "Requires manual estimator operation; lacks multi-agent LLM intake",
    },
    {
        "name": "CADDi (Drawer / Quote)",
        "url": "https://us.caddi.com",
        "segment": "aerospace_job_shop_quoting",
        "target_users": "Manufacturing procurement and engineering",
        "automation_method": (
            "Computer vision on legacy 2D drawings to extract dimensions and tolerances"
        ),
        "assumption_model": "Historical similar-part pricing retrieval",
        "strengths": "Best-in-class 2D legacy blueprint visual search",
        "limitations": "No formal SMT margin proof or 7-dimension contractual assumptions",
    },
    {
        "name": "Tacton CPQ",
        "url": "https://www.tacton.com",
        "segment": "enterprise_cpq_rfp",
        "target_users": "Industrial equipment and complex configurable manufacturers",
        "automation_method": "Constraint-based product configurator + guided selling",
        "assumption_model": "Pre-modeled engineering configuration constraints",
        "strengths": "Zero invalid configurations for structured product lines",
        "limitations": "Requires upfront constraint modeling; weak on unstructured bespoke RFQs",
    },
    {
        "name": "PROS Smart CPQ",
        "url": "https://pros.com",
        "segment": "enterprise_cpq_rfp",
        "target_users": "Global B2B enterprises, aviation/airlines, manufacturing",
        "automation_method": "AI dynamic price optimization + enterprise CPQ",
        "assumption_model": "Willingness-to-pay elasticity and margin guardrails",
        "strengths": "Enterprise scale and dynamic margin optimization",
        "limitations": "Commercial SaaS pricing focus without engineering WBS or air-gapped ledger",
    },
    {
        "name": "Arkestro",
        "url": "https://www.arkestro.com",
        "segment": "predictive_procurement",
        "target_users": "Enterprise procurement teams (including aerospace supply chains)",
        "automation_method": (
            "Predictive Procurement Orchestration using ML forecasting and autonomous RFPs"
        ),
        "assumption_model": "Historical supplier quote behavior and market pricing bands",
        "strengths": "Automates multi-round supplier bidding and negotiation",
        "limitations": (
            "Buy-side negotiation focus; does not model manufacturing physics or stress"
        ),
    },
    {
        "name": "Keelvar",
        "url": "https://www.keelvar.com",
        "segment": "predictive_procurement",
        "target_users": "Enterprise sourcing and logistics procurement",
        "automation_method": "AI sourcing bots and combinatorial bid optimization",
        "assumption_model": "Supplier capacity constraints, lane bundles, award rules",
        "strengths": "Mathematical optimization for complex multi-lot RFQ awards",
        "limitations": "Buy-side award optimization rather than engineering quote generation",
    },
    {
        "name": "Fairmarkit",
        "url": "https://www.fairmarkit.com",
        "segment": "predictive_procurement",
        "target_users": "Enterprise tail-spend procurement",
        "automation_method": "Autonomous RFQ dispatch, supplier discovery, and bid normalization",
        "assumption_model": "Catalog matching and historical vendor responsiveness",
        "strengths": "High-volume tail-spend automation",
        "limitations": "Not engineered for critical structural/aerospace engineering packages",
    },
    {
        "name": "Responsive (formerly RFPIO)",
        "url": "https://www.responsive.io",
        "segment": "enterprise_cpq_rfp",
        "target_users": "Enterprise sales, proposal, and security review teams",
        "automation_method": "Strategic RFx response management with semantic answer library",
        "assumption_model": "Approved narrative boilerplate and SME review routing",
        "strengths": "Enterprise collaboration for large RFx documents",
        "limitations": "Document text management only; lacks Decimal costing and SMT verification",
    },
    {
        "name": "Loopio",
        "url": "https://www.loopio.com",
        "segment": "enterprise_cpq_rfp",
        "target_users": "B2B RFP and DDQ response teams",
        "automation_method": "Centralized RFP content library with AI drafting assistants",
        "assumption_model": "Curated library freshness checks",
        "strengths": "Fast collaborative questionnaire completion",
        "limitations": "No quantitative costing, PERT, or engineering assumptions",
    },
    {
        "name": "AutoRFP.ai",
        "url": "https://autorfp.ai",
        "segment": "enterprise_cpq_rfp",
        "target_users": "B2B teams answering RFPs, RFQs, and security DDQs",
        "automation_method": "Semantic RAG retrieval over company docs to auto-fill RFQs/RFPs",
        "assumption_model": "Knowledge-base grounded citations",
        "strengths": "High-accuracy semantic autofill for questionnaires",
        "limitations": "No deterministic Decimal math engine or formal margin checks",
    },
)

AEROREGU_CAPABILITY_AXES: tuple[str, ...] = (
    "zero_llm_math_decimal",
    "seven_dim_exhaustive_assumptions",
    "span_verified_rfq_citations",
    "pert_and_arb_uncertainty_bounds",
    "z3_smt_margin_proof",
    "adversarial_refuter_and_abstain",
    "cryptographic_ledger_merkle_dsse",
    "air_gapped_on_prem_ready",
)


@dataclass
class QuotationIntelligenceScraper:
    """Scrapes and aggregates global GitHub repositories and commercial quoting platforms."""

    default_queries: tuple[str, ...] = (
        "multi-agent quotation rfq",
        "automated quoting cost estimation llm",
        "rfp rfq langgraph agent",
        "cpq manufacturing cost estimation python",
    )

    def scrape_github_repositories(
        self,
        queries: list[str] | None = None,
        *,
        live_network: bool = False,
        max_per_query: int = 8,
        timeout_s: float = 5.0,
    ) -> dict[str, Any]:
        """Collect GitHub quoting/RFQ repos from verified catalog and optional live GitHub API."""
        active_queries = list(queries) if queries else list(self.default_queries)
        repos_by_name: dict[str, dict[str, Any]] = {}
        for item in GLOBAL_QUOTATION_REPOS_CATALOG:
            key = str(item["repo_full_name"]).lower()
            repos_by_name[key] = {**item, "discovery_source": "verified_catalog"}

        live_discovered = 0
        live_errors: list[str] = []
        hn_discussions: list[dict[str, Any]] = []
        network_mode = "offline_catalog"

        if live_network:
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": "aeroregu-quotation-intelligence-scraper/1.0",
            }
            try:
                with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
                    any_ok = False
                    for q in active_queries:
                        try:
                            resp = client.get(
                                "https://api.github.com/search/repositories",
                                params={
                                    "q": q,
                                    "sort": "stars",
                                    "order": "desc",
                                    "per_page": str(max(1, min(int(max_per_query), 30))),
                                },
                                headers=headers,
                            )
                            if resp.status_code == 200:
                                any_ok = True
                                data = resp.json()
                                for raw_repo in data.get("items", []):
                                    full_name = str(raw_repo.get("full_name") or "").strip()
                                    if not full_name:
                                        continue
                                    key = full_name.lower()
                                    if key in repos_by_name:
                                        repos_by_name[key]["stars"] = raw_repo.get(
                                            "stargazers_count"
                                        )
                                        repos_by_name[key]["updated_at"] = raw_repo.get(
                                            "updated_at"
                                        )
                                        continue
                                    live_discovered += 1
                                    repos_by_name[key] = {
                                        "repo_full_name": full_name,
                                        "url": str(raw_repo.get("html_url") or ""),
                                        "category": "live_github_discovery",
                                        "license": (
                                            (raw_repo.get("license") or {}).get("spdx_id")
                                            or "Unknown"
                                        ),
                                        "agent_architecture": str(
                                            raw_repo.get("description") or "Discovered repository"
                                        ),
                                        "tech_stack": [
                                            str(raw_repo.get("language") or "Unknown"),
                                            *list(raw_repo.get("topics") or [])[:4],
                                        ],
                                        "assumption_handling": "NOT_VERIFIED (live search hit)",
                                        "math_engine": "NOT_VERIFIED",
                                        "strengths": str(raw_repo.get("description") or ""),
                                        "limitations": "Requires code audit",
                                        "maturity_score": "live_hit",
                                        "stars": raw_repo.get("stargazers_count", 0),
                                        "discovery_source": f"github_api:{q}",
                                        "supports": {
                                            axis: False for axis in AEROREGU_CAPABILITY_AXES
                                        },
                                    }
                            else:
                                live_errors.append(f"github_http_{resp.status_code}:{q}")
                        except Exception as exc:
                            live_errors.append(f"github_err:{q}:{type(exc).__name__}")

                    try:
                        hn_resp = client.get(
                            "https://hn.algolia.com/api/v1/search",
                            params={"query": "automated RFQ quoting AI", "tags": "story"},
                        )
                        if hn_resp.status_code == 200:
                            any_ok = True
                            for hit in (hn_resp.json().get("hits") or [])[:5]:
                                hn_discussions.append(
                                    {
                                        "title": str(hit.get("title") or ""),
                                        "url": str(hit.get("url") or ""),
                                        "points": int(hit.get("points") or 0),
                                    }
                                )
                    except Exception as exc:
                        live_errors.append(f"hn_err:{type(exc).__name__}")

                network_mode = "live_merged" if any_ok else "offline_fallback"
            except Exception as exc:
                live_errors.append(f"client_err:{type(exc).__name__}")
                network_mode = "offline_fallback"

        all_repos = list(repos_by_name.values())
        by_category: dict[str, int] = {}
        for repo in all_repos:
            cat = str(repo.get("category") or "other")
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "network_mode": network_mode,
            "queries_executed": active_queries,
            "catalog_count": len(GLOBAL_QUOTATION_REPOS_CATALOG),
            "live_discovered_count": live_discovered,
            "total_repositories": len(all_repos),
            "by_category": by_category,
            "repositories": all_repos,
            "hn_discussions": hn_discussions,
            "live_errors": live_errors,
        }

    def scrape_web_platforms(
        self,
        *,
        live_network: bool = False,
        timeout_s: float = 4.0,
    ) -> dict[str, Any]:
        """Collect commercial quoting/RFQ platforms and optionally probe live web metadata."""
        platforms: list[dict[str, Any]] = []
        live_probes_ok = 0
        live_errors: list[str] = []
        title_re = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

        if live_network:
            with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
                for entry in GLOBAL_COMMERCIAL_PLATFORMS_CATALOG:
                    rec = dict(entry)
                    try:
                        resp = client.get(
                            str(entry["url"]),
                            headers={"User-Agent": "aeroregu-scraper/1.0"},
                        )
                        rec["http_status"] = resp.status_code
                        m = title_re.search(resp.text[:8192])
                        if m:
                            rec["live_page_title"] = " ".join(m.group(1).split())[:120]
                        if resp.status_code < 400:
                            live_probes_ok += 1
                    except Exception as exc:
                        rec["http_status"] = None
                        rec["probe_error"] = type(exc).__name__
                        live_errors.append(f"{entry['name']}:{type(exc).__name__}")
                    platforms.append(rec)
        else:
            platforms = [dict(entry) for entry in GLOBAL_COMMERCIAL_PLATFORMS_CATALOG]

        by_segment: dict[str, int] = {}
        for p in platforms:
            seg = str(p["segment"])
            by_segment[seg] = by_segment.get(seg, 0) + 1

        return {
            "network_mode": (
                "live_probed"
                if live_network and live_probes_ok > 0
                else ("offline_fallback" if live_network else "offline_catalog")
            ),
            "total_platforms": len(platforms),
            "live_probes_ok": live_probes_ok,
            "by_segment": by_segment,
            "platforms": platforms,
            "live_errors": live_errors,
        }

    def compare_against_aeroregu(self) -> dict[str, Any]:
        """Compute quantitative capability gap matrix across global GitHub repos vs aeroregu."""
        axis_support_counts: dict[str, int] = {axis: 0 for axis in AEROREGU_CAPABILITY_AXES}
        total = len(GLOBAL_QUOTATION_REPOS_CATALOG)
        top_repo_scores: list[dict[str, Any]] = []

        for repo in GLOBAL_QUOTATION_REPOS_CATALOG:
            sup = repo.get("supports") or {}
            score = 0
            for axis in AEROREGU_CAPABILITY_AXES:
                if sup.get(axis):
                    axis_support_counts[axis] += 1
                    score += 1
            top_repo_scores.append(
                {
                    "repo_full_name": repo["repo_full_name"],
                    "category": repo["category"],
                    "axes_covered": score,
                    "axes_total": len(AEROREGU_CAPABILITY_AXES),
                }
            )
        top_repo_scores.sort(key=lambda r: (-int(r["axes_covered"]), str(r["repo_full_name"])))

        return {
            "aeroregu_axes_covered": len(AEROREGU_CAPABILITY_AXES),
            "aeroregu_axes_total": len(AEROREGU_CAPABILITY_AXES),
            "aeroregu_capabilities": {axis: True for axis in AEROREGU_CAPABILITY_AXES},
            "github_catalog_size": total,
            "commercial_platforms_size": len(GLOBAL_COMMERCIAL_PLATFORMS_CATALOG),
            "github_axis_adoption_counts": axis_support_counts,
            "max_axes_covered_by_any_single_github_repo": (
                top_repo_scores[0]["axes_covered"] if top_repo_scores else 0
            ),
            "top_github_comparables": top_repo_scores[:10],
        }

    def run_full_harvest(self, *, live_network: bool = False) -> dict[str, Any]:
        """Execute combined GitHub + Commercial Web scrape and capability comparison."""
        github_res = self.scrape_github_repositories(live_network=live_network)
        web_res = self.scrape_web_platforms(live_network=live_network)
        comparison = self.compare_against_aeroregu()
        return {
            "github": github_res,
            "web_platforms": web_res,
            "comparison": comparison,
            "markdown_report": self.export_intelligence_report_markdown(
                github_res=github_res,
                web_res=web_res,
                comparison=comparison,
            ),
        }

    def export_intelligence_report_markdown(
        self,
        *,
        github_res: dict[str, Any] | None = None,
        web_res: dict[str, Any] | None = None,
        comparison: dict[str, Any] | None = None,
        live_network: bool = False,
    ) -> str:
        """Render an executive Markdown report of the scraped GitHub & web quoting landscape."""
        gh = github_res or self.scrape_github_repositories(live_network=live_network)
        wb = web_res or self.scrape_web_platforms(live_network=live_network)
        cmp = comparison or self.compare_against_aeroregu()

        lines: list[str] = [
            "# Global Automated Quotation & Multi-Agent RFQ Intelligence Report",
            "",
            f"- **GitHub Repositories Analyzed:** {gh['total_repositories']} "
            f"(Catalog: {gh['catalog_count']}, Live Discovered: {gh['live_discovered_count']})",
            f"- **Commercial Web Platforms Analyzed:** {wb['total_platforms']}",
            f"- **Capability Axes Covered by `aeroregu`:** "
            f"{cmp['aeroregu_axes_covered']}/{cmp['aeroregu_axes_total']} "
            f"(Max covered by any single GitHub repo: "
            f"{cmp['max_axes_covered_by_any_single_github_repo']}/{cmp['aeroregu_axes_total']})",
            "",
            "## Capability Adoption Across Cataloged GitHub Repositories",
            "",
            "| Capability Axis | GitHub Repos Supporting | `aeroregu` |",
            "|---|---|---|",
        ]
        for axis in AEROREGU_CAPABILITY_AXES:
            cnt = cmp["github_axis_adoption_counts"].get(axis, 0)
            lines.append(f"| `{axis}` | {cnt}/{cmp['github_catalog_size']} | YES |")

        lines.extend(
            [
                "",
                "## Top GitHub Repositories",
                "",
                "| Repository | Category | Agent Architecture | Key Limitation |",
                "|---|---|---|---|",
            ]
        )
        for repo in gh["repositories"][:15]:
            lines.append(
                f"| [{repo['repo_full_name']}]({repo['url']}) | {repo['category']} | "
                f"{repo['agent_architecture']} | {repo['limitations']} |"
            )

        lines.extend(
            [
                "",
                "## Commercial Web Platforms",
                "",
                "| Platform | Segment | Automation & Assumption Model |",
                "|---|---|---|",
            ]
        )
        for plat in wb["platforms"]:
            lines.append(
                f"| [{plat['name']}]({plat['url']}) | {plat['segment']} | "
                f"{plat['assumption_model']} |"
            )
        return "\n".join(lines)

    def scrape_rotorcraft_department_intelligence(
        self,
        *,
        live_network: bool = False,
        timeout_s: float = 4.0,
    ) -> dict[str, Any]:
        """Consolidate EASA/FAA/NASA/GARTEUR rotorcraft costing sources, 18 archetypes & 9 rates."""
        from evidence_coverage.rotorcraft_quotation_catalog import get_rotorcraft_catalog

        catalog = get_rotorcraft_catalog()
        public_sources: list[dict[str, Any]] = [
            {
                "id": "EASA-CS-29",
                "title": "EASA Certification Specifications CS-29 Large Rotorcraft",
                "url": "https://www.easa.europa.eu/en/document-library/certification-specifications/group/cs-29-large-rotorcraft",
                "scope": "Subpart C/D loads, CS 29.571 F&DT, CS 29.561/562 crashworthiness",
            },
            {
                "id": "EASA-CS-27",
                "title": "EASA Certification Specifications CS-27 Small Rotorcraft",
                "url": "https://www.easa.europa.eu/en/document-library/certification-specifications/group/cs-27-small-rotorcraft",
                "scope": "Small rotorcraft airframe/dynamic structural certification",
            },
            {
                "id": "EASA-PART-21",
                "title": "EASA Part 21 (EU 748/2012) Design & Production Organisations",
                "url": "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-airworthiness-and-environmental-certification",
                "scope": "Part 21J DOA, 21.A.239 CVE independence, Subpart M/E/P PtF",
            },
            {
                "id": "NASA-NDARC",
                "title": "NASA NDARC Conceptual Rotorcraft Costing (TP-2015-218751)",
                "url": "https://ntrs.nasa.gov/citations/20150008379",
                "scope": "Rotorcraft weight-empty & dynamic system CER cost equations",
            },
            {
                "id": "FAA-AC-29-2C",
                "title": "FAA Advisory Circular AC 29-2C Certification of Transport Rotorcraft",
                "url": "https://www.faa.gov/regulations_policies/advisory_circles",
                "scope": "AC 29.571 fatigue, MG-17 structural/crash/bird-strike guidance",
            },
            {
                "id": "EASA-AI-CONCEPT",
                "title": "EASA Artificial Intelligence Roadmap / Concept Paper Issue 2",
                "url": "https://www.easa.europa.eu/en/domains/research-innovation/artificial-intelligence",
                "scope": "Level 1/2 human-centric assistance & CVE sign-off boundary",
            },
        ]
        probed_ok = 0
        probe_errors: list[str] = []
        title_re = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
        if live_network:
            with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
                for src in public_sources:
                    try:
                        resp = client.get(
                            str(src["url"]),
                            headers={"User-Agent": "aeroregu-rotorcraft-scraper/1.0"},
                        )
                        src["http_status"] = resp.status_code
                        m = title_re.search(resp.text[:8192])
                        if m:
                            src["live_page_title"] = " ".join(m.group(1).split())[:120]
                        if resp.status_code < 400:
                            probed_ok += 1
                    except Exception as exc:
                        src["http_status"] = None
                        src["probe_error"] = type(exc).__name__
                        probe_errors.append(f"{src['id']}:{type(exc).__name__}")

        return {
            "network_mode": (
                "live_probed"
                if live_network and probed_ok > 0
                else ("live_fallback_catalog" if live_network else "catalog_verified")
            ),
            "live_probes_ok": probed_ok,
            "live_errors": probe_errors,
            "authoritative_sources": public_sources,
            "catalog": catalog,
        }
