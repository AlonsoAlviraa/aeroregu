"""8-Agent Supervised Automated Quotation & Exhaustive 7-Dimension Assumption Engine.

Strict separation of concerns:
- Specialist agents extract spans, decompose WBS, synthesize exhaustive 7-axis
  assumptions, audit export/compliance, refute adversarially, gate decisions,
  and assemble executive dossiers.
- ZERO numbers are computed by an LLM: every cost, PERT percentile (P50/P80/P90),
  Tornado sensitivity delta, and margin is computed by tested Decimal + FLINT/Arb
  methods in ``evidence_calc``, then formally checked across continuous assumption
  uncertainty bounds via Z3 SMT.
- Every agent turn, deterministic calculation, or ABSTAIN decision is hash-chained
  into the tamper-evident ``Ledger``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
from typing import Any, Literal

import z3
from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method
from evidence_kernel.canonical import inputs_hash
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.gateway import prompt_hash
from evidence_kernel.guardrails import check_text_safety
from evidence_kernel.ledger import Ledger
from evidence_kernel.numbers import DECIMAL_TOKEN, INTEGER_TOKEN, stray_physical_numbers
from evidence_kernel.orchestrator import record

ASSUMPTION_CATEGORIES: tuple[str, ...] = (
    "TECHNICAL_ENGINEERING",
    "MATERIAL_SUPPLY",
    "MANUFACTURING_TOOLING",
    "REGULATORY_COMPLIANCE",
    "COMMERCIAL_FINANCIAL",
    "SCHEDULE_LOGISTICS",
    "EXCLUSIONS_BOUNDARIES",
)

ASSUMPTION_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "TECHNICAL_ENGINEERING": (
        "CAD geometry maturity, load spectra, allowables basis (MMPDS/CMH-17), and FEA fidelity."
    ),
    "MATERIAL_SUPPLY": (
        "Alloy/composite spec, certification (EN 10204 3.1/AMS), buy-to-fly, and stock lead time."
    ),
    "MANUFACTURING_TOOLING": (
        "CNC/autoclave hourly rates, setup NRE, tooling amortization, GD&T, and NDT sampling."
    ),
    "REGULATORY_COMPLIANCE": (
        "AS9100/EN9100 QMS, EASA/FAA advisory boundary, REACH/RoHS, and export-control scope."
    ),
    "COMMERCIAL_FINANCIAL": (
        "Target/floor margins, overhead, PERT P80 contingency, payment terms, and quote validity."
    ),
    "SCHEDULE_LOGISTICS": (
        "Lead time ARO, customer review SLA turnaround, Incoterms 2020, and aerospace packaging."
    ),
    "EXCLUSIONS_BOUNDARIES": (
        "Explicit out-of-scope hardware/tests, authority fees, and ECN Change-Order thresholds."
    ),
}

MATERIAL_PRICE_CATALOG: dict[str, dict[str, str]] = {
    "Ti-6Al-4V": {
        "spec": "AMS 4911 / AMS 4928 Aerospace Grade 5 Titanium",
        "unit_cost_eur_kg": "145.000",
        "default_buy_to_fly": "4.800",
        "machining_hours_per_kg": "6.500",
        "lead_time_weeks": "14",
        "ndt_cost_per_part_eur": "320.000",
    },
    "Al 7075-T6": {
        "spec": "AMS 4045 / EN AW-7075-T651 High-Strength Aerospace Aluminum",
        "unit_cost_eur_kg": "24.500",
        "default_buy_to_fly": "3.600",
        "machining_hours_per_kg": "2.400",
        "lead_time_weeks": "8",
        "ndt_cost_per_part_eur": "140.000",
    },
    "Al 2024-T3": {
        "spec": "AMS 4037 Damage-Tolerant Aerospace Aluminum",
        "unit_cost_eur_kg": "22.000",
        "default_buy_to_fly": "3.200",
        "machining_hours_per_kg": "2.200",
        "lead_time_weeks": "8",
        "ndt_cost_per_part_eur": "130.000",
    },
    "Inconel 718": {
        "spec": "AMS 5662 / AMS 5663 Nickel-Chromium Superalloy",
        "unit_cost_eur_kg": "195.000",
        "default_buy_to_fly": "5.200",
        "machining_hours_per_kg": "8.500",
        "lead_time_weeks": "18",
        "ndt_cost_per_part_eur": "420.000",
    },
    "CFRP IM7-8552": {
        "spec": "Carbon/Epoxy Unidirectional Aerospace Prepreg (Autoclave Cure)",
        "unit_cost_eur_kg": "280.000",
        "default_buy_to_fly": "1.650",
        "machining_hours_per_kg": "7.200",
        "lead_time_weeks": "16",
        "ndt_cost_per_part_eur": "480.000",
    },
    "17-4PH Steel": {
        "spec": "AMS 5643 Precipitation-Hardening Stainless Steel",
        "unit_cost_eur_kg": "48.000",
        "default_buy_to_fly": "3.800",
        "machining_hours_per_kg": "4.200",
        "lead_time_weeks": "10",
        "ndt_cost_per_part_eur": "210.000",
    },
}

PROCESS_RATE_CARDS: dict[str, str] = {
    "machining_rate_eur_hr": "135.000",
    "engineering_rate_eur_hr": "125.000",
    "senior_stress_rate_eur_hr": "140.000",
    "cve_rate_eur_hr": "175.000",
    "tooling_nre_base_eur": "4500.000",
    "engineering_setup_hours_default": "32.000",
    "overhead_pct_default": "14.000",
    "risk_contingency_pct_default": "8.000",
    "rework_contingency_pct_default": "10.000",
    "pert_note_hours_optimistic": "12.000",
    "pert_note_hours_likely": "18.000",
    "pert_note_hours_pessimistic": "30.000",
    "hours_per_fem_model_default": "42.000",
    "cve_review_ratio_default": "0.200",
    "software_compute_surcharge_per_fem_eur": "450.000",
    "quote_validity_days": "30",
    "client_sla_review_days": "5",
    "included_ecn_cycles": "2",
    "payment_advance_pct": "30",
    "payment_cdr_pct": "40",
    "payment_fat_pct": "30",
}

_QUANTUM_2 = Decimal("0.01")
_QUANTUM_3 = Decimal("0.001")
_HUNDRED = Decimal("100")

_AGENT_ROSTER: tuple[dict[str, str], ...] = (
    {"quotation_role": "rfq_intake_agent", "ledger_agent_id": "reader"},
    {"quotation_role": "scope_wbs_agent", "ledger_agent_id": "reader"},
    {"quotation_role": "assumption_generator_agent", "ledger_agent_id": "checker"},
    {"quotation_role": "deterministic_cost_engine", "ledger_agent_id": "checker"},
    {"quotation_role": "compliance_export_agent", "ledger_agent_id": "envelope_critic"},
    {"quotation_role": "adversarial_quote_refuter", "ledger_agent_id": "refuter"},
    {"quotation_role": "decision_gate_agent", "ledger_agent_id": "decision_gate"},
    {"quotation_role": "quotation_scribe_agent", "ledger_agent_id": "scribe"},
)


class QuotationAbstain(Exception):
    """Fail-closed abstention raised when a quotation violates integrity or safety checks."""

    def __init__(self, reason: str, stage: str = "pipeline") -> None:
        super().__init__(reason)
        self.reason = reason
        self.stage = stage


@dataclass(frozen=True)
class AssumptionRecord:
    assumption_id: str
    category: str
    label: str
    parameter_name: str
    assumed_value: str
    unit: str
    rationale: str
    trigger_condition: str
    cost_sensitivity_pct: str
    contractual_fallback: str
    source_span: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WBSLineItem:
    line_id: str
    title: str
    category: str
    quantity: str
    unit: str
    unit_rate: str
    subtotal: str
    method_id: str
    assumption_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["assumption_ids"] = list(self.assumption_ids)
        return data


@dataclass
class QuotationRequestSpec:
    rfq_text: str
    quotation_kind: Literal[
        "aerospace_manufacturing", "engineering_workpackage", "hybrid_turnkey"
    ] = "hybrid_turnkey"
    tenant_id: str = "demo"
    actor_id: str = "author"
    created_at: str | None = None
    currency: str = "EUR"
    target_margin_pct: str = "22.000"
    min_acceptable_margin_pct: str = "10.000"
    explicit_params: dict[str, Any] = field(default_factory=dict)
    bom_items: list[dict[str, Any]] = field(default_factory=list)
    assumption_overrides: dict[str, Any] = field(default_factory=dict)
    enable_formal_smt: bool = True
    export_control_restricted: bool = False
    customer_name: str = "Aerospace Client"
    rfq_id: str = "RFQ-AUTO-001"


@dataclass
class QuotationDossier:
    rfq_id: str
    tenant_id: str
    quotation_kind: str
    confidence: str
    decision_status: str
    currency: str
    abstain_reason: str | None = None
    escalate_to: str | None = None
    extracted_spans: list[dict[str, Any]] = field(default_factory=list)
    wbs_items: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    assumptions_by_category: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    cost_breakdown: dict[str, Any] = field(default_factory=dict)
    pert_summary: dict[str, Any] = field(default_factory=dict)
    sensitivity_matrix: list[dict[str, Any]] = field(default_factory=list)
    arb_intervals: dict[str, Any] = field(default_factory=dict)
    formal_margin_proof: dict[str, Any] | None = None
    compliance_audit: dict[str, Any] = field(default_factory=dict)
    adversarial_review: dict[str, Any] = field(default_factory=dict)
    agent_turns: list[dict[str, Any]] = field(default_factory=list)
    event_hashes: list[str] = field(default_factory=list)
    merkle_root: str = ""
    markdown_report: str = ""
    disclaimer: str = (
        "This quotation engine assists human estimators and engineers. "
        "It does not determine regulatory compliance or execute binding commercial offers."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_quotation_catalog() -> dict[str, Any]:
    """Return deterministic rate cards, materials, and 7-dimension assumption taxonomy."""
    return {
        "assumption_categories": [
            {
                "category": cat,
                "description": ASSUMPTION_CATEGORY_DESCRIPTIONS[cat],
            }
            for cat in ASSUMPTION_CATEGORIES
        ],
        "materials": MATERIAL_PRICE_CATALOG,
        "process_rate_cards": PROCESS_RATE_CARDS,
        "agent_roster": list(_AGENT_ROSTER),
    }


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _q3(val: Decimal) -> str:
    return format(val.quantize(_QUANTUM_3, rounding=ROUND_HALF_EVEN), "f")


def _q2(val: Decimal) -> str:
    return format(val.quantize(_QUANTUM_2, rounding=ROUND_HALF_EVEN), "f")


def _to_dec(raw: Any, field_name: str) -> Decimal:
    try:
        d = Decimal(str(raw))
    except Exception as exc:
        raise QuotationAbstain(f"invalid_decimal:{field_name}", stage="intake") from exc
    if not d.is_finite():
        raise QuotationAbstain(f"non_finite:{field_name}", stage="intake")
    return d


def _find_span(text: str, pattern: str, label: str) -> dict[str, Any] | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        return None
    s, e = match.span()
    return {
        "field": label,
        "quotation": text[s:e],
        "span_start": str(s),
        "span_end": str(e),
    }


def _extract_int_or_dec_from_text(
    text: str, patterns: tuple[str, ...]
) -> tuple[str | None, dict[str, Any] | None]:
    for idx, pat in enumerate(patterns):
        m = re.search(pat, text, re.IGNORECASE)
        if m is not None:
            val = m.group(1)
            s, e = m.span(0)
            return val, {
                "field": f"extracted_{idx}",
                "quotation": text[s:e],
                "span_start": str(s),
                "span_end": str(e),
            }
    return None, None


def _run_rfq_intake_agent(spec: QuotationRequestSpec) -> dict[str, Any]:
    """Agent 1: Parse RFQ text, validate safety, and extract literal spans."""
    text = (spec.rfq_text or "").strip()
    if not text:
        raise QuotationAbstain("empty_rfq_text", stage="rfq_intake_agent")

    safety_reason = check_text_safety(text)
    if safety_reason is not None:
        raise QuotationAbstain(f"safety_guardrail:{safety_reason}", stage="rfq_intake_agent")

    # Detect explicit adversarial or contradictory commercial instructions in text
    lower_txt = text.lower()
    if any(
        bad in lower_txt
        for bad in (
            "negative margin",
            "margin <= 0",
            "zero cost mandatory",
            "ignore export control",
            "bypass as9100",
        )
    ):
        raise QuotationAbstain("contradictory_or_unsafe_rfq_constraint", stage="rfq_intake_agent")

    spans: list[dict[str, Any]] = []

    rfq_id_match = re.search(r"\b(RFQ[-_][A-Z0-9-]+)\b", text, re.IGNORECASE)
    rfq_id = rfq_id_match.group(1) if rfq_id_match else spec.rfq_id
    if rfq_id_match:
        s, e = rfq_id_match.span(1)
        spans.append(
            {"field": "rfq_id", "quotation": text[s:e], "span_start": str(s), "span_end": str(e)}
        )

    qty_val, qty_span = _extract_int_or_dec_from_text(
        text,
        (
            r"(?:supply|manufacture|deliver|qty|quantity|units?|parts?|lot\s+of)\s*[:=]?\s*(\d+)\b",
            r"\b(\d+)\s+(?:units?|parts?|brackets?|fittings?|assemblies?|components?)\b",
        ),
    )
    if qty_span:
        qty_span["field"] = "part_quantity"
        spans.append(qty_span)

    mass_val, mass_span = _extract_int_or_dec_from_text(
        text,
        (
            r"(\d+(?:\.\d+)?)\s*kg\b",
            r"(?:mass|weight)\s*[:=]?\s*(\d+(?:\.\d+)?)\b",
        ),
    )
    if mass_span:
        mass_span["field"] = "finished_mass_kg"
        spans.append(mass_span)

    notes_val, notes_span = _extract_int_or_dec_from_text(
        text,
        (
            r"(\d+)\s+(?:structural\s+)?(?:stress\s+)?(?:calculation|calc)\s+notes?\b",
            r"(?:notes?)\s*[:=]\s*(\d+)\b",
        ),
    )
    if notes_span:
        notes_span["field"] = "calc_notes_count"
        spans.append(notes_span)

    fem_val, fem_span = _extract_int_or_dec_from_text(
        text,
        (
            r"(\d+)\s+(?:nastran|abaqus|ansys|fem|fea)\s+models?\b",
            r"(?:fem_models)\s*[:=]\s*(\d+)\b",
        ),
    )
    if fem_span:
        fem_span["field"] = "fem_models_count"
        spans.append(fem_span)

    lead_val, lead_span = _extract_int_or_dec_from_text(
        text,
        (
            r"(\d+)\s+weeks?\b",
            r"(?:lead\s*time|delivery)\s*[:=]?\s*(\d+)\s*w\b",
        ),
    )
    if lead_span:
        lead_span["field"] = "requested_lead_weeks"
        spans.append(lead_span)

    detected_material: str | None = None
    mat_aliases = {
        "Ti-6Al-4V": (r"\bTi-?6Al-?4V\b", r"\btitanium\b"),
        "Al 7075-T6": (r"\bAl\s*7075(?:-T6\d*)?\b", r"\b7075-T6\b"),
        "Al 2024-T3": (r"\bAl\s*2024(?:-T3\d*)?\b", r"\b2024-T3\b"),
        "Inconel 718": (r"\bInconel\s*718\b",),
        "CFRP IM7-8552": (r"\bCFRP\b", r"\bIM7\b", r"\bcarbon\s*fiber\b", r"\bcomposite\b"),
        "17-4PH Steel": (r"\b17-4\s*PH\b", r"\b17-4PH\b"),
    }
    for mat_name, mat_pats in mat_aliases.items():
        for mp in mat_pats:
            sp = _find_span(text, mp, "material_grade")
            if sp is not None:
                detected_material = mat_name
                spans.append(sp)
                break
        if detected_material:
            break

    reg_standards: list[str] = []
    for reg_pat, reg_label in (
        (r"\bCS-27\b", "EASA CS-27"),
        (r"\bCS-29\b", "EASA CS-29"),
        (r"\bSC-VTOL\b", "EASA SC-VTOL"),
        (r"\bPart\s*21\b", "EASA Part 21"),
        (r"\bAS\s*9100\b|\bEN\s*9100\b", "AS9100 / EN9100"),
        (r"\bDO-178C\b|\bDO-330\b", "DO-178C / DO-330"),
        (r"\bREACH\b", "EU REACH"),
        (r"\bITAR\b|\bEAR\b", "US ITAR/EAR"),
        (r"\b2021/821\b|\bdual-use\b", "EU Dual-Use 2021/821"),
    ):
        sp = _find_span(text, reg_pat, f"standard:{reg_label}")
        if sp is not None:
            reg_standards.append(reg_label)
            spans.append(sp)

    has_cnc = bool(
        re.search(r"\b(?:cnc|5-axis|machin|milling|turning|bracket|fitting)\b", lower_txt)
    )
    has_ndt = bool(re.search(r"\b(?:ndt|ultrasonic|penetrant|x-ray|radiograph)\b", lower_txt))
    has_stress = bool(
        notes_val
        or fem_val
        or re.search(r"\b(?:stress|nastran|abaqus|fem|fea|margin)\b", lower_txt)
    )

    # Merge explicit overrides cleanly
    exp = dict(spec.explicit_params or {})
    if spec.bom_items:
        total_bom_qty = sum(int(item.get("quantity", 1)) for item in spec.bom_items)
        if not qty_val and total_bom_qty > 0:
            qty_val = str(total_bom_qty)
        if not mass_val:
            total_bom_mass = sum(
                Decimal(str(item.get("mass_kg", "0"))) * Decimal(str(item.get("quantity", 1)))
                for item in spec.bom_items
            )
            if total_bom_qty > 0 and total_bom_mass > 0:
                mass_val = _q3(total_bom_mass / Decimal(total_bom_qty))

    part_quantity = str(exp.get("part_quantity") or qty_val or "10")
    finished_mass_kg = str(exp.get("finished_mass_kg") or mass_val or "1.500")
    material_grade = str(exp.get("material_grade") or detected_material or "Ti-6Al-4V")
    if material_grade not in MATERIAL_PRICE_CATALOG:
        material_grade = "Ti-6Al-4V"

    calc_notes_count = str(exp.get("calc_notes_count") or notes_val or ("4" if has_stress else "0"))
    fem_models_count = str(exp.get("fem_models_count") or fem_val or ("1" if has_stress else "0"))
    if (
        spec.quotation_kind == "engineering_workpackage"
        and int(calc_notes_count) == 0
        and int(fem_models_count) == 0
    ):
        calc_notes_count = "4"
        fem_models_count = "1"

    # Validate non-negative/positive basic bounds immediately
    if _to_dec(part_quantity, "part_quantity") <= 0:
        raise QuotationAbstain("non_positive_quantity", stage="rfq_intake_agent")
    if _to_dec(finished_mass_kg, "finished_mass_kg") <= 0:
        raise QuotationAbstain("non_positive_mass", stage="rfq_intake_agent")

    return {
        "rfq_id": rfq_id,
        "extracted_spans": spans,
        "verified_from_rfq": {
            "part_quantity": qty_val is not None or "part_quantity" in exp,
            "finished_mass_kg": mass_val is not None or "finished_mass_kg" in exp,
            "material_grade": detected_material is not None or "material_grade" in exp,
            "calc_notes_count": notes_val is not None or "calc_notes_count" in exp,
            "fem_models_count": fem_val is not None or "fem_models_count" in exp,
            "requested_lead_weeks": lead_val is not None,
        },
        "raw_parameters": {
            "part_quantity": part_quantity,
            "finished_mass_kg": finished_mass_kg,
            "material_grade": material_grade,
            "calc_notes_count": calc_notes_count,
            "fem_models_count": fem_models_count,
            "requested_lead_weeks": lead_val,
            "has_cnc": has_cnc,
            "has_ndt": has_ndt,
            "has_stress": has_stress,
            "regulatory_standards": reg_standards or ["EASA CS-29", "AS9100 / EN9100"],
        },
    }


def _run_scope_wbs_agent(
    spec: QuotationRequestSpec,
    intake: dict[str, Any],
) -> dict[str, Any]:
    """Agent 2: Plan engineering & manufacturing Work Breakdown Structure (WBS)."""
    raw = intake["raw_parameters"]
    mat_info = MATERIAL_PRICE_CATALOG[raw["material_grade"]]
    exp = dict(spec.explicit_params or {})
    ov = dict(spec.assumption_overrides or {})

    include_mfg = spec.quotation_kind in {"aerospace_manufacturing", "hybrid_turnkey"}
    include_eng = spec.quotation_kind in {"engineering_workpackage", "hybrid_turnkey"} and (
        int(raw["calc_notes_count"]) > 0 or int(raw["fem_models_count"]) > 0
    )

    mass_dec = _to_dec(raw["finished_mass_kg"], "finished_mass_kg")
    mach_hrs_per_kg = _to_dec(mat_info["machining_hours_per_kg"], "machining_hours_per_kg")
    default_mach_hrs = _q3(max(Decimal("1.500"), mass_dec * mach_hrs_per_kg))

    mfg_inputs: dict[str, Any] = {}
    if include_mfg:
        mfg_inputs = {
            "part_quantity": str(raw["part_quantity"]),
            "finished_mass_kg": str(raw["finished_mass_kg"]),
            "buy_to_fly_ratio": str(
                ov.get("buy_to_fly_ratio")
                or exp.get("buy_to_fly_ratio")
                or mat_info["default_buy_to_fly"]
            ),
            "material_unit_cost_eur_kg": str(
                ov.get("material_unit_cost_eur_kg")
                or exp.get("material_unit_cost_eur_kg")
                or mat_info["unit_cost_eur_kg"]
            ),
            "machining_hours_per_part": str(
                ov.get("machining_hours_per_part")
                or exp.get("machining_hours_per_part")
                or default_mach_hrs
            ),
            "machining_rate_eur_hr": str(
                ov.get("machining_rate_eur_hr")
                or exp.get("machining_rate_eur_hr")
                or PROCESS_RATE_CARDS["machining_rate_eur_hr"]
            ),
            "engineering_setup_hours": str(
                ov.get("engineering_setup_hours")
                or exp.get("engineering_setup_hours")
                or PROCESS_RATE_CARDS["engineering_setup_hours_default"]
            ),
            "engineering_rate_eur_hr": str(
                ov.get("engineering_rate_eur_hr")
                or exp.get("engineering_rate_eur_hr")
                or PROCESS_RATE_CARDS["engineering_rate_eur_hr"]
            ),
            "ndt_qa_cost_per_part_eur": str(
                ov.get("ndt_qa_cost_per_part_eur")
                or exp.get("ndt_qa_cost_per_part_eur")
                or mat_info["ndt_cost_per_part_eur"]
            ),
            "tooling_nre_eur": str(
                ov.get("tooling_nre_eur")
                or exp.get("tooling_nre_eur")
                or PROCESS_RATE_CARDS["tooling_nre_base_eur"]
            ),
            "risk_contingency_pct": str(
                ov.get("risk_contingency_pct")
                or exp.get("risk_contingency_pct")
                or PROCESS_RATE_CARDS["risk_contingency_pct_default"]
            ),
            "overhead_pct": str(
                ov.get("overhead_pct")
                or exp.get("overhead_pct")
                or PROCESS_RATE_CARDS["overhead_pct_default"]
            ),
            "target_margin_pct": str(ov.get("target_margin_pct") or spec.target_margin_pct),
        }

    eng_inputs: dict[str, Any] = {}
    if include_eng:
        fem_cnt = _to_dec(raw["fem_models_count"], "fem_models_count")
        surcharge_per_fem = _to_dec(
            PROCESS_RATE_CARDS["software_compute_surcharge_per_fem_eur"], "surcharge"
        )
        eng_inputs = {
            "calc_notes_count": str(raw["calc_notes_count"]),
            "hours_per_calc_note_optimistic": str(
                ov.get("hours_per_calc_note_optimistic")
                or exp.get("hours_per_calc_note_optimistic")
                or PROCESS_RATE_CARDS["pert_note_hours_optimistic"]
            ),
            "hours_per_calc_note_likely": str(
                ov.get("hours_per_calc_note_likely")
                or exp.get("hours_per_calc_note_likely")
                or PROCESS_RATE_CARDS["pert_note_hours_likely"]
            ),
            "hours_per_calc_note_pessimistic": str(
                ov.get("hours_per_calc_note_pessimistic")
                or exp.get("hours_per_calc_note_pessimistic")
                or PROCESS_RATE_CARDS["pert_note_hours_pessimistic"]
            ),
            "fem_models_count": str(raw["fem_models_count"]),
            "hours_per_fem_model": str(
                ov.get("hours_per_fem_model")
                or exp.get("hours_per_fem_model")
                or PROCESS_RATE_CARDS["hours_per_fem_model_default"]
            ),
            "cve_review_ratio": str(
                ov.get("cve_review_ratio")
                or exp.get("cve_review_ratio")
                or PROCESS_RATE_CARDS["cve_review_ratio_default"]
            ),
            "senior_rate_eur_hr": str(
                ov.get("senior_rate_eur_hr")
                or exp.get("senior_rate_eur_hr")
                or PROCESS_RATE_CARDS["senior_stress_rate_eur_hr"]
            ),
            "cve_rate_eur_hr": str(
                ov.get("cve_rate_eur_hr")
                or exp.get("cve_rate_eur_hr")
                or PROCESS_RATE_CARDS["cve_rate_eur_hr"]
            ),
            "software_compute_surcharge_eur": str(
                ov.get("software_compute_surcharge_eur")
                or exp.get("software_compute_surcharge_eur")
                or _q3(fem_cnt * surcharge_per_fem)
            ),
            "rework_contingency_pct": str(
                ov.get("rework_contingency_pct")
                or exp.get("rework_contingency_pct")
                or PROCESS_RATE_CARDS["rework_contingency_pct_default"]
            ),
            "target_margin_pct": str(ov.get("target_margin_pct") or spec.target_margin_pct),
        }

    return {
        "include_mfg": include_mfg,
        "include_eng": include_eng,
        "mfg_inputs": mfg_inputs,
        "eng_inputs": eng_inputs,
        "material_grade": raw["material_grade"],
        "material_spec": mat_info,
        "regulatory_standards": raw["regulatory_standards"],
        "requested_lead_weeks": raw["requested_lead_weeks"],
    }


def _run_assumption_generator_agent(
    spec: QuotationRequestSpec,
    intake: dict[str, Any],
    wbs_plan: dict[str, Any],
) -> list[AssumptionRecord]:
    """Agent 3: Exhaustively synthesize assumptions across all 7 mandatory categories."""
    verified_flags = intake["verified_from_rfq"]
    spans_by_field = {sp["field"]: sp for sp in intake["extracted_spans"]}
    mat_name = wbs_plan["material_grade"]
    mat_spec = wbs_plan["material_spec"]
    mfg_in = wbs_plan["mfg_inputs"]
    eng_in = wbs_plan["eng_inputs"]

    lead_weeks = str(wbs_plan.get("requested_lead_weeks") or mat_spec["lead_time_weeks"])
    btf_val = str(mfg_in.get("buy_to_fly_ratio") or mat_spec["default_buy_to_fly"])
    mat_cost = str(mfg_in.get("material_unit_cost_eur_kg") or mat_spec["unit_cost_eur_kg"])
    mach_hrs = str(mfg_in.get("machining_hours_per_part") or "0.000")
    mach_rate = str(
        mfg_in.get("machining_rate_eur_hr") or PROCESS_RATE_CARDS["machining_rate_eur_hr"]
    )
    tooling_nre = str(mfg_in.get("tooling_nre_eur") or PROCESS_RATE_CARDS["tooling_nre_base_eur"])
    ndt_cost = str(mfg_in.get("ndt_qa_cost_per_part_eur") or mat_spec["ndt_cost_per_part_eur"])
    risk_pct = str(
        mfg_in.get("risk_contingency_pct") or PROCESS_RATE_CARDS["risk_contingency_pct_default"]
    )
    overhead_pct = str(mfg_in.get("overhead_pct") or PROCESS_RATE_CARDS["overhead_pct_default"])
    margin_pct = str(
        mfg_in.get("target_margin_pct") or eng_in.get("target_margin_pct") or spec.target_margin_pct
    )

    h_opt = str(
        eng_in.get("hours_per_calc_note_optimistic")
        or PROCESS_RATE_CARDS["pert_note_hours_optimistic"]
    )
    h_lik = str(
        eng_in.get("hours_per_calc_note_likely") or PROCESS_RATE_CARDS["pert_note_hours_likely"]
    )
    h_pes = str(
        eng_in.get("hours_per_calc_note_pessimistic")
        or PROCESS_RATE_CARDS["pert_note_hours_pessimistic"]
    )
    cve_ratio = str(
        eng_in.get("cve_review_ratio") or PROCESS_RATE_CARDS["cve_review_ratio_default"]
    )
    rework_pct = str(
        eng_in.get("rework_contingency_pct") or PROCESS_RATE_CARDS["rework_contingency_pct_default"]
    )

    records: list[AssumptionRecord] = [
        # 1. TECHNICAL_ENGINEERING
        AssumptionRecord(
            assumption_id="ASM-TECH-001",
            category="TECHNICAL_ENGINEERING",
            label="ASSUMPTION",
            parameter_name="cad_geometry_readiness",
            assumed_value="STEP AP242 clean B-Rep solid + frozen GD&T rev",
            unit="dimensionless",
            rationale=(
                "RFQ lacks native CATIA/STEP validation; assumes watertight B-Rep solids "
                "without manual CAD repair."
            ),
            trigger_condition="missing_from_rfq:cad_quality_gate",
            cost_sensitivity_pct="4.00",
            contractual_fallback=(
                "Missing or corrupt CAD surfaces trigger NRE geometry healing at engineering "
                "hourly rate via Change Order."
            ),
            source_span=spans_by_field.get("finished_mass_kg"),
        ),
        AssumptionRecord(
            assumption_id="ASM-TECH-002",
            category="TECHNICAL_ENGINEERING",
            label="ASSUMPTION",
            parameter_name="stress_allowables_basis",
            assumed_value="MMPDS-16 / CMH-17 B-Basis metallic & composite allowables",
            unit="dimensionless",
            rationale=(
                "Design stress margins assume published B-basis allowables under RTD/ETW "
                "conditions without custom coupon test campaigns."
            ),
            trigger_condition="implicit_domain_requirement:allowables",
            cost_sensitivity_pct="5.50",
            contractual_fallback=(
                "A-basis knockdown or proprietary OEM test allowables require re-issue "
                "of calculation notes as an addendum."
            ),
            source_span=spans_by_field.get("calc_notes_count"),
        ),
        AssumptionRecord(
            assumption_id="ASM-TECH-003",
            category="TECHNICAL_ENGINEERING",
            label="ESTIMATE",
            parameter_name="pert_calc_note_effort_bounds",
            assumed_value=f"O={h_opt}h / M={h_lik}h / P={h_pes}h per note",
            unit="hour",
            rationale=(
                "Structural calc note effort varies with load-case count; 3-point PERT "
                "bounds capture complexity uncertainty up to P80."
            ),
            trigger_condition="missing_from_rfq:engineering_hours",
            cost_sensitivity_pct="7.50",
            contractual_fallback=(
                "Additional flight load envelopes or nonlinear contact iterations beyond "
                "P80 hours are billed T&M."
            ),
            source_span=spans_by_field.get("calc_notes_count"),
        ),
        AssumptionRecord(
            assumption_id="ASM-TECH-004",
            category="TECHNICAL_ENGINEERING",
            label="ASSUMPTION",
            parameter_name="cve_independent_review_ratio",
            assumed_value=cve_ratio,
            unit="dimensionless",
            rationale=(
                "Enforces Segregation of Duties (Author != CVE) with independent "
                "Compliance Verification Engineer review coverage."
            ),
            trigger_condition="implicit_domain_requirement:sod_cve_review",
            cost_sensitivity_pct="2.80",
            contractual_fallback=(
                "Additional witness audits requested by the customer authority "
                "are billed separately."
            ),
            source_span=None,
        ),
        # 2. MATERIAL_SUPPLY
        AssumptionRecord(
            assumption_id="ASM-MAT-001",
            category="MATERIAL_SUPPLY",
            label="VERIFIED" if verified_flags["material_grade"] else "ASSUMPTION",
            parameter_name="material_grade_certification",
            assumed_value=f"{mat_name} ({mat_spec['spec']})",
            unit="dimensionless",
            rationale=(
                "Material billet/prepreg requires full lot traceability "
                "(EN 10204 3.1 / AMS aerospace melt certification)."
            ),
            trigger_condition="rfq_spec_binding"
            if verified_flags["material_grade"]
            else "missing_from_rfq:material_spec",
            cost_sensitivity_pct="6.00",
            contractual_fallback=(
                "Substitution to exotic or dual-certified melt grades adjusts raw "
                "material cost 1:1 plus mill MOQ."
            ),
            source_span=spans_by_field.get("material_grade"),
        ),
        AssumptionRecord(
            assumption_id="ASM-MAT-002",
            category="MATERIAL_SUPPLY",
            label="ESTIMATE",
            parameter_name="buy_to_fly_ratio",
            assumed_value=btf_val,
            unit="dimensionless",
            rationale=(
                "Accounts for pocket hog-out, billet bar sizing, and fixture clamping "
                "stock allowance before finish 5-axis machining."
            ),
            trigger_condition="missing_from_rfq:raw_stock_envelope",
            cost_sensitivity_pct="6.50",
            contractual_fallback=(
                "Final nesting on frozen 3D STEP model adjusts buy-to-fly ratio "
                "if raw billet exceeds +15% variance."
            ),
            source_span=spans_by_field.get("finished_mass_kg"),
        ),
        AssumptionRecord(
            assumption_id="ASM-MAT-003",
            category="MATERIAL_SUPPLY",
            label="ESTIMATE",
            parameter_name="material_unit_cost_eur_kg",
            assumed_value=mat_cost,
            unit="EUR/kg",
            rationale=(
                "Indexed to current aerospace mill distributor quotes valid for "
                "30 calendar days from quotation issue."
            ),
            trigger_condition="market_volatility:mill_surcharge",
            cost_sensitivity_pct="5.20",
            contractual_fallback=(
                "Raw alloy/prepreg price indexed at Purchase Order date if mill "
                "surcharge changes >5%."
            ),
            source_span=None,
        ),
        # 3. MANUFACTURING_TOOLING
        AssumptionRecord(
            assumption_id="ASM-MFG-001",
            category="MANUFACTURING_TOOLING",
            label="ESTIMATE",
            parameter_name="machining_hours_and_rate",
            assumed_value=f"{mach_hrs} h/part @ {mach_rate} EUR/h",
            unit="hour",
            rationale=(
                "Assumes simultaneous 5-axis CNC machining with standard aerospace "
                "flood coolant and automated probing."
            ),
            trigger_condition="missing_from_rfq:routing_cycle_time",
            cost_sensitivity_pct="8.00",
            contractual_fallback=(
                "Tighter surface finishes (<Ra 0.8 um) or thin-wall (<1.2 mm) "
                "chatter suppression revise cycle hours."
            ),
            source_span=spans_by_field.get("part_quantity"),
        ),
        AssumptionRecord(
            assumption_id="ASM-MFG-002",
            category="MANUFACTURING_TOOLING",
            label="ASSUMPTION",
            parameter_name="tooling_nre_eur",
            assumed_value=tooling_nre,
            unit="EUR",
            rationale=(
                "Covers dedicated soft-jaw workholding, CMM inspection fixtures, "
                "and NC post-processor verification for one part."
            ),
            trigger_condition="missing_from_rfq:tooling_ownership",
            cost_sensitivity_pct="3.20",
            contractual_fallback=(
                "Customer-owned hard production dies or multi-cavity assembly jigs "
                "are quoted as separate NRE."
            ),
            source_span=None,
        ),
        AssumptionRecord(
            assumption_id="ASM-MFG-003",
            category="MANUFACTURING_TOOLING",
            label="ASSUMPTION",
            parameter_name="ndt_qa_cost_per_part_eur",
            assumed_value=ndt_cost,
            unit="EUR/part",
            rationale=(
                "Includes 100% dimensional CMM report (FAI AS9102) and "
                "dye-penetrant/ultrasonic NDT per lot."
            ),
            trigger_condition="implicit_domain_requirement:aerospace_ndt",
            cost_sensitivity_pct="2.40",
            contractual_fallback=(
                "Radiographic X-ray or Class-A ultrasonic immersion scanning adds "
                "pass-through third-party lab fees."
            ),
            source_span=None,
        ),
        # 4. REGULATORY_COMPLIANCE
        AssumptionRecord(
            assumption_id="ASM-REG-001",
            category="REGULATORY_COMPLIANCE",
            label="ASSUMPTION",
            parameter_name="qms_and_advisory_boundary",
            assumed_value=", ".join(wbs_plan["regulatory_standards"]),
            unit="dimensionless",
            rationale=(
                "Work follows AS9100/EN9100 traceability; tool outputs assist human "
                "engineers and never claim automatic authority certification."
            ),
            trigger_condition="implicit_domain_requirement:regulatory_scope",
            cost_sensitivity_pct="3.00",
            contractual_fallback=(
                "Additional national authority Special Conditions or DO-330 TQL-5 "
                "qualification artifacts require scope addendum."
            ),
            source_span=None,
        ),
        AssumptionRecord(
            assumption_id="ASM-REG-002",
            category="REGULATORY_COMPLIANCE",
            label="ASSUMPTION",
            parameter_name="export_control_and_reach",
            assumed_value=(
                "EU Reg. 2021/821 Dual-Use & REACH/RoHS compliant baseline (Non-ITAR assumed)"
            ),
            unit="dimensionless",
            rationale=(
                "Assumes technical data package contains no US ITAR/EAR controlled "
                "technical data requiring segregated US-person enclaves."
            ),
            trigger_condition="export_control_gate:default_non_itar",
            cost_sensitivity_pct="4.50",
            contractual_fallback=(
                "Any ITAR/EAR classification disclosed after award triggers immediate "
                "hold and compliance surcharge."
            ),
            source_span=None,
        ),
        # 5. COMMERCIAL_FINANCIAL
        AssumptionRecord(
            assumption_id="ASM-COM-001",
            category="COMMERCIAL_FINANCIAL",
            label="ASSUMPTION",
            parameter_name="target_and_floor_margin",
            assumed_value=f"Target={margin_pct}% / Floor={spec.min_acceptable_margin_pct}%",
            unit="percent",
            rationale=(
                "Gross margin target funds engineering risk, working capital, and "
                "formal Z3 margin floor protection."
            ),
            trigger_condition="commercial_policy:margin_guardrail",
            cost_sensitivity_pct="10.00",
            contractual_fallback=("Volume discounts apply only under firm multi-year blanket POs."),
            source_span=None,
        ),
        AssumptionRecord(
            assumption_id="ASM-COM-002",
            category="COMMERCIAL_FINANCIAL",
            label="ESTIMATE",
            parameter_name="risk_and_rework_contingency",
            assumed_value=(
                f"Mfg Risk={risk_pct}% | Eng Rework={rework_pct}% | Overhead={overhead_pct}%"
            ),
            unit="percent",
            rationale=(
                "Captures unmodeled setup scrap, ECN rework loops, and indirect "
                "facility overhead across P80 confidence band."
            ),
            trigger_condition="uncertainty_buffer:p80_reserve",
            cost_sensitivity_pct="6.00",
            contractual_fallback=(
                "Unused contingency is internal risk reserve; fixed-price assumes "
                "P80 risk absorption."
            ),
            source_span=None,
        ),
        AssumptionRecord(
            assumption_id="ASM-COM-003",
            category="COMMERCIAL_FINANCIAL",
            label="ASSUMPTION",
            parameter_name="payment_terms_and_validity",
            assumed_value=(
                f"{PROCESS_RATE_CARDS['payment_advance_pct']}/"
                f"{PROCESS_RATE_CARDS['payment_cdr_pct']}/"
                f"{PROCESS_RATE_CARDS['payment_fat_pct']}% milestones | "
                f"{PROCESS_RATE_CARDS['quote_validity_days']} days validity ({spec.currency})"
            ),
            unit="dimensionless",
            rationale=(
                "30% advance at PO covers raw titanium/prepreg procurement; "
                "40% at CDR/FAI; 30% net-30 on delivery."
            ),
            trigger_condition="missing_from_rfq:payment_schedule",
            cost_sensitivity_pct="1.50",
            contractual_fallback=(
                "Extended net-90/120 payment terms incur 1.8% financing surcharge."
            ),
            source_span=None,
        ),
        # 6. SCHEDULE_LOGISTICS
        AssumptionRecord(
            assumption_id="ASM-SCH-001",
            category="SCHEDULE_LOGISTICS",
            label="ESTIMATE",
            parameter_name="nominal_lead_time_aro",
            assumed_value=f"{lead_weeks} weeks ARO",
            unit="week",
            rationale=(
                "Includes raw stock procurement, CAM/Stress execution, CNC machining, "
                "NDT, and AS9102 FAI pack."
            ),
            trigger_condition="rfq_schedule_target"
            if wbs_plan.get("requested_lead_weeks")
            else "missing_from_rfq:delivery_schedule",
            cost_sensitivity_pct="4.20",
            contractual_fallback=(
                "Expedited AOG schedule (<60% nominal weeks) incurs 18% overtime "
                "& priority mill fee."
            ),
            source_span=spans_by_field.get("requested_lead_weeks"),
        ),
        AssumptionRecord(
            assumption_id="ASM-SCH-002",
            category="SCHEDULE_LOGISTICS",
            label="ASSUMPTION",
            parameter_name="client_review_sla_and_incoterms",
            assumed_value=(
                f"{PROCESS_RATE_CARDS['client_sla_review_days']} business-day "
                "client approval SLA | EXW (Incoterms 2020)"
            ),
            unit="day",
            rationale=(
                "Schedule assumes client freezes inputs at Kick-Off and returns CDR "
                "comments within 5 business days; Ex-Works aerospace packaging."
            ),
            trigger_condition="missing_from_rfq:incoterms_and_sla",
            cost_sensitivity_pct="1.80",
            contractual_fallback=(
                "Client review delays slip delivery day-for-day; DAP/DDP freight "
                "and shock-monitored crating billed at cost."
            ),
            source_span=None,
        ),
        # 7. EXCLUSIONS_BOUNDARIES
        AssumptionRecord(
            assumption_id="ASM-EXC-001",
            category="EXCLUSIONS_BOUNDARIES",
            label="ASSUMPTION",
            parameter_name="excluded_destructive_and_flight_tests",
            assumed_value=(
                "Full-scale static/fatigue test rigs & flight-test instrumentation excluded"
            ),
            unit="dimensionless",
            rationale=(
                "Quotation covers analytical stress notes, FEM, and non-destructive FAI "
                "parts only; physical coupon/rig destruction excluded."
            ),
            trigger_condition="scope_boundary:physical_qualification_test",
            cost_sensitivity_pct="12.00",
            contractual_fallback=(
                "Coupon or full-scale qualification testing requires a separate test-campaign RFQ."
            ),
            source_span=None,
        ),
        AssumptionRecord(
            assumption_id="ASM-EXC-002",
            category="EXCLUSIONS_BOUNDARIES",
            label="ASSUMPTION",
            parameter_name="ecn_revision_cap_and_authority_fees",
            assumed_value=(
                f"Max {PROCESS_RATE_CARDS['included_ecn_cycles']} ECN cycles included; "
                "EASA/FAA authority fees excluded"
            ),
            unit="dimensionless",
            rationale=(
                "Covers up to 2 minor ECN iterations; regulatory authority "
                "certification fees are borne by Type Certificate holder."
            ),
            trigger_condition="scope_boundary:ecn_and_authority_fees",
            cost_sensitivity_pct="5.00",
            contractual_fallback=(
                "ECN cycle #3+ or geometry re-cuts trigger an automated Change Order quotation."
            ),
            source_span=None,
        ),
    ]
    return records


def _compute_combined_cost_snapshot(
    wbs_plan: dict[str, Any],
    *,
    mfg_override: dict[str, str] | None = None,
    eng_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Invoke deterministic Decimal + FLINT/Arb methods in evidence_calc."""
    mfg_res: dict[str, Any] | None = None
    eng_res: dict[str, Any] | None = None

    if wbs_plan["include_mfg"]:
        m_in = dict(wbs_plan["mfg_inputs"])
        if mfg_override:
            m_in.update(mfg_override)
        mfg_res = run_method(
            "aerospace_quotation_costing",
            m_in,
            include_intervals=True,
        )

    if wbs_plan["include_eng"]:
        e_in = dict(wbs_plan["eng_inputs"])
        if eng_override:
            e_in.update(eng_override)
        eng_res = run_method(
            "engineering_workpackage_quote",
            e_in,
            include_intervals=True,
        )

    with localcontext() as ctx:
        ctx.prec = 50
        mfg_cost = (
            Decimal(mfg_res["outputs"]["total_cost_baseline_eur"]) if mfg_res else Decimal("0")
        )
        mfg_price = (
            Decimal(mfg_res["outputs"]["quoted_total_price_eur"]) if mfg_res else Decimal("0")
        )

        eng_cost_p50 = (
            (
                Decimal(eng_res["outputs"]["labor_cost_p50_eur"])
                * (
                    Decimal("1")
                    + Decimal(
                        (eng_override or {}).get("rework_contingency_pct")
                        or wbs_plan["eng_inputs"]["rework_contingency_pct"]
                    )
                    / _HUNDRED
                )
            )
            + Decimal(
                (eng_override or {}).get("software_compute_surcharge_eur")
                or wbs_plan["eng_inputs"]["software_compute_surcharge_eur"]
            )
            if eng_res
            else Decimal("0")
        )
        eng_cost_p80 = (
            Decimal(eng_res["outputs"]["total_cost_p80_eur"]) if eng_res else Decimal("0")
        )
        eng_price_p50 = (
            Decimal(eng_res["outputs"]["quoted_price_p50_eur"]) if eng_res else Decimal("0")
        )
        eng_price_p80 = (
            Decimal(eng_res["outputs"]["quoted_price_p80_eur"]) if eng_res else Decimal("0")
        )
        eng_price_p90 = (
            Decimal(eng_res["outputs"]["quoted_price_p90_eur"]) if eng_res else Decimal("0")
        )

        # For manufacturing uncertainty when combined into P50/P80/P90:
        # P50 subtracts 35% of risk contingency, P80 uses baseline, P90 adds 65%.
        mfg_risk = Decimal(mfg_res["outputs"]["risk_contingency_eur"]) if mfg_res else Decimal("0")
        mfg_cost_p50 = max(Decimal("0"), mfg_cost - (mfg_risk * Decimal("0.35")))
        mfg_cost_p90 = mfg_cost + (mfg_risk * Decimal("0.65"))

        target_margin_pct = Decimal(
            str(
                (mfg_override or {}).get("target_margin_pct")
                or (eng_override or {}).get("target_margin_pct")
                or wbs_plan.get("mfg_inputs", {}).get("target_margin_pct")
                or wbs_plan.get("eng_inputs", {}).get("target_margin_pct")
                or "22.000"
            )
        )
        margin_denom = Decimal("1") - (target_margin_pct / _HUNDRED)
        mfg_price_p50 = mfg_cost_p50 / margin_denom if mfg_res else Decimal("0")
        mfg_price_p90 = mfg_cost_p90 / margin_denom if mfg_res else Decimal("0")

        total_cost_p50 = mfg_cost_p50 + eng_cost_p50
        total_cost_p80 = mfg_cost + eng_cost_p80
        total_cost_p90 = mfg_cost_p90 + (eng_price_p90 * margin_denom if eng_res else Decimal("0"))

        quoted_price_p50 = mfg_price_p50 + eng_price_p50
        quoted_price_p80 = mfg_price + eng_price_p80
        quoted_price_p90 = mfg_price_p90 + eng_price_p90

        gross_margin_p80 = quoted_price_p80 - total_cost_p80
        achieved_margin_pct = (
            (gross_margin_p80 / quoted_price_p80) * _HUNDRED
            if quoted_price_p80 > 0
            else Decimal("0")
        )

        mfg_ovh_risk = (
            Decimal(mfg_res["outputs"]["overhead_cost_eur"])
            + Decimal(mfg_res["outputs"]["risk_contingency_eur"])
            if mfg_res
            else Decimal("0")
        )
        mfg_qty = Decimal(str(wbs_plan["mfg_inputs"]["part_quantity"])) if mfg_res else Decimal("1")
        mfg_ovh_risk_per_part = mfg_ovh_risk / mfg_qty if mfg_res else Decimal("0")
        eng_rework_plus_compute = (
            Decimal(eng_res["outputs"]["rework_reserve_eur"])
            + Decimal(
                str(
                    (eng_override or {}).get("software_compute_surcharge_eur")
                    or wbs_plan["eng_inputs"]["software_compute_surcharge_eur"]
                )
            )
            if eng_res
            else Decimal("0")
        )

    return {
        "mfg_result": mfg_res,
        "eng_result": eng_res,
        "summary": {
            "total_cost_p50_eur": _q3(total_cost_p50),
            "total_cost_p80_eur": _q3(total_cost_p80),
            "total_cost_p90_eur": _q3(total_cost_p90),
            "quoted_price_p50_eur": _q3(quoted_price_p50),
            "quoted_price_p80_eur": _q3(quoted_price_p80),
            "quoted_price_p90_eur": _q3(quoted_price_p90),
            "gross_margin_p80_eur": _q3(gross_margin_p80),
            "achieved_margin_pct": _q3(achieved_margin_pct),
            "mfg_direct_cost_eur": (
                mfg_res["outputs"]["direct_cost_subtotal_eur"] if mfg_res else "0.000"
            ),
            "mfg_total_price_eur": _q3(mfg_price),
            "eng_total_price_p80_eur": _q3(eng_price_p80),
            "mfg_overhead_plus_risk_eur": _q3(mfg_ovh_risk),
            "mfg_overhead_plus_risk_per_part_eur": _q3(mfg_ovh_risk_per_part),
            "eng_rework_plus_compute_eur": _q3(eng_rework_plus_compute),
        },
    }


def _run_deterministic_cost_engine(
    spec: QuotationRequestSpec,
    wbs_plan: dict[str, Any],
    assumptions: list[AssumptionRecord],
) -> dict[str, Any]:
    """Agent 4: Execute deterministic Decimal + Arb costing, WBS lines, and Tornado sensitivity."""
    try:
        base = _compute_combined_cost_snapshot(wbs_plan)
    except AbstainError as exc:
        raise QuotationAbstain(exc.reason, stage="deterministic_cost_engine") from exc

    base_p80 = Decimal(base["summary"]["quoted_price_p80_eur"])
    mfg_res = base["mfg_result"]
    eng_res = base["eng_result"]
    mfg_in = wbs_plan["mfg_inputs"]
    eng_in = wbs_plan["eng_inputs"]

    wbs_items: list[WBSLineItem] = []
    if mfg_res is not None:
        m_out = mfg_res["outputs"]
        qty_s = str(mfg_in["part_quantity"])
        qty_d = Decimal(qty_s)
        mat_sub = Decimal(m_out["material_cost_total_eur"])
        mach_sub = Decimal(m_out["manufacturing_cost_total_eur"])
        nre_sub = Decimal(m_out["engineering_nre_total_eur"])
        ndt_sub = Decimal(m_out["ndt_qa_total_eur"])
        ovh_risk = Decimal(m_out["overhead_cost_eur"]) + Decimal(m_out["risk_contingency_eur"])

        wbs_items.extend(
            [
                WBSLineItem(
                    line_id="WBS-MFG-01",
                    title=f"Certified Raw Material ({wbs_plan['material_grade']})",
                    category="MATERIAL_SUPPLY",
                    quantity=m_out["raw_material_mass_per_part_kg"],
                    unit="kg/part",
                    unit_rate=str(mfg_in["material_unit_cost_eur_kg"]),
                    subtotal=_q3(mat_sub),
                    method_id="aerospace_quotation_costing",
                    assumption_ids=("ASM-MAT-001", "ASM-MAT-002", "ASM-MAT-003"),
                ),
                WBSLineItem(
                    line_id="WBS-MFG-02",
                    title="5-Axis CNC Machining & Forming Operations",
                    category="MANUFACTURING_TOOLING",
                    quantity=str(mfg_in["machining_hours_per_part"]),
                    unit="hour/part",
                    unit_rate=str(mfg_in["machining_rate_eur_hr"]),
                    subtotal=_q3(mach_sub),
                    method_id="aerospace_quotation_costing",
                    assumption_ids=("ASM-TECH-001", "ASM-MFG-001"),
                ),
                WBSLineItem(
                    line_id="WBS-MFG-03",
                    title="Manufacturing Engineering Setup, CAM & Dedicated Tooling NRE",
                    category="MANUFACTURING_TOOLING",
                    quantity="1",
                    unit="lot",
                    unit_rate=_q3(nre_sub),
                    subtotal=_q3(nre_sub),
                    method_id="aerospace_quotation_costing",
                    assumption_ids=("ASM-MFG-002",),
                ),
                WBSLineItem(
                    line_id="WBS-MFG-04",
                    title="AS9102 FAI & Non-Destructive Testing (NDT / CMM)",
                    category="REGULATORY_COMPLIANCE",
                    quantity=qty_s,
                    unit="part",
                    unit_rate=str(mfg_in["ndt_qa_cost_per_part_eur"]),
                    subtotal=_q3(ndt_sub),
                    method_id="aerospace_quotation_costing",
                    assumption_ids=("ASM-MFG-003", "ASM-REG-001"),
                ),
                WBSLineItem(
                    line_id="WBS-MFG-05",
                    title="Manufacturing Overhead & Risk Contingency Reserve",
                    category="COMMERCIAL_FINANCIAL",
                    quantity=qty_s,
                    unit="part",
                    unit_rate=_q3(ovh_risk / qty_d),
                    subtotal=_q3(ovh_risk),
                    method_id="aerospace_quotation_costing",
                    assumption_ids=("ASM-COM-002",),
                ),
            ]
        )

    if eng_res is not None:
        e_out = eng_res["outputs"]
        labor_p80 = Decimal(e_out["labor_cost_p80_eur"])
        rework_p80 = Decimal(e_out["rework_reserve_eur"])
        surcharge = Decimal(str(eng_in["software_compute_surcharge_eur"]))
        wbs_items.extend(
            [
                WBSLineItem(
                    line_id="WBS-ENG-01",
                    title="Structural Stress Calculation Notes & FEM Modeling (P80 PERT + CVE)",
                    category="TECHNICAL_ENGINEERING",
                    quantity=e_out["total_engineering_hours_p80"],
                    unit="hour",
                    unit_rate=str(eng_in["senior_rate_eur_hr"]),
                    subtotal=_q3(labor_p80),
                    method_id="engineering_workpackage_quote",
                    assumption_ids=("ASM-TECH-002", "ASM-TECH-003", "ASM-TECH-004"),
                ),
                WBSLineItem(
                    line_id="WBS-ENG-02",
                    title="Engineering Rework Reserve & FEA Solver Compute",
                    category="COMMERCIAL_FINANCIAL",
                    quantity="1",
                    unit="lot",
                    unit_rate=_q3(rework_p80 + surcharge),
                    subtotal=_q3(rework_p80 + surcharge),
                    method_id="engineering_workpackage_quote",
                    assumption_ids=("ASM-COM-002", "ASM-EXC-002"),
                ),
            ]
        )

    # Tornado sensitivity analysis (+10% stress on key assumption drivers)
    sensitivity_drivers: list[tuple[str, str, str, str]] = []
    if wbs_plan["include_mfg"]:
        sensitivity_drivers.extend(
            [
                ("ASM-MFG-001", "mfg", "machining_hours_per_part", "+10% CNC machining hours/part"),
                ("ASM-MAT-002", "mfg", "buy_to_fly_ratio", "+10% raw material buy-to-fly ratio"),
                ("ASM-MAT-003", "mfg", "material_unit_cost_eur_kg", "+10% certified alloy price"),
                ("ASM-COM-002", "mfg", "risk_contingency_pct", "+25% risk contingency buffer"),
            ]
        )
    if wbs_plan["include_eng"]:
        sensitivity_drivers.extend(
            [
                (
                    "ASM-TECH-003",
                    "eng",
                    "hours_per_calc_note_pessimistic",
                    "+15% PERT pessimistic note hours",
                ),
                ("ASM-TECH-004", "eng", "cve_review_ratio", "+25% independent CVE review ratio"),
                ("ASM-COM-002", "eng", "rework_contingency_pct", "+25% engineering rework reserve"),
            ]
        )

    sensitivity_matrix: list[dict[str, Any]] = []
    sens_by_assumption: dict[str, str] = {}
    for asm_id, scope_key, param, desc in sensitivity_drivers:
        if scope_key == "mfg":
            cur_val = Decimal(str(mfg_in[param]))
            scale = Decimal("1.25") if "25%" in desc else Decimal("1.10")
            new_val = _q3(cur_val * scale)
            try:
                perturbed = _compute_combined_cost_snapshot(wbs_plan, mfg_override={param: new_val})
            except AbstainError:
                continue
        else:
            cur_val = Decimal(str(eng_in[param]))
            scale = (
                Decimal("1.25")
                if "25%" in desc
                else (Decimal("1.15") if "15%" in desc else Decimal("1.10"))
            )
            new_val = _q3(cur_val * scale)
            try:
                perturbed = _compute_combined_cost_snapshot(wbs_plan, eng_override={param: new_val})
            except AbstainError:
                continue

        new_p80 = Decimal(perturbed["summary"]["quoted_price_p80_eur"])
        delta_eur = new_p80 - base_p80
        delta_pct = (delta_eur / base_p80) * _HUNDRED if base_p80 > 0 else Decimal("0")
        delta_pct_s = _q2(delta_pct)
        sens_by_assumption[asm_id] = delta_pct_s
        sensitivity_matrix.append(
            {
                "assumption_id": asm_id,
                "parameter": param,
                "scenario": desc,
                "baseline_value": str(cur_val),
                "stressed_value": new_val,
                "baseline_price_p80_eur": _q3(base_p80),
                "stressed_price_p80_eur": _q3(new_p80),
                "delta_price_eur": _q3(delta_eur),
                "price_sensitivity_pct": delta_pct_s,
            }
        )

    sensitivity_matrix.sort(key=lambda r: Decimal(r["delta_price_eur"]), reverse=True)

    # Update assumptions with exact computed Tornado sensitivity where measured
    updated_assumptions: list[AssumptionRecord] = []
    for rec in assumptions:
        if rec.assumption_id in sens_by_assumption:
            updated_assumptions.append(
                AssumptionRecord(
                    **{
                        **rec.to_dict(),
                        "cost_sensitivity_pct": sens_by_assumption[rec.assumption_id],
                    }
                )
            )
        else:
            updated_assumptions.append(rec)

    arb_intervals: dict[str, Any] = {}
    if mfg_res is not None:
        arb_intervals["aerospace_quotation_costing"] = mfg_res.get("exact_intervals", {})
    if eng_res is not None:
        arb_intervals["engineering_workpackage_quote"] = eng_res.get("exact_intervals", {})

    pert_summary = {
        "total_cost_p50_eur": base["summary"]["total_cost_p50_eur"],
        "total_cost_p80_eur": base["summary"]["total_cost_p80_eur"],
        "total_cost_p90_eur": base["summary"]["total_cost_p90_eur"],
        "quoted_price_p50_eur": base["summary"]["quoted_price_p50_eur"],
        "quoted_price_p80_eur": base["summary"]["quoted_price_p80_eur"],
        "quoted_price_p90_eur": base["summary"]["quoted_price_p90_eur"],
        "recommended_bid_percentile": "P80",
        "engineering_pert_details": eng_res["outputs"] if eng_res else None,
        "manufacturing_cost_details": mfg_res["outputs"] if mfg_res else None,
    }

    return {
        "summary": base["summary"],
        "pert_summary": pert_summary,
        "wbs_items": wbs_items,
        "assumptions": updated_assumptions,
        "sensitivity_matrix": sensitivity_matrix,
        "arb_intervals": arb_intervals,
        "mfg_result": mfg_res,
        "eng_result": eng_res,
    }


def _run_compliance_export_agent(
    spec: QuotationRequestSpec,
    intake: dict[str, Any],
    wbs_plan: dict[str, Any],
) -> dict[str, Any]:
    """Agent 5: Audit regulatory scope & export-control restrictions without claiming compliance."""
    text_lower = spec.rfq_text.lower()
    itar_mentioned = bool(re.search(r"\b(?:itar|usml|ear99|classified)\b", text_lower))
    blocked = bool(spec.export_control_restricted)
    return {
        "standards_referenced": list(wbs_plan["regulatory_standards"]),
        "export_control_restricted": blocked,
        "itar_or_ear_flag_in_rfq": itar_mentioned,
        "advisory_only_boundary": True,
        "compliance_claim_absent": True,
        "export_clearance_status": "HOLD_FOR_EXPORT_OFFICER"
        if blocked
        else "STANDARD_EU_DUAL_USE_REVIEW",
    }


def prove_quotation_margin_envelope(
    *,
    quoted_price_p80_eur: str,
    direct_cost_baseline_eur: str,
    fixed_reserve_cost_eur: str,
    min_acceptable_margin_pct: str,
    cost_drift_bounds: tuple[str, str] = ("0.950", "1.080"),
) -> dict[str, Any]:
    """Formally prove via Z3 SMT that gross margin stays >= floor across continuous cost drift."""
    price_dec = Decimal(quoted_price_p80_eur)
    direct_dec = Decimal(direct_cost_baseline_eur)
    fixed_dec = Decimal(fixed_reserve_cost_eur)
    floor_dec = Decimal(min_acceptable_margin_pct)

    def _q(val: Decimal | str) -> z3.ArithRef:
        f = Fraction(str(val))
        return z3.Q(f.numerator, f.denominator)

    solver = z3.Solver()
    solver.set("timeout", 3000)

    drift = z3.Real("cost_drift_factor")
    lo_f = _q(cost_drift_bounds[0])
    hi_f = _q(cost_drift_bounds[1])
    solver.add(drift >= lo_f, drift <= hi_f)

    price_z3 = _q(price_dec)
    stressed_cost = _q(direct_dec) * drift + _q(fixed_dec)
    floor_frac = _q(floor_dec) / z3.Q(100, 1)

    # Negate safety property: exists drift in [lo, hi] violating floor margin.
    solver.add((price_z3 - stressed_cost) < (floor_frac * price_z3))
    status_res = solver.check()

    assumptions_payload = {
        "quoted_price_p80_eur": quoted_price_p80_eur,
        "direct_cost_baseline_eur": direct_cost_baseline_eur,
        "fixed_reserve_cost_eur": fixed_reserve_cost_eur,
        "min_acceptable_margin_pct": min_acceptable_margin_pct,
        "cost_drift_bounds": list(cost_drift_bounds),
    }
    assertion = (
        f"forall cost_drift in [{cost_drift_bounds[0]}, {cost_drift_bounds[1]}]: "
        f"(quoted_price_p80 - stressed_cost) / quoted_price_p80 >= {min_acceptable_margin_pct}%"
    )

    counterexample: dict[str, str] | None = None
    if status_res == z3.unsat:
        status = "PROVED_UNSAT"
        proved = True
    elif status_res == z3.sat:
        status = "COUNTEREXAMPLE_FOUND"
        proved = False
        model = solver.model()
        d_val = model.eval(drift, model_completion=True)
        if hasattr(d_val, "as_fraction"):
            frac = d_val.as_fraction()
            d_dec = Decimal(frac.numerator) / Decimal(frac.denominator)
        else:
            d_dec = Decimal(cost_drift_bounds[1])
        ce_cost = direct_dec * d_dec + fixed_dec
        ce_margin = (
            ((price_dec - ce_cost) / price_dec) * _HUNDRED if price_dec > 0 else Decimal("0")
        )
        counterexample = {
            "cost_drift_factor": _q3(d_dec),
            "stressed_cost_eur": _q3(ce_cost),
            "breached_margin_pct": _q2(ce_margin),
        }
    else:
        status = "UNKNOWN"
        proved = False

    proof_hash = inputs_hash(
        {
            "property_name": "quotation_margin_envelope",
            "status": status,
            "assumptions": assumptions_payload,
            "assertion": assertion,
            "counterexample": counterexample,
        }
    )
    return {
        "property_name": "quotation_margin_envelope",
        "proved": proved,
        "status": status,
        "assumptions": assumptions_payload,
        "assertion": assertion,
        "counterexample": counterexample,
        "proof_hash": proof_hash,
    }


def _collect_allowed_numbers(
    spec: QuotationRequestSpec,
    wbs_plan: dict[str, Any],
    costing: dict[str, Any],
) -> set[str]:
    """Collect every numeric token authorized from RFQ spans or deterministic calculations."""
    allowed: set[str] = {"1"}

    def _add_from(obj: Any) -> None:
        if isinstance(obj, str):
            allowed.update(DECIMAL_TOKEN.findall(obj))
            allowed.update(INTEGER_TOKEN.findall(obj))
            return
        if isinstance(obj, list):
            for x in obj:
                _add_from(x)
        elif isinstance(obj, dict):
            for x in obj.values():
                _add_from(x)

    _add_from(spec.rfq_text)
    _add_from(wbs_plan)
    if costing.get("mfg_result"):
        _add_from(costing["mfg_result"].get("outputs"))
    if costing.get("eng_result"):
        _add_from(costing["eng_result"].get("outputs"))
    _add_from(costing["summary"])
    _add_from(costing["sensitivity_matrix"])
    _add_from(PROCESS_RATE_CARDS)
    _add_from(MATERIAL_PRICE_CATALOG)
    _add_from([spec.target_margin_pct, spec.min_acceptable_margin_pct])
    return allowed


def _run_adversarial_refuter_agent(
    spec: QuotationRequestSpec,
    intake: dict[str, Any],
    wbs_plan: dict[str, Any],
    costing: dict[str, Any],
) -> dict[str, Any]:
    """Agent 6: Attack assumptions, check stray numbers, and verify formal Z3 margin envelope."""
    assumptions: list[AssumptionRecord] = costing["assumptions"]
    categories_present = {a.category for a in assumptions}
    missing_categories = [c for c in ASSUMPTION_CATEGORIES if c not in categories_present]

    target_m = _to_dec(
        (wbs_plan.get("mfg_inputs") or wbs_plan.get("eng_inputs") or {}).get("target_margin_pct")
        or spec.target_margin_pct,
        "target_margin_pct",
    )
    floor_m = _to_dec(spec.min_acceptable_margin_pct, "min_acceptable_margin_pct")
    achieved_m = Decimal(costing["summary"]["achieved_margin_pct"])

    contradictions: list[str] = []
    if floor_m > target_m:
        contradictions.append("min_acceptable_margin_exceeds_target")
    if achieved_m < floor_m:
        contradictions.append("achieved_margin_below_floor")
    if missing_categories:
        contradictions.append(f"missing_assumption_categories:{','.join(missing_categories)}")

    # Validate literal spans extracted from RFQ
    for sp in intake["extracted_spans"]:
        s = int(sp["span_start"])
        e = int(sp["span_end"])
        if spec.rfq_text[s:e] != sp["quotation"]:
            contradictions.append(f"bad_span:{sp['field']}")

    # Check stray physical numbers in WBS numeric claims and cost summary
    allowed = _collect_allowed_numbers(spec, wbs_plan, costing)
    stray = stray_physical_numbers(
        {
            "summary": costing["summary"],
            "pert_summary": costing["pert_summary"],
            "wbs_numeric_claims": [
                {
                    "line_id": item.line_id,
                    "quantity": item.quantity,
                    "unit_rate": item.unit_rate,
                    "subtotal": item.subtotal,
                }
                for item in costing["wbs_items"]
            ],
        },
        allowed,
    )
    if stray:
        contradictions.append(f"stray_numbers:{','.join(stray[:5])}")

    # Formal Z3 SMT proof on margin resilience across bounded cost drift
    formal_proof: dict[str, Any] | None = None
    if spec.enable_formal_smt:
        p80_price = Decimal(costing["summary"]["quoted_price_p80_eur"])
        p80_cost = Decimal(costing["summary"]["total_cost_p80_eur"])
        # Direct portion vs fixed reserve (split 75% variable / 25% fixed)
        variable_part = _q3(p80_cost * Decimal("0.750"))
        fixed_part = _q3(p80_cost - Decimal(variable_part))
        formal_proof = prove_quotation_margin_envelope(
            quoted_price_p80_eur=_q3(p80_price),
            direct_cost_baseline_eur=variable_part,
            fixed_reserve_cost_eur=fixed_part,
            min_acceptable_margin_pct=_q3(floor_m),
            cost_drift_bounds=("0.950", "1.080"),
        )
        if not formal_proof["proved"]:
            contradictions.append(f"z3_margin_breach:{formal_proof['status']}")

    attack = "hit" if contradictions else "miss"
    return {
        "attack": attack,
        "contradictions": contradictions,
        "stray_numbers_count": len(stray),
        "categories_covered": len(categories_present),
        "formal_proof": formal_proof,
    }


def _run_decision_gate_agent(
    spec: QuotationRequestSpec,
    compliance: dict[str, Any],
    refuter: dict[str, Any],
) -> dict[str, Any]:
    """Agent 7: Enforce fail-closed governance gate before releasing quote."""
    if compliance["export_control_restricted"]:
        raise QuotationAbstain("export_control_restricted_hold", stage="decision_gate_agent")
    if refuter["attack"] == "hit":
        reason = refuter["contradictions"][0] if refuter["contradictions"] else "refuter_hit"
        raise QuotationAbstain(reason, stage="decision_gate_agent")
    return {
        "decision": "continue",
        "gate_status": "APPROVED_FOR_HUMAN_REVIEW",
        "export_clearance_status": compliance["export_clearance_status"],
        "formal_margin_proved": bool((refuter.get("formal_proof") or {}).get("proved", False)),
    }


def _run_quotation_scribe_agent(
    spec: QuotationRequestSpec,
    intake: dict[str, Any],
    wbs_plan: dict[str, Any],
    costing: dict[str, Any],
    compliance: dict[str, Any],
    refuter: dict[str, Any],
    gate: dict[str, Any],
    *,
    event_hashes: list[str],
    merkle_root: str,
) -> str:
    """Agent 8: Assemble human-auditable Markdown quotation dossier with all assumptions."""
    summary = costing["summary"]
    pert = costing["pert_summary"]
    assumptions: list[AssumptionRecord] = costing["assumptions"]
    wbs_items: list[WBSLineItem] = costing["wbs_items"]
    sens = costing["sensitivity_matrix"]
    fp = refuter.get("formal_proof") or {}
    cur = spec.currency

    lines: list[str] = [
        f"# Automated Multi-Agent Quotation Dossier — {intake['rfq_id']}",
        "",
        "> **Advisory Notice:** This tool assists human estimators and engineers. "
        "It does not determine regulatory compliance or issue binding legal offers.",
        "",
        f"- **Customer:** {spec.customer_name}",
        f"- **Quotation Mode:** `{spec.quotation_kind}`",
        f"- **Material Baseline:** {wbs_plan['material_grade']} "
        f"({wbs_plan['material_spec']['spec']})",
        f"- **Gate Status:** `{gate['gate_status']}` | **Confidence:** `deterministic`",
        f"- **Merkle Root:** `{merkle_root}` ({len(event_hashes)} ledger events)",
        "",
        "## 1. Executive Price & PERT Risk Summary",
        "",
        "| Confidence Level | Total Baseline Cost | Quoted Price | Gross Margin |",
        "|---|---|---|---|",
        (
            f"| **P50 (Expected)** | {pert['total_cost_p50_eur']} {cur} | "
            f"{pert['quoted_price_p50_eur']} {cur} | — |"
        ),
        (
            f"| **P80 (Recommended Bid)** | {pert['total_cost_p80_eur']} {cur} | "
            f"**{pert['quoted_price_p80_eur']} {cur}** | "
            f"{summary['gross_margin_p80_eur']} {cur} ({summary['achieved_margin_pct']}%) |"
        ),
        (
            f"| **P90 (Conservative)** | {pert['total_cost_p90_eur']} {cur} | "
            f"{pert['quoted_price_p90_eur']} {cur} | — |"
        ),
        "",
        "## 2. Work Breakdown Structure (WBS)",
        "",
        "| WBS ID | Item | Category | Qty | Unit | Rate | Subtotal | Assumptions |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in wbs_items:
        lines.append(
            f"| `{item.line_id}` | {item.title} | `{item.category}` | {item.quantity} | "
            f"{item.unit} | {item.unit_rate} | **{item.subtotal} {cur}** | "
            f"{', '.join(item.assumption_ids)} |"
        )

    lines.extend(
        [
            "",
            "## 3. Exhaustive Assumptions Register (All 7 Mandatory Dimensions)",
            "",
            (
                "| ID | Category | Label | Parameter | Assumed Value | "
                "Sensitivity | Contractual Fallback |"
            ),
            "|---|---|---|---|---|---|---|",
        ]
    )
    for asm in assumptions:
        lines.append(
            f"| `{asm.assumption_id}` | `{asm.category}` | `{asm.label}` | "
            f"`{asm.parameter_name}` | {asm.assumed_value} | +{asm.cost_sensitivity_pct}% | "
            f"{asm.contractual_fallback} |"
        )

    lines.extend(
        [
            "",
            "## 4. Tornado Sensitivity Matrix (Top Cost Drivers)",
            "",
            (
                "| Assumption ID | Scenario | Baseline Price (P80) | "
                "Stressed Price (P80) | Delta | Impact |"
            ),
            "|---|---|---|---|---|---|",
        ]
    )
    for row in sens:
        lines.append(
            f"| `{row['assumption_id']}` | {row['scenario']} | "
            f"{row['baseline_price_p80_eur']} {cur} | "
            f"{row['stressed_price_p80_eur']} {cur} | "
            f"+{row['delta_price_eur']} {cur} | +{row['price_sensitivity_pct']}% |"
        )

    lines.extend(
        [
            "",
            "## 5. Formal Margin Verification (Z3 SMT) & Export Control",
            "",
            f"- **Z3 SMT Property:** `{fp.get('assertion', 'disabled')}`",
            (
                f"- **Z3 Status:** `{fp.get('status', 'NOT_RUN')}` "
                f"(Proof Hash: `{fp.get('proof_hash', 'none')}`)"
            ),
            f"- **Export Clearance:** `{compliance['export_clearance_status']}`",
            (
                f"- **Adversarial Refuter:** `{refuter['attack']}` "
                f"(Stray numbers: {refuter['stray_numbers_count']})"
            ),
        ]
    )
    return "\n".join(lines)


def _record_quotation_abstain(
    ledger: Ledger,
    spec: QuotationRequestSpec,
    *,
    created_at: str,
    reason: str,
    stage: str,
) -> QuotationDossier:
    rfq_hash = hashlib.sha256(spec.rfq_text.encode("utf-8")).hexdigest()
    # Keep abstain envelope and payload free of physical numbers per Ledger._validate_body
    safe_inputs = {"rfq_sha256": rfq_hash, "stage": stage}
    env = make_envelope(
        sources=[
            project_source("quotation-supervisor", "https://aeroregu.local/quote", "ASSUMPTION")
        ],
        method_version="quotation_multiagent@1.0.0",
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
    return QuotationDossier(
        rfq_id=spec.rfq_id,
        tenant_id=ledger.tenant_id,
        quotation_kind=spec.quotation_kind,
        confidence="abstain",
        decision_status="ABSTAIN_ESCALATED",
        currency=spec.currency,
        abstain_reason=reason,
        escalate_to="human_engineer",
        event_hashes=[ev_hash],
        merkle_root=ledger.merkle_root(),
        markdown_report=(
            f"# Quotation Abstained ({reason})\n\n"
            f"- **Stage:** `{stage}`\n"
            f"- **Escalate To:** `human_engineer`\n"
            f"- **Ledger Event:** `{ev_hash}`\n"
        ),
    )


def run_multiagent_quotation(
    ledger: Ledger,
    spec: QuotationRequestSpec,
) -> QuotationDossier:
    """Execute the 8-agent supervised quotation pipeline and seal every step in the Ledger."""
    created_at = spec.created_at or _now_utc()
    try:
        intake = _run_rfq_intake_agent(spec)
        wbs_plan = _run_scope_wbs_agent(spec, intake)
        assumptions = _run_assumption_generator_agent(spec, intake, wbs_plan)
        costing = _run_deterministic_cost_engine(spec, wbs_plan, assumptions)
        compliance = _run_compliance_export_agent(spec, intake, wbs_plan)
        refuter = _run_adversarial_refuter_agent(spec, intake, wbs_plan, costing)
        gate = _run_decision_gate_agent(spec, compliance, refuter)
    except QuotationAbstain as exc:
        return _record_quotation_abstain(
            ledger,
            spec,
            created_at=created_at,
            reason=exc.reason,
            stage=exc.stage,
        )

    event_hashes: list[str] = []
    # Record deterministic calc events first
    for method_key, res_key in (
        ("aerospace_quotation_costing", "mfg_result"),
        ("engineering_workpackage_quote", "eng_result"),
    ):
        ran = costing.get(res_key)
        if ran is None:
            continue
        in_key = "mfg_inputs" if res_key == "mfg_result" else "eng_inputs"
        calc_inputs = wbs_plan[in_key]
        env = make_envelope(
            sources=ran["sources"],
            method_version=ran["method_version"],
            inputs=calc_inputs,
            confidence="deterministic",
            result=ran["outputs"],
        )
        ev_h = record(
            ledger,
            {
                "event_type": "calc",
                "tenant_id": ledger.tenant_id,
                "actor_id": spec.actor_id,
                "created_at": created_at,
                "payload": {
                    "method_id": method_key,
                    "inputs": calc_inputs,
                    "outputs": ran["outputs"],
                },
                "envelope": env,
            },
        )
        event_hashes.append(ev_h)

    # Record each of the 8 specialist agent turns into the Ledger
    turn_outputs: dict[str, dict[str, Any]] = {
        "rfq_intake_agent": {
            "rfq_id": intake["rfq_id"],
            "spans_extracted": len(intake["extracted_spans"]),
            "material_grade": wbs_plan["material_grade"],
        },
        "scope_wbs_agent": {
            "wbs_line_count": len(costing["wbs_items"]),
            "include_mfg": wbs_plan["include_mfg"],
            "include_eng": wbs_plan["include_eng"],
        },
        "assumption_generator_agent": {
            "assumptions_count": len(costing["assumptions"]),
            "categories_count": len(ASSUMPTION_CATEGORIES),
        },
        "deterministic_cost_engine": {
            "quoted_price_p80_eur": costing["summary"]["quoted_price_p80_eur"],
            "achieved_margin_pct": costing["summary"]["achieved_margin_pct"],
        },
        "compliance_export_agent": compliance,
        "adversarial_quote_refuter": {
            "attack": refuter["attack"],
            "stray_numbers_count": refuter["stray_numbers_count"],
            "z3_status": (refuter.get("formal_proof") or {}).get("status", "SKIPPED"),
        },
        "decision_gate_agent": gate,
        "quotation_scribe_agent": {
            "rfq_id": intake["rfq_id"],
            "recommended_bid_percentile": "P80",
        },
    }

    agent_turns_summary: list[dict[str, Any]] = []
    for entry in _AGENT_ROSTER:
        q_role = entry["quotation_role"]
        l_agent_id = entry["ledger_agent_id"]
        out_payload = {"quotation_agent_role": q_role, **turn_outputs[q_role]}
        turn_env = make_envelope(
            sources=[
                project_source(q_role, f"https://aeroregu.local/agents/{q_role}", "ASSUMPTION")
            ],
            method_version=f"{q_role}@1.0.0",
            inputs={"rfq_id": intake["rfq_id"], "role": q_role},
            confidence="deterministic" if q_role == "deterministic_cost_engine" else "draft",
            result=out_payload,
        )
        turn_body = {
            "agent_id": l_agent_id,
            "prompt_hash": prompt_hash(l_agent_id),
            "temperature": "0",
            "input_event_hashes": list(event_hashes),
            "output": out_payload,
            "envelope": turn_env,
        }
        ev_h = record(
            ledger,
            {
                "event_type": "agent_turn",
                "tenant_id": ledger.tenant_id,
                "actor_id": spec.actor_id,
                "created_at": created_at,
                "payload": turn_body,
                "envelope": turn_env,
            },
        )
        event_hashes.append(ev_h)
        agent_turns_summary.append(
            {
                "quotation_agent_role": q_role,
                "ledger_agent_id": l_agent_id,
                "event_hash": ev_h,
                "output": out_payload,
            }
        )

    m_root = ledger.merkle_root()
    markdown_report = _run_quotation_scribe_agent(
        spec,
        intake,
        wbs_plan,
        costing,
        compliance,
        refuter,
        gate,
        event_hashes=event_hashes,
        merkle_root=m_root,
    )

    assumptions_dicts = [a.to_dict() for a in costing["assumptions"]]
    by_category: dict[str, list[dict[str, Any]]] = {cat: [] for cat in ASSUMPTION_CATEGORIES}
    for ad in assumptions_dicts:
        by_category[ad["category"]].append(ad)

    return QuotationDossier(
        rfq_id=intake["rfq_id"],
        tenant_id=ledger.tenant_id,
        quotation_kind=spec.quotation_kind,
        confidence="deterministic",
        decision_status=gate["gate_status"],
        currency=spec.currency,
        abstain_reason=None,
        escalate_to=None,
        extracted_spans=intake["extracted_spans"],
        wbs_items=[item.to_dict() for item in costing["wbs_items"]],
        assumptions=assumptions_dicts,
        assumptions_by_category=by_category,
        cost_breakdown=costing["summary"],
        pert_summary=costing["pert_summary"],
        sensitivity_matrix=costing["sensitivity_matrix"],
        arb_intervals=costing["arb_intervals"],
        formal_margin_proof=refuter.get("formal_proof"),
        compliance_audit=compliance,
        adversarial_review={
            "attack": refuter["attack"],
            "contradictions": refuter["contradictions"],
            "stray_numbers_count": refuter["stray_numbers_count"],
            "categories_covered": refuter["categories_covered"],
        },
        agent_turns=agent_turns_summary,
        event_hashes=event_hashes,
        merkle_root=m_root,
        markdown_report=markdown_report,
    )


def run_whatif_sensitivity(
    ledger: Ledger,
    spec: QuotationRequestSpec,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Compare baseline quotation against deterministic What-If assumption overrides."""
    baseline = run_multiagent_quotation(ledger, spec)
    updated_overrides = {**spec.assumption_overrides, **overrides}
    scenario_spec = QuotationRequestSpec(
        rfq_text=spec.rfq_text,
        quotation_kind=spec.quotation_kind,
        tenant_id=spec.tenant_id,
        actor_id=spec.actor_id,
        created_at=spec.created_at,
        currency=spec.currency,
        target_margin_pct=str(overrides.get("target_margin_pct", spec.target_margin_pct)),
        min_acceptable_margin_pct=spec.min_acceptable_margin_pct,
        explicit_params=dict(spec.explicit_params),
        bom_items=list(spec.bom_items),
        assumption_overrides=updated_overrides,
        enable_formal_smt=spec.enable_formal_smt,
        export_control_restricted=spec.export_control_restricted,
        customer_name=spec.customer_name,
        rfq_id=spec.rfq_id,
    )
    scenario = run_multiagent_quotation(ledger, scenario_spec)

    if baseline.confidence == "abstain" or scenario.confidence == "abstain":
        return {
            "baseline_confidence": baseline.confidence,
            "scenario_confidence": scenario.confidence,
            "baseline_abstain_reason": baseline.abstain_reason,
            "scenario_abstain_reason": scenario.abstain_reason,
            "baseline": baseline.to_dict(),
            "scenario": scenario.to_dict(),
        }

    b_p80 = Decimal(baseline.cost_breakdown["quoted_price_p80_eur"])
    s_p80 = Decimal(scenario.cost_breakdown["quoted_price_p80_eur"])
    delta_p80 = s_p80 - b_p80
    pct_change = (delta_p80 / b_p80) * _HUNDRED if b_p80 > 0 else Decimal("0")
    return {
        "baseline_confidence": baseline.confidence,
        "scenario_confidence": scenario.confidence,
        "overrides_applied": dict(overrides),
        "baseline_price_p80_eur": _q3(b_p80),
        "scenario_price_p80_eur": _q3(s_p80),
        "delta_price_p80_eur": _q3(delta_p80),
        "delta_price_pct": _q2(pct_change),
        "baseline": baseline.to_dict(),
        "scenario": scenario.to_dict(),
    }
