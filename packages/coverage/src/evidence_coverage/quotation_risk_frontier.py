"""Deterministic Seeded Quotation Risk Simulation & Bid-Price Pareto Frontier Optimizer.

All commercial cost distributions, Tornado sensitivity swings, win-rate estimates,
Expected Monetary Value (EMV) points, and Pareto-optimal bid prices are strictly
labeled ESTIMATE / ASSUMPTION with the mandatory human-reviewer advisory disclaimer.
Uses Halton low-discrepancy deterministic sequences in exact Decimal arithmetic and
proves recommended margin floors via Z3 SMT.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import z3
from evidence_calc.quantize import format_quantum
from openpyxl import Workbook

from evidence_coverage.pdf_layout import CorporatePDFBuilder, compute_dsse_sig_prefix
from evidence_coverage.quotation_exporter import (
    _ACCENT_FILL,
    _BOLD_FONT,
    _TITLE_FONT,
    _autofit_columns,
    _num_val,
    _resolve_signing_keypair,
    _sanitize_excel_text,
    _style_header_row,
)

ASSISTANCE_DISCLAIMER = "This tool assists a human reviewer. It does not determine compliance."
_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_Q2 = Decimal("0.01")
_Q4 = Decimal("0.0001")

DEFAULT_RISK_DRIVERS: list[dict[str, Any]] = [
    {
        "driver_id": "DRV-LABOR-PROD",
        "label": "Stress / CAD Engineering Productivity",
        "min_pct": "-8.00",
        "mode_pct": "2.00",
        "max_pct": "18.00",
        "weight": "0.35",
    },
    {
        "driver_id": "DRV-ECN-CHURN",
        "label": "OEM Requirements & ECN Churn Cycles",
        "min_pct": "-2.00",
        "mode_pct": "4.50",
        "max_pct": "22.00",
        "weight": "0.25",
    },
    {
        "driver_id": "DRV-FX-VOL",
        "label": "EUR/USD/GBP FX & Inflation Escalation",
        "min_pct": "-4.00",
        "mode_pct": "1.50",
        "max_pct": "11.00",
        "weight": "0.15",
    },
    {
        "driver_id": "DRV-SUBCON-RATE",
        "label": "Special Process / Nearshore Subcontracting",
        "min_pct": "-6.00",
        "mode_pct": "1.00",
        "max_pct": "14.00",
        "weight": "0.15",
    },
    {
        "driver_id": "DRV-TEST-RIG",
        "label": "Structural Test Rig & FTI Lead-Time",
        "min_pct": "-3.00",
        "mode_pct": "3.00",
        "max_pct": "20.00",
        "weight": "0.10",
    },
]


def _dec(val: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(val))
    except Exception as exc:
        raise ValueError(f"invalid_decimal:{name}") from exc
    if not d.is_finite():
        raise ValueError(f"non_finite:{name}")
    return d


def _halton_dec(index: int, base: int) -> Decimal:
    """Return exact Decimal Halton discrepancy value in (0, 1)."""
    result = _ZERO
    denom = Decimal(base)
    i = index
    while i > 0:
        i, rem = divmod(i, base)
        result += Decimal(rem) / denom
        denom *= Decimal(base)
    return min(max(result, Decimal("0.00001")), Decimal("0.99999"))


def _seeded_offset(seed: int, dim: int) -> Decimal:
    """Return deterministic Cranley-Patterson Decimal shift in [0, 1) from SHA-256."""
    digest = hashlib.sha256(f"{seed}:{dim}".encode("ascii")).hexdigest()[:12]
    return Decimal(int(digest, 16)) / Decimal(16**12)


def _triangular_inverse_cdf(u: Decimal, a: Decimal, m: Decimal, b: Decimal) -> Decimal:
    """Invert continuous triangular CDF (min=a, mode=m, max=b) in exact Decimal."""
    if b <= a:
        return a
    fc = (m - a) / (b - a)
    if u <= fc:
        return a + (u * (b - a) * (m - a)).sqrt()
    return b - ((_ONE - u) * (b - a) * (b - m)).sqrt()


def _quantile_sorted(values: list[Decimal], p: Decimal) -> Decimal:
    if not values:
        return _ZERO
    if len(values) == 1:
        return values[0]
    pos = p * Decimal(len(values) - 1)
    lo = int(pos)
    hi = min(len(values) - 1, lo + 1)
    frac = pos - Decimal(lo)
    return values[lo] * (_ONE - frac) + values[hi] * frac


def _logistic_win_probability_pct(
    price_eur: Decimal,
    market_ref_eur: Decimal,
    elasticity: Decimal,
) -> Decimal:
    """Smooth logistic commercial win probability (%) in exact Decimal."""
    if market_ref_eur <= _ZERO:
        return Decimal("50.00")
    x = elasticity * ((price_eur - market_ref_eur) / market_ref_eur)
    # Clamp exponent argument to avoid Decimal overflow on extreme candidates
    x_clamped = max(min(x, Decimal("25")), Decimal("-25"))
    prob = _ONE / (_ONE + x_clamped.exp())
    return (prob * _HUNDRED).quantize(_Q2)


def _prove_bid_margin_floor_z3(
    recommended_bid_eur: Decimal,
    cost_lower_eur: Decimal,
    cost_upper_eur: Decimal,
    min_margin_floor_pct: Decimal,
) -> dict[str, Any]:
    """Formally verify via Z3 SMT that bid margin holds across [cost_lower, cost_upper]."""
    solver = z3.Solver()
    solver.set(timeout=3000)
    cost = z3.Real("scenario_cost_eur")
    bid_v = z3.RealVal(format(recommended_bid_eur, "f"))
    c_lo = z3.RealVal(format(cost_lower_eur, "f"))
    c_hi = z3.RealVal(format(cost_upper_eur, "f"))
    floor_frac = z3.RealVal(format(min_margin_floor_pct / _HUNDRED, "f"))
    solver.add(cost >= c_lo, cost <= c_hi)
    # Negated safety property: (bid - cost) < floor_frac * bid
    solver.add((bid_v - cost) < (floor_frac * bid_v))
    chk = solver.check()
    if chk == z3.unsat:
        return {
            "property_name": "recommended_bid_margin_floor",
            "status": "PROVED_UNSAT",
            "proved": True,
            "cost_interval_eur": [
                format_quantum(cost_lower_eur, _Q2),
                format_quantum(cost_upper_eur, _Q2),
            ],
            "recommended_bid_eur": format_quantum(recommended_bid_eur, _Q2),
            "min_margin_floor_pct": format_quantum(min_margin_floor_pct, _Q2),
            "reason": "Recommended bid satisfies net margin floor across P10-P80 cost interval",
        }
    cex_cost = ""
    if chk == z3.sat:
        m = solver.model()
        val = m.eval(cost, model_completion=True)
        cex_cost = str(val.as_decimal(4) if hasattr(val, "as_decimal") else val).rstrip("?")
    return {
        "property_name": "recommended_bid_margin_floor",
        "status": "COUNTEREXAMPLE_FOUND" if chk == z3.sat else "UNKNOWN",
        "proved": False,
        "cost_interval_eur": [
            format_quantum(cost_lower_eur, _Q2),
            format_quantum(cost_upper_eur, _Q2),
        ],
        "recommended_bid_eur": format_quantum(recommended_bid_eur, _Q2),
        "min_margin_floor_pct": format_quantum(min_margin_floor_pct, _Q2),
        "counterexample_cost_eur": cex_cost,
        "reason": "Upper envelope scenario violates requested margin floor",
    }


def run_quotation_risk_frontier(
    *,
    base_cost_eur: str | Decimal = "375000",
    base_quote_price_eur: str | Decimal = "480000",
    bid_prep_cost_eur: str | Decimal = "25000",
    min_margin_floor_pct: str | Decimal = "12.00",
    num_scenarios: int = 500,
    seed: int = 20261126,
    risk_drivers: list[dict[str, Any]] | None = None,
    market_price_reference_eur: str | Decimal | None = None,
    price_elasticity: str | Decimal = "10.0",
    baseline_dossier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run deterministic low-discrepancy cost risk simulation & EMV Pareto bid optimizer."""
    if num_scenarios < 50 or num_scenarios > 2000:
        raise ValueError("num_scenarios_out_of_range")

    with localcontext() as ctx:
        ctx.prec = 40
        if isinstance(baseline_dossier, dict):
            fin = (baseline_dossier.get("multiyear_cashflow_learning") or {}).get("outputs") or {}
            if fin.get("escalated_total_cost_eur"):
                base_cost_eur = fin["escalated_total_cost_eur"]
            if fin.get("quoted_price_eur"):
                base_quote_price_eur = fin["quoted_price_eur"]

        base_cost = _dec(base_cost_eur, "base_cost_eur")
        base_price = _dec(base_quote_price_eur, "base_quote_price_eur")
        bid_prep = _dec(bid_prep_cost_eur, "bid_prep_cost_eur")
        margin_floor = _dec(min_margin_floor_pct, "min_margin_floor_pct")
        elasticity = _dec(price_elasticity, "price_elasticity")
        market_ref = (
            _dec(market_price_reference_eur, "market_price_reference_eur")
            if market_price_reference_eur is not None
            else base_price
        )
        if base_cost <= _ZERO or base_price <= _ZERO:
            raise ValueError("non_positive_quotation_amounts")

        raw_drivers = (
            list(risk_drivers)
            if risk_drivers is not None
            else [dict(d) for d in DEFAULT_RISK_DRIVERS]
        )
        if not raw_drivers:
            raise ValueError("empty_risk_drivers")

        drivers: list[dict[str, Any]] = []
        raw_weights_sum = _ZERO
        for idx, d in enumerate(raw_drivers):
            w = _dec(d.get("weight", "1"), f"weight:{idx}")
            lo = _dec(d["min_pct"], f"min_pct:{idx}")
            md = _dec(d["mode_pct"], f"mode_pct:{idx}")
            hi = _dec(d["max_pct"], f"max_pct:{idx}")
            if not (lo <= md <= hi) or w <= _ZERO:
                raise ValueError(f"invalid_driver_bounds:{idx}")
            raw_weights_sum += w
            drivers.append(
                {
                    "driver_id": str(d.get("driver_id") or f"DRV-{idx + 1:02d}"),
                    "label": str(d.get("label") or f"Driver {idx + 1}"),
                    "min_pct": lo,
                    "mode_pct": md,
                    "max_pct": hi,
                    "weight": w,
                }
            )
        for drv in drivers:
            drv["norm_weight"] = drv["weight"] / raw_weights_sum

        # Deterministic Halton + Cranley-Patterson simulation
        shifts = [_seeded_offset(seed, dim) for dim in range(len(drivers))]
        scenario_costs: list[Decimal] = []
        driver_modes_weighted = sum(drv["norm_weight"] * drv["mode_pct"] for drv in drivers)

        for s_idx in range(1, num_scenarios + 1):
            total_shift_pct = _ZERO
            for dim, drv in enumerate(drivers):
                prime = _PRIMES[dim % len(_PRIMES)]
                u = (_halton_dec(s_idx + (seed % 97), prime) + shifts[dim]) % _ONE
                sample_pct = _triangular_inverse_cdf(
                    u, drv["min_pct"], drv["mode_pct"], drv["max_pct"]
                )
                total_shift_pct += drv["norm_weight"] * sample_pct
            cost_s = base_cost * (_ONE + (total_shift_pct / _HUNDRED))
            scenario_costs.append(cost_s)

        sorted_costs = sorted(scenario_costs)
        n_dec = Decimal(len(sorted_costs))
        cost_mean = sum(sorted_costs) / n_dec
        p10 = _quantile_sorted(sorted_costs, Decimal("0.10"))
        p50 = _quantile_sorted(sorted_costs, Decimal("0.50"))
        p80 = _quantile_sorted(sorted_costs, Decimal("0.80"))
        p90 = _quantile_sorted(sorted_costs, Decimal("0.90"))
        p95 = _quantile_sorted(sorted_costs, Decimal("0.95"))
        tail_start = max(0, int(Decimal("0.95") * Decimal(len(sorted_costs))))
        tail_vals = sorted_costs[tail_start:] or [p95]
        cvar_95 = sum(tail_vals) / Decimal(len(tail_vals))

        # Tornado driver sensitivity (one-at-a-time min vs max swing holding peers at mode)
        tornado_raw: list[dict[str, Any]] = []
        swing_sq_total = _ZERO
        for drv in drivers:
            other_pct = driver_modes_weighted - (drv["norm_weight"] * drv["mode_pct"])
            low_cost = base_cost * (
                _ONE + (other_pct + drv["norm_weight"] * drv["min_pct"]) / _HUNDRED
            )
            high_cost = base_cost * (
                _ONE + (other_pct + drv["norm_weight"] * drv["max_pct"]) / _HUNDRED
            )
            swing = abs(high_cost - low_cost)
            swing_sq = swing * swing
            swing_sq_total += swing_sq
            tornado_raw.append(
                {
                    "driver_id": drv["driver_id"],
                    "label": drv["label"],
                    "weight": format_quantum(drv["norm_weight"], _Q2),
                    "low_cost_eur": low_cost,
                    "high_cost_eur": high_cost,
                    "swing_eur": swing,
                    "swing_sq": swing_sq,
                }
            )
        tornado_rows: list[dict[str, Any]] = []
        for item in sorted(tornado_raw, key=lambda r: r["swing_eur"], reverse=True):
            share = (
                (item["swing_sq"] / swing_sq_total) * _HUNDRED if swing_sq_total > _ZERO else _ZERO
            )
            tornado_rows.append(
                {
                    "driver_id": item["driver_id"],
                    "label": item["label"],
                    "weight": item["weight"],
                    "low_cost_eur": format_quantum(item["low_cost_eur"], _Q2),
                    "high_cost_eur": format_quantum(item["high_cost_eur"], _Q2),
                    "swing_eur": format_quantum(item["swing_eur"], _Q2),
                    "variance_share_pct": format_quantum(share, _Q2),
                }
            )

        # Pareto Bid-Price Frontier across 13 adaptive candidates centered around market/base ref
        raw_offsets = (-15, -9, -4, 0, 4, 8, 12, 16, 22, 30, 42)
        frontier_rows: list[dict[str, Any]] = []
        best_emv: Decimal | None = None
        recommended_idx = 0
        for idx, off_pct in enumerate(raw_offsets):
            bid_p = market_ref * (_ONE + (Decimal(str(off_pct)) / _HUNDRED))
            mk = ((bid_p - p50) / p50) * _HUNDRED if p50 > _ZERO else _ZERO
            win_pct = _logistic_win_probability_pct(bid_p, market_ref, elasticity)
            win_prob = win_pct / _HUNDRED
            exp_margin_pct = ((bid_p - cost_mean) / bid_p) * _HUNDRED
            breach_cnt = sum(
                1 for c in sorted_costs if (((bid_p - c) / bid_p) * _HUNDRED) < margin_floor
            )
            breach_prob_pct = (Decimal(breach_cnt) / n_dec) * _HUNDRED
            emv = (win_prob * (bid_p - cost_mean)) - ((_ONE - win_prob) * bid_prep)
            row = {
                "candidate_id": f"BID-{idx + 1:02d}",
                "markup_over_p50_pct": format_quantum(mk, _Q2),
                "bid_price_eur": format_quantum(bid_p, _Q2),
                "win_probability_pct": format_quantum(win_pct, _Q2),
                "expected_margin_pct": format_quantum(exp_margin_pct, _Q2),
                "prob_margin_below_floor_pct": format_quantum(breach_prob_pct, _Q2),
                "expected_monetary_value_eur": format_quantum(emv, _Q2),
                "pareto_efficient": False,
                "recommended_max_emv": False,
                "_raw_bid": bid_p,
                "_raw_win": win_pct,
                "_raw_margin": exp_margin_pct,
                "_raw_emv": emv,
            }
            frontier_rows.append(row)
            if best_emv is None or emv > best_emv:
                best_emv = emv
                recommended_idx = idx

        # Mark non-dominated Pareto candidates maximizing (win_probability_pct, expected_margin_pct)
        for i, cand in enumerate(frontier_rows):
            dominated = any(
                j != i
                and other["_raw_win"] >= cand["_raw_win"]
                and other["_raw_margin"] >= cand["_raw_margin"]
                and (
                    other["_raw_win"] > cand["_raw_win"]
                    or other["_raw_margin"] > cand["_raw_margin"]
                )
                for j, other in enumerate(frontier_rows)
            )
            cand["pareto_efficient"] = not dominated
        frontier_rows[recommended_idx]["recommended_max_emv"] = True
        optimum_location = (
            "INTERIOR_MAXIMUM"
            if 0 < recommended_idx < (len(frontier_rows) - 1)
            else "BOUNDARY_CLAMPED"
        )
        rec_row = frontier_rows[recommended_idx]
        rec_bid_dec = rec_row["_raw_bid"]

        # Strip internal Decimal sorting keys cleanly
        for row in frontier_rows:
            for k in ("_raw_bid", "_raw_win", "_raw_margin", "_raw_emv"):
                row.pop(k, None)

        z3_proof = _prove_bid_margin_floor_z3(rec_bid_dec, p10, p80, margin_floor)

        digest_payload = {
            "seed": seed,
            "num_scenarios": num_scenarios,
            "cost_p50_eur": format_quantum(p50, _Q2),
            "cost_p80_eur": format_quantum(p80, _Q2),
            "recommended_bid_price_eur": rec_row["bid_price_eur"],
            "max_emv_eur": rec_row["expected_monetary_value_eur"],
            "optimum_location": optimum_location,
        }
        report_sha = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        return {
            "label": "ESTIMATE",
            "not_a_certification_method": True,
            "assistance_disclaimer": ASSISTANCE_DISCLAIMER,
            "seed": seed,
            "num_scenarios": num_scenarios,
            "base_cost_eur": format_quantum(base_cost, _Q2),
            "base_quote_price_eur": format_quantum(base_price, _Q2),
            "market_price_reference_eur": format_quantum(market_ref, _Q2),
            "bid_prep_cost_eur": format_quantum(bid_prep, _Q2),
            "min_margin_floor_pct": format_quantum(margin_floor, _Q2),
            "optimum_location": optimum_location,
            "cost_distribution": {
                "cost_mean_eur": format_quantum(cost_mean, _Q2),
                "cost_p10_eur": format_quantum(p10, _Q2),
                "cost_p50_eur": format_quantum(p50, _Q2),
                "cost_p80_eur": format_quantum(p80, _Q2),
                "cost_p90_eur": format_quantum(p90, _Q2),
                "cost_p95_eur": format_quantum(p95, _Q2),
                "cvar_95_cost_eur": format_quantum(cvar_95, _Q2),
            },
            "recommended_bid": {
                "candidate_id": rec_row["candidate_id"],
                "recommended_bid_price_eur": rec_row["bid_price_eur"],
                "win_probability_pct": rec_row["win_probability_pct"],
                "expected_margin_pct": rec_row["expected_margin_pct"],
                "max_expected_monetary_value_eur": rec_row["expected_monetary_value_eur"],
                "optimum_location": optimum_location,
            },
            "formal_margin_floor_proof": z3_proof,
            "tornado_drivers": tornado_rows,
            "pareto_frontier": frontier_rows,
            "report_sha256": report_sha,
            "generated_at": datetime.now(UTC).isoformat(),
        }


def export_risk_frontier_xlsx(
    report: dict[str, Any],
    *,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export multi-tab live-formula Excel (.xlsx) Risk Simulation & Pareto Frontier workbook."""
    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "1_Executive_Risk_Brief"
    ws_par = wb.create_sheet("2_Pareto_Bid_Frontier")
    ws_tor = wb.create_sheet("3_Tornado_Drivers")
    ws_q = wb.create_sheet("4_Cost_Quantiles")

    formula_count = 0

    # TAB 2: Pareto Bid Frontier
    par_hdr = [
        "Candidate",
        "Markup vs P50 (%)",
        "Bid Price (EUR)",
        "Win Prob (%)",
        "Expected Margin (%)",
        "Below Floor Prob (%)",
        "Expected Monetary Value (EUR)",
        "Pareto",
        "EMV Gate",
    ]
    ws_par.append(par_hdr)
    _style_header_row(ws_par, 1, len(par_hdr))
    ws_par.freeze_panes = "A2"
    par_rows = list(report.get("pareto_frontier") or [])
    for idx, r in enumerate(par_rows, start=2):
        ws_par.append(
            [
                _sanitize_excel_text(r.get("candidate_id", "")),
                _num_val(r.get("markup_over_p50_pct")),
                _num_val(r.get("bid_price_eur")),
                _num_val(r.get("win_probability_pct")),
                _num_val(r.get("expected_margin_pct")),
                _num_val(r.get("prob_margin_below_floor_pct")),
                _num_val(r.get("expected_monetary_value_eur")),
                "PARETO" if r.get("pareto_efficient") else "DOMINATED",
                "RECOMMENDED" if r.get("recommended_max_emv") else "ALTERNATIVE",
            ]
        )
        ws_par.cell(row=idx, column=3).number_format = "#,##0.00"
        ws_par.cell(row=idx, column=7).number_format = "#,##0.00"
    par_last = max(2, 1 + len(par_rows))
    par_tot = par_last + 1
    ws_par.append(
        [
            "OPTIMUM SUMMARY",
            f"=COUNTA(A2:A{par_last})",
            f"=INDEX(C2:C{par_last},MATCH(MAX(G2:G{par_last}),G2:G{par_last},0))",
            f"=INDEX(D2:D{par_last},MATCH(MAX(G2:G{par_last}),G2:G{par_last},0))",
            f"=INDEX(E2:E{par_last},MATCH(MAX(G2:G{par_last}),G2:G{par_last},0))",
            f"=MIN(F2:F{par_last})",
            f"=MAX(G2:G{par_last})",
            f'=COUNTIF(H2:H{par_last},"PARETO")',
            "=IF(G" + str(par_tot) + '>0,"POSITIVE_EMV","NEGATIVE_EMV")',
        ]
    )
    formula_count += 8
    for c_i in range(1, len(par_hdr) + 1):
        ws_par.cell(row=par_tot, column=c_i).font = _BOLD_FONT
        ws_par.cell(row=par_tot, column=c_i).fill = _ACCENT_FILL
    _autofit_columns(ws_par)

    # TAB 3: Tornado Drivers
    tor_hdr = [
        "Driver ID",
        "Risk Factor",
        "Weight",
        "Low Cost (EUR)",
        "High Cost (EUR)",
        "Swing (EUR)",
        "Variance Share (%)",
    ]
    ws_tor.append(tor_hdr)
    _style_header_row(ws_tor, 1, len(tor_hdr))
    ws_tor.freeze_panes = "A2"
    tor_rows = list(report.get("tornado_drivers") or [])
    for idx, t in enumerate(tor_rows, start=2):
        ws_tor.append(
            [
                _sanitize_excel_text(t.get("driver_id", "")),
                _sanitize_excel_text(t.get("label", "")),
                _num_val(t.get("weight")),
                _num_val(t.get("low_cost_eur")),
                _num_val(t.get("high_cost_eur")),
                f"=E{idx}-D{idx}",
                _num_val(t.get("variance_share_pct")),
            ]
        )
        formula_count += 1
    _autofit_columns(ws_tor)

    # TAB 4: Cost Quantiles
    ws_q.append(["Quantile Metric", "Estimated Cost (EUR)"])
    _style_header_row(ws_q, 1, 2)
    dist = report.get("cost_distribution") or {}
    for k in (
        "cost_mean_eur",
        "cost_p10_eur",
        "cost_p50_eur",
        "cost_p80_eur",
        "cost_p90_eur",
        "cost_p95_eur",
        "cvar_95_cost_eur",
    ):
        ws_q.append([k, _num_val(dist.get(k))])
    _autofit_columns(ws_q)

    # TAB 1: Executive Brief
    ws_sum.append(["AeroRegu — Quotation Risk & Pareto EMV Optimizer (ESTIMATE)", "", ""])
    ws_sum["A1"].font = _TITLE_FONT
    ws_sum.append(["ADVISORY NOTICE", ASSISTANCE_DISCLAIMER, ""])
    ws_sum.append(["KPI", "Live Formula / Value", "Source"])
    _style_header_row(ws_sum, 3, 3)

    summary_rows = [
        (
            "Simulation Seed / Scenarios",
            f"{report.get('seed')} / {report.get('num_scenarios')}",
            "Halton QMC",
        ),
        ("Base Cost (EUR)", _num_val(report.get("base_cost_eur")), "Baseline"),
        ("Estimated Cost P50 (EUR)", "='4_Cost_Quantiles'!B4", "Live Quantiles"),
        ("Estimated Cost P80 (EUR)", "='4_Cost_Quantiles'!B5", "Live Quantiles"),
        ("Tail CVaR 95% Cost (EUR)", "='4_Cost_Quantiles'!B8", "Live Quantiles"),
        ("Recommended EMV Bid Price (EUR)", f"='2_Pareto_Bid_Frontier'!C{par_tot}", "Live Pareto"),
        (
            "Max Expected Monetary Value (EUR)",
            f"='2_Pareto_Bid_Frontier'!G{par_tot}",
            "Live Pareto",
        ),
        ("Win Prob at Recommended Bid (%)", f"='2_Pareto_Bid_Frontier'!D{par_tot}", "Live Pareto"),
        ("Pareto Frontier Points", f"='2_Pareto_Bid_Frontier'!H{par_tot}", "Live Pareto"),
        (
            "Z3 Formal Margin Floor Status",
            _sanitize_excel_text((report.get("formal_margin_floor_proof") or {}).get("status", "")),
            "Z3 SMT",
        ),
    ]
    for r_i, (lbl, val, src) in enumerate(summary_rows, start=4):
        ws_sum.append([lbl, val, src])
        if isinstance(val, str) and val.startswith("="):
            formula_count += 1
            ws_sum.cell(row=r_i, column=2).number_format = "#,##0.00"
    _autofit_columns(ws_sum)

    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()
    out_str: str | None = None
    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(xlsx_bytes)
        out_str = str(out_p)
    return {
        "xlsx_bytes": xlsx_bytes,
        "xlsx_sha256": hashlib.sha256(xlsx_bytes).hexdigest(),
        "sheet_names": wb.sheetnames,
        "formula_count": formula_count,
        "output_path": out_str,
    }


def export_risk_frontier_pdf(
    report: dict[str, Any],
    *,
    private_key_pem: bytes | None = None,
    public_key_pem: bytes | None = None,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Export Ed25519 DSSE + ISO QR signed PDF Commercial Risk & Pareto EMV Brief."""
    priv_pem, pub_pem = _resolve_signing_keypair(private_key_pem, public_key_pem)
    merkle = str(report.get("report_sha256") or ("0" * 64))
    rec = report.get("recommended_bid") or {}
    dist = report.get("cost_distribution") or {}
    z3p = report.get("formal_margin_floor_proof") or {}

    attestation_payload = {
        "schema": "evidence-layer/quotation-risk-frontier@1.0.0",
        "seed": int(report.get("seed") or 0),
        "num_scenarios": int(report.get("num_scenarios") or 0),
        "recommended_bid_price_eur": str(rec.get("recommended_bid_price_eur") or "0.00"),
        "max_expected_monetary_value_eur": str(
            rec.get("max_expected_monetary_value_eur") or "0.00"
        ),
        "z3_status": str(z3p.get("status") or ""),
        "report_sha256": merkle,
    }
    sig_sha256 = compute_dsse_sig_prefix(attestation_payload, priv_pem)
    qr_payload = "aeroregu-risk:" + json.dumps(
        {
            "v": 1,
            "sd": report.get("seed"),
            "m": merkle[:16],
            "s": sig_sha256[:16],
            "bid": str(rec.get("recommended_bid_price_eur") or ""),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    builder = CorporatePDFBuilder(
        title="AeroRegu - Quotation Risk & Pareto Bid Frontier Brief (ESTIMATE)",
        subtitle=ASSISTANCE_DISCLAIMER,
        merkle_root=merkle,
        qr_payload=qr_payload,
        meta_kpis=[
            ("Halton QMC Scenarios", f"{report.get('num_scenarios')} (seed={report.get('seed')})"),
            (
                "Cost P10 / P50 / P80 / P95 (EUR)",
                f"{dist.get('cost_p10_eur')} / {dist.get('cost_p50_eur')} / "
                f"{dist.get('cost_p80_eur')} / {dist.get('cost_p95_eur')}",
            ),
            (
                "Recommended Max-EMV Bid",
                f"{rec.get('recommended_bid_price_eur')} EUR ({rec.get('optimum_location', '')})",
            ),
            (
                "Max EMV / Win / Margin",
                f"{rec.get('max_expected_monetary_value_eur')} EUR | "
                f"Win {rec.get('win_probability_pct')}% | Margin {rec.get('expected_margin_pct')}%",
            ),
            ("Z3 Margin Floor Proof", str(z3p.get("status") or "")),
            ("SHA-256 Digest", f"{merkle[:36]}..."),
        ],
        creator="aeroregu-risk-frontier-exporter",
    )
    cand_rows = [
        [
            c.get("candidate_id", ""),
            f"{c.get('bid_price_eur', '')} EUR",
            f"{c.get('win_probability_pct', '')}%",
            f"{c.get('expected_margin_pct', '')}%",
            f"{c.get('expected_monetary_value_eur', '')} EUR",
            "RECOMMENDED (*REC*)"
            if c.get("recommended_max_emv")
            else ("PARETO" if c.get("pareto_efficient") else "DOMINATED"),
        ]
        for c in (report.get("pareto_frontier") or [])
    ]
    builder.add_table(
        "Bid-Price Pareto Frontier Candidates (ESTIMATE)",
        ["ID", "Bid Price (EUR)", "Win Prob", "Exp Margin", "EMV (EUR)", "Frontier Status"],
        cand_rows,
        col_widths=[56, 108, 66, 68, 108, 117],
    )
    return builder.finalize_signed(
        attestation_payload=attestation_payload,
        private_key_pem=priv_pem,
        public_key_pem=pub_pem,
        metadata_title="AeroRegu Quotation Risk & Pareto Frontier Brief",
        output_path=output_path,
    )
