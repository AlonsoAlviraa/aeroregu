"""Advanced Calibration: Stratified K-Fold CV, Outlier/Drift Detection, Win-Rate & ERP/SAP Export.

Implements Q4 Year-1 Master Roadmap analytical & calibration capabilities in pure Decimal:
- Exogenous overrun outlier detection (`IQR` + `MAD` Z-score per archetype)
- Stratified K-Fold cross-validation across `(archetype_id, country_code)`
- Temporal calibration drift & broken-assumption shift monitoring
- Commercial Win-Rate vs Bid Percentile (`P50..P90`) Pareto optimizer honoring margin floor
- Official ERP/SAP CSV & multi-sheet XLSX import template ready for 2,000+ real quotations
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import asdict
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from evidence_calc.quantize import format_quantum
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from evidence_coverage.historical_quotation_calibrator import (
    HistoricalQuotationRecord,
    _mean_decimal,
    _quantile_sorted,
    calibrate_from_historical_corpus,
    generate_reference_historical_corpus,
)
from evidence_coverage.rotorcraft_quotation_catalog import (
    COUNTRY_RATE_CARDS,
    ROTORCRAFT_QUOTATION_ARCHETYPES,
)

_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")

ERP_IMPORT_COLUMNS: tuple[str, ...] = (
    "quote_id",
    "archetype_id",
    "country_code",
    "cert_basis",
    "material_family",
    "cosysmo_complexity",
    "idp_maturity",
    "fem_nodes_count",
    "load_cases_count",
    "cbush_joints_count",
    "cad_drawings_count",
    "ply_count",
    "quoted_hours",
    "actual_burned_hours",
    "quoted_price_eur",
    "actual_cost_eur",
    "ecn_iterations_actual",
    "broken_assumption_ids",
    "outcome",
)

_SAP_FIELD_MAPPING: tuple[tuple[str, str, str, str], ...] = (
    ("quote_id", "VBAK-VBELN / PRPS-POSID", "String", "Unique quotation / WBS element ID"),
    ("archetype_id", "PRPS-USR00", "Enum(18)", "One of Q-DES-01 .. Q-TST-02"),
    ("country_code", "T001-LAND1", "Enum(9)", "EU_DEFAULT, FR, DE, ES, IT, UK, US, PL, IN"),
    ("cert_basis", "Z_CERT_BASIS", "Enum(4)", "CS-27, CS-29, STC, PART21J_REPAIR"),
    (
        "material_family",
        "MARA-MTART",
        "Enum(4)",
        "ALUMINUM_2024_7075, HYBRID_AL_CFRP, TI_6AL_4V, CFRP_PRIMARY_HONEYCOMB",
    ),
    ("cosysmo_complexity", "Z_COSYSMO", "Enum(4)", "LOW, NOMINAL, ELEVATED, HIGH"),
    ("idp_maturity", "Z_IDP_MATURITY", "Enum(3)", "COMPLETE, PARTIAL, INCOMPLETE"),
    ("fem_nodes_count", "Z_FEM_NODES", "Integer", "Total GRID nodes in BDF/OP2"),
    ("load_cases_count", "Z_SUBCASES", "Integer", "Total SUBCASE / load combinations"),
    ("cbush_joints_count", "Z_CBUSH_RBE", "Integer", "Total CBUSH/PBUSH/RBE2/RBE3 joints"),
    ("cad_drawings_count", "Z_DRAWINGS", "Integer", "Released 2D drawings count"),
    ("ply_count", "Z_PCOMP_PLIES", "Integer", "Composite laminate plies count"),
    ("quoted_hours", "COSP-WTG001_PLAN", "Decimal", "As-bid total engineering hours"),
    ("actual_burned_hours", "CATSDB-CATSHOURS", "Decimal", "As-burned actual engineering hours"),
    ("quoted_price_eur", "VBAK-NETWR", "Decimal", "Commercial selling price (EUR)"),
    ("actual_cost_eur", "COSP-WKG001_ACT", "Decimal", "Actual incurred total cost (EUR)"),
    ("ecn_iterations_actual", "AENR-ECN_CNT", "Integer", "Realized ECN/design loop count"),
    (
        "broken_assumption_ids",
        "Z_BROKEN_ASM",
        "Text(;)",
        "Semicolon-separated IDs (e.g. ASM-IDP-01;ASM-RL-01)",
    ),
    (
        "outcome",
        "VBAK-ABGRU / Z_OUTCOME",
        "Enum",
        "WON_ON_BUDGET, WON_OVERRUN, CHANGE_ORDER_RECOVERY, LOST_PRICE",
    ),
)


def detect_historical_outliers(
    corpus: list[HistoricalQuotationRecord],
    *,
    archetype_id: str | None = None,
    iqr_multiplier: str = "1.500",
    mad_z_threshold: str = "3.500",
) -> dict[str, Any]:
    """Detect exogenous extreme overrun outliers per archetype via Decimal IQR & MAD Z-score."""
    subset = [r for r in corpus if archetype_id is None or r.archetype_id == archetype_id]
    if not subset:
        return {
            "total_records": 0,
            "outlier_count": 0,
            "outlier_rate_pct": "0.00",
            "outliers": [],
            "cleaned_records": [],
            "outlier_records": [],
        }

    iqr_k = Decimal(iqr_multiplier)
    mad_thresh = Decimal(mad_z_threshold)
    by_arch: dict[str, list[HistoricalQuotationRecord]] = {}
    for rec in subset:
        by_arch.setdefault(rec.archetype_id, []).append(rec)

    outliers: list[dict[str, Any]] = []
    outlier_ids: set[str] = set()
    all_ratios: list[Decimal] = []
    cleaned_ratios: list[Decimal] = []

    for a_id, grp in sorted(by_arch.items()):
        ratios = sorted(Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours) for r in grp)
        q1 = _quantile_sorted(ratios, Decimal("25"))
        med = _quantile_sorted(ratios, Decimal("50"))
        q3 = _quantile_sorted(ratios, Decimal("75"))
        iqr = max(Decimal("0.050"), q3 - q1)
        upper_fence = q3 + (iqr_k * iqr)
        lower_fence = max(Decimal("0.200"), q1 - (iqr_k * iqr))

        abs_devs = sorted((r - med).copy_abs() for r in ratios)
        mad = max(Decimal("0.020"), _quantile_sorted(abs_devs, Decimal("50")))

        for rec in grp:
            ratio = Decimal(rec.actual_burned_hours) / Decimal(rec.quoted_hours)
            all_ratios.append(ratio)
            mad_z = (Decimal("0.6745") * (ratio - med).copy_abs()) / mad
            is_iqr_out = ratio > upper_fence or ratio < lower_fence
            is_mad_out = mad_z > mad_thresh
            if is_iqr_out or is_mad_out:
                outlier_ids.add(rec.quote_id)
                outliers.append(
                    {
                        "quote_id": rec.quote_id,
                        "archetype_id": a_id,
                        "country_code": rec.country_code,
                        "quoted_hours": rec.quoted_hours,
                        "actual_burned_hours": rec.actual_burned_hours,
                        "overrun_ratio": format_quantum(ratio, _Q3),
                        "archetype_median_ratio": format_quantum(med, _Q3),
                        "upper_iqr_fence": format_quantum(upper_fence, _Q3),
                        "mad_z_score": format_quantum(mad_z, _Q2),
                        "reason": (
                            "EXTREME_EXOGENOUS_OVERRUN"
                            if ratio > upper_fence
                            else "LOW_RATIO_ANOMALY"
                        ),
                    }
                )
            else:
                cleaned_ratios.append(ratio)

    cleaned_records = [r for r in subset if r.quote_id not in outlier_ids]
    outlier_records = [r for r in subset if r.quote_id in outlier_ids]
    out_rate = (Decimal(len(outliers)) / Decimal(len(subset))) * _HUNDRED

    return {
        "total_records": len(subset),
        "outlier_count": len(outliers),
        "cleaned_count": len(cleaned_records),
        "outlier_rate_pct": format_quantum(out_rate, _Q2),
        "mean_overrun_before": format_quantum(_mean_decimal(all_ratios), _Q3),
        "mean_overrun_after_cleaning": format_quantum(
            _mean_decimal(cleaned_ratios) if cleaned_ratios else _mean_decimal(all_ratios), _Q3
        ),
        "outliers": sorted(outliers, key=lambda o: Decimal(o["mad_z_score"]), reverse=True),
        "cleaned_records": cleaned_records,
        "outlier_records": outlier_records,
    }


def run_stratified_kfold_calibration(
    corpus: list[HistoricalQuotationRecord],
    *,
    k_folds: int = 5,
    exclude_outliers: bool = True,
) -> dict[str, Any]:
    """Run deterministic K-fold cross-validation stratified by (archetype_id, country_code)."""
    if k_folds < 2 or k_folds > 10:
        raise ValueError("k_folds must be in [2, 10]")

    outlier_info = detect_historical_outliers(corpus) if exclude_outliers else None
    working = list(outlier_info["cleaned_records"]) if outlier_info else list(corpus)
    if len(working) < k_folds:
        raise ValueError("Not enough records for requested k_folds")

    strata: dict[tuple[str, str], list[HistoricalQuotationRecord]] = {}
    for rec in working:
        strata.setdefault((rec.archetype_id, rec.country_code), []).append(rec)

    folds: list[list[HistoricalQuotationRecord]] = [[] for _ in range(k_folds)]
    seq = 0
    for key in sorted(strata):
        items = sorted(strata[key], key=lambda r: r.quote_id)
        for rec in items:
            folds[seq % k_folds].append(rec)
            seq += 1

    fold_reports: list[dict[str, Any]] = []
    all_pre_errs: list[Decimal] = []
    all_post_errs: list[Decimal] = []
    arch_post_errs: dict[str, list[Decimal]] = {}
    ctry_post_errs: dict[str, list[Decimal]] = {}

    for f_idx in range(k_folds):
        val = folds[f_idx]
        train = [r for j, fld in enumerate(folds) if j != f_idx for r in fld]

        # Fit hierarchical multipliers per archetype on train folds
        by_arch: dict[str, list[Decimal]] = {}
        by_arch_idp: dict[tuple[str, str], list[Decimal]] = {}
        by_arch_cos: dict[tuple[str, str], list[Decimal]] = {}
        for r in train:
            ratio = Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours)
            by_arch.setdefault(r.archetype_id, []).append(ratio)
            by_arch_idp.setdefault((r.archetype_id, r.idp_maturity), []).append(ratio)
            by_arch_cos.setdefault((r.archetype_id, r.cosysmo_complexity), []).append(ratio)

        arch_mean = {k: _mean_decimal(v) for k, v in by_arch.items()}
        idp_mult = {k: _mean_decimal(v) for k, v in by_arch_idp.items() if len(v) >= 2}
        cos_rel = {
            (a, c): (_mean_decimal(v) / arch_mean[a])
            for (a, c), v in by_arch_cos.items()
            if len(v) >= 2 and a in arch_mean and arch_mean[a] > _ZERO
        }

        f_pre: list[Decimal] = []
        f_post: list[Decimal] = []
        f_abs_hrs: list[Decimal] = []
        f_bias: list[Decimal] = []
        for r in val:
            act = Decimal(r.actual_burned_hours)
            q = Decimal(r.quoted_hours)
            base_m = arch_mean.get(r.archetype_id, _ONE)
            pred_ratio = idp_mult.get((r.archetype_id, r.idp_maturity), base_m) * cos_rel.get(
                (r.archetype_id, r.cosysmo_complexity), _ONE
            )
            pred = q * pred_ratio
            pre_e = ((act - q).copy_abs() / act) * _HUNDRED
            post_e = ((act - pred).copy_abs() / act) * _HUNDRED
            f_pre.append(pre_e)
            f_post.append(post_e)
            f_abs_hrs.append((act - pred).copy_abs())
            f_bias.append(((pred - act) / act) * _HUNDRED)
            all_pre_errs.append(pre_e)
            all_post_errs.append(post_e)
            arch_post_errs.setdefault(r.archetype_id, []).append(post_e)
            ctry_post_errs.setdefault(r.country_code, []).append(post_e)

        pre_m = _mean_decimal(f_pre)
        post_m = _mean_decimal(f_post)
        fold_reports.append(
            {
                "fold_index": f_idx + 1,
                "train_count": len(train),
                "val_count": len(val),
                "pre_calibration_mape_pct": format_quantum(pre_m, _Q2),
                "post_calibration_mape_pct": format_quantum(post_m, _Q2),
                "mape_improvement_pct_points": format_quantum(pre_m - post_m, _Q2),
                "mae_hours": format_quantum(_mean_decimal(f_abs_hrs), _Q2),
                "mean_bias_pct": format_quantum(_mean_decimal(f_bias), _Q2),
            }
        )

    global_pre = _mean_decimal(all_pre_errs)
    global_post = _mean_decimal(all_post_errs)
    worst_fold_post = max(Decimal(f["post_calibration_mape_pct"]) for f in fold_reports)

    return {
        "k_folds": k_folds,
        "exclude_outliers": exclude_outliers,
        "outliers_excluded_count": outlier_info["outlier_count"] if outlier_info else 0,
        "evaluated_records_count": len(working),
        "global_pre_mape_pct": format_quantum(global_pre, _Q2),
        "global_post_mape_pct": format_quantum(global_post, _Q2),
        "global_mape_improvement_pct_points": format_quantum(global_pre - global_post, _Q2),
        "worst_fold_post_mape_pct": format_quantum(worst_fold_post, _Q2),
        "folds": fold_reports,
        "per_archetype_cv_mape_pct": {
            k: format_quantum(_mean_decimal(v), _Q2) for k, v in sorted(arch_post_errs.items())
        },
        "per_country_cv_mape_pct": {
            k: format_quantum(_mean_decimal(v), _Q2) for k, v in sorted(ctry_post_errs.items())
        },
    }


def detect_calibration_drift(
    corpus: list[HistoricalQuotationRecord],
    *,
    recent_fraction: str = "0.250",
) -> dict[str, Any]:
    """Detect temporal cost/overrun & broken-assumption drift between baseline and recent bids."""
    if len(corpus) < 20:
        return {
            "drift_status": "INSUFFICIENT_HISTORY",
            "baseline_count": len(corpus),
            "recent_count": 0,
        }

    frac = min(Decimal("0.500"), max(Decimal("0.100"), Decimal(recent_fraction)))
    recent_n = max(10, int(Decimal(len(corpus)) * frac))
    baseline = corpus[:-recent_n]
    recent = corpus[-recent_n:]

    def _window_stats(rows: list[HistoricalQuotationRecord]) -> tuple[Decimal, Decimal, Decimal]:
        ratios = sorted(Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours) for r in rows)
        broken_cnt = sum(1 for r in rows if r.broken_assumption_ids)
        return (
            _mean_decimal(ratios),
            _quantile_sorted(ratios, Decimal("90")),
            (Decimal(broken_cnt) / Decimal(len(rows))) * _HUNDRED,
        )

    b_mean, b_p90, b_brk = _window_stats(baseline)
    r_mean, r_p90, r_brk = _window_stats(recent)
    mean_shift_pct = ((r_mean - b_mean) / b_mean) * _HUNDRED if b_mean > _ZERO else _ZERO
    p90_shift_pct = ((r_p90 - b_p90) / b_p90) * _HUNDRED if b_p90 > _ZERO else _ZERO
    brk_shift_pp = r_brk - b_brk

    if mean_shift_pct.copy_abs() >= Decimal("6.00") or brk_shift_pp.copy_abs() >= Decimal("10.00"):
        status = "RECALIBRATE_REQUIRED"
    elif mean_shift_pct.copy_abs() >= Decimal("3.00") or p90_shift_pct.copy_abs() >= Decimal(
        "5.00"
    ):
        status = "WATCH"
    else:
        status = "STABLE"

    arch_alerts: list[dict[str, str]] = []
    for a_id in sorted({r.archetype_id for r in corpus}):
        b_a = [
            Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours)
            for r in baseline
            if r.archetype_id == a_id
        ]
        r_a = [
            Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours)
            for r in recent
            if r.archetype_id == a_id
        ]
        if len(b_a) >= 5 and len(r_a) >= 3:
            bm = _mean_decimal(b_a)
            rm = _mean_decimal(r_a)
            sh = ((rm - bm) / bm) * _HUNDRED
            if sh.copy_abs() >= Decimal("5.00"):
                arch_alerts.append(
                    {
                        "archetype_id": a_id,
                        "baseline_mean_ratio": format_quantum(bm, _Q3),
                        "recent_mean_ratio": format_quantum(rm, _Q3),
                        "shift_pct": format_quantum(sh, _Q2),
                    }
                )

    return {
        "drift_status": status,
        "baseline_count": len(baseline),
        "recent_count": len(recent),
        "baseline_mean_overrun_ratio": format_quantum(b_mean, _Q3),
        "recent_mean_overrun_ratio": format_quantum(r_mean, _Q3),
        "mean_overrun_shift_pct": format_quantum(mean_shift_pct, _Q2),
        "baseline_p90_overrun_ratio": format_quantum(b_p90, _Q3),
        "recent_p90_overrun_ratio": format_quantum(r_p90, _Q3),
        "p90_overrun_shift_pct": format_quantum(p90_shift_pct, _Q2),
        "broken_assumption_shift_pp": format_quantum(brk_shift_pp, _Q2),
        "archetype_drift_alerts": arch_alerts,
    }


def calibrate_win_rate_by_percentile(
    corpus: list[HistoricalQuotationRecord],
    *,
    archetype_id: str = "Q-STR-03",
    country_code: str = "EU_DEFAULT",
    target_margin_pct: str = "22.000",
    min_acceptable_margin_pct: str = "10.000",
) -> dict[str, Any]:
    """Calibrate Win-Rate vs Bid Percentile (P50..P90) and find margin-safe optimal bid."""
    cal = calibrate_from_historical_corpus(
        corpus,
        archetype_id=archetype_id,
        country_code=country_code,
    )
    co = cal["calibration_outputs"]
    p50_h = Decimal(co["calibrated_pert_expected_hours"])
    p80_h = Decimal(co["calibrated_pert_p80_hours"])
    sigma_h = max(Decimal("1.000"), (p80_h - p50_h) / Decimal("0.84162123"))

    c_card = COUNTRY_RATE_CARDS[country_code]
    eu_card = COUNTRY_RATE_CARDS["EU_DEFAULT"]
    rate = Decimal(c_card["rates"]["stress_rate"])
    eu_rate = Decimal(eu_card["rates"]["stress_rate"])
    rate_comp_adj = ((eu_rate - rate) / eu_rate) * Decimal(
        "12.000"
    )  # lower rate -> higher win odds

    oh_mult = _ONE + (Decimal(c_card["overhead_pct"]) / _HUNDRED)
    target_m = Decimal(target_margin_pct)
    floor_m = Decimal(min_acceptable_margin_pct)
    margin_denom = _ONE - (target_m / _HUNDRED)

    slice_rows = [r for r in corpus if r.archetype_id == archetype_id]
    slice_ratios = [Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours) for r in slice_rows]
    arch_ml = Decimal(
        ROTORCRAFT_QUOTATION_ARCHETYPES[archetype_id]["pert_total_hours"]["most_likely"]
    )
    burned_hours = [arch_ml * r for r in slice_ratios]

    percentile_specs: tuple[tuple[str, Decimal, Decimal], ...] = (
        ("P50", Decimal("0.0000"), Decimal("62.00")),
        ("P65", Decimal("0.3853"), Decimal("55.00")),
        ("P75", Decimal("0.6745"), Decimal("49.00")),
        ("P80", Decimal("0.8416"), Decimal("45.00")),
        ("P85", Decimal("1.0364"), Decimal("39.00")),
        ("P90", Decimal("1.2816"), Decimal("32.00")),
    )

    curve: list[dict[str, Any]] = []
    best_candidate: dict[str, Any] | None = None
    best_ev = Decimal("-999999999")

    with localcontext() as ctx:
        ctx.prec = 30
        for p_lbl, z_val, base_win in percentile_specs:
            bid_h = p50_h + (z_val * sigma_h)
            bid_cost = bid_h * rate * oh_mult
            bid_price = bid_cost / margin_denom
            expected_actual_cost = p50_h * rate * oh_mult
            expected_margin_eur = bid_price - expected_actual_cost
            expected_margin_pct = (expected_margin_eur / bid_price) * _HUNDRED

            # Empirical loss probability where burned cost exceeds bid price
            if burned_hours:
                loss_hits = sum(1 for bh in burned_hours if (bh * rate * oh_mult) > bid_price)
                prob_loss_pct = (Decimal(loss_hits) / Decimal(len(burned_hours))) * _HUNDRED
            else:
                prob_loss_pct = _ZERO

            win_rate = min(Decimal("90.00"), max(Decimal("5.00"), base_win + rate_comp_adj))
            expected_profit = (win_rate / _HUNDRED) * expected_margin_eur
            floor_ok = expected_margin_pct >= floor_m

            row = {
                "percentile": p_lbl,
                "z_score": format_quantum(z_val, _Q3),
                "bid_hours": format_quantum(bid_h, _Q2),
                "bid_price_eur": format_quantum(bid_price, _Q2),
                "expected_gross_margin_eur": format_quantum(expected_margin_eur, _Q2),
                "expected_gross_margin_pct": format_quantum(expected_margin_pct, _Q2),
                "calibrated_win_rate_pct": format_quantum(win_rate, _Q2),
                "empirical_loss_risk_pct": format_quantum(prob_loss_pct, _Q2),
                "expected_commercial_value_eur": format_quantum(expected_profit, _Q2),
                "meets_margin_floor": floor_ok,
            }
            curve.append(row)
            if floor_ok and expected_profit > best_ev:
                best_ev = expected_profit
                best_candidate = row

    return {
        "archetype_id": archetype_id,
        "country_code": country_code,
        "recommended_percentile": best_candidate["percentile"] if best_candidate else "P80",
        "recommended_bid": best_candidate,
        "percentile_curve": curve,
        "note": (
            "Win-Rate curve calibrated deterministically against rate competitiveness and "
            "empirical As-Burned overrun distribution (ASSUMPTION/ESTIMATE)."
        ),
    }


def export_erp_sap_import_template(
    *,
    fmt: str = "xlsx",
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Generate official ERP/SAP bulk historical bid import template (.xlsx or .csv)."""
    sample_corpus = generate_reference_historical_corpus(count=3, seed=2026)
    norm_fmt = fmt.strip().lower()

    if norm_fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(ERP_IMPORT_COLUMNS))
        writer.writeheader()
        for idx, rec in enumerate(sample_corpus, start=1):
            d = asdict(rec)
            d.pop("record_sha256", None)
            d["quote_id"] = f"SYNTHETIC_EXAMPLE_{idx:03d}"
            d["broken_assumption_ids"] = ";".join(rec.broken_assumption_ids)
            writer.writerow(d)
        raw_bytes = buf.getvalue().encode("utf-8")
    elif norm_fmt == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = "Historical_Bids_Import"
        ws.append(list(ERP_IMPORT_COLUMNS))
        hdr_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
        hdr_font = Font(color="FFFFFF", bold=True, size=10)
        for col_i in range(1, len(ERP_IMPORT_COLUMNS) + 1):
            c = ws.cell(row=1, column=col_i)
            c.fill = hdr_fill
            c.font = hdr_font
        ws.freeze_panes = "A2"

        for idx, rec in enumerate(sample_corpus, start=1):
            d = asdict(rec)
            d["quote_id"] = f"SYNTHETIC_EXAMPLE_{idx:03d}"
            d["broken_assumption_ids"] = ";".join(rec.broken_assumption_ids)
            ws.append([d[col] for col in ERP_IMPORT_COLUMNS])

        ws_dict = wb.create_sheet("Data_Dictionary_SAP_Mapping")
        ws_dict.append(
            [
                "Column Name",
                "SAP ERP Source (PS/SD/CO/CATS)",
                "Data Type",
                "Validation Rules / Allowed Values",
            ]
        )
        for col_i in range(1, 5):
            c = ws_dict.cell(row=1, column=col_i)
            c.fill = hdr_fill
            c.font = hdr_font
        for row_spec in _SAP_FIELD_MAPPING:
            ws_dict.append(list(row_spec))

        out_io = io.BytesIO()
        wb.save(out_io)
        raw_bytes = out_io.getvalue()
    else:
        raise ValueError(f"Unsupported ERP template format: {fmt}")

    sha = hashlib.sha256(raw_bytes).hexdigest()
    out_str: str | None = None
    if output_path is not None:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw_bytes)
        out_str = str(p)

    return {
        "format": norm_fmt,
        "columns": list(ERP_IMPORT_COLUMNS),
        "sample_rows_count": len(sample_corpus),
        "sha256": sha,
        "content_bytes": raw_bytes,
        "output_path": out_str,
    }


def run_advanced_calibration_suite(
    *,
    corpus: list[HistoricalQuotationRecord] | None = None,
    archetype_id: str = "Q-STR-03",
    country_code: str = "EU_DEFAULT",
    k_folds: int = 5,
    exclude_outliers: bool = True,
    target_margin_pct: str = "22.000",
    min_acceptable_margin_pct: str = "10.000",
) -> dict[str, Any]:
    """Run K-Fold CV, outlier audit, drift check, and Win-Rate P50..P90 calibration together."""
    active_corpus = corpus if corpus is not None else generate_reference_historical_corpus(2160)
    outliers = detect_historical_outliers(active_corpus)
    kfold = run_stratified_kfold_calibration(
        active_corpus, k_folds=k_folds, exclude_outliers=exclude_outliers
    )
    drift = detect_calibration_drift(active_corpus)
    win_rate = calibrate_win_rate_by_percentile(
        active_corpus,
        archetype_id=archetype_id,
        country_code=country_code,
        target_margin_pct=target_margin_pct,
        min_acceptable_margin_pct=min_acceptable_margin_pct,
    )
    return {
        "corpus_size": len(active_corpus),
        "outlier_report": {
            k: v for k, v in outliers.items() if k not in ("cleaned_records", "outlier_records")
        },
        "kfold_cv": kfold,
        "drift_diagnostics": drift,
        "win_rate_calibration": win_rate,
    }
