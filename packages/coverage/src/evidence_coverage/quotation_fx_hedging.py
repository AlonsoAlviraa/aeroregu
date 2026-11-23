"""Multi-Currency FX Hedging Simulator & Continuous Z3 SMT Margin-Floor Proof.

Computes foreign-currency invoice values, FX forward hedge carry costs, 5-point spot shock
sensitivity, recommended minimum hedge ratio, and a formal Z3 SMT proof over simultaneous
currency shock + cost-drift boxes verifying that hedged net EUR margin >= contractual floor.

Advisory notice: Financial outputs are ASSUMPTION / ESTIMATE decision-support aides for
human commercial/finance signatories; never determines regulatory compliance or treasury policy.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Any

import z3
from evidence_calc.quantize import format_quantum

_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")
_Q4 = Decimal("0.0001")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_TEN_THOUSAND = Decimal("10000")

# Indicative EUR per 1 unit of foreign currency (ASSUMPTION reference spot table)
FX_REFERENCE_RATES_TO_EUR: dict[str, dict[str, str]] = {
    "EUR": {"eur_per_unit": "1.0000", "currency_name": "Euro", "data_status": "ASSUMPTION"},
    "USD": {
        "eur_per_unit": "0.9200",
        "currency_name": "US Dollar",
        "data_status": "ASSUMPTION",
    },
    "GBP": {
        "eur_per_unit": "1.1700",
        "currency_name": "British Pound",
        "data_status": "ASSUMPTION",
    },
    "PLN": {
        "eur_per_unit": "0.2320",
        "currency_name": "Polish Zloty",
        "data_status": "ASSUMPTION",
    },
    "INR": {
        "eur_per_unit": "0.0110",
        "currency_name": "Indian Rupee",
        "data_status": "ASSUMPTION",
    },
}


def _d(val: Any, name: str = "value") -> Decimal:
    try:
        d = Decimal(str(val))
    except Exception as exc:
        raise ValueError(f"invalid_decimal:{name}") from exc
    if not d.is_finite():
        raise ValueError(f"non_finite:{name}")
    return d


def _frac(d: Decimal) -> z3.RatNumRef:
    f = Fraction(d)
    return z3.RealVal(f"{f.numerator}/{f.denominator}")


def _to_dec(val: Any) -> Decimal:
    if z3.is_rational_value(val):
        return Decimal(val.numerator_as_long()) / Decimal(val.denominator_as_long())
    return Decimal(str(val.as_decimal(8)).rstrip("?"))


def prove_fx_margin_envelope(
    *,
    quoted_price_eur: str | Decimal,
    cost_eur: str | Decimal,
    billing_currency: str = "USD",
    cost_currency: str = "EUR",
    hedge_ratio_pct: str | Decimal = "80.000",
    forward_carry_bps_per_year: str | Decimal = "85.000",
    program_years: int = 3,
    fx_shock_band_pct: str | Decimal = "10.000",
    cost_drift_band_pct: str | Decimal = "5.000",
    min_acceptable_margin_pct: str | Decimal = "10.000",
) -> dict[str, Any]:
    """Prove via Z3 SMT that hedged EUR net margin >= floor across continuous FX+cost box."""
    q_eur = _d(quoted_price_eur, "quoted_price_eur")
    c_eur = _d(cost_eur, "cost_eur")
    h_pct = max(_ZERO, min(_HUNDRED, _d(hedge_ratio_pct, "hedge_ratio_pct")))
    bps = max(_ZERO, _d(forward_carry_bps_per_year, "forward_carry_bps_per_year"))
    yrs = max(1, int(program_years))
    fx_band = max(_ZERO, _d(fx_shock_band_pct, "fx_shock_band_pct"))
    c_band = max(_ZERO, _d(cost_drift_band_pct, "cost_drift_band_pct"))
    m_floor = _d(min_acceptable_margin_pct, "min_acceptable_margin_pct")

    bill_ccy = billing_currency.strip().upper()
    cost_ccy = cost_currency.strip().upper()
    if bill_ccy not in FX_REFERENCE_RATES_TO_EUR:
        raise ValueError(f"unsupported_currency:{bill_ccy}")
    if cost_ccy not in FX_REFERENCE_RATES_TO_EUR:
        raise ValueError(f"unsupported_currency:{cost_ccy}")

    with localcontext() as ctx:
        ctx.prec = 30
        h_frac = h_pct / _HUNDRED
        carry_eur = q_eur * h_frac * (bps / _TEN_THOUSAND) * Decimal(yrs)
        fx_delta = (fx_band / _HUNDRED) if bill_ccy != "EUR" else _ZERO
        cost_fx_delta = (fx_band / _HUNDRED) if cost_ccy != "EUR" else _ZERO
        c_delta = c_band / _HUNDRED
        m_frac = m_floor / _HUNDRED

    s = z3.Solver()
    s.set("timeout", 2500)
    k_fx = z3.Real("k_fx")
    k_cost_fx = z3.Real("k_cost_fx")
    k_cost_op = z3.Real("k_cost_op")

    s.add(k_fx >= _frac(_ONE - fx_delta), k_fx <= _frac(_ONE + fx_delta))
    s.add(k_cost_fx >= _frac(_ONE - cost_fx_delta), k_cost_fx <= _frac(_ONE + cost_fx_delta))
    s.add(k_cost_op >= _frac(_ONE - c_delta), k_cost_op <= _frac(_ONE + c_delta))

    zq = _frac(q_eur)
    zc = _frac(c_eur)
    zh = _frac(h_frac)
    zcarry = _frac(carry_eur)
    zm = _frac(m_frac)

    rev_eur = zq * (zh + (1 - zh) * k_fx) - zcarry
    act_cost_eur = zc * k_cost_op * (zh + (1 - zh) * k_cost_fx)
    # Violation if rev_eur <= 0 OR (rev_eur - act_cost_eur)/rev_eur < m_frac
    s.add(z3.Or(rev_eur <= 0, (1 - zm) * rev_eur < act_cost_eur))

    res = s.check()
    if res == z3.unsat:
        return {
            "property_name": "multicurrency_fx_hedged_margin_floor",
            "status": "PROVED_UNSAT",
            "proved": True,
            "solver": "z3",
            "billing_currency": bill_ccy,
            "cost_currency": cost_ccy,
            "assertion": (
                f"net_margin_pct(k_fx in +/-{fx_band}%, k_cost in +/-{c_band}%) >= {m_floor}%"
            ),
            "carry_cost_eur": format_quantum(carry_eur, _Q3),
            "reason": (
                "No combination inside continuous FX shock & cost-drift box breaks margin floor."
            ),
            "counterexample": None,
        }

    if res == z3.sat:
        mod = s.model()
        kx_d = _to_dec(mod.eval(k_fx, model_completion=True))
        kcfx_d = _to_dec(mod.eval(k_cost_fx, model_completion=True))
        kcop_d = _to_dec(mod.eval(k_cost_op, model_completion=True))
        rev_w = q_eur * (h_frac + (_ONE - h_frac) * kx_d) - carry_eur
        cost_w = c_eur * kcop_d * (h_frac + (_ONE - h_frac) * kcfx_d)
        m_w = ((rev_w - cost_w) / rev_w) * _HUNDRED if rev_w > _ZERO else Decimal("-999")
        return {
            "property_name": "multicurrency_fx_hedged_margin_floor",
            "status": "COUNTEREXAMPLE_FOUND",
            "proved": False,
            "solver": "z3",
            "billing_currency": bill_ccy,
            "cost_currency": cost_ccy,
            "assertion": (
                f"net_margin_pct(k_fx in +/-{fx_band}%, k_cost in +/-{c_band}%) >= {m_floor}%"
            ),
            "carry_cost_eur": format_quantum(carry_eur, _Q3),
            "reason": (
                "Counterexample found where unhedged FX shock + cost drift breaches margin floor."
            ),
            "counterexample": {
                "fx_multiplier": format_quantum(kx_d, _Q4),
                "cost_fx_multiplier": format_quantum(kcfx_d, _Q4),
                "cost_op_multiplier": format_quantum(kcop_d, _Q4),
                "witness_revenue_eur": format_quantum(rev_w, _Q3),
                "witness_cost_eur": format_quantum(cost_w, _Q3),
                "witness_margin_pct": format_quantum(m_w, _Q3),
            },
        }

    return {
        "property_name": "multicurrency_fx_hedged_margin_floor",
        "status": "UNKNOWN",
        "proved": False,
        "solver": "z3",
        "billing_currency": bill_ccy,
        "cost_currency": cost_ccy,
        "counterexample": None,
    }


def evaluate_quotation_fx_hedging(
    *,
    quoted_price_eur: str | Decimal,
    cost_eur: str | Decimal,
    billing_currency: str = "USD",
    cost_currency: str = "EUR",
    hedge_ratio_pct: str | Decimal = "80.000",
    forward_carry_bps_per_year: str | Decimal = "85.000",
    program_years: int = 3,
    fx_shock_band_pct: str | Decimal = "10.000",
    cost_drift_band_pct: str | Decimal = "5.000",
    min_acceptable_margin_pct: str | Decimal = "10.000",
) -> dict[str, Any]:
    """Evaluate multi-currency FX billing conversion, forward carry, shock table & Z3 proof."""
    q_eur = _d(quoted_price_eur, "quoted_price_eur")
    c_eur = _d(cost_eur, "cost_eur")
    if q_eur <= _ZERO or c_eur <= _ZERO:
        raise ValueError("quoted_price_eur_and_cost_eur_must_be_positive")
    h_pct = max(_ZERO, min(_HUNDRED, _d(hedge_ratio_pct, "hedge_ratio_pct")))
    bps = max(_ZERO, _d(forward_carry_bps_per_year, "forward_carry_bps_per_year"))
    yrs = max(1, int(program_years))
    fx_band = max(_ZERO, _d(fx_shock_band_pct, "fx_shock_band_pct"))
    c_band = max(_ZERO, _d(cost_drift_band_pct, "cost_drift_band_pct"))
    m_floor = _d(min_acceptable_margin_pct, "min_acceptable_margin_pct")

    bill_ccy = billing_currency.strip().upper()
    cost_ccy = cost_currency.strip().upper()
    if bill_ccy not in FX_REFERENCE_RATES_TO_EUR:
        raise ValueError(f"unsupported_currency:{bill_ccy}")
    if cost_ccy not in FX_REFERENCE_RATES_TO_EUR:
        raise ValueError(f"unsupported_currency:{cost_ccy}")

    spot_eur_per_bill = Decimal(FX_REFERENCE_RATES_TO_EUR[bill_ccy]["eur_per_unit"])
    spot_eur_per_cost = Decimal(FX_REFERENCE_RATES_TO_EUR[cost_ccy]["eur_per_unit"])

    with localcontext() as ctx:
        ctx.prec = 30
        invoice_billing = q_eur / spot_eur_per_bill
        cost_local = c_eur / spot_eur_per_cost
        h_frac = h_pct / _HUNDRED
        carry_rate_total = (bps / _TEN_THOUSAND) * Decimal(yrs)
        carry_cost_eur = q_eur * h_frac * carry_rate_total
        nominal_margin_eur = q_eur - carry_cost_eur - c_eur
        nominal_margin_pct = (nominal_margin_eur / (q_eur - carry_cost_eur)) * _HUNDRED

        # 5-point sensitivity grid over FX shock (-band, -band/2, 0, +band/2, +band)
        shocks = (
            -fx_band,
            -(fx_band / Decimal("2")),
            _ZERO,
            fx_band / Decimal("2"),
            fx_band,
        )
        sensitivity_scenarios: list[dict[str, str]] = []
        for s_pct in shocks:
            eff_s = s_pct if bill_ccy != "EUR" else _ZERO
            eff_cs = (-s_pct) if cost_ccy != "EUR" else _ZERO
            k_fx = _ONE + (eff_s / _HUNDRED)
            k_cfx = _ONE + (eff_cs / _HUNDRED)
            unhedged_rev = q_eur * k_fx
            hedged_rev = q_eur * (h_frac + (_ONE - h_frac) * k_fx) - carry_cost_eur
            hedged_cost = c_eur * (h_frac + (_ONE - h_frac) * k_cfx)
            unhedged_cost = c_eur * k_cfx
            unh_m = (
                ((unhedged_rev - unhedged_cost) / unhedged_rev) * _HUNDRED
                if unhedged_rev > _ZERO
                else Decimal("-999")
            )
            hdg_m = (
                ((hedged_rev - hedged_cost) / hedged_rev) * _HUNDRED
                if hedged_rev > _ZERO
                else Decimal("-999")
            )
            sensitivity_scenarios.append(
                {
                    "fx_shock_pct": format_quantum(s_pct, _Q2),
                    "unhedged_revenue_eur": format_quantum(unhedged_rev, _Q3),
                    "hedged_revenue_eur": format_quantum(hedged_rev, _Q3),
                    "unhedged_margin_pct": format_quantum(unh_m, _Q2),
                    "hedged_margin_pct": format_quantum(hdg_m, _Q2),
                }
            )

        # Scan minimum hedge ratio (0%..100% step 1%) satisfying floor under worst corner
        k_fx_min = _ONE - ((fx_band / _HUNDRED) if bill_ccy != "EUR" else _ZERO)
        k_cfx_max = _ONE + ((fx_band / _HUNDRED) if cost_ccy != "EUR" else _ZERO)
        c_max = c_eur * (_ONE + (c_band / _HUNDRED))
        rec_hedge_pct: str | None = None
        for step_pct in range(0, 101):
            hh = Decimal(step_pct) / _HUNDRED
            rev_wc = q_eur * (hh + (_ONE - hh) * k_fx_min) - (q_eur * hh * carry_rate_total)
            cost_wc = c_max * (hh + (_ONE - hh) * k_cfx_max)
            if rev_wc > _ZERO:
                m_wc = ((rev_wc - cost_wc) / rev_wc) * _HUNDRED
                if m_wc >= m_floor:
                    rec_hedge_pct = format_quantum(Decimal(step_pct), _Q2)
                    break

    formal_proof = prove_fx_margin_envelope(
        quoted_price_eur=q_eur,
        cost_eur=c_eur,
        billing_currency=bill_ccy,
        cost_currency=cost_ccy,
        hedge_ratio_pct=h_pct,
        forward_carry_bps_per_year=bps,
        program_years=yrs,
        fx_shock_band_pct=fx_band,
        cost_drift_band_pct=c_band,
        min_acceptable_margin_pct=m_floor,
    )

    return {
        "billing_currency": bill_ccy,
        "cost_currency": cost_ccy,
        "spot_eur_per_billing_unit": str(spot_eur_per_bill),
        "spot_eur_per_cost_unit": str(spot_eur_per_cost),
        "quoted_price_eur": format_quantum(q_eur, _Q3),
        "invoice_amount_billing_ccy": format_quantum(invoice_billing, _Q3),
        "cost_eur": format_quantum(c_eur, _Q3),
        "cost_local_ccy": format_quantum(cost_local, _Q3),
        "hedge_ratio_pct": format_quantum(h_pct, _Q2),
        "forward_carry_bps_per_year": format_quantum(bps, _Q2),
        "program_years": yrs,
        "hedge_carry_cost_eur": format_quantum(carry_cost_eur, _Q3),
        "nominal_hedged_margin_eur": format_quantum(nominal_margin_eur, _Q3),
        "nominal_hedged_margin_pct": format_quantum(nominal_margin_pct, _Q2),
        "recommended_min_hedge_ratio_pct": rec_hedge_pct,
        "sensitivity_scenarios": sensitivity_scenarios,
        "formal_fx_margin_proof": formal_proof,
        "data_status": "ASSUMPTION",
        "advisory_boundary": (
            "Multi-currency FX simulation & Z3 bounds provide treasury decision support only."
        ),
    }
