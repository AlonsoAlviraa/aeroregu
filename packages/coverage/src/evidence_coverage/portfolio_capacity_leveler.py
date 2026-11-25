"""Multi-RFQ Portfolio Stress Office Capacity & Deterministic RCPSP Leveling Engine.

Aggregates multiple composite or single-archetype rotorcraft quotations across a shared
engineering department (7 specialized roles), identifies unconstrained utilization spikes and
bottlenecks (typically `LEAD_CVE` and `FDT_SPEC`), runs a deterministic parallel Resource-
Constrained Project Scheduling Problem (RCPSP) priority-list heuristic preserving all WBS DAG
precedences, quantifies schedule slip & nearshore overflow hours, and computes combined
portfolio monthly Peak Negative Cash Flow.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from evidence_calc.quantize import format_quantum

from evidence_coverage.rotorcraft_quotation_catalog import (
    COUNTRY_RATE_CARDS,
    ROTORCRAFT_QUOTATION_ARCHETYPES,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")

STRESS_OFFICE_ROLES: tuple[str, ...] = (
    "LEAD_CVE",
    "SENIOR_STRESS",
    "STRESS_ENG",
    "CAD_ENG",
    "FDT_SPEC",
    "TEST_ENG",
    "PM_DOA",
)

DEFAULT_STRESS_OFFICE_HEADCOUNT: dict[str, int] = {
    "LEAD_CVE": 2,
    "SENIOR_STRESS": 3,
    "STRESS_ENG": 5,
    "CAD_ENG": 4,
    "FDT_SPEC": 2,
    "TEST_ENG": 2,
    "PM_DOA": 2,
}

EFFECTIVE_HOURS_PER_FTE_WEEK = Decimal("38.000")


def _d(val: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def _node_role_hours(archetype_id: str, net_hours: Decimal) -> dict[str, Decimal]:
    """Allocate a WBS node's net hours deterministically across the 7 Stress Office roles."""
    arch = ROTORCRAFT_QUOTATION_ARCHETYPES.get(archetype_id) or {}
    hbs = arch.get("hours_by_specialty") or {}
    if not hbs:
        return {
            "LEAD_CVE": net_hours * Decimal("0.12"),
            "SENIOR_STRESS": net_hours * Decimal("0.20"),
            "STRESS_ENG": net_hours * Decimal("0.35"),
            "CAD_ENG": net_hours * Decimal("0.18"),
            "FDT_SPEC": net_hours * Decimal("0.08"),
            "TEST_ENG": net_hours * Decimal("0.02"),
            "PM_DOA": net_hours * Decimal("0.05"),
        }

    raw_roles = {
        "LEAD_CVE": _d(hbs.get("cve_hours")),
        "SENIOR_STRESS": _d(hbs.get("loads_hours")) + Decimal("0.35") * _d(hbs.get("stress_hours")),
        "STRESS_ENG": Decimal("0.65") * _d(hbs.get("stress_hours")),
        "CAD_ENG": _d(hbs.get("cad_hours")) + _d(hbs.get("proto_hours")),
        "FDT_SPEC": _d(hbs.get("fdt_dyn_hours")),
        "TEST_ENG": _d(hbs.get("test_hours")),
        "PM_DOA": _d(hbs.get("systems_hours")),
    }
    raw_sum = sum(raw_roles.values(), _ZERO)
    if raw_sum <= _ZERO:
        raw_roles["STRESS_ENG"] = _ONE
        raw_sum = _ONE
    scale = net_hours / raw_sum
    return {role: hrs * scale for role, hrs in raw_roles.items()}


@dataclass
class _Activity:
    uid: str
    rfq_id: str
    dossier_index: int
    archetype_id: str
    duration_weeks: int
    es_week: int
    unconstrained_ef: int
    total_float: Decimal
    preds: tuple[str, ...]
    weekly_role_hours: dict[str, Decimal]
    total_hours: Decimal


def _extract_activities(dossiers: list[dict[str, Any]]) -> list[_Activity]:
    activities: list[_Activity] = []
    for idx, dos in enumerate(dossiers):
        rfq_id = str(dos.get("rfq_id") or f"RFQ-{idx + 1:03d}")
        dag = dos.get("composite_wbs_dag") or {}
        nodes = list(dag.get("nodes") or [])
        if not nodes:
            arch = dos.get("archetype") or {}
            det = dos.get("deterministic_quote") or {}
            aid = str(arch.get("archetype_id") or "Q-STR-03")
            hrs = _d(det.get("total_scaled_hours") or 500)
            dur = max(1, int(math.ceil(float(hrs / Decimal("100")))))
            nodes = [
                {
                    "archetype_id": aid,
                    "net_hours": str(hrs),
                    "duration_weeks": str(dur),
                    "early_start_week": "0",
                    "total_float_weeks": "0",
                    "predecessors": [],
                }
            ]
        for node in nodes:
            aid = str(node["archetype_id"])
            dur_w = max(1, int(math.ceil(float(_d(node.get("duration_weeks"), "1")))))
            es_w = max(0, int(math.floor(float(_d(node.get("early_start_week"), "0")))))
            tf_w = _d(node.get("total_float_weeks"), "0")
            net_h = max(_ONE, _d(node.get("net_hours"), "100"))
            role_hrs = _node_role_hours(aid, net_h)
            weekly = {r: v / Decimal(dur_w) for r, v in role_hrs.items()}
            preds = tuple(f"{idx}:{p}" for p in (node.get("predecessors") or []))
            activities.append(
                _Activity(
                    uid=f"{idx}:{aid}",
                    rfq_id=rfq_id,
                    dossier_index=idx,
                    archetype_id=aid,
                    duration_weeks=dur_w,
                    es_week=es_w,
                    unconstrained_ef=es_w + dur_w,
                    total_float=tf_w,
                    preds=preds,
                    weekly_role_hours=weekly,
                    total_hours=net_h,
                )
            )
    return activities


def level_portfolio_capacity(
    dossiers: list[dict[str, Any]],
    *,
    team_headcount: dict[str, int] | None = None,
    max_utilization_pct: str = "85.000",
    max_horizon_weeks: int = 104,
) -> dict[str, Any]:
    """Perform deterministic RCPSP capacity leveling across multiple queued RFQ dossiers."""
    if not dossiers:
        return {
            "portfolio_rfq_count": 0,
            "activity_count": 0,
            "headcount": dict(DEFAULT_STRESS_OFFICE_HEADCOUNT),
            "max_utilization_pct": max_utilization_pct,
            "overloaded_weeks_before_leveling": 0,
            "bottleneck_roles": [],
            "peak_utilization_by_role_pct": {},
            "leveled_peak_utilization_by_role_pct": {},
            "recommended_nearshore_overflow_hours": "0.000",
            "rfq_schedules": [],
            "leveled_schedule": [],
            "combined_peak_negative_cashflow_eur": "0.000",
            "combined_monthly_cashflow": [],
        }

    headcount = dict(DEFAULT_STRESS_OFFICE_HEADCOUNT)
    if team_headcount:
        for role, cnt in team_headcount.items():
            if role in STRESS_OFFICE_ROLES:
                headcount[role] = max(1, int(cnt))

    util_frac = max(Decimal("0.10"), min(_ONE, _d(max_utilization_pct, "85") / _HUNDRED))
    nominal_cap = {
        role: Decimal(headcount[role]) * EFFECTIVE_HOURS_PER_FTE_WEEK
        for role in STRESS_OFFICE_ROLES
    }
    target_cap = {role: nominal_cap[role] * util_frac for role in STRESS_OFFICE_ROLES}

    activities = _extract_activities(dossiers)
    by_uid = {a.uid: a for a in activities}

    # 1. Unconstrained demand profile
    unconstr_grid: dict[int, dict[str, Decimal]] = {}
    for act in activities:
        for w in range(act.es_week, act.unconstrained_ef):
            row = unconstr_grid.setdefault(w, {r: _ZERO for r in STRESS_OFFICE_ROLES})
            for role in STRESS_OFFICE_ROLES:
                row[role] += act.weekly_role_hours[role]

    overloaded_weeks_before = 0
    peak_unconstr_hrs = {r: _ZERO for r in STRESS_OFFICE_ROLES}
    for w_row in unconstr_grid.values():
        week_over = False
        for role in STRESS_OFFICE_ROLES:
            if w_row[role] > peak_unconstr_hrs[role]:
                peak_unconstr_hrs[role] = w_row[role]
            if w_row[role] > target_cap[role]:
                week_over = True
        if week_over:
            overloaded_weeks_before += 1

    peak_util_before = {
        role: format_quantum((peak_unconstr_hrs[role] / nominal_cap[role]) * _HUNDRED, _Q2)
        for role in STRESS_OFFICE_ROLES
    }

    # 2. Deterministic Parallel RCPSP Priority-List Scheduling
    ordered = sorted(
        activities,
        key=lambda a: (
            a.total_float,
            Decimal(a.es_week),
            a.rfq_id,
            a.archetype_id,
            a.dossier_index,
        ),
    )
    scheduled_start: dict[str, int] = {}
    scheduled_finish: dict[str, int] = {}
    leveled_grid: dict[int, dict[str, Decimal]] = {}
    overflow_hours = _ZERO
    horizon_cap = max(max_horizon_weeks, 208)

    for week in range(horizon_cap):
        if len(scheduled_start) == len(ordered):
            break
        for act in ordered:
            if act.uid in scheduled_start:
                continue
            if week < act.es_week:
                continue
            if any(
                pred not in scheduled_finish or scheduled_finish[pred] > week
                for pred in act.preds
                if pred in by_uid
            ):
                continue

            # Check whether activity fits remaining weekly budget without exceeding target_cap
            # (or if single-activity peak already exceeds empty cap, schedule now and spill excess)
            fits = True
            for role in STRESS_OFFICE_ROLES:
                req = act.weekly_role_hours[role]
                if req <= target_cap[role]:
                    for w in range(week, week + act.duration_weeks):
                        used = (leveled_grid.get(w) or {}).get(role, _ZERO)
                        if used + req > target_cap[role]:
                            fits = False
                            break
                if not fits:
                    break
            if not fits and week < max_horizon_weeks - act.duration_weeks:
                continue

            # Schedule act at [week, week + dur)
            scheduled_start[act.uid] = week
            scheduled_finish[act.uid] = week + act.duration_weeks
            for w in range(week, week + act.duration_weeks):
                row = leveled_grid.setdefault(w, {r: _ZERO for r in STRESS_OFFICE_ROLES})
                for role in STRESS_OFFICE_ROLES:
                    row[role] += act.weekly_role_hours[role]
                    if row[role] > target_cap[role]:
                        # Count marginal overflow caused in this role-week beyond target_cap
                        pass

    # Compute exact overflow hours across leveled grid (any week > target_cap or past max_horizon)
    peak_leveled_hrs = {r: _ZERO for r in STRESS_OFFICE_ROLES}
    overflow_by_role = {r: _ZERO for r in STRESS_OFFICE_ROLES}
    for w, w_row in leveled_grid.items():
        for role in STRESS_OFFICE_ROLES:
            if w_row[role] > peak_leveled_hrs[role]:
                peak_leveled_hrs[role] = w_row[role]
            if w >= max_horizon_weeks:
                overflow_hours += w_row[role]
                overflow_by_role[role] += w_row[role]
            elif w_row[role] > target_cap[role]:
                exc = w_row[role] - target_cap[role]
                overflow_hours += exc
                overflow_by_role[role] += exc

    peak_util_after = {
        role: format_quantum((peak_leveled_hrs[role] / nominal_cap[role]) * _HUNDRED, _Q2)
        for role in STRESS_OFFICE_ROLES
    }

    bottleneck_roles = [
        {
            "role": role,
            "headcount": headcount[role],
            "weekly_target_hours": format_quantum(target_cap[role], _Q2),
            "unconstrained_peak_hours": format_quantum(peak_unconstr_hrs[role], _Q2),
            "unconstrained_peak_utilization_pct": peak_util_before[role],
            "leveled_peak_utilization_pct": peak_util_after[role],
        }
        for role in STRESS_OFFICE_ROLES
    ]
    bottleneck_roles.sort(
        key=lambda r: Decimal(r["unconstrained_peak_utilization_pct"]),
        reverse=True,
    )

    leveled_schedule: list[dict[str, Any]] = []
    rfq_min_start: dict[int, int] = {}
    rfq_unconstr_end: dict[int, int] = {}
    rfq_leveled_end: dict[int, int] = {}
    for act in ordered:
        ls = scheduled_start.get(act.uid, act.es_week)
        lf = scheduled_finish.get(act.uid, act.unconstrained_ef)
        rfq_min_start[act.dossier_index] = min(rfq_min_start.get(act.dossier_index, ls), ls)
        rfq_unconstr_end[act.dossier_index] = max(
            rfq_unconstr_end.get(act.dossier_index, act.unconstrained_ef), act.unconstrained_ef
        )
        rfq_leveled_end[act.dossier_index] = max(rfq_leveled_end.get(act.dossier_index, lf), lf)
        leveled_schedule.append(
            {
                "rfq_id": act.rfq_id,
                "archetype_id": act.archetype_id,
                "duration_weeks": act.duration_weeks,
                "unconstrained_start_week": act.es_week,
                "unconstrained_finish_week": act.unconstrained_ef,
                "leveled_start_week": ls,
                "leveled_finish_week": lf,
                "delay_weeks": ls - act.es_week,
                "total_hours": format_quantum(act.total_hours, _Q2),
            }
        )

    rfq_schedules = []
    for idx, dos in enumerate(dossiers):
        rfq_id = str(dos.get("rfq_id") or f"RFQ-{idx + 1:03d}")
        ue = rfq_unconstr_end.get(idx, 1)
        le = rfq_leveled_end.get(idx, ue)
        rfq_schedules.append(
            {
                "rfq_id": rfq_id,
                "unconstrained_finish_week": ue,
                "leveled_finish_week": le,
                "schedule_slip_weeks": max(0, le - ue),
                "leveled_start_month": int(round(rfq_min_start.get(idx, 0) / 4.33)),
            }
        )

    # 3. Aggregate Monthly Cash Flow across Portfolio RFQs aligned at leveled start month
    monthly_agg: dict[int, dict[str, Decimal]] = {}
    for idx, dos in enumerate(dossiers):
        offset_m = rfq_schedules[idx]["leveled_start_month"]
        my_diag = (dos.get("multiyear_cashflow_learning") or {}).get("diagnostics") or {}
        sched = list(my_diag.get("monthly_cashflow_schedule") or [])
        for row in sched:
            m_idx = offset_m + int(row["month"])
            bucket = monthly_agg.setdefault(m_idx, {"out": _ZERO, "in": _ZERO})
            bucket["out"] += _d(row.get("outflow_eur"))
            bucket["in"] += _d(row.get("inflow_eur"))

    cum_cash = _ZERO
    peak_neg = _ZERO
    combined_monthly: list[dict[str, Any]] = []
    for m_idx in sorted(monthly_agg):
        bkt = monthly_agg[m_idx]
        net_m = bkt["in"] - bkt["out"]
        cum_cash += net_m
        if cum_cash < _ZERO and (-cum_cash) > peak_neg:
            peak_neg = -cum_cash
        combined_monthly.append(
            {
                "month": m_idx,
                "outflow_eur": format_quantum(bkt["out"], _Q2),
                "inflow_eur": format_quantum(bkt["in"], _Q2),
                "net_eur": format_quantum(net_m, _Q2),
                "cumulative_cash_eur": format_quantum(cum_cash, _Q2),
            }
        )

    return {
        "portfolio_rfq_count": len(dossiers),
        "activity_count": len(activities),
        "headcount": headcount,
        "max_utilization_pct": max_utilization_pct,
        "overloaded_weeks_before_leveling": overloaded_weeks_before,
        "bottleneck_roles": bottleneck_roles,
        "peak_utilization_by_role_pct": peak_util_before,
        "leveled_peak_utilization_by_role_pct": peak_util_after,
        "overflow_hours_by_role": {
            r: format_quantum(overflow_by_role[r], _Q3) for r in STRESS_OFFICE_ROLES
        },
        "recommended_nearshore_overflow_hours": format_quantum(overflow_hours, _Q3),
        "rfq_schedules": rfq_schedules,
        "leveled_schedule": leveled_schedule,
        "combined_peak_negative_cashflow_eur": format_quantum(peak_neg, _Q3),
        "combined_monthly_cashflow": combined_monthly,
        "advisory_only": (
            "ESTIMATE portfolio capacity leveling model for Stress Office resource planning only."
        ),
    }


_ROLE_TO_RATE_KEY: dict[str, str] = {
    "LEAD_CVE": "cve_rate",
    "SENIOR_STRESS": "loads_rate",
    "STRESS_ENG": "stress_rate",
    "CAD_ENG": "cad_rate",
    "FDT_SPEC": "fdt_dyn_rate",
    "TEST_ENG": "test_rate",
    "PM_DOA": "systems_rate",
}


def optimize_portfolio_nearshore_allocation(
    portfolio_result: dict[str, Any],
    *,
    onshore_country: str = "DE",
    nearshore_country: str = "ES",
    cve_onshore_only: bool = True,
    coordination_overhead_pct: str = "6.000",
    onshore_overtime_surcharge_pct: str = "15.000",
) -> dict[str, Any]:
    """Optimize multi-site overflow allocation while keeping Part 21.A.239(b) CVE onshore."""
    on_c = onshore_country.strip().upper() or "EU_DEFAULT"
    ns_c = nearshore_country.strip().upper() or "ES"
    if on_c not in COUNTRY_RATE_CARDS or ns_c not in COUNTRY_RATE_CARDS:
        raise ValueError("unknown_country_code")

    on_card = COUNTRY_RATE_CARDS[on_c]
    ns_card = COUNTRY_RATE_CARDS[ns_c]
    coord_frac = max(_ZERO, _d(coordination_overhead_pct, "6.000") / _HUNDRED)
    ot_mult = _ONE + max(_ZERO, _d(onshore_overtime_surcharge_pct, "15.000") / _HUNDRED)

    overflow_map = portfolio_result.get("overflow_hours_by_role") or {}
    # Backward-compatible fallback if portfolio_result came from an un-expanded caller dict
    if not overflow_map:
        total_ov = _d(portfolio_result.get("recommended_nearshore_overflow_hours"))
        overflow_map = {r: "0.000" for r in STRESS_OFFICE_ROLES}
        if total_ov > _ZERO:
            overflow_map["STRESS_ENG"] = format_quantum(total_ov, _Q3)

    per_role: list[dict[str, Any]] = []
    tot_overflow = _ZERO
    tot_offloaded = _ZERO
    tot_retained = _ZERO
    tot_base_cost = _ZERO
    tot_hybrid_cost = _ZERO
    cve_offloaded_h = _ZERO

    for role in STRESS_OFFICE_ROLES:
        ov_h = max(_ZERO, _d(overflow_map.get(role)))
        rk = _ROLE_TO_RATE_KEY[role]
        r_on = _d(on_card["rates"][rk])
        r_ns = _d(ns_card["rates"][rk])

        base_cost = ov_h * r_on * ot_mult
        ns_unit_eff = r_ns * (_ONE + coord_frac)
        if role == "LEAD_CVE" and cve_onshore_only:
            off_h = _ZERO
            ret_h = ov_h
            hyb_cost = base_cost
            policy = "ONSHORE_ONLY_PART21_CVE"
        elif ov_h > _ZERO and ns_unit_eff < (r_on * ot_mult):
            off_h = ov_h
            ret_h = _ZERO
            hyb_cost = ov_h * ns_unit_eff
            policy = f"OFFLOAD_TO_{ns_c}"
        else:
            off_h = _ZERO
            ret_h = ov_h
            hyb_cost = base_cost
            policy = f"RETAIN_AT_{on_c}"

        if role == "LEAD_CVE":
            cve_offloaded_h = off_h

        savings = base_cost - hyb_cost
        tot_overflow += ov_h
        tot_offloaded += off_h
        tot_retained += ret_h
        tot_base_cost += base_cost
        tot_hybrid_cost += hyb_cost
        per_role.append(
            {
                "role": role,
                "overflow_hours": format_quantum(ov_h, _Q3),
                "retained_onshore_hours": format_quantum(ret_h, _Q3),
                "offloaded_nearshore_hours": format_quantum(off_h, _Q3),
                "onshore_rate_eur_h": format_quantum(r_on, _Q2),
                "nearshore_rate_eur_h": format_quantum(r_ns, _Q2),
                "baseline_onshore_cost_eur": format_quantum(base_cost, _Q2),
                "hybrid_cost_eur": format_quantum(hyb_cost, _Q2),
                "savings_eur": format_quantum(savings, _Q2),
                "allocation_policy": policy,
            }
        )

    net_savings = tot_base_cost - tot_hybrid_cost
    savings_pct = (net_savings / tot_base_cost) * _HUNDRED if tot_base_cost > _ZERO else _ZERO
    return {
        "onshore_country": on_c,
        "nearshore_country": ns_c,
        "cve_onshore_only": cve_onshore_only,
        "cve_governance_preserved": cve_offloaded_h == _ZERO,
        "coordination_overhead_pct": format_quantum(coord_frac * _HUNDRED, _Q2),
        "total_overflow_hours": format_quantum(tot_overflow, _Q3),
        "total_offloaded_hours": format_quantum(tot_offloaded, _Q3),
        "total_retained_onshore_hours": format_quantum(tot_retained, _Q3),
        "baseline_onshore_overflow_cost_eur": format_quantum(tot_base_cost, _Q2),
        "hybrid_overflow_cost_eur": format_quantum(tot_hybrid_cost, _Q2),
        "net_savings_eur": format_quantum(net_savings, _Q2),
        "savings_pct": format_quantum(savings_pct, _Q2),
        "per_role_allocation": per_role,
        "advisory_only": (
            "ESTIMATE multi-site allocation heuristic; requires HR/DOA CVE governance sign-off."
        ),
    }
