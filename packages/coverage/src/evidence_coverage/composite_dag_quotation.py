"""Composite Multi-Archetype WBS DAG (CPM + Synergy) & Multi-Year Aerospace Financial Engine.

Implements Q1 Year-1 Master Roadmap capabilities:
1. Composite WBS Directed Acyclic Graph (DAG) across N simultaneous rotorcraft archetypes
   (`Q-DES-01..Q-TST-02`), topological Kahn validation (fail-closed ABSTAIN on cycles),
   deterministic Critical Path Method (ES, EF, LS, LF, Total/Free Float in weeks), and
   bounded engineering reuse synergy (CAD/DMU, Loads, GFEM mesh, Stress dossier, Test correlation)
   that never compromises the mandatory Part 21.A.239(b) CVE verification floor.
2. Multi-year Wright & Crawford learning curves, Y1..Y5 country-parameterized inflation escalation,
   monthly cash-flow & working capital financing cost (`aerospace_multiyear_cashflow_learning`).
3. Formal Z3 SMT proofs verifying that both P80 gross margin AND multi-year NPV + post-financing
   net margin remain >= contractual minimum floors across continuous drift/inflation/WACC boxes.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import asdict, dataclass, field
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any

import z3
from evidence_calc.errors import AbstainError
from evidence_calc.quantize import format_quantum
from evidence_calc.registry import run_method
from evidence_kernel.canonical import inputs_hash
from evidence_kernel.envelope import make_envelope, project_source
from evidence_kernel.gateway import prompt_hash
from evidence_kernel.guardrails import check_text_safety
from evidence_kernel.ledger import Ledger
from evidence_kernel.orchestrator import record

from evidence_coverage.contract_clause_auditor import audit_rfq_contract_clauses
from evidence_coverage.historical_quotation_calibrator import (
    calibrate_from_historical_corpus,
    extract_idp_physical_complexity,
    generate_reference_historical_corpus,
    ingest_historical_quotations,
    retrieve_nearest_historical_quotations,
)
from evidence_coverage.quotation_multiagent import (
    QuotationAbstain,
    prove_quotation_margin_envelope,
)
from evidence_coverage.rotorcraft_quotation_catalog import (
    _CERT_BASIS_FACTORS,
    _COSYSMO_FACTORS,
    _MATERIAL_FACTORS,
    COUNTRY_RATE_CARDS,
    RESEARCH_BENCHMARK_MODELS,
    ROTORCRAFT_QUOTATION_ARCHETYPES,
    build_archetype_assumptions,
    classify_rotorcraft_rfq,
)

_Q1 = Decimal("0.1")
_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_FOUR = Decimal("4")
_SIX = Decimal("6")
_HUNDRED = Decimal("100")
_Z_P80 = Decimal("0.84162123")
_Z_P90 = Decimal("1.28155157")

COUNTRY_INFLATION_PROFILES: dict[str, dict[str, str]] = {
    "EU_DEFAULT": {
        "annual_inflation_pct": "3.200",
        "wacc_annual_pct": "7.500",
        "default_payment_terms_days": "60",
        "label": "ASSUMPTION",
    },
    "FR": {
        "annual_inflation_pct": "2.900",
        "wacc_annual_pct": "7.200",
        "default_payment_terms_days": "60",
        "label": "ASSUMPTION",
    },
    "DE": {
        "annual_inflation_pct": "3.100",
        "wacc_annual_pct": "7.000",
        "default_payment_terms_days": "45",
        "label": "ASSUMPTION",
    },
    "ES": {
        "annual_inflation_pct": "3.300",
        "wacc_annual_pct": "7.800",
        "default_payment_terms_days": "60",
        "label": "ASSUMPTION",
    },
    "IT": {
        "annual_inflation_pct": "3.400",
        "wacc_annual_pct": "8.000",
        "default_payment_terms_days": "60",
        "label": "ASSUMPTION",
    },
    "UK": {
        "annual_inflation_pct": "3.800",
        "wacc_annual_pct": "8.200",
        "default_payment_terms_days": "45",
        "label": "ASSUMPTION",
    },
    "US": {
        "annual_inflation_pct": "3.500",
        "wacc_annual_pct": "8.500",
        "default_payment_terms_days": "30",
        "label": "ASSUMPTION",
    },
    "PL": {
        "annual_inflation_pct": "4.600",
        "wacc_annual_pct": "9.000",
        "default_payment_terms_days": "60",
        "label": "ASSUMPTION",
    },
    "IN": {
        "annual_inflation_pct": "5.200",
        "wacc_annual_pct": "10.500",
        "default_payment_terms_days": "60",
        "label": "ASSUMPTION",
    },
}

CANONICAL_ARCHETYPE_PRECEDENCE: tuple[tuple[str, str, str], ...] = (
    ("Q-DES-01", "Q-DES-02", "CAD_DMU"),
    ("Q-DES-01", "Q-DES-03", "CAD_DMU"),
    ("Q-DES-01", "Q-DES-04", "CAD_DMU"),
    ("Q-DES-02", "Q-DES-04", "CAD_DMU"),
    ("Q-DES-03", "Q-DES-04", "CAD_DMU"),
    ("Q-DES-04", "Q-STR-01", "CAD_DMU"),
    ("Q-DES-01", "Q-STR-02", "CAD_DMU"),
    ("Q-DES-02", "Q-STR-03", "CAD_DMU"),
    ("Q-DES-03", "Q-STR-03", "CAD_DMU"),
    ("Q-STR-01", "Q-STR-02", "LOADS_BOOK"),
    ("Q-STR-01", "Q-STR-03", "LOADS_BOOK"),
    ("Q-STR-02", "Q-STR-03", "GFEM_MESH"),
    ("Q-STR-02", "Q-DYN-01", "GFEM_MESH"),
    ("Q-STR-02", "Q-DYN-02", "GFEM_MESH"),
    ("Q-STR-02", "Q-DYN-03", "GFEM_MESH"),
    ("Q-STR-01", "Q-DYN-01", "LOADS_BOOK"),
    ("Q-STR-01", "Q-DOA-02", "LOADS_BOOK"),
    ("Q-STR-01", "Q-DOA-03", "LOADS_BOOK"),
    ("Q-STR-03", "Q-FDT-01", "STRESS_DOSSIER"),
    ("Q-STR-03", "Q-FDT-02", "STRESS_DOSSIER"),
    ("Q-STR-03", "Q-STR-04", "STRESS_DOSSIER"),
    ("Q-STR-03", "Q-DOA-01", "STRESS_DOSSIER"),
    ("Q-STR-03", "Q-DOA-02", "STRESS_DOSSIER"),
    ("Q-STR-03", "Q-TST-01", "STRESS_DOSSIER"),
    ("Q-FDT-01", "Q-DOA-02", "STRESS_DOSSIER"),
    ("Q-DYN-01", "Q-DOA-02", "TEST_CORRELATION"),
    ("Q-DYN-01", "Q-TST-02", "TEST_CORRELATION"),
    ("Q-DOA-02", "Q-TST-01", "TEST_CORRELATION"),
    ("Q-TST-01", "Q-TST-02", "TEST_CORRELATION"),
)

_SYNERGY_CHANNEL_RULES: dict[str, tuple[tuple[str, Decimal], ...]] = {
    "CAD_DMU": (("cad_hours", Decimal("0.200")),),
    "LOADS_BOOK": (("loads_hours", Decimal("0.250")),),
    "GFEM_MESH": (("stress_hours", Decimal("0.180")), ("hpc_hours", Decimal("0.150"))),
    "STRESS_DOSSIER": (("stress_hours", Decimal("0.120")),),
    "TEST_CORRELATION": (("test_hours", Decimal("0.150")),),
}
_MAX_SYNERGY_DISCOUNT_PER_DISC = Decimal("0.350")


def _effective_fte_for_family(family: str) -> Decimal:
    return {
        "DESIGN": Decimal("2.5"),
        "STRESS": Decimal("3.0"),
        "FDT": Decimal("2.5"),
        "DYNAMICS": Decimal("3.0"),
        "DOA": Decimal("2.0"),
        "TEST": Decimal("2.5"),
    }.get(family, Decimal("2.5"))


def _compute_node_inputs(
    arch: dict[str, Any],
    country_card: dict[str, Any],
    *,
    cert_basis_factor: str,
    material_complexity_factor: str,
    cosysmo_driver_factor: str,
    pvt_compression_factor: str,
    margin_pct: str,
    cve_min_ratio_pct: str,
    contingency_override: str,
    discounts: dict[str, Decimal] | None = None,
    extra_stress_hours: Decimal = _ZERO,
    hour_scale: Decimal = _ONE,
) -> dict[str, Any]:
    rates = country_card["rates"]
    hours = arch["hours_by_specialty"]
    disc = discounts or {}

    def _scaled_disc(field_key: str, raw_val: str, bonus: Decimal = _ZERO) -> str:
        factor = max(
            Decimal("0.650"), _ONE - min(_MAX_SYNERGY_DISCOUNT_PER_DISC, disc.get(field_key, _ZERO))
        )
        val = ((Decimal(raw_val) * factor) + bonus) * hour_scale
        return format_quantum(val, _Q3)

    return {
        "cad_hours": _scaled_disc("cad_hours", hours["cad_hours"]),
        "loads_hours": _scaled_disc("loads_hours", hours["loads_hours"]),
        "stress_hours": _scaled_disc("stress_hours", hours["stress_hours"], extra_stress_hours),
        "fdt_dyn_hours": _scaled_disc("fdt_dyn_hours", hours["fdt_dyn_hours"]),
        "systems_hours": _scaled_disc("systems_hours", hours["systems_hours"]),
        "test_hours": _scaled_disc("test_hours", hours["test_hours"]),
        # CVE hours NEVER discounted by synergy
        "cve_hours": format_quantum(Decimal(hours["cve_hours"]) * hour_scale, _Q3),
        "proto_hours": format_quantum(Decimal(hours["proto_hours"]) * hour_scale, _Q3),
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
        "hpc_hours": _scaled_disc("hpc_hours", arch["default_hpc_hours"]),
        "hpc_rate": rates["hpc_rate"],
        "travel_hardware_eur": arch["default_travel_hardware_eur"],
        "overhead_pct": country_card["overhead_pct"],
        "contingency_pct": contingency_override,
        "margin_pct": margin_pct,
        "fixed_price_share_pct": arch["fixed_price_share_pct"],
        "cve_min_ratio_pct": cve_min_ratio_pct,
    }


def build_composite_wbs_dag(
    archetype_ids: list[str] | tuple[str, ...],
    *,
    custom_edges: list[tuple[str, str, str]] | None = None,
    country_code: str = "EU_DEFAULT",
    cert_basis: str = "CS-29",
    material_family: str = "HYBRID_AL_CFRP",
    cosysmo_complexity: str = "NOMINAL",
    idp_maturity: str = "COMPLETE",
    target_margin_pct: str = "22.000",
    cve_min_ratio_pct: str | None = None,
    idp_feature_factor: str = "1.000",
    extra_solve_postproc_hours: str = "0.000",
) -> dict[str, Any]:
    """Build deterministic multi-archetype WBS DAG with CPM float & synergy reuse."""
    ordered_unique = list(dict.fromkeys(str(a).strip() for a in archetype_ids if str(a).strip()))
    if not ordered_unique:
        raise QuotationAbstain("empty_archetype_list", "wbs_dag")
    for aid in ordered_unique:
        if aid not in ROTORCRAFT_QUOTATION_ARCHETYPES:
            raise QuotationAbstain(f"unknown_rotorcraft_archetype:{aid}", "wbs_dag")
    if country_code not in COUNTRY_RATE_CARDS:
        raise QuotationAbstain("unsupported_country_code", "wbs_dag")

    country_card = COUNTRY_RATE_CARDS[country_code]
    cert_factor = _CERT_BASIS_FACTORS.get(cert_basis, "1.350")
    mat_factor = _MATERIAL_FACTORS.get(material_family, "1.250")
    cos_base = Decimal(_COSYSMO_FACTORS.get(cosysmo_complexity.upper(), "1.000")) * Decimal(
        idp_feature_factor
    )
    base_cont = Decimal(country_card["contingency_pct"])
    if idp_maturity.upper() == "INCOMPLETE":
        base_cont += Decimal("6.000")
    elif idp_maturity.upper() == "PARTIAL":
        base_cont += Decimal("3.000")
    contingency_str = format_quantum(base_cont, _Q3)

    node_set = set(ordered_unique)
    edges_map: dict[tuple[str, str], str] = {}
    for pred, succ, channel in CANONICAL_ARCHETYPE_PRECEDENCE:
        if pred in node_set and succ in node_set and pred != succ:
            edges_map[(pred, succ)] = channel
    for item in custom_edges or ():
        if len(item) >= 2:
            pred = str(item[0]).strip()
            succ = str(item[1]).strip()
            channel = str(item[2]).strip() if len(item) >= 3 else "CAD_DMU"
            if pred in node_set and succ in node_set:
                edges_map[(pred, succ)] = channel

    preds: dict[str, list[str]] = {aid: [] for aid in ordered_unique}
    succs: dict[str, list[str]] = {aid: [] for aid in ordered_unique}
    in_degree: dict[str, int] = {aid: 0 for aid in ordered_unique}
    edge_list: list[dict[str, str]] = []

    for (u, v), chan in sorted(edges_map.items()):
        preds[v].append(u)
        succs[u].append(v)
        in_degree[v] += 1
        edge_list.append({"from": u, "to": v, "synergy_channel": chan})

    # Kahn topological sort (detects cycles deterministically)
    queue: deque[str] = deque(sorted(aid for aid, deg in in_degree.items() if deg == 0))
    topo_order: list[str] = []
    in_deg_mut = dict(in_degree)
    while queue:
        cur = queue.popleft()
        topo_order.append(cur)
        for nxt in sorted(succs[cur]):
            in_deg_mut[nxt] -= 1
            if in_deg_mut[nxt] == 0:
                queue.append(nxt)

    if len(topo_order) != len(ordered_unique):
        raise QuotationAbstain("cyclic_wbs_dag", "wbs_dag")

    # Determine which single stress-related node receives deep IDP solve/postproc hours (if any)
    extra_solve_d = Decimal(extra_solve_postproc_hours or "0")
    solve_target_node = next(
        (n for n in ("Q-STR-03", "Q-STR-02", "Q-FDT-01", "Q-DYN-01") if n in node_set),
        topo_order[0],
    )

    node_details: dict[str, dict[str, Any]] = {}
    standalone_hours_sum = _ZERO
    standalone_cost_sum = _ZERO
    standalone_price_sum = _ZERO
    synergy_hours_sum = _ZERO
    synergy_cost_sum = _ZERO
    synergy_price_sum = _ZERO
    cve_hours_sum = _ZERO

    agg_raw_hours: dict[str, Decimal] = {
        k: _ZERO
        for k in (
            "cad_hours",
            "loads_hours",
            "stress_hours",
            "fdt_dyn_hours",
            "systems_hours",
            "test_hours",
            "cve_hours",
            "proto_hours",
            "hpc_hours",
        )
    }
    agg_travel_hw = _ZERO

    for aid in topo_order:
        arch = ROTORCRAFT_QUOTATION_ARCHETYPES[aid]
        eff_cos = format_quantum(Decimal(arch["default_cosysmo_factor"]) * cos_base, _Q3)
        eff_cve_floor = cve_min_ratio_pct or arch["cve_min_ratio_pct"]
        node_extra_stress = extra_solve_d if aid == solve_target_node else _ZERO

        # Accumulate synergy reuse discounts from all incoming edges
        discounts: dict[str, Decimal] = {}
        active_channels: list[str] = []
        for p_id in preds[aid]:
            chan = edges_map[(p_id, aid)]
            active_channels.append(f"{p_id}:{chan}")
            for field_k, red in _SYNERGY_CHANNEL_RULES.get(chan, ()):
                discounts[field_k] = min(
                    _MAX_SYNERGY_DISCOUNT_PER_DISC, discounts.get(field_k, _ZERO) + red
                )

        standalone_inp = _compute_node_inputs(
            arch,
            country_card,
            cert_basis_factor=cert_factor,
            material_complexity_factor=mat_factor,
            cosysmo_driver_factor=eff_cos,
            pvt_compression_factor=arch["default_pvt_factor"],
            margin_pct=target_margin_pct,
            cve_min_ratio_pct=eff_cve_floor,
            contingency_override=contingency_str,
            discounts={},
            extra_stress_hours=node_extra_stress,
        )
        synergy_inp = _compute_node_inputs(
            arch,
            country_card,
            cert_basis_factor=cert_factor,
            material_complexity_factor=mat_factor,
            cosysmo_driver_factor=eff_cos,
            pvt_compression_factor=arch["default_pvt_factor"],
            margin_pct=target_margin_pct,
            cve_min_ratio_pct=eff_cve_floor,
            contingency_override=contingency_str,
            discounts=discounts,
            extra_stress_hours=node_extra_stress,
        )

        try:
            st_res = run_method(
                "rotorcraft_archetype_quote", standalone_inp, include_intervals=False
            )
            sy_res = run_method("rotorcraft_archetype_quote", synergy_inp, include_intervals=False)
        except AbstainError as exc:
            raise QuotationAbstain("calc_guard_abstain", f"wbs_dag:{exc.reason}") from exc

        st_out = st_res["outputs"]
        sy_out = sy_res["outputs"]
        st_hrs = Decimal(st_out["total_scaled_hours"])
        sy_hrs = Decimal(sy_out["total_scaled_hours"])
        st_cost = Decimal(st_out["total_cost_eur"])
        sy_cost = Decimal(sy_out["total_cost_eur"])
        st_price = Decimal(st_out["quote_price_eur"])
        sy_price = Decimal(sy_out["quote_price_eur"])

        standalone_hours_sum += st_hrs
        standalone_cost_sum += st_cost
        standalone_price_sum += st_price
        synergy_hours_sum += sy_hrs
        synergy_cost_sum += sy_cost
        synergy_price_sum += sy_price
        cve_hours_sum += Decimal(sy_out["cve_scaled_hours"])

        # Track net scaled hours per specialty for 9-country composite benchmark
        core_scale = Decimal(cert_factor) * Decimal(mat_factor) * Decimal(eff_cos)
        agg_raw_hours["cad_hours"] += Decimal(synergy_inp["cad_hours"]) * core_scale
        agg_raw_hours["loads_hours"] += Decimal(synergy_inp["loads_hours"]) * core_scale
        agg_raw_hours["stress_hours"] += Decimal(synergy_inp["stress_hours"]) * core_scale
        agg_raw_hours["fdt_dyn_hours"] += Decimal(synergy_inp["fdt_dyn_hours"]) * core_scale
        agg_raw_hours["systems_hours"] += Decimal(synergy_inp["systems_hours"]) * core_scale
        agg_raw_hours["test_hours"] += (
            Decimal(synergy_inp["test_hours"])
            * Decimal(cert_factor)
            * Decimal(arch["default_pvt_factor"])
        )
        agg_raw_hours["proto_hours"] += Decimal(synergy_inp["proto_hours"]) * Decimal(mat_factor)
        agg_raw_hours["cve_hours"] += Decimal(sy_out["cve_scaled_hours"])
        agg_raw_hours["hpc_hours"] += Decimal(synergy_inp["hpc_hours"])
        agg_travel_hw += Decimal(synergy_inp["travel_hardware_eur"])

        with localcontext() as ctx:
            ctx.prec = 30
            fte = _effective_fte_for_family(arch["family"])
            dur_weeks = max(Decimal("2.0"), (sy_hrs / (fte * Decimal("40"))).quantize(_Q1))
            synergy_pct = ((st_hrs - sy_hrs) / st_hrs) * _HUNDRED if st_hrs > _ZERO else _ZERO

        node_details[aid] = {
            "archetype_id": aid,
            "family": arch["family"],
            "title": arch["title"],
            "predecessors": list(sorted(preds[aid])),
            "successors": list(sorted(succs[aid])),
            "synergy_channels": active_channels,
            "synergy_reduction_pct": format_quantum(synergy_pct, _Q2),
            "standalone_hours": format_quantum(st_hrs, _Q3),
            "net_hours": format_quantum(sy_hrs, _Q3),
            "hours_saved": format_quantum(st_hrs - sy_hrs, _Q3),
            "cve_hours": sy_out["cve_scaled_hours"],
            "cve_share_pct": sy_out["cve_share_pct"],
            "standalone_cost_eur": format_quantum(st_cost, _Q3),
            "net_cost_eur": format_quantum(sy_cost, _Q3),
            "standalone_price_eur": format_quantum(st_price, _Q3),
            "net_price_eur": format_quantum(sy_price, _Q3),
            "duration_weeks": format_quantum(dur_weeks, _Q1),
            "fixed_price_share_pct": arch["fixed_price_share_pct"],
            "synergy_inputs": synergy_inp,
        }

    # CPM Forward Pass (Early Start, Early Finish)
    for aid in topo_order:
        p_finishes = [Decimal(node_details[p]["early_finish_week"]) for p in preds[aid]]
        es = max(p_finishes) if p_finishes else _ZERO
        ef = es + Decimal(node_details[aid]["duration_weeks"])
        node_details[aid]["early_start_week"] = format_quantum(es, _Q1)
        node_details[aid]["early_finish_week"] = format_quantum(ef, _Q1)

    project_duration = max(Decimal(node_details[aid]["early_finish_week"]) for aid in topo_order)

    # CPM Backward Pass (Late Start, Late Finish, Total Float, Free Float)
    for aid in reversed(topo_order):
        s_starts = [Decimal(node_details[s]["late_start_week"]) for s in succs[aid]]
        lf = min(s_starts) if s_starts else project_duration
        dur = Decimal(node_details[aid]["duration_weeks"])
        ls = lf - dur
        es = Decimal(node_details[aid]["early_start_week"])
        ef = Decimal(node_details[aid]["early_finish_week"])
        tot_float = max(_ZERO, ls - es)
        s_es = [Decimal(node_details[s]["early_start_week"]) for s in succs[aid]]
        free_float = max(_ZERO, (min(s_es) - ef) if s_es else (project_duration - ef))
        node_details[aid]["late_start_week"] = format_quantum(ls, _Q1)
        node_details[aid]["late_finish_week"] = format_quantum(lf, _Q1)
        node_details[aid]["total_float_weeks"] = format_quantum(tot_float, _Q1)
        node_details[aid]["free_float_weeks"] = format_quantum(free_float, _Q1)
        node_details[aid]["is_critical"] = tot_float == _ZERO

    critical_path = [aid for aid in topo_order if node_details[aid]["is_critical"]]

    with localcontext() as ctx:
        ctx.prec = 30
        synergy_savings_pct = (
            ((standalone_price_sum - synergy_price_sum) / standalone_price_sum) * _HUNDRED
            if standalone_price_sum > _ZERO
            else _ZERO
        )
        cve_total_share_pct = (
            (cve_hours_sum / synergy_hours_sum) * _HUNDRED if synergy_hours_sum > _ZERO else _ZERO
        )

    return {
        "node_count": len(topo_order),
        "edge_count": len(edge_list),
        "topological_order": topo_order,
        "edges": edge_list,
        "nodes": [node_details[aid] for aid in topo_order],
        "critical_path_archetypes": critical_path,
        "project_duration_weeks": format_quantum(project_duration, _Q1),
        "standalone_total_hours": format_quantum(standalone_hours_sum, _Q3),
        "synergy_net_total_hours": format_quantum(synergy_hours_sum, _Q3),
        "synergy_hours_saved": format_quantum(standalone_hours_sum - synergy_hours_sum, _Q3),
        "standalone_total_cost_eur": format_quantum(standalone_cost_sum, _Q3),
        "synergy_net_total_cost_eur": format_quantum(synergy_cost_sum, _Q3),
        "standalone_total_price_eur": format_quantum(standalone_price_sum, _Q3),
        "synergy_net_total_price_eur": format_quantum(synergy_price_sum, _Q3),
        "synergy_price_saved_eur": format_quantum(standalone_price_sum - synergy_price_sum, _Q3),
        "synergy_savings_pct": format_quantum(synergy_savings_pct, _Q2),
        "cve_total_hours": format_quantum(cve_hours_sum, _Q3),
        "cve_total_share_pct": format_quantum(cve_total_share_pct, _Q2),
        "aggregated_net_hours_by_specialty": {
            k: format_quantum(v, _Q3) for k, v in agg_raw_hours.items()
        },
        "aggregated_travel_hardware_eur": format_quantum(agg_travel_hw, _Q3),
    }


def prove_multiyear_npv_and_margin_envelope(
    *,
    quoted_price_eur: str,
    active_base_total_cost_eur: str,
    program_years: int,
    payment_terms_days: int,
    milestone_pcts: tuple[str, str, str, str, str],
    wc_deficit_exposure_eur: str,
    min_npv_eur: str = "0.000",
    min_net_margin_pct: str = "10.000",
    cost_drift_bounds: tuple[str, str] = ("0.950", "1.080"),
    annual_inflation_bounds_pct: tuple[str, str] = ("2.500", "5.500"),
    annual_wacc_bounds_pct: tuple[str, str] = ("6.500", "10.500"),
) -> dict[str, Any]:
    """Formally prove via denominator-cleared Z3 SMT that NPV >= floor & net margin >= floor."""
    price_dec = Decimal(quoted_price_eur)
    base_dec = Decimal(active_base_total_cost_eur)
    wc_exp_dec = Decimal(wc_deficit_exposure_eur)
    min_npv_dec = Decimal(min_npv_eur)
    min_margin_dec = Decimal(min_net_margin_pct)
    n_years = max(1, min(5, int(program_years)))
    lag_months = (max(0, int(payment_terms_days)) + 29) // 30
    max_yr_pow = n_years + (1 if lag_months > 0 else 0)

    def _q(val: Decimal | str) -> z3.ArithRef:
        f = Fraction(str(val))
        return z3.Q(f.numerator, f.denominator)

    solver = z3.Solver()
    solver.set("timeout", 5000)

    drift = z3.Real("cost_drift_factor")
    inf_rate = z3.Real("annual_inflation_rate")
    wacc_rate = z3.Real("annual_wacc_rate")

    solver.add(drift >= _q(cost_drift_bounds[0]), drift <= _q(cost_drift_bounds[1]))
    solver.add(
        inf_rate >= _q(Decimal(annual_inflation_bounds_pct[0]) / _HUNDRED),
        inf_rate <= _q(Decimal(annual_inflation_bounds_pct[1]) / _HUNDRED),
    )
    solver.add(
        wacc_rate >= _q(Decimal(annual_wacc_bounds_pct[0]) / _HUNDRED),
        wacc_rate <= _q(Decimal(annual_wacc_bounds_pct[1]) / _HUNDRED),
    )

    u = 1 + inf_rate
    v = 1 + wacc_rate
    u_pows = [z3.Q(1, 1)]
    for _ in range(1, n_years):
        u_pows.append(u_pows[-1] * u)

    v_pows = [z3.Q(1, 1)]
    for _ in range(1, max_yr_pow + 1):
        v_pows.append(v_pows[-1] * v)

    p_z3 = _q(price_dec)
    b_z3 = _q(base_dec)
    annual_b_z3 = b_z3 / z3.Q(n_years, 1)

    esc_cost = sum(annual_b_z3 * drift * u_pows[y] for y in range(n_years))

    total_months = 12 * n_years
    bill_months = (
        1,
        max(1, (total_months * 25 + 50) // 100),
        max(1, (total_months * 50 + 50) // 100),
        max(1, (total_months * 80 + 50) // 100),
        total_months,
    )
    npv_in_scaled = z3.Q(0, 1)
    for b_m, m_pct in zip(bill_months, milestone_pcts, strict=True):
        cash_m = b_m + lag_months
        ceil_yr = min(max_yr_pow, (cash_m + 11) // 12)
        share = _q(Decimal(m_pct) / _HUNDRED)
        npv_in_scaled = npv_in_scaled + p_z3 * share * v_pows[max_yr_pow - ceil_yr]

    # Outflows during year y discounted conservatively at start of year y
    npv_out_scaled = sum(
        annual_b_z3 * drift * u_pows[y] * v_pows[max_yr_pow - y] for y in range(n_years)
    )

    wc_fin = (_q(wc_exp_dec) * drift) * (wacc_rate / z3.Q(12, 1))
    net_margin = p_z3 - esc_cost - wc_fin
    floor_frac = _q(min_margin_dec / _HUNDRED)

    solver.add(
        z3.Or(
            (npv_in_scaled - npv_out_scaled) < (_q(min_npv_dec) * v_pows[max_yr_pow]),
            net_margin < (floor_frac * p_z3),
        )
    )

    res_status = solver.check()
    counterexample: dict[str, str] | None = None
    if res_status == z3.unsat:
        status = "PROVED_UNSAT"
        proved = True
    elif res_status == z3.sat:
        status = "COUNTEREXAMPLE_FOUND"
        proved = False
        model = solver.model()

        def _eval_dec(expr: Any, fallback: str) -> Decimal:
            ev = model.eval(expr, model_completion=True)
            if hasattr(ev, "as_fraction"):
                fr = ev.as_fraction()
                return Decimal(fr.numerator) / Decimal(fr.denominator)
            return Decimal(fallback)

        d_dec = _eval_dec(drift, cost_drift_bounds[1])
        inf_dec = _eval_dec(inf_rate, str(Decimal(annual_inflation_bounds_pct[1]) / _HUNDRED))
        wacc_dec = _eval_dec(wacc_rate, str(Decimal(annual_wacc_bounds_pct[1]) / _HUNDRED))

        ce_esc = sum(
            (base_dec / Decimal(n_years)) * d_dec * ((_ONE + inf_dec) ** y) for y in range(n_years)
        )
        ce_wc = (wc_exp_dec * d_dec) * (wacc_dec / Decimal("12"))
        ce_margin_pct = (
            ((price_dec - ce_esc - ce_wc) / price_dec) * _HUNDRED if price_dec > _ZERO else _ZERO
        )
        ce_npv_in = sum(
            price_dec
            * (Decimal(m_pct) / _HUNDRED)
            / ((_ONE + wacc_dec) ** min(max_yr_pow, (b_m + lag_months + 11) // 12))
            for b_m, m_pct in zip(bill_months, milestone_pcts, strict=True)
        )
        ce_npv_out = sum(
            ((base_dec / Decimal(n_years)) * d_dec * ((_ONE + inf_dec) ** y))
            / ((_ONE + wacc_dec) ** y)
            for y in range(n_years)
        )
        counterexample = {
            "cost_drift_factor": format_quantum(d_dec, _Q3),
            "annual_inflation_pct": format_quantum(inf_dec * _HUNDRED, _Q2),
            "annual_wacc_pct": format_quantum(wacc_dec * _HUNDRED, _Q2),
            "breached_npv_eur": format_quantum(ce_npv_in - ce_npv_out, _Q3),
            "breached_net_margin_pct": format_quantum(ce_margin_pct, _Q2),
        }
    else:
        status = "UNKNOWN"
        proved = False

    assumptions_payload = {
        "quoted_price_eur": quoted_price_eur,
        "active_base_total_cost_eur": active_base_total_cost_eur,
        "program_years": n_years,
        "payment_terms_days": payment_terms_days,
        "min_npv_eur": min_npv_eur,
        "min_net_margin_pct": min_net_margin_pct,
        "cost_drift_bounds": list(cost_drift_bounds),
        "annual_inflation_bounds_pct": list(annual_inflation_bounds_pct),
        "annual_wacc_bounds_pct": list(annual_wacc_bounds_pct),
    }
    assertion = (
        f"forall (drift in [{cost_drift_bounds[0]},{cost_drift_bounds[1]}], "
        f"inf in [{annual_inflation_bounds_pct[0]}%,{annual_inflation_bounds_pct[1]}%], "
        f"wacc in [{annual_wacc_bounds_pct[0]}%,{annual_wacc_bounds_pct[1]}%]): "
        f"NPV >= {min_npv_eur} EUR AND NetMarginAfterFinancing >= {min_net_margin_pct}%"
    )
    proof_hash = inputs_hash(
        {
            "property_name": "multiyear_npv_and_margin_envelope",
            "status": status,
            "assumptions": assumptions_payload,
            "assertion": assertion,
            "counterexample": counterexample,
        }
    )
    return {
        "property_name": "multiyear_npv_and_margin_envelope",
        "proved": proved,
        "status": status,
        "assumptions": assumptions_payload,
        "assertion": assertion,
        "counterexample": counterexample,
        "proof_hash": proof_hash,
    }


@dataclass(frozen=True)
class CompositeRotorcraftQuotationSpec:
    """Unified input specification for Composite DAG + Multi-Year + IDP + Contract Quotation."""

    rfq_text: str
    archetype_ids: tuple[str, ...] = ()
    custom_edges: tuple[tuple[str, str, str], ...] = ()
    country_code: str = "EU_DEFAULT"
    nearshore_country: str = "ES"
    cert_basis: str = "CS-29"
    material_family: str = "HYBRID_AL_CFRP"
    cosysmo_complexity: str = "NOMINAL"
    idp_maturity: str = "COMPLETE"
    target_margin_pct: str = "22.000"
    min_acceptable_margin_pct: str = "10.000"
    min_npv_eur: str = "0.000"
    unit_count: int = 1
    learning_rate_pct: str = "85.000"
    crawford_weight_pct: str = "50.000"
    program_years: int = 3
    annual_inflation_pct: str | None = None
    wacc_annual_pct: str | None = None
    payment_terms_days: int | None = None
    milestone_ko_pct: str = "25.000"
    milestone_pdr_pct: str = "20.000"
    milestone_cdr_pct: str = "25.000"
    milestone_test_pct: str = "15.000"
    milestone_cve_pct: str = "15.000"
    cve_min_ratio_pct: str | None = None
    enable_formal_smt: bool = True
    export_control_restricted: bool = False
    enforce_contract_gate: bool = True
    contract_clauses: list[dict[str, Any]] | None = None
    idp_attachments: dict[str, Any] = field(default_factory=dict)
    use_historical_calibration: bool = True
    historical_corpus_path: str | None = None
    historical_top_k: int = 3
    assumption_overrides: dict[str, str] = field(default_factory=dict)
    tenant_id: str = "demo"
    actor_id: str = "author"
    created_at: str = ""
    rfq_id: str = "RFQ-COMP-001"
    customer_name: str = "Rotorcraft OEM / DOA Client"
    currency: str = "EUR"


def _compute_composite_9_country_comparison(
    dag: dict[str, Any],
    *,
    selected_country: str,
    nearshore_country: str,
    target_margin_pct: str,
    contingency_override: str,
    cve_min_ratio_pct: str,
) -> dict[str, Any]:
    """Compare total composite WBS price across all 9 countries + Onshore/Nearshore hybrid."""
    net_hrs = dag["aggregated_net_hours_by_specialty"]
    travel_hw = dag["aggregated_travel_hardware_eur"]

    def _run_country(
        rates: dict[str, str],
        overhead_pct: str,
        cont_pct: str,
    ) -> dict[str, str]:
        inp = {
            "cad_hours": net_hrs["cad_hours"],
            "loads_hours": net_hrs["loads_hours"],
            "stress_hours": net_hrs["stress_hours"],
            "fdt_dyn_hours": net_hrs["fdt_dyn_hours"],
            "systems_hours": net_hrs["systems_hours"],
            "test_hours": net_hrs["test_hours"],
            "cve_hours": net_hrs["cve_hours"],
            "proto_hours": net_hrs["proto_hours"],
            "cad_rate": rates["cad_rate"],
            "loads_rate": rates["loads_rate"],
            "stress_rate": rates["stress_rate"],
            "fdt_dyn_rate": rates["fdt_dyn_rate"],
            "systems_rate": rates["systems_rate"],
            "test_rate": rates["test_rate"],
            "cve_rate": rates["cve_rate"],
            "proto_rate": rates["proto_rate"],
            "cert_basis_factor": "1.000",
            "material_complexity_factor": "1.000",
            "cosysmo_driver_factor": "1.000",
            "pvt_compression_factor": "1.000",
            "hpc_hours": net_hrs["hpc_hours"],
            "hpc_rate": rates["hpc_rate"],
            "travel_hardware_eur": travel_hw,
            "overhead_pct": overhead_pct,
            "contingency_pct": cont_pct,
            "margin_pct": target_margin_pct,
            "fixed_price_share_pct": "65.000",
            "cve_min_ratio_pct": cve_min_ratio_pct,
        }
        return run_method("rotorcraft_archetype_quote", inp, include_intervals=False)["outputs"]

    rows: list[dict[str, Any]] = []
    eu_price = _ZERO
    sel_price = _ZERO
    for code, card in COUNTRY_RATE_CARDS.items():
        cont = contingency_override if code == selected_country else card["contingency_pct"]
        out = _run_country(card["rates"], card["overhead_pct"], cont)
        p = Decimal(out["quote_price_eur"])
        if code == "EU_DEFAULT":
            eu_price = p
        if code == selected_country:
            sel_price = p
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

    for row in rows:
        p = Decimal(row["quote_price_eur"])
        row["delta_vs_eu_default_pct"] = format_quantum(
            ((p - eu_price) / eu_price) * _HUNDRED if eu_price > _ZERO else _ZERO, _Q2
        )
        row["delta_vs_selected_pct"] = format_quantum(
            ((p - sel_price) / sel_price) * _HUNDRED if sel_price > _ZERO else _ZERO, _Q2
        )
    rows.sort(key=lambda r: Decimal(r["quote_price_eur"]), reverse=True)

    onshore_code = "EU_DEFAULT" if selected_country in ("ES", "PL", "IN") else selected_country
    near_code = nearshore_country if nearshore_country in COUNTRY_RATE_CARDS else "ES"
    on_card = COUNTRY_RATE_CARDS[onshore_code]
    nr_card = COUNTRY_RATE_CARDS[near_code]
    hyb_rates = {
        "cad_rate": nr_card["rates"]["cad_rate"],
        "loads_rate": on_card["rates"]["loads_rate"],
        "stress_rate": nr_card["rates"]["stress_rate"],
        "fdt_dyn_rate": nr_card["rates"]["fdt_dyn_rate"],
        "systems_rate": on_card["rates"]["systems_rate"],
        "test_rate": nr_card["rates"]["test_rate"],
        "cve_rate": on_card["rates"]["cve_rate"],
        "proto_rate": nr_card["rates"]["proto_rate"],
        "hpc_rate": nr_card["rates"]["hpc_rate"],
    }
    hyb_cont = format_quantum(Decimal(nr_card["contingency_pct"]) + Decimal("2.000"), _Q3)
    hyb_out = _run_country(hyb_rates, on_card["overhead_pct"], hyb_cont)
    onshore_price = Decimal(
        [r["quote_price_eur"] for r in rows if r["country_code"] == onshore_code][0]
    )
    hyb_delta = ((Decimal(hyb_out["quote_price_eur"]) - onshore_price) / onshore_price) * _HUNDRED

    return {
        "selected_country": selected_country,
        "eu_default_price_eur": format_quantum(eu_price, _Q3),
        "countries": rows,
        "onshore_nearshore_hybrid": {
            "onshore_cve_country": onshore_code,
            "nearshore_execution_country": near_code,
            "coordination_contingency_pct": hyb_cont,
            "quote_price_eur": hyb_out["quote_price_eur"],
            "total_cost_eur": hyb_out["total_cost_eur"],
            "blended_hourly_rate_eur": hyb_out["blended_hourly_rate_eur"],
            "delta_vs_onshore_pct": format_quantum(hyb_delta, _Q2),
            "note": (
                f"Onshore Part 21J CVE/Systems/Loads in {onshore_code} + "
                f"CAD/FEM/F&DT execution in {near_code}."
            ),
        },
    }


def _record_composite_abstain(
    ledger: Ledger,
    spec: CompositeRotorcraftQuotationSpec,
    *,
    created_at: str,
    reason: str,
    stage: str,
    contract_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rfq_hash = hashlib.sha256(spec.rfq_text.encode("utf-8")).hexdigest()
    env = make_envelope(
        sources=[
            project_source(
                "composite-quotation-supervisor",
                "https://aeroregu.local/rotorcraft/composite-quote",
                "ASSUMPTION",
            )
        ],
        method_version="composite_rotorcraft_quotation@1.0.0",
        inputs={"rfq_sha256": rfq_hash, "stage": stage},
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
        "escalate_to": "human_engineer_cve_and_legal",
        "contract_audit": contract_audit,
        "event_hashes": [ev_hash],
        "merkle_root": ledger.merkle_root(),
        "markdown_report": (
            f"# Composite Rotorcraft Quotation Abstained (`{reason}`)\n\n"
            f"- **Stage:** `{stage}`\n"
            f"- **Escalate To:** `human_engineer_cve_and_legal`\n"
            f"- **Ledger Event:** `{ev_hash}`\n"
        ),
    }


def run_composite_rotorcraft_quotation(
    ledger: Ledger,
    spec: CompositeRotorcraftQuotationSpec,
) -> dict[str, Any]:
    """Execute complete Q1-Q4 composite DAG, multi-year cashflow, deep IDP, audit & Z3 quote."""
    from datetime import UTC, datetime

    created_at = spec.created_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    safety = check_text_safety(spec.rfq_text or "composite quotation")
    if safety is not None:
        return _record_composite_abstain(
            ledger, spec, created_at=created_at, reason=f"safety_guardrail:{safety}", stage="safety"
        )

    contract_audit = audit_rfq_contract_clauses(
        spec.rfq_text,
        clauses=spec.contract_clauses,
        filename=f"{spec.rfq_id}.txt",
    )

    try:
        margin_d = Decimal(spec.target_margin_pct)
        min_margin_d = Decimal(spec.min_acceptable_margin_pct)
        if margin_d <= _ZERO or min_margin_d < _ZERO or min_margin_d > margin_d:
            raise QuotationAbstain("invalid_margin_bounds", "commercial_gate")

        if spec.country_code not in COUNTRY_RATE_CARDS:
            raise QuotationAbstain("unsupported_country_code", "intake_country")

        if spec.cve_min_ratio_pct is not None and Decimal(spec.cve_min_ratio_pct) < Decimal(
            "5.000"
        ):
            raise QuotationAbstain("cve_independence_mandatory", "compliance_gate")

        # Contractual poison-clause blocking check
        if spec.enforce_contract_gate and contract_audit["has_blocking_reject_clauses"]:
            poisons = [p["poison_id"] for p in contract_audit["poison_clauses_detected"]]
            if "CVE_INDEPENDENCE_WAIVER" in poisons:
                raise QuotationAbstain("cve_independence_mandatory", "contract_audit")
            raise QuotationAbstain(
                f"blocking_contract_clause:{','.join(sorted(set(poisons)))}", "contract_audit"
            )

        # Classify primary archetype if none supplied explicitly
        cls_res = classify_rotorcraft_rfq(
            spec.rfq_text,
            archetype_id=spec.archetype_ids[0] if spec.archetype_ids else None,
            cert_basis=spec.cert_basis,
            material_family=spec.material_family,
            country_code=spec.country_code,
        )
        chosen_ids = list(spec.archetype_ids) if spec.archetype_ids else [cls_res["archetype_id"]]

        # Deep Physical IDP Inspection (Q2)
        idp_profile = extract_idp_physical_complexity(
            spec.idp_attachments,
            default_cosysmo=spec.cosysmo_complexity,
            default_idp_maturity=spec.idp_maturity,
        )
        deep_metrics = idp_profile.deep_metrics or {}
        extra_solve_hrs = str(deep_metrics.get("estimated_solve_postproc_hours") or "0.000")

        # Composite WBS DAG + CPM + Synergy (Q1)
        dag = build_composite_wbs_dag(
            chosen_ids,
            custom_edges=list(spec.custom_edges),
            country_code=spec.country_code,
            cert_basis=cls_res["cert_basis"],
            material_family=cls_res["material_family"],
            cosysmo_complexity=idp_profile.derived_cosysmo_complexity,
            idp_maturity=idp_profile.derived_idp_maturity,
            target_margin_pct=spec.target_margin_pct,
            cve_min_ratio_pct=spec.cve_min_ratio_pct,
            idp_feature_factor=idp_profile.idp_feature_complexity_factor,
            extra_solve_postproc_hours=extra_solve_hrs,
        )

        country_card = COUNTRY_RATE_CARDS[spec.country_code]
        infl_prof = COUNTRY_INFLATION_PROFILES[spec.country_code]
        ann_inf = spec.annual_inflation_pct or infl_prof["annual_inflation_pct"]
        wacc_pct = spec.wacc_annual_pct or infl_prof["wacc_annual_pct"]
        pay_days = (
            int(spec.payment_terms_days)
            if spec.payment_terms_days is not None
            else int(infl_prof["default_payment_terms_days"])
        )

        # Compute composite PERT P50 / P80 / P90 across DAG nodes (variance sum over PERT)
        net_cost_m = Decimal(dag["synergy_net_total_cost_eur"])
        net_price_m = Decimal(dag["synergy_net_total_price_eur"])
        net_hours_m = Decimal(dag["synergy_net_total_hours"])

        pert_expected_total_h = _ZERO
        pert_var_sum_h = _ZERO
        for node in dag["nodes"]:
            arch = ROTORCRAFT_QUOTATION_ARCHETYPES[node["archetype_id"]]
            p_def = arch["pert_total_hours"]
            ml_raw = Decimal(p_def["most_likely"])
            opt_raw = Decimal(p_def["optimistic"])
            pess_raw = Decimal(p_def["pessimistic"])
            node_net_h = Decimal(node["net_hours"])
            scale_ratio = node_net_h / ml_raw if ml_raw > _ZERO else _ONE
            node_exp = ((opt_raw + _FOUR * ml_raw + pess_raw) / _SIX) * scale_ratio
            node_sig = ((pess_raw - opt_raw) / _SIX) * scale_ratio
            pert_expected_total_h += node_exp
            pert_var_sum_h += node_sig * node_sig

        with localcontext() as ctx:
            ctx.prec = 30
            pert_sigma_h = pert_var_sum_h.sqrt() if pert_var_sum_h > _ZERO else _ZERO
            pert_p50_h = pert_expected_total_h
            pert_p80_h = pert_p50_h + (_Z_P80 * pert_sigma_h)
            pert_p90_h = pert_p50_h + (_Z_P90 * pert_sigma_h)
            r_p50 = pert_p50_h / net_hours_m if net_hours_m > _ZERO else _ONE
            r_p80 = pert_p80_h / net_hours_m if net_hours_m > _ZERO else _ONE
            r_p90 = pert_p90_h / net_hours_m if net_hours_m > _ZERO else _ONE

        cost_p80 = net_cost_m * r_p80
        price_p50 = net_price_m * r_p50
        price_p80 = net_price_m * r_p80
        price_p90 = net_price_m * r_p90

        pert_envelope = {
            "hours_most_likely_scaled": format_quantum(net_hours_m, _Q3),
            "hours_p50_scaled": format_quantum(pert_p50_h, _Q3),
            "hours_p80_scaled": format_quantum(pert_p80_h, _Q3),
            "hours_p90_scaled": format_quantum(pert_p90_h, _Q3),
            "price_most_likely_eur": format_quantum(net_price_m, _Q3),
            "price_p50_eur": format_quantum(price_p50, _Q3),
            "price_p80_eur": format_quantum(price_p80, _Q3),
            "price_p90_eur": format_quantum(price_p90, _Q3),
            "cost_p80_eur": format_quantum(cost_p80, _Q3),
        }

        # Multi-Year Learning Curve, Inflation Escalation & Cash-Flow Deterministic Calc + Arb
        multiyear_inputs = {
            "first_unit_cost_eur": format_quantum(cost_p80, _Q3),
            "unit_count": str(spec.unit_count),
            "learning_rate_pct": spec.learning_rate_pct,
            "crawford_weight_pct": spec.crawford_weight_pct,
            "program_years": str(spec.program_years),
            "annual_inflation_pct": ann_inf,
            "target_margin_pct": spec.target_margin_pct,
            "wacc_annual_pct": wacc_pct,
            "payment_terms_days": str(pay_days),
            "milestone_ko_pct": spec.milestone_ko_pct,
            "milestone_pdr_pct": spec.milestone_pdr_pct,
            "milestone_cdr_pct": spec.milestone_cdr_pct,
            "milestone_test_pct": spec.milestone_test_pct,
            "milestone_cve_pct": spec.milestone_cve_pct,
        }
        try:
            my_res = run_method(
                "aerospace_multiyear_cashflow_learning", multiyear_inputs, include_intervals=True
            )
        except AbstainError as exc:
            raise QuotationAbstain("multiyear_calc_abstain", f"multiyear:{exc.reason}") from exc

        my_out = my_res["outputs"]
        my_diag = my_res.get("diagnostics") or {}
        monthly_sched = my_diag.get("monthly_cashflow_schedule") or []
        sum_deficit_eur = sum(
            max(_ZERO, -Decimal(m["cumulative_cashflow_eur"])) for m in monthly_sched
        )
        wc_exposure_conservative = max(
            sum_deficit_eur * Decimal("1.150"),
            Decimal(my_out["active_base_total_cost_eur"])
            * Decimal("0.050")
            * Decimal(max(1, (pay_days + 29) // 30)),
        )

        # Dual Z3 Formal Proofs: Unit P80 Margin Envelope + Multi-Year NPV & Post-Financing Margin
        if spec.enable_formal_smt:
            formal_margin = prove_quotation_margin_envelope(
                quoted_price_p80_eur=format_quantum(price_p80, _Q3),
                direct_cost_baseline_eur=format_quantum(cost_p80 * Decimal("0.780"), _Q3),
                fixed_reserve_cost_eur=format_quantum(cost_p80 * Decimal("0.220"), _Q3),
                min_acceptable_margin_pct=spec.min_acceptable_margin_pct,
            )
            inf_hi = format_quantum(Decimal(ann_inf) + Decimal("2.500"), _Q3)
            wacc_hi = format_quantum(Decimal(wacc_pct) + Decimal("2.000"), _Q3)
            formal_multiyear = prove_multiyear_npv_and_margin_envelope(
                quoted_price_eur=my_out["quoted_price_eur"],
                active_base_total_cost_eur=my_out["active_base_total_cost_eur"],
                program_years=spec.program_years,
                payment_terms_days=pay_days,
                milestone_pcts=(
                    spec.milestone_ko_pct,
                    spec.milestone_pdr_pct,
                    spec.milestone_cdr_pct,
                    spec.milestone_test_pct,
                    spec.milestone_cve_pct,
                ),
                wc_deficit_exposure_eur=format_quantum(wc_exposure_conservative, _Q3),
                min_npv_eur=spec.min_npv_eur,
                min_net_margin_pct=spec.min_acceptable_margin_pct,
                annual_inflation_bounds_pct=(ann_inf, inf_hi),
                annual_wacc_bounds_pct=(wacc_pct, wacc_hi),
            )
        else:
            formal_margin = {"status": "SKIPPED", "proved": False}
            formal_multiyear = {"status": "SKIPPED", "proved": False}

        # 9-Country + Hybrid benchmark on composite WBS
        base_cont = Decimal(country_card["contingency_pct"])
        if idp_profile.derived_idp_maturity.upper() == "INCOMPLETE":
            base_cont += Decimal("6.000")
        elif idp_profile.derived_idp_maturity.upper() == "PARTIAL":
            base_cont += Decimal("3.000")
        cont_str = format_quantum(base_cont, _Q3)
        multi_country = _compute_composite_9_country_comparison(
            dag,
            selected_country=spec.country_code,
            nearshore_country=spec.nearshore_country,
            target_margin_pct=spec.target_margin_pct,
            contingency_override=cont_str,
            cve_min_ratio_pct=spec.cve_min_ratio_pct or "10.000",
        )

        # Tornado sensitivity across composite P80 price
        tornado: list[dict[str, Any]] = []
        base_p80_d = price_p80
        for drv_key, drv_label, lo_kwargs, hi_kwargs in (
            (
                "cert_basis_factor",
                "Certification Basis (CS-27 vs CS-29)",
                {"cert_basis": "CS-27"},
                {"cert_basis": "CS-29"},
            ),
            (
                "material_complexity_factor",
                "Material Complexity (Al vs CFRP)",
                {"material_family": "ALUMINUM_2024_7075"},
                {"material_family": "CFRP_PRIMARY_HONEYCOMB"},
            ),
            (
                "cosysmo_driver_factor",
                "COSYSMO Complexity (LOW vs HIGH)",
                {"cosysmo_complexity": "LOW"},
                {"cosysmo_complexity": "HIGH"},
            ),
            (
                "idp_maturity",
                "IDP Maturity (COMPLETE vs INCOMPLETE)",
                {"idp_maturity": "COMPLETE"},
                {"idp_maturity": "INCOMPLETE"},
            ),
        ):
            lo_dag = build_composite_wbs_dag(
                chosen_ids,
                custom_edges=list(spec.custom_edges),
                country_code=spec.country_code,
                cert_basis=lo_kwargs.get("cert_basis", cls_res["cert_basis"]),
                material_family=lo_kwargs.get("material_family", cls_res["material_family"]),
                cosysmo_complexity=lo_kwargs.get(
                    "cosysmo_complexity", idp_profile.derived_cosysmo_complexity
                ),
                idp_maturity=lo_kwargs.get("idp_maturity", idp_profile.derived_idp_maturity),
                target_margin_pct=spec.target_margin_pct,
                cve_min_ratio_pct=spec.cve_min_ratio_pct,
                idp_feature_factor=idp_profile.idp_feature_complexity_factor,
                extra_solve_postproc_hours=extra_solve_hrs,
            )
            hi_dag = build_composite_wbs_dag(
                chosen_ids,
                custom_edges=list(spec.custom_edges),
                country_code=spec.country_code,
                cert_basis=hi_kwargs.get("cert_basis", cls_res["cert_basis"]),
                material_family=hi_kwargs.get("material_family", cls_res["material_family"]),
                cosysmo_complexity=hi_kwargs.get(
                    "cosysmo_complexity", idp_profile.derived_cosysmo_complexity
                ),
                idp_maturity=hi_kwargs.get("idp_maturity", idp_profile.derived_idp_maturity),
                target_margin_pct=spec.target_margin_pct,
                cve_min_ratio_pct=spec.cve_min_ratio_pct,
                idp_feature_factor=idp_profile.idp_feature_complexity_factor,
                extra_solve_postproc_hours=extra_solve_hrs,
            )
            lo_p = Decimal(lo_dag["synergy_net_total_price_eur"]) * r_p80
            hi_p = Decimal(hi_dag["synergy_net_total_price_eur"]) * r_p80
            swing = abs(hi_p - lo_p)
            tornado.append(
                {
                    "driver_key": drv_key,
                    "driver_label": drv_label,
                    "low_price_eur": format_quantum(lo_p, _Q3),
                    "high_price_eur": format_quantum(hi_p, _Q3),
                    "swing_eur": format_quantum(swing, _Q3),
                    "swing_pct_of_p80": format_quantum(
                        (swing / base_p80_d) * _HUNDRED if base_p80_d > _ZERO else _ZERO, _Q2
                    ),
                }
            )
        tornado.sort(key=lambda r: Decimal(r["swing_eur"]), reverse=True)

        primary_arch = ROTORCRAFT_QUOTATION_ARCHETYPES[chosen_ids[0]]
        assumptions_by_dim = build_archetype_assumptions(
            primary_arch,
            country_card,
            cert_basis=cls_res["cert_basis"],
            material_family=cls_res["material_family"],
            idp_maturity=idp_profile.derived_idp_maturity,
            cosysmo_complexity=idp_profile.derived_cosysmo_complexity,
            export_control_restricted=spec.export_control_restricted,
            overrides=spec.assumption_overrides,
        )

        # Historical Calibration & k-NN retrieval
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
                archetype_id=chosen_ids[0],
                country_code=spec.country_code,
                idp_feature_factor=idp_profile.idp_feature_complexity_factor,
                corpus_origin=corpus_origin,
            )
            nearest_quotes = retrieve_nearest_historical_quotations(
                corpus,
                archetype_id=chosen_ids[0],
                country_code=spec.country_code,
                cert_basis=cls_res["cert_basis"],
                material_family=cls_res["material_family"],
                cosysmo_complexity=idp_profile.derived_cosysmo_complexity,
                idp_maturity=idp_profile.derived_idp_maturity,
                fem_nodes_count=idp_profile.fem_nodes_count,
                load_cases_count=idp_profile.load_cases_count,
                cbush_joints_count=idp_profile.cbush_joints_count,
                cad_drawings_count=idp_profile.dxf_entities_count,
                ply_count=idp_profile.pcomp_laminates_count,
                k=spec.historical_top_k,
            )
    except QuotationAbstain as exc:
        return _record_composite_abstain(
            ledger,
            spec,
            created_at=created_at,
            reason=exc.reason,
            stage=exc.stage,
            contract_audit=contract_audit,
        )

    # Seal composite multiyear calculation & Z3 gates into tamper-evident Ledger
    event_hashes: list[str] = []
    calc_env = make_envelope(
        sources=my_res["sources"],
        method_version=my_res["method_version"],
        inputs=multiyear_inputs,
        confidence="deterministic",
        result=my_out,
    )
    ev_calc = record(
        ledger,
        {
            "event_type": "calc",
            "tenant_id": ledger.tenant_id,
            "actor_id": spec.actor_id,
            "created_at": created_at,
            "payload": {
                "method_id": "aerospace_multiyear_cashflow_learning",
                "inputs": multiyear_inputs,
                "outputs": my_out,
                "composite_dag_nodes": dag["topological_order"],
                "critical_path": dag["critical_path_archetypes"],
            },
            "envelope": calc_env,
        },
    )
    event_hashes.append(ev_calc)

    both_proved = (not spec.enable_formal_smt) or (
        bool(formal_margin.get("proved")) and bool(formal_multiyear.get("proved"))
    )
    decision_status = (
        "APPROVED_FOR_HUMAN_REVIEW" if both_proved else "MARGIN_FLOOR_COUNTEREXAMPLE_HOLD"
    )
    total_assumptions = sum(len(v) for v in assumptions_by_dim.values())

    agent_steps = (
        ("composite_rfq_intake_reader", "reader", {"archetypes": chosen_ids, **cls_res}),
        (
            "wbs_dag_cpm_synergy_checker",
            "checker",
            {
                "node_count": dag["node_count"],
                "critical_path": dag["critical_path_archetypes"],
                "project_duration_weeks": dag["project_duration_weeks"],
                "synergy_savings_pct": dag["synergy_savings_pct"],
            },
        ),
        (
            "multiyear_cashflow_learning_checker",
            "checker",
            {
                "quoted_price_eur": my_out["quoted_price_eur"],
                "net_present_value_eur": my_out["net_present_value_eur"],
                "peak_negative_cashflow_eur": my_out["peak_negative_cashflow_eur"],
            },
        ),
        (
            "contract_clause_auditor",
            "envelope_critic",
            {
                "overall_contract_gate": contract_audit["overall_contract_gate"],
                "poison_clauses_count": contract_audit["poison_clauses_count"],
            },
        ),
        (
            "z3_multiyear_npv_gate",
            "decision_gate",
            {
                "margin_proof": formal_margin.get("status"),
                "multiyear_npv_proof": formal_multiyear.get("status"),
                "decision_status": decision_status,
            },
        ),
        (
            "composite_dossier_scribe",
            "scribe",
            {"rfq_id": spec.rfq_id, "assumptions_total_count": total_assumptions},
        ),
    )

    agent_trace: list[dict[str, Any]] = []
    for role_name, l_agent_id, out_data in agent_steps:
        out_payload = {"quotation_agent_role": role_name, **out_data}
        t_env = make_envelope(
            sources=[
                project_source(
                    role_name,
                    f"https://aeroregu.local/rotorcraft/composite/{role_name}",
                    "ASSUMPTION",
                )
            ],
            method_version=f"{role_name}@1.0.0",
            inputs={"rfq_id": spec.rfq_id, "role": role_name},
            confidence="deterministic" if l_agent_id == "checker" else "draft",
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
    dossier: dict[str, Any] = {
        "rfq_id": spec.rfq_id,
        "tenant_id": ledger.tenant_id,
        "customer_name": spec.customer_name,
        "confidence": "deterministic",
        "decision_status": decision_status,
        "currency": spec.currency,
        "classification": cls_res,
        "archetype": primary_arch,
        "country_profile": country_card,
        "country_inflation_profile": infl_prof,
        "research_models_applied": RESEARCH_BENCHMARK_MODELS,
        "composite_wbs_dag": dag,
        "pert_envelope": pert_envelope,
        "multiyear_cashflow_learning": {
            "inputs": multiyear_inputs,
            "outputs": my_out,
            "exact_intervals": my_res.get("exact_intervals", {}),
            "diagnostics": my_diag,
        },
        "tornado_sensitivity": tornado,
        "multi_country_comparison": multi_country,
        "idp_physical_extraction": asdict(idp_profile),
        "contract_audit": contract_audit,
        "historical_calibration": historical_cal,
        "nearest_historical_quotes": nearest_quotes,
        "assumptions_dimensions_count": len(assumptions_by_dim),
        "assumptions_total_count": total_assumptions,
        "assumptions_by_dimension": assumptions_by_dim,
        "formal_margin_proof": formal_margin,
        "formal_multiyear_npv_proof": formal_multiyear,
        "agent_trace": agent_trace,
        "event_hashes": event_hashes,
        "merkle_root": merkle_root,
        "spec": asdict(spec),
        "advisory_boundary": (
            "Tool provides deterministic ASSUMPTION/ESTIMATE quotations to assist "
            "engineers and independent Part 21J CVEs; never determines compliance."
        ),
    }
    dossier["markdown_report"] = _render_composite_markdown(dossier)
    return dossier


def _render_composite_markdown(dossier: dict[str, Any]) -> str:
    dag = dossier["composite_wbs_dag"]
    my = dossier["multiyear_cashflow_learning"]["outputs"]
    ca = dossier["contract_audit"]
    lines = [
        f"# Composite Multi-Archetype Rotorcraft Quotation — `{dossier['rfq_id']}`",
        "",
        "> **Advisory Notice:** All estimates are `ASSUMPTION` / `ESTIMATE` decision support for "
        "human engineering managers and Part 21J CVEs; never determines regulatory compliance.",
        "",
        f"- **Archetypes ({dag['node_count']}):** {', '.join(dag['topological_order'])}",
        f"- **Critical Path ({dag['project_duration_weeks']} w):** "
        + " -> ".join(dag["critical_path_archetypes"]),
        f"- **Synergy Savings:** {dag['synergy_hours_saved']} h "
        f"({dag['synergy_savings_pct']}%, {dag['synergy_price_saved_eur']} EUR)",
        f"- **Multi-Year Price / NPV / Peak Negative CF:** "
        f"{my['quoted_price_eur']} EUR / {my['net_present_value_eur']} EUR / "
        f"-{my['peak_negative_cashflow_eur']} EUR",
        f"- **Z3 Unit Margin Proof:** `{dossier['formal_margin_proof'].get('status')}` | "
        f"**Z3 Multi-Year NPV Proof:** `{dossier['formal_multiyear_npv_proof'].get('status')}`",
        f"- **Contract Gate:** `{ca['overall_contract_gate']}` "
        f"(poison flags: {ca['poison_clauses_count']})",
        f"- **Merkle Root:** `{dossier['merkle_root']}`",
    ]
    return "\n".join(lines)
