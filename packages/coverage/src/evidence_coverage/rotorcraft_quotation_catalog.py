"""Helicopter Aerospace Engineering Design & Stress Quotation Engine.

Covers:
- Default EU rate card (EU_DEFAULT) + 8 country profiles (FR, DE, ES, IT, UK, US, PL, IN)
  plus automated 9-country comparison & Onshore-CVE + Nearshore-Execution hybrid quoting.
- 18 professional rotorcraft engineering archetypes (Q-DES-01 .. Q-TST-02) aligned with
  EASA CS-27 / CS-29 / Part 21J / Part 21G and real design/stress department workflows.
- 6 academic & institutional cost-estimation models (NASA NDARC, RAND NAFCOM, USC COSYSMO,
  Curran/Scanlan/Roy MDO, GARTEUR HELIX/FELIX/PVT, EASA AI Concept Paper + Part 21 CVE).
- 10 rotorcraft assumption dimensions (42 standardized assumptions) with Change-Order rules.
- Supervised 8-agent deterministic pipeline + FLINT/Arb intervals + Z3 SMT margin proof +
  SHA-256 Merkle Ledger sealing.

Advisory note: Outputs are decision-support ASSUMPTION / ESTIMATE packages for human
engineers and CVE signatories; this module never determines regulatory compliance.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum
from evidence_calc.registry import run_method
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.gateway import prompt_hash
from evidence_kernel.guardrails import check_text_safety
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record

from evidence_coverage.quotation_multiagent import (
    QuotationAbstain,
    prove_quotation_margin_envelope,
)

_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")
_ONE = Decimal("1")
_FOUR = Decimal("4")
_SIX = Decimal("6")
_HUNDRED = Decimal("100")
_Z_P80 = Decimal("0.84162123")
_Z_P90 = Decimal("1.28155157")

ROTORCRAFT_ASSUMPTION_DIMENSIONS: tuple[str, ...] = (
    "TECHNICAL_SCOPE",
    "ROTORCRAFT_LOADS_SPECTRA",
    "DYNAMICS_VIBRATION_AEROELASTIC",
    "DOA_CERTIFICATION_PRIVILEGES",
    "DATA_AND_IDP",
    "SCHEDULE_AND_ITERATIONS",
    "COMMERCIAL_AND_RATES",
    "LEGAL_IP_AND_EXPORT",
    "TOOLING_AND_COMPUTE",
    "RISK_AND_ABSTAIN_TRIGGERS",
)

COUNTRY_RATE_CARDS: dict[str, dict[str, Any]] = {
    "EU_DEFAULT": {
        "country_code": "EU_DEFAULT",
        "country_name": "European Union Baseline (Default Rate Card)",
        "cluster_hubs": "Pan-European EASA Part 21J Reference",
        "is_default": True,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "88.000",
            "loads_rate": "108.000",
            "stress_rate": "112.000",
            "fdt_dyn_rate": "122.000",
            "systems_rate": "115.000",
            "test_rate": "102.000",
            "cve_rate": "138.000",
            "proto_rate": "85.000",
            "hpc_rate": "18.000",
        },
        "overhead_pct": "12.000",
        "contingency_pct": "10.000",
        "export_control_regime": "EU Dual-Use Reg. 2021/821 / EASA Part 21J ITAR-free",
        "fx_and_tax_notes": "EUR functional currency baseline before VAT; benchmark reference.",
        "nearshore_eligible": True,
        "data_status": "ASSUMPTION",
    },
    "FR": {
        "country_code": "FR",
        "country_name": "France",
        "cluster_hubs": "Toulouse / Marignane / Paris-Saclay",
        "is_default": False,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "96.000",
            "loads_rate": "118.000",
            "stress_rate": "124.000",
            "fdt_dyn_rate": "134.000",
            "systems_rate": "125.000",
            "test_rate": "112.000",
            "cve_rate": "150.000",
            "proto_rate": "95.000",
            "hpc_rate": "18.000",
        },
        "overhead_pct": "14.000",
        "contingency_pct": "10.000",
        "export_control_regime": "DGA / CIEEMG EU Dual-Use; strong ITAR-free rotorcraft ecosystem",
        "fx_and_tax_notes": "EUR domestic; French social charges & Syntec calendar incorporated.",
        "nearshore_eligible": False,
        "data_status": "ASSUMPTION",
    },
    "DE": {
        "country_code": "DE",
        "country_name": "Germany",
        "cluster_hubs": "Donauwoerth / Ottobrunn / Munich",
        "is_default": False,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "104.000",
            "loads_rate": "126.000",
            "stress_rate": "132.000",
            "fdt_dyn_rate": "144.000",
            "systems_rate": "135.000",
            "test_rate": "120.000",
            "cve_rate": "160.000",
            "proto_rate": "105.000",
            "hpc_rate": "19.000",
        },
        "overhead_pct": "15.000",
        "contingency_pct": "10.000",
        "export_control_regime": "BAFA EU Dual-Use + LBA/EASA Part 21J; strict AUG contracting",
        "fx_and_tax_notes": "EUR domestic; IG Metall tariff structure and BfL documentation rules.",
        "nearshore_eligible": False,
        "data_status": "ASSUMPTION",
    },
    "ES": {
        "country_code": "ES",
        "country_name": "Spain",
        "cluster_hubs": "Albacete / Madrid / Seville",
        "is_default": False,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "74.000",
            "loads_rate": "92.000",
            "stress_rate": "95.000",
            "fdt_dyn_rate": "104.000",
            "systems_rate": "98.000",
            "test_rate": "88.000",
            "cve_rate": "122.000",
            "proto_rate": "72.000",
            "hpc_rate": "17.000",
        },
        "overhead_pct": "11.000",
        "contingency_pct": "9.000",
        "export_control_regime": "EU Dual-Use / AESA-EASA Part 21J sovereign EU hub",
        "fx_and_tax_notes": (
            "EUR domestic; high cost-to-quality nearshore EU structural stress hub."
        ),
        "nearshore_eligible": True,
        "data_status": "ASSUMPTION",
    },
    "IT": {
        "country_code": "IT",
        "country_name": "Italy",
        "cluster_hubs": "Cascina Costa / Turin / Brindisi",
        "is_default": False,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "82.000",
            "loads_rate": "100.000",
            "stress_rate": "105.000",
            "fdt_dyn_rate": "114.000",
            "systems_rate": "108.000",
            "test_rate": "96.000",
            "cve_rate": "130.000",
            "proto_rate": "80.000",
            "hpc_rate": "18.000",
        },
        "overhead_pct": "12.000",
        "contingency_pct": "10.000",
        "export_control_regime": "UAMA / EU Dual-Use & ENAC-EASA Part 21J rotorcraft cluster",
        "fx_and_tax_notes": "EUR domestic; deep helicopter transmission and dynamic hub expertise.",
        "nearshore_eligible": True,
        "data_status": "ASSUMPTION",
    },
    "UK": {
        "country_code": "UK",
        "country_name": "United Kingdom",
        "cluster_hubs": "Yeovil / Bristol / Farnborough",
        "is_default": False,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "94.000",
            "loads_rate": "114.000",
            "stress_rate": "118.000",
            "fdt_dyn_rate": "128.000",
            "systems_rate": "122.000",
            "test_rate": "108.000",
            "cve_rate": "146.000",
            "proto_rate": "92.000",
            "hpc_rate": "19.000",
        },
        "overhead_pct": "13.000",
        "contingency_pct": "11.000",
        "export_control_regime": "UK ECJU + dual UK CAA / EASA Part 21 bilateral rules",
        "fx_and_tax_notes": "GBP-to-EUR FX buffer & IR35 off-payroll contractor tax overhead.",
        "nearshore_eligible": False,
        "data_status": "ASSUMPTION",
    },
    "US": {
        "country_code": "US",
        "country_name": "United States",
        "cluster_hubs": "Fort Worth TX / Stratford CT / Mesa AZ",
        "is_default": False,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "128.000",
            "loads_rate": "152.000",
            "stress_rate": "158.000",
            "fdt_dyn_rate": "172.000",
            "systems_rate": "162.000",
            "test_rate": "145.000",
            "cve_rate": "195.000",
            "proto_rate": "130.000",
            "hpc_rate": "22.000",
        },
        "overhead_pct": "16.000",
        "contingency_pct": "12.000",
        "export_control_regime": "ITAR 22 CFR / EAR TAA required; segregated US Persons enclaves",
        "fx_and_tax_notes": "USD-to-EUR FX reserve & elevated US product liability insurance.",
        "nearshore_eligible": False,
        "data_status": "ASSUMPTION",
    },
    "PL": {
        "country_code": "PL",
        "country_name": "Poland",
        "cluster_hubs": "Mielec / Swidnik / Rzeszow (Aviation Valley)",
        "is_default": False,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "58.000",
            "loads_rate": "72.000",
            "stress_rate": "76.000",
            "fdt_dyn_rate": "84.000",
            "systems_rate": "78.000",
            "test_rate": "70.000",
            "cve_rate": "102.000",
            "proto_rate": "56.000",
            "hpc_rate": "16.000",
        },
        "overhead_pct": "10.000",
        "contingency_pct": "10.000",
        "export_control_regime": "EU Dual-Use / NATO AQAP / ULC-EASA Part 21G & 21J",
        "fx_and_tax_notes": "PLN-to-EUR FX buffer; competitive intra-EU airframe & cabin hub.",
        "nearshore_eligible": True,
        "data_status": "ASSUMPTION",
    },
    "IN": {
        "country_code": "IN",
        "country_name": "India",
        "cluster_hubs": "Bengaluru / Hyderabad Aerospace GCCs",
        "is_default": False,
        "currency_basis": "EUR",
        "rates": {
            "cad_rate": "42.000",
            "loads_rate": "54.000",
            "stress_rate": "58.000",
            "fdt_dyn_rate": "66.000",
            "systems_rate": "60.000",
            "test_rate": "52.000",
            "cve_rate": "90.000",
            "proto_rate": "44.000",
            "hpc_rate": "15.000",
        },
        "overhead_pct": "10.000",
        "contingency_pct": "14.000",
        "export_control_regime": (
            "Non-EU offshore; ITAR/EAR & EU defense data carve-out + Onshore CVE"
        ),
        "fx_and_tax_notes": (
            "Higher rework/timezone buffer (14%) and mandatory Onshore Part 21J CVE."
        ),
        "nearshore_eligible": True,
        "data_status": "ASSUMPTION",
    },
}

RESEARCH_BENCHMARK_MODELS: dict[str, dict[str, Any]] = {
    "NASA_NDARC": {
        "title": "NASA NDARC Rotorcraft Cost Estimating Relationships (Ames TP-2015-218751)",
        "authors": "W. Johnson / J. Scott (NASA Ames Research Center CTM)",
        "mechanism": (
            "Component-level CERs separating primary airframe, dynamic systems "
            "(MRB/MRH/MGB), and mission equipment by weight empty & configuration."
        ),
        "calc_driver": "cert_basis_factor",
        "assumptions": "Applies parametric rotorcraft NRE scaling; requires calibration to OEM.",
    },
    "RAND_NAFCOM": {
        "title": "RAND Airframe & Rotary-Wing Material Complexity Models (MG-196 / MR-1695)",
        "authors": "O. Younossi, M. Arena et al. (RAND Corporation / NAFCOM)",
        "mechanism": (
            "Material complexity multipliers relative to 2024/7075 Aluminum baseline: "
            "Al=1.000, Hybrid Al-CFRP=1.450, Ti-6Al-4V=1.650, Primary CFRP=1.750."
        ),
        "calc_driver": "material_complexity_factor",
        "assumptions": "Captures ply-book, delamination/BVID, and machining cycle NRE deltas.",
    },
    "USC_COSYSMO": {
        "title": "USC COSYSMO Constructive Systems Engineering Cost Model",
        "authors": "R. Valerdi & B. Boehm (USC CSSE / INCOSE)",
        "mechanism": (
            "Sizes systems & integration engineering hours from external/internal ICD "
            "interfaces, requirements volatility, and certification algorithms."
        ),
        "calc_driver": "cosysmo_driver_factor",
        "assumptions": "Nominal=1.000, Elevated ICDs=1.180, High Multi-STC Volatility=1.350.",
    },
    "CURRAN_SCANLAN_ROY": {
        "title": "Curran, Scanlan & Roy Genetic-Causal Design-to-Cost MDO (DATUM / FLAVIIR)",
        "authors": "R. Curran, J. Scanlan, R. Roy (Queen's Belfast / Southampton / Cranfield)",
        "mechanism": (
            "Links physical design features (frames, fasteners, ply drop-offs, tolerances) "
            "causally to WBS specialty hours rather than opaque lump-sum analogies."
        ),
        "calc_driver": "WBS specialty decomposition",
        "assumptions": "Supports full Tornado sensitivity across every engineering specialty.",
    },
    "GARTEUR_PVT": {
        "title": "GARTEUR HELIX / FELIX / ASTERIX & Predictive Virtual Testing (PVT)",
        "authors": "GARTEUR Rotorcraft Group (DLR / ONERA / CIRA / NLR / QinetiQ)",
        "mechanism": (
            "Models building-block test pyramid trade-off: high-fidelity virtual testing "
            "compresses physical test rig/flight campaign duration while shifting effort to FEM."
        ),
        "calc_driver": "pvt_compression_factor",
        "assumptions": "Requires GVT/strain-gauge correlation tolerance agreement before contract.",
    },
    "EASA_AI_PART21_CVE": {
        "title": "EASA AI Concept Paper Issue 2 (Level 1/2) & Part 21.A.239(b) CVE Independence",
        "authors": "EASA Part 21J Design Organisation & AI Task Force",
        "mechanism": (
            "Enforces human-in-the-loop traceability and a non-waivable independent CVE "
            "verification floor (10%-15% of engineering hours) separate from authoring staff."
        ),
        "calc_driver": "cve_min_ratio_pct",
        "assumptions": (
            "Tool assists engineers & CVEs; never issues autonomous compliance findings."
        ),
    },
}

_MATERIAL_FACTORS: dict[str, str] = {
    "ALUMINUM_2024_7075": "1.000",
    "HYBRID_AL_CFRP": "1.250",
    "TI_6AL_4V": "1.450",
    "CFRP_PRIMARY_HONEYCOMB": "1.550",
}

_CERT_BASIS_FACTORS: dict[str, str] = {
    "CS-27": "1.000",
    "PART21J_REPAIR": "1.050",
    "STC": "1.180",
    "CS-29": "1.350",
}

_COSYSMO_FACTORS: dict[str, str] = {
    "LOW": "0.920",
    "NOMINAL": "1.000",
    "ELEVATED": "1.180",
    "HIGH": "1.350",
}

ROTORCRAFT_QUOTATION_ARCHETYPES: dict[str, dict[str, Any]] = {
    "Q-DES-01": {
        "archetype_id": "Q-DES-01",
        "family": "DESIGN",
        "title": "Concept & Preliminary Airframe / Cabin Architecture",
        "description": (
            "Preliminary 3D layout, cabin ergonomics, crashworthy structural load-path concept, "
            "digital mock-up (DMU) space allocation, and architecture trade-off."
        ),
        "keywords": (
            "concept",
            "preliminary",
            "architecture",
            "layout",
            "dmu",
            "ergonomics",
            "cabin",
        ),
        "easa_clauses": ("CS 27/29.301", "CS 27/29.771", "CS 27/29.803"),
        "department_roles": (
            "Aeronautical Concept Architect",
            "Weights & Balance Lead",
            "Human Factors / Crew Station Designer",
            "CVE Structures",
        ),
        "toolchain": ("3DEXPERIENCE / CATIA V5", "ENOVIA VPM", "RAMSYS / Trade Matrix"),
        "idp_requirements": (
            "Mission specification & MTOW target",
            "Cabin internal envelope & seat pitch constraints",
            "Transmission/engine bay keep-out zones",
        ),
        "deliverables": (
            "Preliminary DMU STEP/CATProduct freeze",
            "Structural load-path concept report",
            "Trade-off matrix & preliminary W&B allocation",
        ),
        "fixed_price_share_pct": "70.000",
        "capped_tm_share_pct": "30.000",
        "cve_min_ratio_pct": "8.000",
        "pert_total_hours": {
            "optimistic": "220.000",
            "most_likely": "320.000",
            "pessimistic": "480.000",
        },
        "hours_by_specialty": {
            "cad_hours": "180.000",
            "loads_hours": "35.000",
            "stress_hours": "45.000",
            "fdt_dyn_hours": "10.000",
            "systems_hours": "20.000",
            "test_hours": "0.000",
            "cve_hours": "30.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "40.000",
        "default_travel_hardware_eur": "1800.000",
        "default_cosysmo_factor": "1.050",
        "default_pvt_factor": "1.000",
    },
    "Q-DES-02": {
        "archetype_id": "Q-DES-02",
        "family": "DESIGN",
        "title": "Metallic Detail Design (Machined Frames, Sheet Metal, Fittings)",
        "description": (
            "Detailed CATIA V5/3DEXPERIENCE solids, 2D manufacturing drawings, GD&T PMI "
            "(ASME Y14.5), tolerance stack-up, fastener selection, and DFMA sign-off."
        ),
        "keywords": (
            "metallic",
            "detail design",
            "machined",
            "fitting",
            "sheet metal",
            "drawing",
            "gdt",
        ),
        "easa_clauses": ("CS 27/29.603", "CS 27/29.607", "CS 27/29.611", "CS 27/29.619"),
        "department_roles": (
            "Mechanical Detail Designer",
            "Materials & Processes (M&P) Specialist",
            "Manufacturing DFMA Engineer",
            "Design Check / CVE",
        ),
        "toolchain": ("CATIA V5 / 3DEXPERIENCE", "Tolerance Stack-up", "SAP / Windchill PLM"),
        "idp_requirements": (
            "Frozen parent DMU interfaces & datum scheme",
            "Approved metallic alloy list (MMPDS/OEM)",
            "Preliminary stress sizing envelope",
        ),
        "deliverables": (
            "Released CATPart / STEP models with PMI/GD&T",
            "2D production drawings & BOM",
            "Tolerance stack-up & M&P sign-off sheets",
        ),
        "fixed_price_share_pct": "80.000",
        "capped_tm_share_pct": "20.000",
        "cve_min_ratio_pct": "8.000",
        "pert_total_hours": {
            "optimistic": "260.000",
            "most_likely": "380.000",
            "pessimistic": "540.000",
        },
        "hours_by_specialty": {
            "cad_hours": "250.000",
            "loads_hours": "10.000",
            "stress_hours": "45.000",
            "fdt_dyn_hours": "10.000",
            "systems_hours": "10.000",
            "test_hours": "0.000",
            "cve_hours": "35.000",
            "proto_hours": "20.000",
        },
        "default_hpc_hours": "30.000",
        "default_travel_hardware_eur": "1500.000",
        "default_cosysmo_factor": "1.000",
        "default_pvt_factor": "1.000",
    },
    "Q-DES-03": {
        "archetype_id": "Q-DES-03",
        "family": "DESIGN",
        "title": "Composite Design & Ply-Book / Laminate Drop-Off (CFRP & Sandwich)",
        "description": (
            "CATIA Composites Design (CPD) ply-book authoring, drape/producibility simulation, "
            "honeycomb core ramp-downs, lightning mesh integration, and mold lofting."
        ),
        "keywords": (
            "composite",
            "cfrp",
            "ply-book",
            "plybook",
            "laminate",
            "honeycomb",
            "sandwich",
            "cpd",
        ),
        "easa_clauses": ("CS 27/29.573", "CS 27/29.603", "CS 27/29.613", "AMC 20-29"),
        "department_roles": (
            "Composites Design Engineer (CPD)",
            "M&P Autoclave/RTM Specialist",
            "Tooling / Producibility Engineer",
            "CVE Structures",
        ),
        "toolchain": ("CATIA CPD / FiberSIM", "CMH-17 Allowables", "MSC Nastran PCOMP"),
        "idp_requirements": (
            "Aerodynamic OML / mold line surfaces",
            "Certified prepreg / core allowables & BVID rules",
            "Lightning strike zone map & galvanic isolation specs",
        ),
        "deliverables": (
            "Master Ply-Book & rosette orientation definition",
            "Flat patterns / laser projection files",
            "Layup drop-off check report & DFEM PCOMP deck",
        ),
        "fixed_price_share_pct": "75.000",
        "capped_tm_share_pct": "25.000",
        "cve_min_ratio_pct": "10.000",
        "pert_total_hours": {
            "optimistic": "300.000",
            "most_likely": "440.000",
            "pessimistic": "640.000",
        },
        "hours_by_specialty": {
            "cad_hours": "280.000",
            "loads_hours": "15.000",
            "stress_hours": "60.000",
            "fdt_dyn_hours": "15.000",
            "systems_hours": "15.000",
            "test_hours": "0.000",
            "cve_hours": "40.000",
            "proto_hours": "15.000",
        },
        "default_hpc_hours": "60.000",
        "default_travel_hardware_eur": "2200.000",
        "default_cosysmo_factor": "1.080",
        "default_pvt_factor": "1.000",
    },
    "Q-DES-04": {
        "archetype_id": "Q-DES-04",
        "family": "DESIGN",
        "title": "Configuration Management, Weight & Balance (W&B) & EBOM Roll-Up",
        "description": (
            "Mass properties budget, longitudinal & lateral CG envelope verification across fuel/"
            "mission payloads, MOI tensor extraction for rotor dynamics, and PLM EBOM baselines."
        ),
        "keywords": (
            "weight",
            "balance",
            "w&b",
            "cg",
            "ebom",
            "bom",
            "configuration",
            "mass properties",
        ),
        "easa_clauses": ("CS 27/29.25", "CS 27/29.27", "CS 27/29.1519", "Part 21.A.239"),
        "department_roles": (
            "Mass Properties / W&B Engineer",
            "Configuration & PLM Lead",
            "Design Signatory",
        ),
        "toolchain": ("3DEXPERIENCE ENOVIA / Windchill", "W&B Ledger Tool", "CAD Inertia Scripts"),
        "idp_requirements": (
            "Current EBOM part list with vendor weights",
            "Fuel tank geometry & payload loading stations",
            "Approved datum & station coordinate system",
        ),
        "deliverables": (
            "Certified Weight & Balance Report",
            "CG excursion diagram (longitudinal/lateral)",
            "Configuration Effectivity Matrix & inertia tensor",
        ),
        "fixed_price_share_pct": "85.000",
        "capped_tm_share_pct": "15.000",
        "cve_min_ratio_pct": "8.000",
        "pert_total_hours": {
            "optimistic": "140.000",
            "most_likely": "210.000",
            "pessimistic": "310.000",
        },
        "hours_by_specialty": {
            "cad_hours": "75.000",
            "loads_hours": "45.000",
            "stress_hours": "15.000",
            "fdt_dyn_hours": "15.000",
            "systems_hours": "35.000",
            "test_hours": "0.000",
            "cve_hours": "25.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "20.000",
        "default_travel_hardware_eur": "900.000",
        "default_cosysmo_factor": "1.020",
        "default_pvt_factor": "1.000",
    },
    "Q-STR-01": {
        "archetype_id": "Q-STR-01",
        "family": "STRESS",
        "title": "Flight, Ground, Rotor & Emergency Loads Envelope Generation",
        "description": (
            "Generation of balanced CS-27/CS-29 Subpart C flight maneuver, gust, autorotation, "
            "run-on/level/two-wheel landing, and rotor mast/blade load cases plus V-n diagrams."
        ),
        "keywords": (
            "loads",
            "envelope",
            "v-n",
            "subpart c",
            "landing",
            "maneuver",
            "gust",
            "rotor loads",
        ),
        "easa_clauses": ("CS 29.301", "CS 29.321", "CS 29.337", "CS 29.471", "CS 29.501"),
        "department_roles": (
            "Loads & Aeromechanics Engineer",
            "Aeroelasticity Specialist",
            "Senior Stress Analyst",
            "CVE Loads & Structures",
        ),
        "toolchain": ("CAMRAD II / FLIGHTLAB", "MSC Nastran SOL 144", "Python / MATLAB Spectra"),
        "idp_requirements": (
            "V-n flight envelope & MTOW / CG extremes",
            "Main & tail rotor polar / blade mass distribution",
            "Landing gear oleo stroke & tire stiffness data",
        ),
        "deliverables": (
            "Flight & Ground External Loads Book",
            "Critical Load Case Selection Matrix (Limit/Ultimate)",
            "Balanced nodal FORCE/MOMENT cards for GFEM",
        ),
        "fixed_price_share_pct": "60.000",
        "capped_tm_share_pct": "40.000",
        "cve_min_ratio_pct": "12.000",
        "pert_total_hours": {
            "optimistic": "320.000",
            "most_likely": "460.000",
            "pessimistic": "700.000",
        },
        "hours_by_specialty": {
            "cad_hours": "25.000",
            "loads_hours": "275.000",
            "stress_hours": "75.000",
            "fdt_dyn_hours": "30.000",
            "systems_hours": "10.000",
            "test_hours": "0.000",
            "cve_hours": "45.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "220.000",
        "default_travel_hardware_eur": "2000.000",
        "default_cosysmo_factor": "1.120",
        "default_pvt_factor": "0.950",
    },
    "Q-STR-02": {
        "archetype_id": "Q-STR-02",
        "family": "STRESS",
        "title": "Full-Airframe GFEM Build, Inertia Relief & Nastran .f06 Quality Audit",
        "description": (
            "Global Finite Element Model (GFEM) meshing/assembly of fuselage, tailboom, and "
            "deck with GPWG weight check, OLOAD/SPCFORCE sum balance, EPSILON/MAXRATIO audit."
        ),
        "keywords": (
            "gfem",
            "global fem",
            "f06",
            "nastran",
            "inertia relief",
            "gpwg",
            "fuselage fem",
        ),
        "easa_clauses": ("CS 27/29.305", "CS 27/29.307", "Part 21.A.239"),
        "department_roles": (
            "Global FEM Lead",
            "Loads Balance Engineer",
            "QA / Numerical Audit Engineer",
            "CVE Structures",
        ),
        "toolchain": ("Patran / MSC Apex / HyperMesh", "MSC Nastran SOL 101/103/106", "pyNastran"),
        "idp_requirements": (
            "Frozen OML & primary structural layout",
            "Component mass distribution for NSM/CONM2",
            "Preliminary external loads deck",
        ),
        "deliverables": (
            "Validated Nastran .bdf GFEM & mass check sheet",
            ".f06 GPWG/OLOAD/SPCFORCE/EPSILON audit dossier",
            "Global internal loads extraction (.op2 / .h5)",
        ),
        "fixed_price_share_pct": "70.000",
        "capped_tm_share_pct": "30.000",
        "cve_min_ratio_pct": "12.000",
        "pert_total_hours": {
            "optimistic": "380.000",
            "most_likely": "560.000",
            "pessimistic": "820.000",
        },
        "hours_by_specialty": {
            "cad_hours": "55.000",
            "loads_hours": "85.000",
            "stress_hours": "305.000",
            "fdt_dyn_hours": "40.000",
            "systems_hours": "15.000",
            "test_hours": "0.000",
            "cve_hours": "60.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "340.000",
        "default_travel_hardware_eur": "2500.000",
        "default_cosysmo_factor": "1.100",
        "default_pvt_factor": "0.950",
    },
    "Q-STR-03": {
        "archetype_id": "Q-STR-03",
        "family": "STRESS",
        "title": "Detailed DFEM & Full Static Stress Justification Dossier",
        "description": (
            "Sub-model DFEM with CBUSH/PBUSH Huth bolt stiffness, bearing/bypass interaction, "
            "Bruhn/Roark buckling checks, out-of-core .op2/.h5 MS_min synthesis & stress report."
        ),
        "keywords": (
            "dfem",
            "stress report",
            "static stress",
            "ms_min",
            "margin",
            "buckling",
            "huth",
            "cbush",
        ),
        "easa_clauses": ("CS 27/29.305", "CS 27/29.307", "CS 27/29.625", "CS 27/29.619"),
        "department_roles": (
            "Senior Structural Stress Analyst",
            "Classical Hand-Calc Lead",
            "CVE Structures",
        ),
        "toolchain": ("MSC Nastran SOL 101/105/400", "Abaqus / OptiStruct", "Bruhn / MIL-HDBK-5"),
        "idp_requirements": (
            "Released CATIA detail drawings (PMI)",
            "GFEM boundary displacements / internal loads",
            "Certified allowables & knockdown factors",
        ),
        "deliverables": (
            "Detailed DFEM deck & joint CBUSH extraction",
            "Complete Static Stress Dossier with MS_min table",
            "Independent CVE Review & Comment Resolution",
        ),
        "fixed_price_share_pct": "75.000",
        "capped_tm_share_pct": "25.000",
        "cve_min_ratio_pct": "12.000",
        "pert_total_hours": {
            "optimistic": "340.000",
            "most_likely": "500.000",
            "pessimistic": "740.000",
        },
        "hours_by_specialty": {
            "cad_hours": "35.000",
            "loads_hours": "45.000",
            "stress_hours": "325.000",
            "fdt_dyn_hours": "25.000",
            "systems_hours": "10.000",
            "test_hours": "0.000",
            "cve_hours": "60.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "260.000",
        "default_travel_hardware_eur": "1800.000",
        "default_cosysmo_factor": "1.050",
        "default_pvt_factor": "0.950",
    },
    "Q-STR-04": {
        "archetype_id": "Q-STR-04",
        "family": "STRESS",
        "title": "Sub-Tier Supplier Verification & Stress Gatekeeper Review",
        "description": (
            "Independent Part 21.A.239 oversight & CAD-vs-BDF-vs-.f06-vs-PDF cross-audit of "
            "tier-1/tier-2 vendor stress packages, finding open assumptions & missing cases."
        ),
        "keywords": (
            "supplier",
            "vendor",
            "gatekeeper",
            "sub-tier",
            "cve review",
            "audit",
            "cross-audit",
        ),
        "easa_clauses": ("Part 21.A.239", "Part 21.A.131", "AMC 21.A.239(a)"),
        "department_roles": (
            "CVE Structures Gatekeeper",
            "Senior Verification Stress Engineer",
            "Supplier Quality Assurance Lead",
        ),
        "toolchain": ("pyNastran Cross-Audit", "MSC Nastran", "Document Traceability Gate"),
        "idp_requirements": (
            "Supplier Stress Report PDF + native .bdf/.f06",
            "Parent OEM loads & boundary condition interface",
        ),
        "deliverables": (
            "Finding & Discrepancy Register (Critical/Major/Minor)",
            "Cross-artifact numerical audit matrix",
            "Recommendation Note for CVE Approval/Rejection",
        ),
        "fixed_price_share_pct": "65.000",
        "capped_tm_share_pct": "35.000",
        "cve_min_ratio_pct": "20.000",
        "pert_total_hours": {
            "optimistic": "160.000",
            "most_likely": "240.000",
            "pessimistic": "380.000",
        },
        "hours_by_specialty": {
            "cad_hours": "15.000",
            "loads_hours": "25.000",
            "stress_hours": "125.000",
            "fdt_dyn_hours": "15.000",
            "systems_hours": "0.000",
            "test_hours": "0.000",
            "cve_hours": "60.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "90.000",
        "default_travel_hardware_eur": "1500.000",
        "default_cosysmo_factor": "1.080",
        "default_pvt_factor": "1.000",
    },
    "Q-FDT-01": {
        "archetype_id": "Q-FDT-01",
        "family": "FDT",
        "title": "Primary Airframe Fatigue & Damage Tolerance (F&DT) & ALS/ICA Intervals",
        "description": (
            "Palmgren-Miner cumulative damage, Paris/NASGRO crack propagation da/dN, initial "
            "flaw assumptions, inspectability mapping, and CS 29.571 / 29.573 ALS intervals."
        ),
        "keywords": (
            "fatigue",
            "damage tolerance",
            "f&dt",
            "fdt",
            "crack",
            "nasgro",
            "als",
            "ica",
            "29.571",
        ),
        "easa_clauses": ("CS 29.571", "CS 29.573", "AC 29-2C", "AMC 20-29"),
        "department_roles": (
            "Fatigue & Damage Tolerance Specialist",
            "Fracture Mechanics Lead",
            "M&P Non-Destructive Inspection Lead",
            "CVE F&DT",
        ),
        "toolchain": ("NASGRO / AFGROW", "nCode DesignLife", "MSC Nastran"),
        "idp_requirements": (
            "Measured or certified flight-by-flight load spectra",
            "Dfem peak stress tensors & Kt extraction",
            "NDT method detection threshold (a_NDI / BVID)",
        ),
        "deliverables": (
            "Fatigue & Crack Growth Justification Dossier",
            "Safe-Life / Flaw-Tolerant Inspection Interval Table",
            "Airworthiness Limitations Section (ALS) inputs",
        ),
        "fixed_price_share_pct": "55.000",
        "capped_tm_share_pct": "45.000",
        "cve_min_ratio_pct": "14.000",
        "pert_total_hours": {
            "optimistic": "420.000",
            "most_likely": "640.000",
            "pessimistic": "980.000",
        },
        "hours_by_specialty": {
            "cad_hours": "20.000",
            "loads_hours": "90.000",
            "stress_hours": "120.000",
            "fdt_dyn_hours": "310.000",
            "systems_hours": "10.000",
            "test_hours": "15.000",
            "cve_hours": "75.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "280.000",
        "default_travel_hardware_eur": "2500.000",
        "default_cosysmo_factor": "1.150",
        "default_pvt_factor": "0.900",
    },
    "Q-FDT-02": {
        "archetype_id": "Q-FDT-02",
        "family": "FDT",
        "title": "Dynamic Components Safe-Life & Flaw Tolerance (MRB, MRH, MGB, Swashplate)",
        "description": (
            "High-cycle S-N reduction (3-sigma/99%-95% reliability), fretting/corrosion "
            "knockdowns, Principal Structural Element (PSE) retirement life for blades, hub, MGB."
        ),
        "keywords": (
            "dynamic component",
            "mrb",
            "mrh",
            "mgb",
            "swashplate",
            "rotor hub",
            "safe-life",
            "gearbox",
        ),
        "easa_clauses": ("CS 29.571(e)", "CS 29.547", "CS 29.917", "CS 29.923"),
        "department_roles": (
            "Rotor & Transmission F&DT Specialist",
            "Mechanical Transmission Analyst",
            "Metallurgy / Tribology Lead",
            "CVE Dynamic Systems",
        ),
        "toolchain": ("AFGROW / Custom S-N", "Abaqus Contact", "CAMRAD II Rotor Spectra"),
        "idp_requirements": (
            "Flight strain survey / rotor load spectrum",
            "Coupon S-N raw test population for scatter reduction",
            "Flaw-tolerance damage modes per PSE",
        ),
        "deliverables": (
            "PSE Retirement Life & Top-Cycle Audit Dossier",
            "Worked-out S-N knockdown sensitivity pack",
            "Part 21J CVE Flight-Safety Sign-off Pack",
        ),
        "fixed_price_share_pct": "50.000",
        "capped_tm_share_pct": "50.000",
        "cve_min_ratio_pct": "15.000",
        "pert_total_hours": {
            "optimistic": "480.000",
            "most_likely": "720.000",
            "pessimistic": "1100.000",
        },
        "hours_by_specialty": {
            "cad_hours": "25.000",
            "loads_hours": "120.000",
            "stress_hours": "110.000",
            "fdt_dyn_hours": "335.000",
            "systems_hours": "15.000",
            "test_hours": "25.000",
            "cve_hours": "90.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "360.000",
        "default_travel_hardware_eur": "3200.000",
        "default_cosysmo_factor": "1.200",
        "default_pvt_factor": "0.880",
    },
    "Q-DYN-01": {
        "archetype_id": "Q-DYN-01",
        "family": "DYNAMICS",
        "title": "Structural Dynamics, Modal vs N*b*Omega, Ground Resonance & Aeroelasticity",
        "description": (
            "MSC Nastran SOL 103/111 modal separation vs 1-rev & N-per-rev rotor harmonics, "
            "Coleman ground/air resonance stability, flutter screening, and GVT MAC correlation."
        ),
        "keywords": (
            "dynamics",
            "modal",
            "sol 103",
            "ground resonance",
            "flutter",
            "gvt",
            "vibration",
            "campbell",
        ),
        "easa_clauses": ("CS 29.241", "CS 29.629", "CS 29.631", "CS 29.251"),
        "department_roles": (
            "Rotorcraft Structural Dynamics Specialist",
            "Aeroelasticity & Flutter Analyst",
            "GVT Modal Test Engineer",
            "CVE Dynamics",
        ),
        "toolchain": ("MSC Nastran SOL 103/111/145", "LMS Test.Lab", "CAMRAD II"),
        "idp_requirements": (
            "Verified mass/inertia GFEM matching W&B",
            "Rotor harmonics (1-Omega, b-Omega, 2*b-Omega)",
            "Landing gear damper stiffness/damping curves",
        ),
        "deliverables": (
            "Fan Plot / Campbell modal clearance report",
            "Ground Resonance & Flutter Stability Margin Report",
            "FEM-to-GVT MAC correlation summary",
        ),
        "fixed_price_share_pct": "55.000",
        "capped_tm_share_pct": "45.000",
        "cve_min_ratio_pct": "14.000",
        "pert_total_hours": {
            "optimistic": "360.000",
            "most_likely": "540.000",
            "pessimistic": "840.000",
        },
        "hours_by_specialty": {
            "cad_hours": "15.000",
            "loads_hours": "75.000",
            "stress_hours": "70.000",
            "fdt_dyn_hours": "285.000",
            "systems_hours": "15.000",
            "test_hours": "20.000",
            "cve_hours": "60.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "380.000",
        "default_travel_hardware_eur": "2800.000",
        "default_cosysmo_factor": "1.120",
        "default_pvt_factor": "0.900",
    },
    "Q-DYN-02": {
        "archetype_id": "Q-DYN-02",
        "family": "DYNAMICS",
        "title": "Crashworthiness, Subfloor Energy Absorption & Seat/Mass Retention",
        "description": (
            "Explicit non-linear crash simulation (CS 29.561/562) of subfloor crush boxes, "
            "landing gear fuse pins, overhead high-mass retention (MGB), and seat HIC/lumbar."
        ),
        "keywords": (
            "crashworthiness",
            "crash",
            "ls-dyna",
            "29.562",
            "29.561",
            "seat",
            "subfloor",
            "impact",
        ),
        "easa_clauses": ("CS 29.561", "CS 29.562", "CS 29.785", "CS 29.952"),
        "department_roles": (
            "Explicit Impact Simulation Specialist",
            "Crashworthiness / Subfloor Structural Lead",
            "Occupant Protection / Restraint Engineer",
            "CVE Crashworthiness",
        ),
        "toolchain": ("LS-DYNA / Radioss", "Abaqus/Explicit", "HyperCrash / ANSA"),
        "idp_requirements": (
            "Crash pulse velocity/attitude definitions",
            "High strain-rate material constitutive cards",
            "Seat/litter mass & MGB tie-down geometry",
        ),
        "deliverables": (
            "Explicit FEA Subfloor Crush & Fuel Retention Dossier",
            "20g/16g Mass & Seat Retention Stress Verification",
            "Drop-Test Correlation & CVE Verification Note",
        ),
        "fixed_price_share_pct": "50.000",
        "capped_tm_share_pct": "50.000",
        "cve_min_ratio_pct": "14.000",
        "pert_total_hours": {
            "optimistic": "440.000",
            "most_likely": "680.000",
            "pessimistic": "1040.000",
        },
        "hours_by_specialty": {
            "cad_hours": "35.000",
            "loads_hours": "70.000",
            "stress_hours": "85.000",
            "fdt_dyn_hours": "380.000",
            "systems_hours": "25.000",
            "test_hours": "15.000",
            "cve_hours": "70.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "650.000",
        "default_travel_hardware_eur": "3200.000",
        "default_cosysmo_factor": "1.180",
        "default_pvt_factor": "0.850",
    },
    "Q-DYN-03": {
        "archetype_id": "Q-DYN-03",
        "family": "DYNAMICS",
        "title": "Bird Strike, Hail Impact & Emergency Water Ditching (ALE/SPH FSI)",
        "description": (
            "High-velocity SPH/ALE fluid-structure interaction for CS 29.631 windscreen/nose "
            "1 kg bird impact and CS 29.801/802 emergency ditching sea-state slamming pressures."
        ),
        "keywords": (
            "bird strike",
            "hail",
            "ditching",
            "flotation",
            "sph",
            "ale",
            "windscreen",
            "fsi",
        ),
        "easa_clauses": ("CS 29.631", "CS 29.801", "CS 29.802", "CS 29.775"),
        "department_roles": (
            "SPH/ALE FSI Impact Specialist",
            "Windscreen & Transparency Stress Lead",
            "Ditching / Flotation Systems Lead",
            "CVE Structures",
        ),
        "toolchain": ("LS-DYNA SPH/ALE", "Pam-Crash", "CFD Hydrodynamic Impact"),
        "idp_requirements": (
            "Canopy/windscreen polycarbonate/glass layup curve",
            "V_NE / V_H strike angles & target sea states",
            "Emergency flotation bag inflation volumes",
        ),
        "deliverables": (
            "Bird Strike Penetration & Frame Reaction Dossier",
            "Ditching Hydrodynamic Slamming Pressure Maps",
            "Test-Correlated SPH Calibration Report",
        ),
        "fixed_price_share_pct": "50.000",
        "capped_tm_share_pct": "50.000",
        "cve_min_ratio_pct": "14.000",
        "pert_total_hours": {
            "optimistic": "400.000",
            "most_likely": "600.000",
            "pessimistic": "920.000",
        },
        "hours_by_specialty": {
            "cad_hours": "30.000",
            "loads_hours": "85.000",
            "stress_hours": "75.000",
            "fdt_dyn_hours": "315.000",
            "systems_hours": "20.000",
            "test_hours": "15.000",
            "cve_hours": "60.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "720.000",
        "default_travel_hardware_eur": "3000.000",
        "default_cosysmo_factor": "1.150",
        "default_pvt_factor": "0.860",
    },
    "Q-DOA-01": {
        "archetype_id": "Q-DOA-01",
        "family": "DOA",
        "title": "MRB Concessions, Structural Repairs & Service Bulletins (Part 21J)",
        "description": (
            "Rapid Material Review Board (MRB) disposition on frozen OEM FEM, Major/Minor "
            "repair design (doubler, oversized fastener, composite scarf), and Service Bulletins."
        ),
        "keywords": (
            "mrb",
            "concession",
            "repair",
            "service bulletin",
            "sb",
            "non-conformance",
            "ncr",
            "scarf",
        ),
        "easa_clauses": ("Part 21.A.435", "Part 21.A.437", "Part 21J Subpart D/E"),
        "department_roles": (
            "MRB Sustainment Engineer",
            "Fast-Response Stress Analyst",
            "CVE Repairs / Sustainment",
        ),
        "toolchain": ("Frozen Reference GFEM/DFEM", "Hand-Calc Templates", "Part 21J Workflow"),
        "idp_requirements": (
            "OEM NCR / damage survey measurements & photos",
            "As-built serial number configuration baseline",
        ),
        "deliverables": (
            "Major/Minor Repair Classification Sheet",
            "Repair Stress & F&DT Justification Memo",
            "Service Bulletin / Repair Scheme Drawing",
        ),
        "fixed_price_share_pct": "45.000",
        "capped_tm_share_pct": "55.000",
        "cve_min_ratio_pct": "15.000",
        "pert_total_hours": {
            "optimistic": "90.000",
            "most_likely": "140.000",
            "pessimistic": "240.000",
        },
        "hours_by_specialty": {
            "cad_hours": "35.000",
            "loads_hours": "10.000",
            "stress_hours": "55.000",
            "fdt_dyn_hours": "15.000",
            "systems_hours": "5.000",
            "test_hours": "0.000",
            "cve_hours": "20.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "25.000",
        "default_travel_hardware_eur": "500.000",
        "default_cosysmo_factor": "1.050",
        "default_pvt_factor": "1.000",
    },
    "Q-DOA-02": {
        "archetype_id": "Q-DOA-02",
        "family": "DOA",
        "title": "Mission Equipment & STC Integration (HEMS, HEC Hoist, Cargo Hook, EO/IR)",
        "description": (
            "Design, structural/dynamic/F&DT justification, ICDs, and RFM supplement support "
            "for Supplemental Type Certificates: HEMS medical interiors, rescue hoist, EO/IR."
        ),
        "keywords": (
            "stc",
            "hems",
            "hoist",
            "cargo hook",
            "eoir",
            "eo/ir",
            "mission equipment",
            "rescue",
        ),
        "easa_clauses": ("CS 29.865", "CS 29.785", "CS 29.561", "Part 21J Subpart E"),
        "department_roles": (
            "STC Integration Chief Engineer",
            "Cabin / External Store Designer",
            "Structural & Dynamics Stress Lead",
            "CVE Flight / Structures / Systems",
        ),
        "toolchain": ("CATIA V5", "MSC Nastran", "DOORS Requirements ICD Matrix"),
        "idp_requirements": (
            "Baseline rotorcraft hardpoint interface data (ICD)",
            "Vendor mission equipment inertia & operational loads",
            "Baseline Flight Manual / electrical load margin",
        ),
        "deliverables": (
            "STC Hardpoint Adapter CAD & Production Drawings",
            "Combined Static, Crash & F&DT Justification Pack",
            "Draft RFM Supplement & Compliance Checklist Aid",
        ),
        "fixed_price_share_pct": "65.000",
        "capped_tm_share_pct": "35.000",
        "cve_min_ratio_pct": "12.000",
        "pert_total_hours": {
            "optimistic": "300.000",
            "most_likely": "460.000",
            "pessimistic": "700.000",
        },
        "hours_by_specialty": {
            "cad_hours": "120.000",
            "loads_hours": "45.000",
            "stress_hours": "125.000",
            "fdt_dyn_hours": "45.000",
            "systems_hours": "65.000",
            "test_hours": "10.000",
            "cve_hours": "50.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "140.000",
        "default_travel_hardware_eur": "2400.000",
        "default_cosysmo_factor": "1.220",
        "default_pvt_factor": "0.950",
    },
    "Q-DOA-03": {
        "archetype_id": "Q-DOA-03",
        "family": "DOA",
        "title": "Propulsion Mounts, Titanium Firewall (1100C 15min) & Lightning / HIRF Bonding",
        "description": (
            "Engine/APU dynafocal mount thermo-mechanical design & stress, CS 29.1191 fireproof "
            "bulkhead thermal/structural verification, lightning return paths & DO-160G HIRF."
        ),
        "keywords": (
            "firewall",
            "propulsion",
            "engine mount",
            "apu",
            "lightning",
            "hirf",
            "do-160",
            "thermal",
        ),
        "easa_clauses": ("CS 29.1191", "CS 29.1316", "CS 29.1317", "CS 29.903", "EUROCAE ED-84"),
        "department_roles": (
            "Propulsion & Powerplant Structures Lead",
            "EMC / Lightning / HIRF Specialist",
            "Thermo-Mechanical Stress Analyst",
            "CVE Powerplant / Avionics",
        ),
        "toolchain": ("Abaqus Thermal-Structural", "CST Studio EMC", "MSC Nastran"),
        "idp_requirements": (
            "Engine/APU mount OEI & blade-off seizure loads",
            "Lightning strike zone zoning (1A/1B/2A/3)",
            "Avionics bay bonding impedance targets",
        ),
        "deliverables": (
            "Engine/APU Mount & Thermal Stress Report",
            "Firewall 1100C / 15min Justification & Joint Seal Plan",
            "Lightning Current Return Path & HIRF Test Plan",
        ),
        "fixed_price_share_pct": "60.000",
        "capped_tm_share_pct": "40.000",
        "cve_min_ratio_pct": "12.000",
        "pert_total_hours": {
            "optimistic": "320.000",
            "most_likely": "480.000",
            "pessimistic": "740.000",
        },
        "hours_by_specialty": {
            "cad_hours": "95.000",
            "loads_hours": "55.000",
            "stress_hours": "115.000",
            "fdt_dyn_hours": "35.000",
            "systems_hours": "125.000",
            "test_hours": "0.000",
            "cve_hours": "55.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "210.000",
        "default_travel_hardware_eur": "2600.000",
        "default_cosysmo_factor": "1.180",
        "default_pvt_factor": "0.950",
    },
    "Q-TST-01": {
        "archetype_id": "Q-TST-01",
        "family": "TEST",
        "title": "Structural Test Rig Design, Reaction Tooling & FEM-Strain Correlation",
        "description": (
            "Reaction frame & hydraulic whiffletree load rig engineering, strain-gauge placement "
            "optimization, pre-test blind prediction, and post-test FEM correlation report."
        ),
        "keywords": (
            "test rig",
            "structural test",
            "whiffletree",
            "strain gauge",
            "correlation",
            "iron bird",
        ),
        "easa_clauses": ("CS 27/29.307", "AMC 20-29", "Part 21.A.33"),
        "department_roles": (
            "Structural Ground Test Engineer",
            "Tooling & Reaction Rig Designer",
            "FEM Correlation Analyst",
            "CVE Structures / Test Witness",
        ),
        "toolchain": ("CATIA Tooling", "MSC Nastran Blind Prediction", "DAQ Strain Software"),
        "idp_requirements": (
            "Test article CAD & critical DFEM strain locations",
            "Laboratory floor anchor spacing & actuator specs",
        ),
        "deliverables": (
            "Test Rig CAD & Reaction Frame Stress Report",
            "Strain-Gauge Map & Pre-Test Prediction Dossier",
            "Post-Test Correlation Report (target within +/-10%)",
        ),
        "fixed_price_share_pct": "65.000",
        "capped_tm_share_pct": "35.000",
        "cve_min_ratio_pct": "12.000",
        "pert_total_hours": {
            "optimistic": "280.000",
            "most_likely": "420.000",
            "pessimistic": "660.000",
        },
        "hours_by_specialty": {
            "cad_hours": "95.000",
            "loads_hours": "35.000",
            "stress_hours": "85.000",
            "fdt_dyn_hours": "30.000",
            "systems_hours": "15.000",
            "test_hours": "90.000",
            "cve_hours": "45.000",
            "proto_hours": "25.000",
        },
        "default_hpc_hours": "110.000",
        "default_travel_hardware_eur": "4500.000",
        "default_cosysmo_factor": "1.080",
        "default_pvt_factor": "1.000",
    },
    "Q-TST-02": {
        "archetype_id": "Q-TST-02",
        "family": "TEST",
        "title": "Flight Test Instrumentation (FTI), Telemetry & Permit to Fly (PtF)",
        "description": (
            "Design & stress clearance of temporary FTI racks, external boom/antenna brackets, "
            "slip-ring rotor strain harness, Flight Test Conditions, and Part 21J Subpart P PtF."
        ),
        "keywords": (
            "fti",
            "flight test",
            "permit to fly",
            "ptf",
            "telemetry",
            "slip ring",
            "subpart p",
        ),
        "easa_clauses": ("Part 21J Subpart P (PtF)", "21.A.708", "CS 29.307(d)"),
        "department_roles": (
            "Flight Test Instrumentation (FTI) Lead",
            "Flight Dynamics & Envelope Safety Engineer",
            "Part 21J PtF / CVE Signatory",
        ),
        "toolchain": ("CATIA FTI Harness/Racks", "Nastran Modal Check", "Symvionics / IRIG-106"),
        "idp_requirements": (
            "Flight test parameter list & sensor weights",
            "Envelope expansion limits & telemetry frequency",
        ),
        "deliverables": (
            "FTI Structural Installation & Modal Clearance Pack",
            "Flight Conditions Matrix (EASA Form 18B Aid)",
            "FTI Electrical Load & Failure Mode Check",
        ),
        "fixed_price_share_pct": "55.000",
        "capped_tm_share_pct": "45.000",
        "cve_min_ratio_pct": "14.000",
        "pert_total_hours": {
            "optimistic": "310.000",
            "most_likely": "470.000",
            "pessimistic": "720.000",
        },
        "hours_by_specialty": {
            "cad_hours": "85.000",
            "loads_hours": "45.000",
            "stress_hours": "75.000",
            "fdt_dyn_hours": "40.000",
            "systems_hours": "55.000",
            "test_hours": "115.000",
            "cve_hours": "55.000",
            "proto_hours": "0.000",
        },
        "default_hpc_hours": "95.000",
        "default_travel_hardware_eur": "4200.000",
        "default_cosysmo_factor": "1.150",
        "default_pvt_factor": "0.980",
    },
}


ROTORCRAFT_MASTER_ASSUMPTIONS: tuple[dict[str, Any], ...] = (
    # 1. TECHNICAL_SCOPE (4)
    {
        "assumption_id": "ASM-TS-01",
        "dimension": "TECHNICAL_SCOPE",
        "title": "Configuration Freeze Before Stress Execution",
        "statement": (
            "Design configuration (DMU/CAD revision) is frozen prior to formal DFEM/F&DT run."
        ),
        "change_order_trigger": (
            "Any post-freeze CATIA or ICD geometry modification above tolerance."
        ),
        "risk_if_violated": "Re-meshing and full load-case re-extraction invalidates fixed hours.",
    },
    {
        "assumption_id": "ASM-TS-02",
        "dimension": "TECHNICAL_SCOPE",
        "title": "Redesign Excluded Upon Negative Margin Discovery",
        "statement": (
            "Workpackage covers justification only; structural redesign after MS < 0 is out."
        ),
        "change_order_trigger": (
            "Discovery of negative margin requiring lug/ply thickening or frame rework."
        ),
        "risk_if_violated": "Unbounded design-stress ping-pong loop.",
    },
    {
        "assumption_id": "ASM-TS-03",
        "dimension": "TECHNICAL_SCOPE",
        "title": "Single Baseline Variant & Tail Number Coverage",
        "statement": (
            "Quote covers one helicopter configuration/variant and baseline serial block."
        ),
        "change_order_trigger": (
            "Additional aircraft weight variant or fleet retro-fit configuration."
        ),
        "risk_if_violated": "Multiplies load matrices and ALS differences tables.",
    },
    {
        "assumption_id": "ASM-TS-04",
        "dimension": "TECHNICAL_SCOPE",
        "title": "Boundary Interface & Sub-Model Cut-Plane Isolation",
        "statement": "DFEM boundary loads/displacements come cleanly from parent GFEM cut-planes.",
        "change_order_trigger": (
            "Stiffness mismatch requiring parent GFEM re-tuning or global re-run."
        ),
        "risk_if_violated": "Invalidates free-body interface equilibrium.",
    },
    # 2. ROTORCRAFT_LOADS_SPECTRA (5)
    {
        "assumption_id": "ASM-RL-01",
        "dimension": "ROTORCRAFT_LOADS_SPECTRA",
        "title": "Frozen Flight, Ground & Rotor External Loads Book",
        "statement": "Client supplies approved balanced limit/ultimate loads matrix at KO+5 days.",
        "change_order_trigger": (
            "Addition of extra load cases or revision of V-n/autorotation envelope."
        ),
        "risk_if_violated": "Invalidates critical load case selection and MS_min tables.",
    },
    {
        "assumption_id": "ASM-RL-02",
        "dimension": "ROTORCRAFT_LOADS_SPECTRA",
        "title": "Mission Spectrum Mix (HEMS / SAR / Offshore O&G / Utility)",
        "statement": (
            "Fatigue & crack growth uses agreed mission usage mix and landing cycle counts."
        ),
        "change_order_trigger": (
            "Mission shift (e.g. from VIP transport to sling-load utility or HEMS)."
        ),
        "risk_if_violated": "Severely alters high-amplitude cycle count and ALS intervals.",
    },
    {
        "assumption_id": "ASM-RL-03",
        "dimension": "ROTORCRAFT_LOADS_SPECTRA",
        "title": "Ultimate Safety Factor 1.50 & Casting/Fitting Knockdowns",
        "statement": (
            "Standard CS-27/CS-29 1.50 ultimate factor + CS 29.619/621/625 fitting factors apply."
        ),
        "change_order_trigger": "Non-standard special condition requiring higher special factors.",
        "risk_if_violated": "Requires manual revision of all joint MS_min checks.",
    },
    {
        "assumption_id": "ASM-RL-04",
        "dimension": "ROTORCRAFT_LOADS_SPECTRA",
        "title": "One-Engine Inoperative (OEI) & Hard Landing Limits",
        "statement": (
            "Engine seizure torque and hard-landing sink rates remain within baseline spec."
        ),
        "change_order_trigger": "Higher powerplant rating upgrade or skids/gear energy increase.",
        "risk_if_violated": "Triggers propulsion mount and subfloor crush re-verification.",
    },
    {
        "assumption_id": "ASM-RL-05",
        "dimension": "ROTORCRAFT_LOADS_SPECTRA",
        "title": "External Sling / Hoist / Asymmetric Rotor Loads Bounded",
        "statement": (
            "HEC rescue hoist or cargo hook swing angles follow specified flight envelope."
        ),
        "change_order_trigger": "Expansion of hoist cable cone angle or dynamic snatch factor.",
        "risk_if_violated": "Overloads side-boom hardpoints and fuselage frame shear ties.",
    },
    # 3. DYNAMICS_VIBRATION_AEROELASTIC (4)
    {
        "assumption_id": "ASM-DY-01",
        "dimension": "DYNAMICS_VIBRATION_AEROELASTIC",
        "title": "Rotor Harmonic Crossing Clearance Targets (1-Omega & b-Omega)",
        "statement": (
            "Target +/-10% modal frequency separation from 1-rev, b-rev, and 2*b-rev assumed."
        ),
        "change_order_trigger": "Main rotor RPM window modification or heavier tailboom store.",
        "risk_if_violated": "Causes resonant fatigue amplification or pilot seat vibration.",
    },
    {
        "assumption_id": "ASM-DY-02",
        "dimension": "DYNAMICS_VIBRATION_AEROELASTIC",
        "title": "Assumed Structural Modal Damping Ratios",
        "statement": "Linear modal damping fixed per agreed OEM value prior to GVT measurement.",
        "change_order_trigger": "GVT measured damping differing >25% from analytical baseline.",
        "risk_if_violated": "Requires SOL 111 harmonic response recalibration.",
    },
    {
        "assumption_id": "ASM-DY-03",
        "dimension": "DYNAMICS_VIBRATION_AEROELASTIC",
        "title": "Ground Resonance OLEO & Damper Curve Stability",
        "statement": (
            "Landing gear tire/oleo and elastomeric lead-lag damper properties are frozen."
        ),
        "change_order_trigger": "Vendor damper nonlinear degradation curve update.",
        "risk_if_violated": "Alters Coleman stability boundary across rotor RPM run-up.",
    },
    {
        "assumption_id": "ASM-DY-04",
        "dimension": "DYNAMICS_VIBRATION_AEROELASTIC",
        "title": "GVT & Whirl-Tower Correlation Scope Explicit",
        "statement": (
            "Physical GVT / whirl-tower facility rental excluded unless explicitly priced."
        ),
        "change_order_trigger": "Requirement for on-site modal shaker campaign support.",
        "risk_if_violated": "Creates unbudgeted test hours and hardware mobilization cost.",
    },
    # 4. DOA_CERTIFICATION_PRIVILEGES (5)
    {
        "assumption_id": "ASM-DOA-01",
        "dimension": "DOA_CERTIFICATION_PRIVILEGES",
        "title": "EASA Part 21J.A.239(b) Independent CVE Segregated Sign-Off",
        "statement": "Independent CVE checking is mandatory and segregated from authoring team.",
        "change_order_trigger": (
            "Additional customer CRI/MoC sign-off panels requested beyond baseline."
        ),
        "risk_if_violated": "Non-acceptable under EASA Part 21J; triggers automatic ABSTAIN.",
    },
    {
        "assumption_id": "ASM-DOA-02",
        "dimension": "DOA_CERTIFICATION_PRIVILEGES",
        "title": "Tool Assists Engineers Only — Never Determines Compliance",
        "statement": (
            "Automated outputs assist CVE review; human DOA signatories hold sole authority."
        ),
        "change_order_trigger": "Demand for unverified autonomous compliance assertion.",
        "risk_if_violated": "Violates EASA AI Concept Paper Level 1/2 governance.",
    },
    {
        "assumption_id": "ASM-DOA-03",
        "dimension": "DOA_CERTIFICATION_PRIVILEGES",
        "title": "Authority CRI / CAI Response Cap (Max 2 Rounds Included)",
        "statement": (
            "Includes up to 2 written EASA/FAA Certification Review Item response rounds."
        ),
        "change_order_trigger": (
            "Additional Authority panels, Special Conditions, or FAA validation."
        ),
        "risk_if_violated": "Open-ended authority Q&A erodes fixed-price margin.",
    },
    {
        "assumption_id": "ASM-DOA-04",
        "dimension": "DOA_CERTIFICATION_PRIVILEGES",
        "title": "Single Regulatory Language & Template Standard (English)",
        "statement": (
            "All technical reports and CVE notes delivered in English on standard templates."
        ),
        "change_order_trigger": (
            "Dual-language deliverables or custom OEM legacy Word format migration."
        ),
        "risk_if_violated": "Adds 15-25% documentation formatting hours.",
    },
    {
        "assumption_id": "ASM-DOA-05",
        "dimension": "DOA_CERTIFICATION_PRIVILEGES",
        "title": "Dual Authority (EASA + FAA/UK CAA) Validation Separately Scoped",
        "statement": (
            "Certification basis assumes single lead Authority unless bilateral option chosen."
        ),
        "change_order_trigger": (
            "Late addition of FAA AC 29-2C / CAA UK bilateral differences matrix."
        ),
        "risk_if_violated": "Doubles compliance checklist and test witness documentation.",
    },
    # 5. DATA_AND_IDP (4)
    {
        "assumption_id": "ASM-IDP-01",
        "dimension": "DATA_AND_IDP",
        "title": "Input Data Package (IDP) Cleanliness & Nastran Health",
        "statement": (
            "Client-supplied GFEM/CAD arrives free of corrupt topology, orphan MPCs, or gaps."
        ),
        "change_order_trigger": (
            "Mesh repair > 8h or GPWG/EPSILON errors in inherited client GFEM."
        ),
        "risk_if_violated": ("Consumes stress engineering budget on cleanup instead of analysis."),
    },
    {
        "assumption_id": "ASM-IDP-02",
        "dimension": "DATA_AND_IDP",
        "title": "Certified Material Allowables (MMPDS / CMH-17 A/B-Basis)",
        "statement": ("Material cards, BVID knockdowns, and hot/wet factors are pre-approved."),
        "change_order_trigger": (
            "Missing coupon data requiring building-block material allowables test."
        ),
        "risk_if_violated": "Halts sizing work; forces conservative floor assumptions.",
    },
    {
        "assumption_id": "ASM-IDP-03",
        "dimension": "DATA_AND_IDP",
        "title": "Native CAD History-Tree vs Dumb STEP Availability",
        "statement": ("Native CATIA V5/3DEXPERIENCE feature trees provided for design mod scopes."),
        "change_order_trigger": (
            "Delivery of dumb STEP/IGES solids requiring full reverse modeling."
        ),
        "risk_if_violated": "Doubles CAD modification & drafting hours.",
    },
    {
        "assumption_id": "ASM-IDP-04",
        "dimension": "DATA_AND_IDP",
        "title": "Fastener / Joint Database Completeness",
        "statement": (
            "Fastener specs, shear/tension allowables, and edge-distance rules are ready."
        ),
        "change_order_trigger": (
            "Bespoke titanium/Inconel bolts requiring test-derived bearing data."
        ),
        "risk_if_violated": "Delays CBUSH stiffness & Huth joint sign-off.",
    },
    # 6. SCHEDULE_AND_ITERATIONS (4)
    {
        "assumption_id": "ASM-SCH-01",
        "dimension": "SCHEDULE_AND_ITERATIONS",
        "title": "Maximum Two CAD-Stress Optimization Loops Included",
        "statement": (
            "Includes baseline analysis plus one iterative geometry/layup refinement loop."
        ),
        "change_order_trigger": (
            "Three or more design iterations driven by late customer changes."
        ),
        "risk_if_violated": "Unbounded schedule slip and overtime burn.",
    },
    {
        "assumption_id": "ASM-SCH-02",
        "dimension": "SCHEDULE_AND_ITERATIONS",
        "title": "Client RFI / Review Turnaround SLA (5 Business Days)",
        "statement": (
            "Customer answers technical queries & reviews intermediate gates within 5 days."
        ),
        "change_order_trigger": (
            "Client review delay > 5 days holding dedicated senior stress seats."
        ),
        "risk_if_violated": "Standby cost & day-for-day milestone shift.",
    },
    {
        "assumption_id": "ASM-SCH-03",
        "dimension": "SCHEDULE_AND_ITERATIONS",
        "title": "Sequential Predecessor Gate Discipline",
        "statement": ("Downstream F&DT/CVE work starts only after static internal loads freeze."),
        "change_order_trigger": (
            "Customer mandates fast-track parallel execution prior to loads freeze."
        ),
        "risk_if_violated": "Triggers mandatory +15% Capped T&M rework allowance.",
    },
    {
        "assumption_id": "ASM-SCH-04",
        "dimension": "SCHEDULE_AND_ITERATIONS",
        "title": "Standard 8-Hour Single-Shift Engineering Calendar",
        "statement": "Rates assume standard business-day calendar without weekend/AOG surge.",
        "change_order_trigger": ("Aircraft-on-Ground (AOG) 24/7 or weekend MRB turnaround demand."),
        "risk_if_violated": "Requires statutory shift/overtime multiplier (+35% to +50%).",
    },
    # 7. COMMERCIAL_AND_RATES (5)
    {
        "assumption_id": "ASM-COM-01",
        "dimension": "COMMERCIAL_AND_RATES",
        "title": "Selected Country Rate Card vs EU_DEFAULT Benchmark",
        "statement": (
            "Quote uses specialty rate card of chosen country with EUR benchmark comparison."
        ),
        "change_order_trigger": "Change in execution country or onshore/nearshore mix after PO.",
        "risk_if_violated": "Alters direct labor cost and overhead recovery.",
    },
    {
        "assumption_id": "ASM-COM-02",
        "dimension": "COMMERCIAL_AND_RATES",
        "title": "Hybrid Fixed-Price + Capped T&M Tranche Split",
        "statement": "Deterministic frozen work is Fixed-Price; discovery/iteration is Capped T&M.",
        "change_order_trigger": "Client demands 100% Fixed-Price despite incomplete loads/IDP.",
        "risk_if_violated": "Requires P90 risk pricing uplift to preserve Z3 floor margin.",
    },
    {
        "assumption_id": "ASM-COM-03",
        "dimension": "COMMERCIAL_AND_RATES",
        "title": "Quote Validity Window (60 Calendar Days) & FX Lock",
        "statement": (
            "Pricing valid 60 days in EUR; non-EUR countries assume +/-3% FX collar at PO."
        ),
        "change_order_trigger": "PO delayed past 60 days or USD/GBP/PLN/INR FX move >3%.",
        "risk_if_violated": "Erodes nominal gross margin below floor.",
    },
    {
        "assumption_id": "ASM-COM-04",
        "dimension": "COMMERCIAL_AND_RATES",
        "title": "Milestone Payment Schedule (30% KO / 40% CDR-FEM / 30% Sign-off)",
        "statement": "Standard aerospace milestone invoicing applies; net 30-day payment terms.",
        "change_order_trigger": "Longer net terms (60-90 days) or deferred acceptance gate.",
        "risk_if_violated": "Increases working-capital financing cost.",
    },
    {
        "assumption_id": "ASM-COM-05",
        "dimension": "COMMERCIAL_AND_RATES",
        "title": "External Lab, Wind Tunnel, Authority & Travel Exclusions",
        "statement": (
            "EASA/FAA Authority fees, physical coupons, and unscheduled travel billed at cost."
        ),
        "change_order_trigger": ("Inclusion of third-party lab testing or flight-test range fees."),
        "risk_if_violated": "Can exceed entire engineering NRE value.",
    },
    # 8. LEGAL_IP_AND_EXPORT (4)
    {
        "assumption_id": "ASM-LEG-01",
        "dimension": "LEGAL_IP_AND_EXPORT",
        "title": "Export Control Screening (EU Dual-Use 2021/821 vs ITAR/EAR)",
        "statement": (
            "Classification verified before file transfer; US/IN scopes enforce enclaves."
        ),
        "change_order_trigger": (
            "Discovery of USML Category VIII / ITAR technical data mid-project."
        ),
        "risk_if_violated": "Severe legal noncompliance; forces immediate sovereign isolation.",
    },
    {
        "assumption_id": "ASM-LEG-02",
        "dimension": "LEGAL_IP_AND_EXPORT",
        "title": "Foreground vs Background Methodology IP Boundary",
        "statement": (
            "Deliverable CAD/FEM/Reports transfer to customer; proprietary scripts stay IP."
        ),
        "change_order_trigger": (
            "Customer demands source ownership of internal solver automation code."
        ),
        "risk_if_violated": "Requires separate IP buyout negotiation.",
    },
    {
        "assumption_id": "ASM-LEG-03",
        "dimension": "LEGAL_IP_AND_EXPORT",
        "title": "Nearshore Sovereign Data Residency & Onshore CVE Control",
        "statement": "Nearshore EU work (ES/PL) maintains EU GDPR/EASA residency with onshore CVE.",
        "change_order_trigger": (
            "Transfer outside EEA (e.g. India GCC) for defense/dual-use hardware."
        ),
        "risk_if_violated": (
            "Blocked by export license unless commercial civilian carve-out exists."
        ),
    },
    {
        "assumption_id": "ASM-LEG-04",
        "dimension": "LEGAL_IP_AND_EXPORT",
        "title": "Liability Cap Linked to Approved Flight/Operating Envelope",
        "statement": "Engineering validity restricted strictly to analyzed envelope & MTOW.",
        "change_order_trigger": (
            "Operator flying unapproved gross weights or mission modifications."
        ),
        "risk_if_violated": "Voids airworthiness justification basis.",
    },
    # 9. TOOLING_AND_COMPUTE (4)
    {
        "assumption_id": "ASM-TC-01",
        "dimension": "TOOLING_AND_COMPUTE",
        "title": "Solver & CAD Major Version Pinning",
        "statement": (
            "MSC Nastran, LS-DYNA, Abaqus, and CATIA/3DEXPERIENCE versions pinned at KO."
        ),
        "change_order_trigger": "Mid-program forced solver or PLM client upgrade.",
        "risk_if_violated": (
            "Breaks script automation & creates binary `.op2`/CAD incompatibilities."
        ),
    },
    {
        "assumption_id": "ASM-TC-02",
        "dimension": "TOOLING_AND_COMPUTE",
        "title": "HPC Core-Hour Budget Cap & Re-Run Policy",
        "statement": "Explicit LS-DYNA/Abaqus/Nastran HPC core hours capped per baseline plan.",
        "change_order_trigger": (
            "Customer requests fine-mesh refinement >2x element count target."
        ),
        "risk_if_violated": "Explodes HPC queue cost and turnaround latency.",
    },
    {
        "assumption_id": "ASM-TC-03",
        "dimension": "TOOLING_AND_COMPUTE",
        "title": "Client vs Contractor Software License Allocation",
        "statement": ("Quotes include contractor toolchain tokens; client VPN PLM tokens free."),
        "change_order_trigger": "Lack of client VDI/VPN seats requiring external license lease.",
        "risk_if_violated": "Adds ~1200-2500 EUR/seat-month unbudgeted software fee.",
    },
    {
        "assumption_id": "ASM-TC-04",
        "dimension": "TOOLING_AND_COMPUTE",
        "title": "No Float / Exact Decimal & Arb Audit Trail Verification",
        "statement": (
            "All quote totals, splits, and sensitivity tables computed in exact Decimal + Arb."
        ),
        "change_order_trigger": "Manual spreadsheet edits outside sealed evidence ledger.",
        "risk_if_violated": "Breaks cryptographic Merkle provenance.",
    },
    # 10. RISK_AND_ABSTAIN_TRIGGERS (4)
    {
        "assumption_id": "ASM-RK-01",
        "dimension": "RISK_AND_ABSTAIN_TRIGGERS",
        "title": "Fail-Closed ABSTAIN on Missing Cert Basis (CS-27 vs CS-29)",
        "statement": (
            "Quotes require valid certification basis or switch to conservative CS-29 factor."
        ),
        "change_order_trigger": "Ambiguous hybrid military/civil airworthiness standard.",
        "risk_if_violated": "Mis-prices structural safety factors and test pyramid requirements.",
    },
    {
        "assumption_id": "ASM-RK-02",
        "dimension": "RISK_AND_ABSTAIN_TRIGGERS",
        "title": "Fail-Closed ABSTAIN on CVE Waiver Requests",
        "statement": "System refuses any quote attempting to bypass Part 21.A.239(b) CVE review.",
        "change_order_trigger": "Contractual clause requesting self-sign-off without CVE.",
        "risk_if_violated": "Renders deliverable non-receivable under EASA Part 21.",
    },
    {
        "assumption_id": "ASM-RK-03",
        "dimension": "RISK_AND_ABSTAIN_TRIGGERS",
        "title": "Z3 SMT Continuous Margin Floor Invariant",
        "statement": (
            "Gross margin must stay >= min floor across [0.950, 1.080] direct cost drift."
        ),
        "change_order_trigger": "Client price ceiling pushing expected margin below Z3 floor.",
        "risk_if_violated": "Flagged automatically as COUNTEREXAMPLE_FOUND -> commercial hold.",
    },
    {
        "assumption_id": "ASM-RK-04",
        "dimension": "RISK_AND_ABSTAIN_TRIGGERS",
        "title": "Predictive Virtual Testing Correlation Threshold Risk",
        "statement": (
            "Where PVT compresses test scope, correlation target (+/-10% strain/MAC) applies."
        ),
        "change_order_trigger": "Physical test deviates >15% forcing model updating + extra runs.",
        "risk_if_violated": "Triggers Capped T&M test-correlation contingency tranche.",
    },
)


def _now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RotorcraftQuotationSpec:
    """Input specification for an automated rotorcraft engineering quotation."""

    rfq_text: str
    country_code: str = "EU_DEFAULT"
    archetype_id: str | None = None
    cert_basis: str = "CS-29"
    material_family: str = "HYBRID_AL_CFRP"
    cosysmo_complexity: str = "NOMINAL"
    idp_maturity: str = "COMPLETE"
    target_margin_pct: str = "22.000"
    min_acceptable_margin_pct: str = "10.000"
    nearshore_country: str = "ES"
    enable_formal_smt: bool = True
    export_control_restricted: bool = False
    tenant_id: str = "demo"
    actor_id: str = "author"
    created_at: str = ""
    rfq_id: str = "RFQ-ROTOR-001"
    customer_name: str = "Rotorcraft OEM / DOA Client"
    currency: str = "EUR"
    extra_travel_hardware_eur: str | None = None
    cve_min_ratio_pct: str | None = None
    assumption_overrides: dict[str, str] = field(default_factory=dict)
    idp_attachments: dict[str, Any] = field(default_factory=dict)
    use_historical_calibration: bool = True
    historical_corpus_path: str | None = None
    historical_top_k: int = 3


def get_rotorcraft_catalog() -> dict[str, Any]:
    """Return full 18-archetype, 9-country, 6-research-model, 10-dimension helicopter catalog."""
    return {
        "default_country_code": "EU_DEFAULT",
        "countries": list(COUNTRY_RATE_CARDS.values()),
        "archetypes_count": len(ROTORCRAFT_QUOTATION_ARCHETYPES),
        "archetypes": list(ROTORCRAFT_QUOTATION_ARCHETYPES.values()),
        "research_models_count": len(RESEARCH_BENCHMARK_MODELS),
        "research_models": RESEARCH_BENCHMARK_MODELS,
        "assumption_dimensions": list(ROTORCRAFT_ASSUMPTION_DIMENSIONS),
        "master_assumptions_count": len(ROTORCRAFT_MASTER_ASSUMPTIONS),
        "master_assumptions": list(ROTORCRAFT_MASTER_ASSUMPTIONS),
        "advisory_boundary": (
            "Decision-support ASSUMPTION / ESTIMATE catalog; human engineers and "
            "independent Part 21J CVEs retain sole technical and regulatory authority."
        ),
    }


def classify_rotorcraft_rfq(
    rfq_text: str,
    *,
    archetype_id: str | None = None,
    cert_basis: str | None = None,
    material_family: str | None = None,
    country_code: str = "EU_DEFAULT",
) -> dict[str, Any]:
    """Deterministically classify RFQ text into one of 18 archetypes and technical drivers."""
    cleaned = (rfq_text or "").strip()
    lower = cleaned.lower()

    if country_code not in COUNTRY_RATE_CARDS:
        raise QuotationAbstain("unsupported_country_code", "intake_country")

    cve_waive_markers = (
        "waive cve",
        "skip cve",
        "no cve",
        "sin cve",
        "omit cve",
        "self-certify without cve",
        "guarantee compliance without",
    )
    if any(m in lower for m in cve_waive_markers):
        raise QuotationAbstain("cve_independence_mandatory", "compliance_gate")

    out_of_domain_markers = (
        "pizza delivery",
        "grocery store",
        "wedding photography",
        "crypto token",
        "hair salon",
        "ecommerce fashion",
    )
    if archetype_id is None and (
        len(cleaned) < 8 or any(m in lower for m in out_of_domain_markers)
    ):
        reason = "empty_or_insufficient_rfq" if len(cleaned) < 8 else "out_of_domain_rfq"
        raise QuotationAbstain(reason, "intake_classifier")

    selected_id: str
    match_scores: dict[str, int] = {}
    if archetype_id is not None:
        if archetype_id not in ROTORCRAFT_QUOTATION_ARCHETYPES:
            raise QuotationAbstain("unknown_rotorcraft_archetype", "intake_classifier")
        selected_id = archetype_id
        match_scores[selected_id] = 100
    else:
        for a_id, arch in ROTORCRAFT_QUOTATION_ARCHETYPES.items():
            score = 0
            if a_id.lower() in lower:
                score += 50
            for kw in arch["keywords"]:
                if kw in lower:
                    score += 10
            if score > 0:
                match_scores[a_id] = score
        domain_hints = (
            "helicopter",
            "rotor",
            "cs-29",
            "cs-27",
            "part 21",
            "fuselage",
            "tailboom",
            "nastran",
            "catia",
            "fem",
            "hems",
            "hoist",
            "mrb",
            "fti",
            "gvt",
        )
        if not match_scores:
            if not any(h in lower for h in domain_hints):
                raise QuotationAbstain("out_of_domain_rfq", "intake_classifier")
            selected_id = "Q-STR-03"
            match_scores[selected_id] = 1
        else:
            selected_id = sorted(match_scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    detected_cert = cert_basis or "CS-29"
    if "cs-27" in lower or "cs 27" in lower:
        detected_cert = "CS-27"
    elif "cs-29" in lower or "cs 29" in lower:
        detected_cert = "CS-29"
    elif "repair" in lower or "concession" in lower or "mrb" in lower:
        if cert_basis is None:
            detected_cert = "PART21J_REPAIR"
    elif "stc" in lower or "hems" in lower or "hoist" in lower:
        if cert_basis is None:
            detected_cert = "STC"
    if detected_cert not in _CERT_BASIS_FACTORS:
        raise QuotationAbstain("unsupported_cert_basis", "intake_classifier")

    detected_mat = material_family or "HYBRID_AL_CFRP"
    if material_family is None:
        if any(w in lower for w in ("cfrp", "composite", "honeycomb", "carbon", "ply")):
            detected_mat = "CFRP_PRIMARY_HONEYCOMB"
        elif any(w in lower for w in ("ti-6al-4v", "titanium", "titanio", "inconel")):
            detected_mat = "TI_6AL_4V"
        elif any(w in lower for w in ("7075", "2024", "aluminum", "aluminium", "aluminio")):
            detected_mat = "ALUMINUM_2024_7075"
    if detected_mat not in _MATERIAL_FACTORS:
        detected_mat = "HYBRID_AL_CFRP"

    return {
        "archetype_id": selected_id,
        "archetype_title": ROTORCRAFT_QUOTATION_ARCHETYPES[selected_id]["title"],
        "family": ROTORCRAFT_QUOTATION_ARCHETYPES[selected_id]["family"],
        "cert_basis": detected_cert,
        "material_family": detected_mat,
        "keyword_scores": match_scores,
        "country_code": country_code,
    }


def build_archetype_assumptions(
    archetype: dict[str, Any],
    country_card: dict[str, Any],
    *,
    cert_basis: str,
    material_family: str,
    idp_maturity: str,
    cosysmo_complexity: str,
    export_control_restricted: bool,
    overrides: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Assemble all 42+ rotorcraft assumptions partitioned cleanly across 10 dimensions."""
    grouped: dict[str, list[dict[str, Any]]] = {dim: [] for dim in ROTORCRAFT_ASSUMPTION_DIMENSIONS}
    ov = overrides or {}
    for row in ROTORCRAFT_MASTER_ASSUMPTIONS:
        item = {
            **row,
            "label": "ASSUMPTION",
            "context_country": country_card["country_code"],
            "context_archetype": archetype["archetype_id"],
            "context_cert_basis": cert_basis,
            "context_material": material_family,
        }
        aid = item["assumption_id"]
        if aid in ov:
            item["statement"] = str(ov[aid])
            item["override_applied"] = True
        else:
            item["override_applied"] = False
        grouped[item["dimension"]].append(item)

    # Inject context-specific tailored assumption entries per quote
    grouped["COMMERCIAL_AND_RATES"].append(
        {
            "assumption_id": "ASM-COM-CTX",
            "dimension": "COMMERCIAL_AND_RATES",
            "title": f"Active Country Rate Profile: {country_card['country_code']}",
            "statement": (
                f"Primary rate card={country_card['country_code']} "
                f"({country_card['country_name']}); {country_card['fx_and_tax_notes']}"
            ),
            "change_order_trigger": "Change in execution geography or currency basis.",
            "risk_if_violated": "Direct labor and overhead variance.",
            "label": "ASSUMPTION",
            "override_applied": False,
        }
    )
    grouped["LEGAL_IP_AND_EXPORT"].append(
        {
            "assumption_id": "ASM-LEG-CTX",
            "dimension": "LEGAL_IP_AND_EXPORT",
            "title": "Active Export Regime & Data Enclave",
            "statement": (
                f"Regime: {country_card['export_control_regime']}; "
                f"restricted_enclave={export_control_restricted}; "
                f"IDP={idp_maturity}, COSYSMO={cosysmo_complexity}."
            ),
            "change_order_trigger": "Introduction of ITAR/classified artifacts mid-program.",
            "risk_if_violated": "Mandatory technical enclave isolation & surcharge.",
            "label": "ASSUMPTION",
            "override_applied": False,
        }
    )
    return grouped


def _build_calc_inputs(
    archetype: dict[str, Any],
    country_card: dict[str, Any],
    *,
    cert_basis_factor: str,
    material_complexity_factor: str,
    cosysmo_driver_factor: str,
    pvt_compression_factor: str,
    margin_pct: str,
    travel_hardware_eur: str,
    cve_min_ratio_pct: str,
    contingency_override: str | None = None,
    rate_overrides: dict[str, str] | None = None,
    hour_scale: Decimal = _ONE,
) -> dict[str, Any]:
    rates = {**country_card["rates"], **(rate_overrides or {})}
    hours = archetype["hours_by_specialty"]

    def _sh(val: str) -> str:
        return format_quantum(Decimal(val) * hour_scale, _Q3)

    return {
        "cad_hours": _sh(hours["cad_hours"]),
        "loads_hours": _sh(hours["loads_hours"]),
        "stress_hours": _sh(hours["stress_hours"]),
        "fdt_dyn_hours": _sh(hours["fdt_dyn_hours"]),
        "systems_hours": _sh(hours["systems_hours"]),
        "test_hours": _sh(hours["test_hours"]),
        "cve_hours": _sh(hours["cve_hours"]),
        "proto_hours": _sh(hours["proto_hours"]),
        "cad_rate": rates["cad_rate"],
        "loads_rate": rates["loads_rate"],
        "stress_rate": rates["stress_rate"],
        "fdt_dyn_rate": rates["fdt_dyn_rate"],
        "systems_rate": rates["systems_rate"],
        "test_rate": rates["test_rate"],
        "cve_rate": rates["cve_rate"],
        "proto_rate": rates["proto_rate"],
        "cert_basis_factor": cert_basis_factor,
        "material_complexity_factor": material_complexity_factor,
        "cosysmo_driver_factor": cosysmo_driver_factor,
        "pvt_compression_factor": pvt_compression_factor,
        "hpc_hours": _sh(archetype["default_hpc_hours"]),
        "hpc_rate": rates["hpc_rate"],
        "travel_hardware_eur": travel_hardware_eur,
        "overhead_pct": country_card["overhead_pct"],
        "contingency_pct": contingency_override or country_card["contingency_pct"],
        "margin_pct": margin_pct,
        "fixed_price_share_pct": archetype["fixed_price_share_pct"],
        "cve_min_ratio_pct": cve_min_ratio_pct,
    }


def compute_multi_country_comparison(
    archetype: dict[str, Any],
    *,
    selected_country: str,
    cert_basis_factor: str,
    material_complexity_factor: str,
    cosysmo_driver_factor: str,
    pvt_compression_factor: str,
    margin_pct: str,
    travel_hardware_eur: str,
    cve_min_ratio_pct: str,
    nearshore_country: str = "ES",
) -> dict[str, Any]:
    """Run deterministic rotorcraft_archetype_quote across all 9 profiles + Onshore/Nearshore."""
    rows: list[dict[str, Any]] = []
    eu_price: Decimal | None = None
    sel_price: Decimal | None = None

    for code, card in COUNTRY_RATE_CARDS.items():
        inp = _build_calc_inputs(
            archetype,
            card,
            cert_basis_factor=cert_basis_factor,
            material_complexity_factor=material_complexity_factor,
            cosysmo_driver_factor=cosysmo_driver_factor,
            pvt_compression_factor=pvt_compression_factor,
            margin_pct=margin_pct,
            travel_hardware_eur=travel_hardware_eur,
            cve_min_ratio_pct=cve_min_ratio_pct,
        )
        res = run_method("rotorcraft_archetype_quote", inp, include_intervals=False)
        out = res["outputs"]
        price_d = Decimal(out["quote_price_eur"])
        if code == "EU_DEFAULT":
            eu_price = price_d
        if code == selected_country:
            sel_price = price_d
        rows.append(
            {
                "country_code": code,
                "country_name": card["country_name"],
                "cluster_hubs": card["cluster_hubs"],
                "blended_hourly_rate_eur": out["blended_hourly_rate_eur"],
                "direct_cost_eur": out["direct_cost_eur"],
                "overhead_eur": out["overhead_eur"],
                "contingency_eur": out["contingency_eur"],
                "total_cost_eur": out["total_cost_eur"],
                "quote_price_eur": out["quote_price_eur"],
                "cve_share_pct": out["cve_share_pct"],
                "export_control_regime": card["export_control_regime"],
            }
        )

    assert eu_price is not None and sel_price is not None
    for row in rows:
        p = Decimal(row["quote_price_eur"])
        vs_eu_pct = ((p - eu_price) / eu_price) * _HUNDRED
        vs_sel_pct = ((p - sel_price) / sel_price) * _HUNDRED
        row["delta_vs_eu_default_pct"] = format_quantum(vs_eu_pct, _Q2)
        row["delta_vs_selected_pct"] = format_quantum(vs_sel_pct, _Q2)

    # Sort highest-to-lowest quoted price for clear comparative readability
    rows.sort(key=lambda r: Decimal(r["quote_price_eur"]), reverse=True)

    # Onshore CVE + Nearshore Execution Hybrid Model
    onshore_code = "EU_DEFAULT" if selected_country in ("ES", "PL", "IN") else selected_country
    near_code = nearshore_country if nearshore_country in COUNTRY_RATE_CARDS else "ES"
    onshore_card = COUNTRY_RATE_CARDS[onshore_code]
    near_card = COUNTRY_RATE_CARDS[near_code]
    hybrid_rates = {
        "cad_rate": near_card["rates"]["cad_rate"],
        "loads_rate": onshore_card["rates"]["loads_rate"],
        "stress_rate": near_card["rates"]["stress_rate"],
        "fdt_dyn_rate": near_card["rates"]["fdt_dyn_rate"],
        "systems_rate": onshore_card["rates"]["systems_rate"],
        "test_rate": onshore_card["rates"]["test_rate"],
        "cve_rate": onshore_card["rates"]["cve_rate"],
        "proto_rate": near_card["rates"]["proto_rate"],
        "hpc_rate": near_card["rates"]["hpc_rate"],
    }
    # Add 2% cross-site coordination reserve in contingency
    hybrid_cont = format_quantum(Decimal(near_card["contingency_pct"]) + Decimal("2.000"), _Q3)
    hybrid_inp = _build_calc_inputs(
        archetype,
        onshore_card,
        cert_basis_factor=cert_basis_factor,
        material_complexity_factor=material_complexity_factor,
        cosysmo_driver_factor=cosysmo_driver_factor,
        pvt_compression_factor=pvt_compression_factor,
        margin_pct=margin_pct,
        travel_hardware_eur=travel_hardware_eur,
        cve_min_ratio_pct=cve_min_ratio_pct,
        contingency_override=hybrid_cont,
        rate_overrides=hybrid_rates,
    )
    hybrid_res = run_method("rotorcraft_archetype_quote", hybrid_inp, include_intervals=False)
    h_out = hybrid_res["outputs"]
    h_price = Decimal(h_out["quote_price_eur"])
    savings_vs_onshore_pct = (
        (
            h_price
            - Decimal([r["quote_price_eur"] for r in rows if r["country_code"] == onshore_code][0])
        )
        / Decimal([r["quote_price_eur"] for r in rows if r["country_code"] == onshore_code][0])
    ) * _HUNDRED

    return {
        "selected_country": selected_country,
        "eu_default_price_eur": format_quantum(eu_price, _Q3),
        "countries": rows,
        "onshore_nearshore_hybrid": {
            "onshore_cve_country": onshore_code,
            "nearshore_execution_country": near_code,
            "coordination_contingency_pct": hybrid_cont,
            "quote_price_eur": h_out["quote_price_eur"],
            "total_cost_eur": h_out["total_cost_eur"],
            "blended_hourly_rate_eur": h_out["blended_hourly_rate_eur"],
            "delta_vs_onshore_pct": format_quantum(savings_vs_onshore_pct, _Q2),
            "note": (
                f"Onshore Part 21J CVE/Systems/Loads in {onshore_code} combined with "
                f"CAD/FEM/F&DT execution in {near_code}."
            ),
        },
    }


def _compute_pert_and_tornado(
    archetype: dict[str, Any],
    country_card: dict[str, Any],
    base_inputs: dict[str, Any],
    base_res: dict[str, Any],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    base_out = base_res["outputs"]
    raw_total = Decimal(base_out["raw_hours_total"])
    pert = archetype["pert_total_hours"]
    ml = Decimal(pert["most_likely"])
    opt = Decimal(pert["optimistic"])
    pess = Decimal(pert["pessimistic"])

    if ml <= 0 or raw_total <= 0:
        raise AbstainError("outside_validity")

    with localcontext() as ctx:
        ctx.prec = 50
        p50_ratio = ((opt + _FOUR * ml + pess) / _SIX) / ml
        sigma_ratio = ((pess - opt) / _SIX) / ml
        p80_ratio = p50_ratio + (_Z_P80 * sigma_ratio)
        p90_ratio = p50_ratio + (_Z_P90 * sigma_ratio)

    def _run_scaled(ratio: Decimal) -> dict[str, Any]:
        scaled_inp = _build_calc_inputs(
            archetype,
            country_card,
            cert_basis_factor=str(base_inputs["cert_basis_factor"]),
            material_complexity_factor=str(base_inputs["material_complexity_factor"]),
            cosysmo_driver_factor=str(base_inputs["cosysmo_driver_factor"]),
            pvt_compression_factor=str(base_inputs["pvt_compression_factor"]),
            margin_pct=str(base_inputs["margin_pct"]),
            travel_hardware_eur=str(base_inputs["travel_hardware_eur"]),
            cve_min_ratio_pct=str(base_inputs["cve_min_ratio_pct"]),
            contingency_override=str(base_inputs["contingency_pct"]),
            hour_scale=ratio,
        )
        return run_method("rotorcraft_archetype_quote", scaled_inp, include_intervals=False)

    res_p50 = _run_scaled(p50_ratio)
    res_p80 = _run_scaled(p80_ratio)
    res_p90 = _run_scaled(p90_ratio)

    pert_summary = {
        "hours_most_likely_scaled": base_out["total_scaled_hours"],
        "hours_p50_scaled": res_p50["outputs"]["total_scaled_hours"],
        "hours_p80_scaled": res_p80["outputs"]["total_scaled_hours"],
        "hours_p90_scaled": res_p90["outputs"]["total_scaled_hours"],
        "price_most_likely_eur": base_out["quote_price_eur"],
        "price_p50_eur": res_p50["outputs"]["quote_price_eur"],
        "price_p80_eur": res_p80["outputs"]["quote_price_eur"],
        "price_p90_eur": res_p90["outputs"]["quote_price_eur"],
        "cost_p80_eur": res_p80["outputs"]["total_cost_eur"],
    }

    # Deterministic Tornado OAT Sensitivity on key drivers
    p80_base_price = Decimal(pert_summary["price_p80_eur"])
    drivers: tuple[tuple[str, str, str, str], ...] = (
        ("cert_basis_factor", "Certification Basis Factor (CS-27 vs CS-29)", "0.850", "1.200"),
        ("material_complexity_factor", "Material Complexity (Al vs Ti/CFRP)", "0.850", "1.250"),
        ("cosysmo_driver_factor", "COSYSMO Interface/Requirement Complexity", "0.900", "1.250"),
        ("contingency_pct", "Rework / Risk Contingency (%)", "5.000", "18.000"),
        ("cve_min_ratio_pct", "Independent CVE Floor Ratio (%)", "8.000", "20.000"),
    )
    tornado: list[dict[str, Any]] = []
    for key, label, lo_m, hi_m in drivers:
        low_inp = dict(base_inputs)
        high_inp = dict(base_inputs)
        if key in ("cert_basis_factor", "material_complexity_factor", "cosysmo_driver_factor"):
            low_inp[key] = format_quantum(Decimal(base_inputs[key]) * Decimal(lo_m), _Q3)
            high_inp[key] = format_quantum(Decimal(base_inputs[key]) * Decimal(hi_m), _Q3)
        else:
            low_inp[key] = lo_m
            high_inp[key] = hi_m
        low_p = Decimal(
            run_method("rotorcraft_archetype_quote", low_inp, include_intervals=False)["outputs"][
                "quote_price_eur"
            ]
        )
        high_p = Decimal(
            run_method("rotorcraft_archetype_quote", high_inp, include_intervals=False)["outputs"][
                "quote_price_eur"
            ]
        )
        swing = abs(high_p - low_p)
        tornado.append(
            {
                "driver_key": key,
                "driver_label": label,
                "low_price_eur": format_quantum(low_p * p80_ratio, _Q3),
                "high_price_eur": format_quantum(high_p * p80_ratio, _Q3),
                "swing_eur": format_quantum(swing * p80_ratio, _Q3),
                "swing_pct_of_p80": format_quantum(
                    ((swing * p80_ratio) / p80_base_price) * _HUNDRED, _Q2
                ),
            }
        )
    tornado.sort(key=lambda r: Decimal(r["swing_eur"]), reverse=True)
    return pert_summary, tornado


def _record_rotorcraft_abstain(
    ledger: Ledger,
    spec: RotorcraftQuotationSpec,
    *,
    created_at: str,
    reason: str,
    stage: str,
) -> dict[str, Any]:
    rfq_hash = hashlib.sha256(spec.rfq_text.encode("utf-8")).hexdigest()
    safe_inputs = {"rfq_sha256": rfq_hash, "stage": stage}
    env = make_envelope(
        sources=[
            project_source(
                "rotorcraft-quotation-supervisor",
                "https://aeroregu.local/rotorcraft/quote",
                "ASSUMPTION",
            )
        ],
        method_version="rotorcraft_quotation@1.0.0",
        inputs=safe_inputs,
        confidence="abstain",
        abstain_reason=reason,
    )
    ev_hash = record(
        ledger,
        {
            "event_type": "abstain",
            "tenant_id": ledger.tenant_id,
            "actor_id": spec.actor_id,
            "created_at": created_at,
            "payload": {"reason": reason, "stage": stage, "rfq_sha256": rfq_hash},
            "envelope": env,
        },
    )
    return {
        "rfq_id": spec.rfq_id,
        "tenant_id": ledger.tenant_id,
        "country_code": spec.country_code,
        "confidence": "abstain",
        "decision_status": "ABSTAIN_ESCALATED",
        "abstain_reason": reason,
        "escalate_to": "human_engineer_and_cve",
        "event_hashes": [ev_hash],
        "merkle_root": ledger.merkle_root(),
        "markdown_report": (
            f"# Rotorcraft Quotation Abstained (`{reason}`)\n\n"
            f"- **Stage:** `{stage}`\n"
            f"- **Escalate To:** `human_engineer_and_cve`\n"
            f"- **Ledger Event:** `{ev_hash}`\n"
        ),
    }


def _render_markdown_dossier(dossier: dict[str, Any]) -> str:
    arch = dossier["archetype"]
    ctry = dossier["country_profile"]
    calc = dossier["deterministic_quote"]
    pert = dossier["pert_envelope"]
    z3p = dossier["formal_margin_proof"]
    comp = dossier["multi_country_comparison"]
    hyb = comp["onshore_nearshore_hybrid"]

    cls = dossier["classification"]
    z3_status = z3p.get("status", "SKIPPED")
    lines: list[str] = [
        f"# Rotorcraft Engineering Quotation Dossier — `{arch['archetype_id']}`",
        "",
        "> **Advisory Notice:** All parametric hours, rates, and schedules are explicit "
        "`ASSUMPTION` / `ESTIMATE` items assisting engineers and independent Part 21J CVEs. "
        "This tool never certifies or determines regulatory compliance.",
        "",
        f"- **RFQ ID:** `{dossier['rfq_id']}` | **Customer:** {dossier['customer_name']}",
        f"- **Archetype:** `{arch['archetype_id']}` — **{arch['title']}**",
        (
            f"- **Selected Country:** `{ctry['country_code']}` "
            f"({ctry['country_name']} — {ctry['cluster_hubs']})"
        ),
        f"- **Cert Basis / Material:** `{cls['cert_basis']}` / `{cls['material_family']}`",
        (
            f"- **Z3 SMT Formal Margin Gate:** `{z3_status}` | "
            f"**Decision:** `{dossier['decision_status']}`"
        ),
        f"- **Merkle Root:** `{dossier['merkle_root']}`",
        "",
        "## 1. Executive Price & Effort Summary (EUR)",
        "",
        (
            f"- **Base Most-Likely (M) Quote Price:** {calc['quote_price_eur']} EUR "
            f"({calc['total_scaled_hours']} h @ blended {calc['blended_hourly_rate_eur']} EUR/h)"
        ),
        (
            f"- **PERT P50 / P80 / P90 Envelope:** {pert['price_p50_eur']} EUR (P50) | "
            f"**{pert['price_p80_eur']} EUR (Recommended P80 Bid)** | "
            f"{pert['price_p90_eur']} EUR (P90)"
        ),
        (
            f"- **Contract Split (Fixed-Price / Capped T&M):** "
            f"{calc['fixed_price_tranche_eur']} EUR FP ({arch['fixed_price_share_pct']}%) + "
            f"{calc['capped_tm_tranche_eur']} EUR Capped T&M ({arch['capped_tm_share_pct']}%)"
        ),
        (
            f"- **Mandatory Independent CVE Verification:** {calc['cve_scaled_hours']} h "
            f"({calc['cve_share_pct']}% of total hours)"
        ),
        "",
        "## 2. All-Country Benchmark & Hybrid Comparison (Default + 8 Countries)",
        "",
        (
            "| Country | Blended Rate (EUR/h) | Total Cost (EUR) | "
            "Quote Price (EUR) | Delta vs EU Default |"
        ),
        "|---|---|---|---|---|",
    ]
    for row in comp["countries"]:
        lines.append(
            f"| `{row['country_code']}` ({row['country_name']}) | "
            f"{row['blended_hourly_rate_eur']} | {row['total_cost_eur']} | "
            f"{row['quote_price_eur']} | {row['delta_vs_eu_default_pct']}% |"
        )
    lines.extend(
        [
            "",
            f"- **Hybrid Onshore CVE (`{hyb['onshore_cve_country']}`) + "
            f"Nearshore Execution (`{hyb['nearshore_execution_country']}`):** "
            f"**{hyb['quote_price_eur']} EUR** ({hyb['delta_vs_onshore_pct']}% vs onshore)",
            "",
            "## 3. Research & Scientific Costing Models Applied",
            "",
        ]
    )
    for mid, mdata in RESEARCH_BENCHMARK_MODELS.items():
        lines.append(f"- **`{mid}`:** {mdata['title']} — `{mdata['calc_driver']}`")

    lines.extend(
        [
            "",
            "## 4. Standardized Assumptions Across 10 Rotorcraft Dimensions",
            "",
        ]
    )
    for dim in ROTORCRAFT_ASSUMPTION_DIMENSIONS:
        items = dossier["assumptions_by_dimension"][dim]
        lines.append(f"### `{dim}` ({len(items)} assumptions)")
        for it in items:
            lines.append(
                f"- **`{it['assumption_id']}` ({it['label']}):** {it['statement']} "
                f"*[CO Trigger: {it['change_order_trigger']}]*"
            )

    idp_ext = dossier.get("idp_physical_extraction") or {}
    hcal = dossier.get("historical_calibration") or {}
    knn = dossier.get("nearest_historical_quotes") or []
    if idp_ext or hcal or knn:
        lines.extend(
            [
                "",
                "## 5. IDP Physical Inspection, Empirical Calibration & Nearest Past Bids",
                "",
            ]
        )
        if idp_ext:
            nodes_c = idp_ext.get("fem_nodes_count", 0)
            cbush_c = idp_ext.get("cbush_joints_count", 0)
            lines.append(
                f"- **IDP Physical Inspection:** "
                f"maturity=`{idp_ext.get('derived_idp_maturity')}` | "
                f"cosysmo=`{idp_ext.get('derived_cosysmo_complexity')}` | "
                f"feature_factor=`{idp_ext.get('idp_feature_complexity_factor')}` | "
                f"nodes={nodes_c}, cbush={cbush_c}"
            )
        if hcal and hcal.get("status") == "CALIBRATED_DETERMINISTIC":
            co = hcal["calibration_outputs"]
            bt = hcal["backtesting"]
            lines.append(
                f"- **Historical Calibration ({hcal['corpus_origin']}, "
                f"N={hcal['sample_size']} / {hcal['corpus_total_records']}):** "
                f"Calibrated PERT Expected={co['calibrated_pert_expected_hours']} h "
                f"(P80={co['calibrated_pert_p80_hours']} h), "
                f"80/20 Backtest MAPE {bt['pre_calibration_mape_pct']}% -> "
                f"{bt['post_calibration_mape_pct']}%"
            )
        if knn:
            lines.extend(
                [
                    "",
                    (
                        "| Past Quote | Similarity | Quoted (h) | Burned (h) | "
                        "Overrun | Broken Assumptions |"
                    ),
                    "|---|---|---|---|---|---|",
                ]
            )
            for row in knn:
                broken_s = ", ".join(row.get("broken_assumption_ids") or ()) or "none"
                lines.append(
                    f"| `{row['quote_id']}` (`{row['archetype_id']}`) | "
                    f"{row['similarity_score']} | {row['quoted_hours']} | "
                    f"{row['actual_burned_hours']} | {row['overrun_pct']}% | {broken_s} |"
                )
    return "\n".join(lines)


def run_rotorcraft_department_quotation(
    ledger: Ledger,
    spec: RotorcraftQuotationSpec,
) -> dict[str, Any]:
    """Execute 8-agent rotorcraft engineering quotation with 18 archetypes & 9 countries."""
    created_at = spec.created_at or _now_utc()
    try:
        margin_d = Decimal(spec.target_margin_pct)
        min_margin_d = Decimal(spec.min_acceptable_margin_pct)
        if margin_d <= Decimal("0") or min_margin_d < Decimal("0") or min_margin_d > margin_d:
            raise QuotationAbstain("invalid_margin_bounds", "commercial_gate")

        classification = classify_rotorcraft_rfq(
            spec.rfq_text,
            archetype_id=spec.archetype_id,
            cert_basis=spec.cert_basis,
            material_family=spec.material_family,
            country_code=spec.country_code,
        )
        arch = ROTORCRAFT_QUOTATION_ARCHETYPES[classification["archetype_id"]]
        country_card = COUNTRY_RATE_CARDS[spec.country_code]
        cve_floor_str = spec.cve_min_ratio_pct or arch["cve_min_ratio_pct"]
        if Decimal(cve_floor_str) < Decimal("5.000"):
            raise QuotationAbstain("cve_independence_mandatory", "compliance_gate")

        from evidence_coverage.historical_quotation_calibrator import (
            calibrate_from_historical_corpus,
            extract_idp_physical_complexity,
            generate_reference_historical_corpus,
            ingest_historical_quotations,
            retrieve_nearest_historical_quotations,
        )

        idp_profile = extract_idp_physical_complexity(
            spec.idp_attachments,
            default_cosysmo=spec.cosysmo_complexity,
            default_idp_maturity=spec.idp_maturity,
        )
        effective_cosysmo = idp_profile.derived_cosysmo_complexity
        effective_idp_maturity = idp_profile.derived_idp_maturity
        idp_feat_factor = Decimal(idp_profile.idp_feature_complexity_factor)

        cert_factor = _CERT_BASIS_FACTORS[classification["cert_basis"]]
        mat_factor = _MATERIAL_FACTORS[classification["material_family"]]
        cosysmo_base = (
            Decimal(arch["default_cosysmo_factor"])
            * Decimal(_COSYSMO_FACTORS.get(effective_cosysmo.upper(), "1.000"))
            * idp_feat_factor
        )
        cosysmo_factor = format_quantum(cosysmo_base, _Q3)
        pvt_factor = arch["default_pvt_factor"]
        travel_hw = spec.extra_travel_hardware_eur or arch["default_travel_hardware_eur"]

        # IDP maturity contingency adjustment
        base_cont = Decimal(country_card["contingency_pct"])
        if effective_idp_maturity.upper() == "INCOMPLETE":
            base_cont += Decimal("6.000")
        elif effective_idp_maturity.upper() == "PARTIAL":
            base_cont += Decimal("3.000")
        contingency_str = format_quantum(base_cont, _Q3)

        historical_cal: dict[str, Any] = {}
        nearest_quotes: list[dict[str, Any]] = []
        if spec.use_historical_calibration:
            if spec.historical_corpus_path:
                ing = ingest_historical_quotations(spec.historical_corpus_path)
                corpus = ing["records"]
                corpus_origin = ing["corpus_origin"]
            else:
                corpus = generate_reference_historical_corpus()
                corpus_origin = "SYNTHETIC_BENCHMARK_ASSUMPTION"
            historical_cal = calibrate_from_historical_corpus(
                corpus,
                archetype_id=classification["archetype_id"],
                country_code=spec.country_code,
                idp_feature_factor=idp_profile.idp_feature_complexity_factor,
                corpus_origin=corpus_origin,
            )
            nearest_quotes = retrieve_nearest_historical_quotations(
                corpus,
                archetype_id=classification["archetype_id"],
                country_code=spec.country_code,
                cert_basis=classification["cert_basis"],
                material_family=classification["material_family"],
                cosysmo_complexity=effective_cosysmo,
                idp_maturity=effective_idp_maturity,
                fem_nodes_count=idp_profile.fem_nodes_count,
                load_cases_count=idp_profile.load_cases_count,
                cbush_joints_count=idp_profile.cbush_joints_count,
                cad_drawings_count=idp_profile.dxf_entities_count,
                ply_count=idp_profile.pcomp_laminates_count,
                k=spec.historical_top_k,
            )

        calc_inputs = _build_calc_inputs(
            arch,
            country_card,
            cert_basis_factor=cert_factor,
            material_complexity_factor=mat_factor,
            cosysmo_driver_factor=cosysmo_factor,
            pvt_compression_factor=pvt_factor,
            margin_pct=spec.target_margin_pct,
            travel_hardware_eur=travel_hw,
            cve_min_ratio_pct=cve_floor_str,
            contingency_override=contingency_str,
        )
        try:
            calc_res = run_method("rotorcraft_archetype_quote", calc_inputs, include_intervals=True)
        except AbstainError as exc:
            raise QuotationAbstain(
                "calc_guard_abstain", f"deterministic_calc:{exc.reason}"
            ) from exc

        pert_envelope, tornado = _compute_pert_and_tornado(
            arch, country_card, calc_inputs, calc_res
        )
        multi_country = compute_multi_country_comparison(
            arch,
            selected_country=spec.country_code,
            cert_basis_factor=cert_factor,
            material_complexity_factor=mat_factor,
            cosysmo_driver_factor=cosysmo_factor,
            pvt_compression_factor=pvt_factor,
            margin_pct=spec.target_margin_pct,
            travel_hardware_eur=travel_hw,
            cve_min_ratio_pct=cve_floor_str,
            nearshore_country=spec.nearshore_country,
        )
        assumptions_by_dim = build_archetype_assumptions(
            arch,
            country_card,
            cert_basis=classification["cert_basis"],
            material_family=classification["material_family"],
            idp_maturity=effective_idp_maturity,
            cosysmo_complexity=effective_cosysmo,
            export_control_restricted=spec.export_control_restricted,
            overrides=spec.assumption_overrides,
        )

        # Formal Z3 SMT proof over P80 quote envelope
        p80_price_d = Decimal(pert_envelope["price_p80_eur"])
        cost_m_d = Decimal(calc_res["outputs"]["total_cost_eur"])
        cost_p80_d = Decimal(pert_envelope["cost_p80_eur"])
        direct_ratio = Decimal(calc_res["outputs"]["direct_cost_eur"]) / cost_m_d
        p80_direct_baseline = format_quantum(cost_p80_d * direct_ratio, _Q3)
        p80_fixed_reserve = format_quantum(cost_p80_d - Decimal(p80_direct_baseline), _Q3)

        if spec.enable_formal_smt:
            formal_proof = prove_quotation_margin_envelope(
                quoted_price_p80_eur=format_quantum(p80_price_d, _Q3),
                direct_cost_baseline_eur=p80_direct_baseline,
                fixed_reserve_cost_eur=p80_fixed_reserve,
                min_acceptable_margin_pct=spec.min_acceptable_margin_pct,
            )
        else:
            formal_proof = {"status": "SKIPPED", "proved": False}
    except QuotationAbstain as exc:
        return _record_rotorcraft_abstain(
            ledger,
            spec,
            created_at=created_at,
            reason=exc.reason,
            stage=exc.stage,
        )

    # Seal deterministic calc + 8-agent workflow into cryptographic Ledger
    event_hashes: list[str] = []
    calc_env = make_envelope(
        sources=calc_res["sources"],
        method_version=calc_res["method_version"],
        inputs=calc_inputs,
        confidence="deterministic",
        result=calc_res["outputs"],
    )
    calc_ev = record(
        ledger,
        {
            "event_type": "calc",
            "tenant_id": ledger.tenant_id,
            "actor_id": spec.actor_id,
            "created_at": created_at,
            "payload": {
                "method_id": "rotorcraft_archetype_quote",
                "inputs": calc_inputs,
                "outputs": calc_res["outputs"],
            },
            "envelope": calc_env,
        },
    )
    event_hashes.append(calc_ev)

    total_assumptions = sum(len(v) for v in assumptions_by_dim.values())
    z3_proved = bool(formal_proof.get("proved", False))
    decision_status = (
        "APPROVED_FOR_HUMAN_REVIEW"
        if (z3_proved or not spec.enable_formal_smt)
        else "MARGIN_FLOOR_COUNTEREXAMPLE_HOLD"
    )

    agent_steps: tuple[tuple[str, str, dict[str, Any]], ...] = (
        ("rotorcraft_intake_reader", "reader", classification),
        (
            "archetype_taxonomy_checker",
            "checker",
            {
                "archetype_id": arch["archetype_id"],
                "easa_clauses": list(arch["easa_clauses"]),
                "department_roles": list(arch["department_roles"]),
                "research_models_count": len(RESEARCH_BENCHMARK_MODELS),
            },
        ),
        (
            "regional_rate_and_wbs_checker",
            "checker",
            {
                "country_code": spec.country_code,
                "quote_price_m_eur": calc_res["outputs"]["quote_price_eur"],
                "blended_rate_eur": calc_res["outputs"]["blended_hourly_rate_eur"],
                "countries_benchmarked": len(multi_country["countries"]),
            },
        ),
        (
            "rotorcraft_assumption_critic",
            "envelope_critic",
            {
                "dimensions_count": len(assumptions_by_dim),
                "total_assumptions": total_assumptions,
            },
        ),
        (
            "tornado_and_pert_sensitivity",
            "checker",
            {
                "price_p50_eur": pert_envelope["price_p50_eur"],
                "price_p80_eur": pert_envelope["price_p80_eur"],
                "price_p90_eur": pert_envelope["price_p90_eur"],
                "top_tornado_driver": tornado[0]["driver_key"] if tornado else "none",
            },
        ),
        (
            "commercial_refuter",
            "refuter",
            {
                "cve_share_pct": calc_res["outputs"]["cve_share_pct"],
                "export_regime": country_card["export_control_regime"],
                "fixed_price_share_pct": arch["fixed_price_share_pct"],
            },
        ),
        (
            "z3_formal_margin_gate",
            "decision_gate",
            {
                "z3_status": formal_proof.get("status", "SKIPPED"),
                "decision_status": decision_status,
            },
        ),
        (
            "dossier_scribe",
            "scribe",
            {"rfq_id": spec.rfq_id, "recommended_bid_percentile": "P80"},
        ),
    )

    agent_trace: list[dict[str, Any]] = []
    for role_name, l_agent_id, out_data in agent_steps:
        out_payload = {"quotation_agent_role": role_name, **out_data}
        t_env = make_envelope(
            sources=[
                project_source(
                    role_name,
                    f"https://aeroregu.local/rotorcraft/agents/{role_name}",
                    "ASSUMPTION",
                )
            ],
            method_version=f"{role_name}@1.0.0",
            inputs={"rfq_id": spec.rfq_id, "role": role_name},
            confidence="deterministic" if role_name == "regional_rate_and_wbs_checker" else "draft",
            result=out_payload,
        )
        ev_h = record(
            ledger,
            {
                "event_type": "agent_turn",
                "tenant_id": ledger.tenant_id,
                "actor_id": spec.actor_id,
                "created_at": created_at,
                "payload": {
                    "agent_id": l_agent_id,
                    "prompt_hash": prompt_hash(l_agent_id),
                    "temperature": "0",
                    "input_event_hashes": list(event_hashes),
                    "output": out_payload,
                    "envelope": t_env,
                },
                "envelope": t_env,
            },
        )
        event_hashes.append(ev_h)
        agent_trace.append(
            {
                "quotation_agent_role": role_name,
                "ledger_agent_id": l_agent_id,
                "event_hash": ev_h,
                "output": out_payload,
            }
        )

    merkle_root = ledger.merkle_root()
    safe_report_check = check_text_safety(
        f"Rotorcraft quotation {arch['archetype_id']} {arch['title']} for {spec.country_code}"
    )

    result: dict[str, Any] = {
        "rfq_id": spec.rfq_id,
        "tenant_id": ledger.tenant_id,
        "customer_name": spec.customer_name,
        "confidence": "deterministic",
        "decision_status": decision_status,
        "currency": spec.currency,
        "classification": classification,
        "archetype": arch,
        "country_profile": country_card,
        "research_models_applied": RESEARCH_BENCHMARK_MODELS,
        "calc_inputs": calc_inputs,
        "deterministic_quote": calc_res["outputs"],
        "arb_intervals": calc_res.get("exact_intervals", {}),
        "pert_envelope": pert_envelope,
        "tornado_sensitivity": tornado,
        "multi_country_comparison": multi_country,
        "idp_physical_extraction": asdict(idp_profile),
        "historical_calibration": historical_cal,
        "nearest_historical_quotes": nearest_quotes,
        "assumptions_dimensions_count": len(assumptions_by_dim),
        "assumptions_total_count": total_assumptions,
        "assumptions_by_dimension": assumptions_by_dim,
        "formal_margin_proof": formal_proof,
        "agent_trace": agent_trace,
        "event_hashes": event_hashes,
        "merkle_root": merkle_root,
        "safety_check": safe_report_check,
        "spec": asdict(spec),
        "advisory_boundary": (
            "Tool provides deterministic ASSUMPTION/ESTIMATE quotations to assist "
            "engineers and independent Part 21J CVEs; never determines compliance."
        ),
    }
    result["markdown_report"] = _render_markdown_dossier(result)
    return result
