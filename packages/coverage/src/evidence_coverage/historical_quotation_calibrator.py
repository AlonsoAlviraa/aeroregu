"""Historical 2,000+ Quotation Ingest, Backtesting Calibrator, IDP Feature Extractor & k-NN.

Implements three deterministic production modules closing the empirical data bottleneck:
1. Bulk Historical Ingestion & Buhlmann-PERT Calibration (`rotorcraft_historical_calibration`):
   Ingests 2,000+ CSV/JSON/JSONL As-Bid vs As-Burned quotations (or generates a reproducible
   2,160-record reference benchmark corpus labeled SYNTHETIC_BENCHMARK_ASSUMPTION), runs an
   80/20 temporal backtest (pre- vs post-calibration MAPE), and calibrates PERT triples and
   contingency via Decimal + 50-digit FLINT/Arb intervals.
2. Physical IDP Complexity Extractor (`extract_idp_physical_complexity`):
   Inspects Nastran `.bdf`/`.dat` decks, `.f06` solver audits (GPWG/OLOAD/SPCFORCE/EPSILON/FATAL),
   STEP `.stp` solids, and DXF drawings with SHA-256 provenance to derive objective
   `cosysmo_complexity`, `idp_maturity`, and `idp_feature_complexity_factor`.
3. Deterministic k-NN Case-Based Retrieval (`retrieve_nearest_historical_quotations`):
   Scores similarity across all historical records using Decimal weighted feature distance and
   surfaces the top-k closest past bids with overrun alerts and broken assumptions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from functools import lru_cache
from pathlib import Path
from typing import Any

from evidence_calc.quantize import format_quantum
from evidence_calc.registry import run_method

_Q2 = Decimal("0.01")
_Q3 = Decimal("0.001")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")

_ARCHETYPE_FAMILY_MAP: dict[str, str] = {
    "Q-DES-01": "DESIGN",
    "Q-DES-02": "DESIGN",
    "Q-DES-03": "DESIGN",
    "Q-DES-04": "DESIGN",
    "Q-STR-01": "STRESS",
    "Q-STR-02": "STRESS",
    "Q-STR-03": "STRESS",
    "Q-STR-04": "STRESS",
    "Q-FDT-01": "FDT",
    "Q-FDT-02": "FDT",
    "Q-DYN-01": "DYNAMICS",
    "Q-DYN-02": "DYNAMICS",
    "Q-DYN-03": "DYNAMICS",
    "Q-DOA-01": "DOA",
    "Q-DOA-02": "DOA",
    "Q-DOA-03": "DOA",
    "Q-TST-01": "TEST",
    "Q-TST-02": "TEST",
}

_BROKEN_ASSUMPTION_BY_DRIVER: dict[str, tuple[str, ...]] = {
    "INCOMPLETE": ("ASM-IDP-01", "ASM-RL-01"),
    "PARTIAL": ("ASM-TS-01", "ASM-SCH-01"),
    "HIGH": ("ASM-DY-01", "ASM-TS-04"),
    "CFRP_PRIMARY_HONEYCOMB": ("ASM-IDP-02", "ASM-DOA-03"),
    "TI_6AL_4V": ("ASM-IDP-04", "ASM-TS-02"),
}


@dataclass(frozen=True)
class HistoricalQuotationRecord:
    """Single As-Bid vs As-Burned rotorcraft engineering quotation record."""

    quote_id: str
    archetype_id: str
    country_code: str
    cert_basis: str
    material_family: str
    cosysmo_complexity: str
    idp_maturity: str
    fem_nodes_count: int
    load_cases_count: int
    cbush_joints_count: int
    cad_drawings_count: int
    ply_count: int
    quoted_hours: str
    actual_burned_hours: str
    quoted_price_eur: str
    actual_cost_eur: str
    ecn_iterations_actual: int
    broken_assumption_ids: tuple[str, ...]
    outcome: str
    record_sha256: str


@dataclass(frozen=True)
class IDPPhysicalComplexityProfile:
    """Objective physical complexity metrics extracted from CAD/FEM IDP artifacts."""

    artifacts_analyzed: tuple[str, ...]
    artifact_hashes: dict[str, str]
    fem_nodes_count: int
    fem_elements_count: int
    cbush_joints_count: int
    pcomp_laminates_count: int
    load_cases_count: int
    step_solids_count: int
    step_faces_count: int
    dxf_entities_count: int
    f06_has_gpwg: bool
    f06_has_oload_spc: bool
    f06_has_fatal: bool
    f06_epsilon_max: str | None
    f06_epsilon_exceeded: bool
    derived_cosysmo_complexity: str
    derived_idp_maturity: str
    idp_feature_complexity_factor: str
    complexity_index: str
    quality_findings: tuple[str, ...] = field(default_factory=tuple)


def _hash_canonical(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _quantile_sorted(sorted_vals: list[Decimal], pct: Decimal) -> Decimal:
    """Linear-interpolated deterministic quantile over pre-sorted Decimal list."""
    n = len(sorted_vals)
    if n == 0:
        return _ZERO
    if n == 1:
        return sorted_vals[0]
    idx_d = (Decimal(n - 1) * pct) / _HUNDRED
    lo = int(idx_d)
    hi = min(n - 1, lo + 1)
    frac = idx_d - Decimal(lo)
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def _mean_decimal(vals: list[Decimal]) -> Decimal:
    if not vals:
        return _ZERO
    return sum(vals, _ZERO) / Decimal(len(vals))


@lru_cache(maxsize=4)
def _cached_reference_corpus(count: int, seed: int) -> tuple[HistoricalQuotationRecord, ...]:
    from evidence_coverage.rotorcraft_quotation_catalog import (
        COUNTRY_RATE_CARDS,
        ROTORCRAFT_QUOTATION_ARCHETYPES,
    )

    arch_ids = tuple(ROTORCRAFT_QUOTATION_ARCHETYPES.keys())
    country_ids = tuple(COUNTRY_RATE_CARDS.keys())
    cert_bases = ("CS-29", "CS-27", "STC", "PART21J_REPAIR")
    materials = (
        "ALUMINUM_2024_7075",
        "HYBRID_AL_CFRP",
        "TI_6AL_4V",
        "CFRP_PRIMARY_HONEYCOMB",
    )
    mat_mults = {
        "ALUMINUM_2024_7075": Decimal("1.000"),
        "HYBRID_AL_CFRP": Decimal("1.250"),
        "TI_6AL_4V": Decimal("1.450"),
        "CFRP_PRIMARY_HONEYCOMB": Decimal("1.550"),
    }
    cert_mults = {
        "CS-27": Decimal("1.000"),
        "PART21J_REPAIR": Decimal("1.050"),
        "STC": Decimal("1.180"),
        "CS-29": Decimal("1.350"),
    }
    idp_levels = ("COMPLETE", "PARTIAL", "INCOMPLETE")
    cosysmo_levels = ("LOW", "NOMINAL", "ELEVATED", "HIGH")

    state = seed & 0xFFFFFFFFFFFFFFFF
    records: list[HistoricalQuotationRecord] = []

    for i in range(count):
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        r1 = (state >> 16) & 0xFFFF
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
        r2 = (state >> 16) & 0xFFFF

        a_id = arch_ids[i % len(arch_ids)]
        arch = ROTORCRAFT_QUOTATION_ARCHETYPES[a_id]
        c_code = country_ids[(i + (r1 % 5)) % len(country_ids)]
        c_card = COUNTRY_RATE_CARDS[c_code]
        cert = cert_bases[(i // 3 + (r1 % 3)) % len(cert_bases)]
        mat = materials[(i // 5 + (r2 % 3)) % len(materials)]
        idp = idp_levels[(i // 7 + r1) % len(idp_levels)]
        cosysmo = cosysmo_levels[(i // 11 + r2) % len(cosysmo_levels)]

        base_ml = Decimal(arch["pert_total_hours"]["most_likely"])
        # Quoted hours reflect nominal prior quote before historical overrun discovery
        scale = cert_mults[cert] * mat_mults[mat]
        spread_pct = Decimal((r1 % 17) - 6) / _HUNDRED  # -0.06 .. +0.10
        quoted_h = (base_ml * scale * (_ONE + spread_pct)).quantize(_Q3)

        # Realistic empirical overrun driven by incomplete IDP, COSYSMO & materials
        overrun = Decimal("1.020")
        broken: list[str] = []
        if idp == "PARTIAL":
            overrun += Decimal("0.110")
            broken.extend(_BROKEN_ASSUMPTION_BY_DRIVER["PARTIAL"])
        elif idp == "INCOMPLETE":
            overrun += Decimal("0.220")
            broken.extend(_BROKEN_ASSUMPTION_BY_DRIVER["INCOMPLETE"])
        if cosysmo == "ELEVATED":
            overrun += Decimal("0.070")
        elif cosysmo == "HIGH":
            overrun += Decimal("0.150")
            broken.extend(_BROKEN_ASSUMPTION_BY_DRIVER["HIGH"])
        if mat in ("CFRP_PRIMARY_HONEYCOMB", "TI_6AL_4V"):
            overrun += Decimal("0.050")
            broken.append(_BROKEN_ASSUMPTION_BY_DRIVER[mat][0])

        noise = Decimal((r2 % 15) - 4) / Decimal("100")  # -0.04 .. +0.10
        burned_h = (quoted_h * (overrun + noise)).quantize(_Q3)
        if burned_h < Decimal("10.000"):
            burned_h = Decimal("10.000")

        stress_r = Decimal(c_card["rates"]["stress_rate"])
        oh_mult = _ONE + (Decimal(c_card["overhead_pct"]) / _HUNDRED)
        cost_quoted = quoted_h * stress_r * oh_mult
        quoted_price = (cost_quoted / Decimal("0.780")).quantize(_Q3)
        actual_cost = (burned_h * stress_r * oh_mult).quantize(_Q3)

        nodes = 4000 + ((r1 % 30) * 1500) + (8000 if cosysmo in ("ELEVATED", "HIGH") else 0)
        load_cases = 12 + (r2 % 64) + (16 if cert == "CS-29" else 0)
        cbush = 15 + (r1 % 90)
        drawings = 4 + (r2 % 28)
        plies = 24 + (r1 % 48) if "CFRP" in mat else 0
        ecn_actual = 1 if idp == "COMPLETE" else (2 if idp == "PARTIAL" else 3 + (r2 % 2))

        if broken and burned_h > quoted_h * Decimal("1.180"):
            outcome = "CHANGE_ORDER_RECOVERY"
        elif burned_h > quoted_h * Decimal("1.080"):
            outcome = "WON_OVERRUN"
        else:
            outcome = "WON_ON_BUDGET"

        rec_dict = {
            "quote_id": f"HIST-{i + 1:05d}",
            "archetype_id": a_id,
            "country_code": c_code,
            "cert_basis": cert,
            "material_family": mat,
            "cosysmo_complexity": cosysmo,
            "idp_maturity": idp,
            "fem_nodes_count": nodes,
            "load_cases_count": load_cases,
            "cbush_joints_count": cbush,
            "cad_drawings_count": drawings,
            "ply_count": plies,
            "quoted_hours": format_quantum(quoted_h, _Q3),
            "actual_burned_hours": format_quantum(burned_h, _Q3),
            "quoted_price_eur": format_quantum(quoted_price, _Q3),
            "actual_cost_eur": format_quantum(actual_cost, _Q3),
            "ecn_iterations_actual": ecn_actual,
            "broken_assumption_ids": tuple(dict.fromkeys(broken)),
            "outcome": outcome,
        }
        rec_sha = _hash_canonical(rec_dict)
        records.append(HistoricalQuotationRecord(**rec_dict, record_sha256=rec_sha))
    return tuple(records)


def generate_reference_historical_corpus(
    count: int = 2160,
    seed: int = 2026,
) -> list[HistoricalQuotationRecord]:
    """Return a deterministic reproducible benchmark corpus of `count` past quotations."""
    if count <= 0:
        raise ValueError("count must be positive")
    return list(_cached_reference_corpus(count, seed))


def _parse_row_to_record(raw: dict[str, Any], idx: int) -> HistoricalQuotationRecord:
    from evidence_coverage.rotorcraft_quotation_catalog import (
        COUNTRY_RATE_CARDS,
        ROTORCRAFT_QUOTATION_ARCHETYPES,
    )

    q_id = str(raw.get("quote_id") or "").strip()
    a_id = str(raw.get("archetype_id") or "").strip()
    if not q_id or a_id not in ROTORCRAFT_QUOTATION_ARCHETYPES:
        raise ValueError(f"invalid quote_id or archetype_id at row {idx}")

    c_code = str(raw.get("country_code") or "EU_DEFAULT").strip() or "EU_DEFAULT"
    if c_code not in COUNTRY_RATE_CARDS:
        raise ValueError(f"unsupported country_code {c_code} at row {idx}")

    try:
        q_hrs = Decimal(str(raw["quoted_hours"]))
        a_hrs = Decimal(str(raw["actual_burned_hours"]))
        q_eur = Decimal(str(raw.get("quoted_price_eur") or (q_hrs * Decimal("120.000"))))
        a_eur = Decimal(str(raw.get("actual_cost_eur") or (a_hrs * Decimal("110.000"))))
    except (KeyError, InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid hours/cost decimal at row {idx}") from exc

    if q_hrs <= _ZERO or a_hrs <= _ZERO:
        raise ValueError(f"hours must be positive at row {idx}")

    broken_raw = raw.get("broken_assumption_ids") or ()
    if isinstance(broken_raw, str):
        broken_tuple = tuple(
            b.strip() for b in broken_raw.replace(";", ",").split(",") if b.strip()
        )
    else:
        broken_tuple = tuple(str(b).strip() for b in broken_raw if str(b).strip())

    clean = {
        "quote_id": q_id,
        "archetype_id": a_id,
        "country_code": c_code,
        "cert_basis": str(raw.get("cert_basis") or "CS-29").strip(),
        "material_family": str(raw.get("material_family") or "HYBRID_AL_CFRP").strip(),
        "cosysmo_complexity": str(raw.get("cosysmo_complexity") or "NOMINAL").strip().upper(),
        "idp_maturity": str(raw.get("idp_maturity") or "COMPLETE").strip().upper(),
        "fem_nodes_count": max(0, int(raw.get("fem_nodes_count") or 0)),
        "load_cases_count": max(0, int(raw.get("load_cases_count") or 0)),
        "cbush_joints_count": max(0, int(raw.get("cbush_joints_count") or 0)),
        "cad_drawings_count": max(0, int(raw.get("cad_drawings_count") or 0)),
        "ply_count": max(0, int(raw.get("ply_count") or 0)),
        "quoted_hours": format_quantum(q_hrs, _Q3),
        "actual_burned_hours": format_quantum(a_hrs, _Q3),
        "quoted_price_eur": format_quantum(q_eur, _Q3),
        "actual_cost_eur": format_quantum(a_eur, _Q3),
        "ecn_iterations_actual": max(0, int(raw.get("ecn_iterations_actual") or 1)),
        "broken_assumption_ids": broken_tuple,
        "outcome": str(raw.get("outcome") or "WON_ON_BUDGET").strip(),
    }
    rec_sha = _hash_canonical(clean)
    return HistoricalQuotationRecord(**clean, record_sha256=rec_sha)


def ingest_historical_quotations(
    source: str | Path | list[dict[str, Any]],
) -> dict[str, Any]:
    """Ingest 2,000+ past quotations from CSV, JSON, JSONL, or list of dicts with SHA-256."""
    raw_rows: list[dict[str, Any]]
    source_desc: str
    if isinstance(source, list):
        raw_rows = source
        source_desc = "in_memory_list"
    else:
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"Historical quotation file not found: {path}")
        source_desc = str(path.name)
        suffix = path.suffix.lower()
        text = path.read_text(encoding="utf-8")
        if suffix == ".csv":
            raw_rows = list(csv.DictReader(text.splitlines()))
        elif suffix == ".jsonl":
            raw_rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        elif suffix == ".json":
            parsed = json.loads(text)
            if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
                raw_rows = list(parsed["records"])
            elif isinstance(parsed, list):
                raw_rows = list(parsed)
            else:
                raise ValueError("JSON corpus must be a list or dict with 'records' key")
        else:
            raise ValueError(f"Unsupported historical file extension: {suffix}")

    records: list[HistoricalQuotationRecord] = []
    rejected_errors: list[str] = []
    by_archetype: dict[str, int] = {}
    by_country: dict[str, int] = {}

    for idx, row in enumerate(raw_rows):
        try:
            rec = _parse_row_to_record(row, idx)
        except ValueError as exc:
            rejected_errors.append(str(exc))
            continue
        records.append(rec)
        by_archetype[rec.archetype_id] = by_archetype.get(rec.archetype_id, 0) + 1
        by_country[rec.country_code] = by_country.get(rec.country_code, 0) + 1

    merkle_input = "\n".join(r.record_sha256 for r in records).encode("utf-8")
    dataset_sha256 = hashlib.sha256(merkle_input).hexdigest()

    return {
        "source": source_desc,
        "corpus_origin": "CUSTOMER_HISTORICAL_DATASET",
        "ingested_count": len(records),
        "rejected_count": len(rejected_errors),
        "rejected_sample": rejected_errors[:10],
        "by_archetype_counts": by_archetype,
        "by_country_counts": by_country,
        "dataset_sha256": dataset_sha256,
        "records": records,
    }


def calibrate_from_historical_corpus(
    corpus: list[HistoricalQuotationRecord],
    *,
    archetype_id: str,
    country_code: str = "EU_DEFAULT",
    idp_feature_factor: str = "1.000",
    credibility_full_n: str = "50.000",
    corpus_origin: str = "SYNTHETIC_BENCHMARK_ASSUMPTION",
) -> dict[str, Any]:
    """Calibrate archetype PERT priors against historical As-Burned hours & 80/20 backtest."""
    from evidence_coverage.rotorcraft_quotation_catalog import (
        COUNTRY_RATE_CARDS,
        ROTORCRAFT_QUOTATION_ARCHETYPES,
    )

    if archetype_id not in ROTORCRAFT_QUOTATION_ARCHETYPES:
        raise ValueError(f"Unknown archetype_id: {archetype_id}")
    if country_code not in COUNTRY_RATE_CARDS:
        raise ValueError(f"Unknown country_code: {country_code}")

    arch = ROTORCRAFT_QUOTATION_ARCHETYPES[archetype_id]
    c_card = COUNTRY_RATE_CARDS[country_code]
    matched_arch = [r for r in corpus if r.archetype_id == archetype_id]
    matched_country = [r for r in matched_arch if r.country_code == country_code]
    active_slice = matched_country if len(matched_country) >= 20 else matched_arch
    scope_used = (
        "archetype_and_country" if active_slice is matched_country else "archetype_all_countries"
    )

    prior_opt = arch["pert_total_hours"]["optimistic"]
    prior_ml = arch["pert_total_hours"]["most_likely"]
    prior_pess = arch["pert_total_hours"]["pessimistic"]

    if not active_slice:
        return {
            "status": "NO_HISTORICAL_RECORDS_PRIOR_RETAINED",
            "corpus_origin": corpus_origin,
            "corpus_total_records": len(corpus),
            "sample_size": 0,
            "scope_used": "none",
            "credibility_weight": "0.000",
            "pre_calibration_mape_pct": "0.00",
            "post_calibration_mape_pct": "0.00",
            "mape_improvement_pct_points": "0.00",
        }

    # 80/20 temporal holdout split on the slice for unbiased backtest error measurement
    split_idx = (
        max(1, (len(active_slice) * 4) // 5) if len(active_slice) >= 5 else len(active_slice)
    )
    train_slice = active_slice[:split_idx]
    val_slice = active_slice[split_idx:] if split_idx < len(active_slice) else active_slice

    burned_sorted = sorted(Decimal(r.actual_burned_hours) for r in train_slice)
    overruns = [Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours) for r in train_slice]
    overruns_sorted = sorted(overruns)
    emp_p10 = _quantile_sorted(burned_sorted, Decimal("10"))
    emp_p50 = _quantile_sorted(burned_sorted, Decimal("50"))
    emp_p90 = _quantile_sorted(burned_sorted, Decimal("90"))
    median_overrun = _quantile_sorted(overruns_sorted, Decimal("50"))
    # Guard calc limits [0.2, 5.0]
    median_overrun = min(Decimal("5.000"), max(Decimal("0.200"), median_overrun))

    # Count broken assumptions
    broken_counts: dict[str, int] = {}
    records_with_broken = 0
    for r in train_slice:
        if r.broken_assumption_ids:
            records_with_broken += 1
        for aid in r.broken_assumption_ids:
            broken_counts[aid] = broken_counts.get(aid, 0) + 1
    broken_rate_pct = (Decimal(records_with_broken) / Decimal(len(train_slice))) * _HUNDRED

    # Ensure empirical quantiles & overrun ratio preserve calibrated PERT monotonicity
    if emp_p10 > emp_p50:
        emp_p10 = emp_p50 * Decimal("0.750")
    if emp_p90 < emp_p50:
        emp_p90 = emp_p50 * Decimal("1.350")
    ml_blend = (_ONE + median_overrun) / Decimal("2")
    safe_overrun = (
        max(_ONE, median_overrun)
        if (emp_p10 > emp_p50 * ml_blend or emp_p90 * median_overrun < emp_p50 * ml_blend)
        else median_overrun
    )

    calc_inputs = {
        "prior_optimistic_hours": prior_opt,
        "prior_most_likely_hours": prior_ml,
        "prior_pessimistic_hours": prior_pess,
        "empirical_p10_hours": format_quantum(emp_p10, _Q3),
        "empirical_p50_hours": format_quantum(emp_p50, _Q3),
        "empirical_p90_hours": format_quantum(emp_p90, _Q3),
        "sample_size": str(len(active_slice)),
        "credibility_full_n": credibility_full_n,
        "historical_overrun_ratio": format_quantum(safe_overrun, _Q3),
        "idp_feature_complexity_factor": idp_feature_factor,
        "base_contingency_pct": c_card["contingency_pct"],
        "broken_assumption_rate_pct": format_quantum(broken_rate_pct, _Q3),
    }
    cal_res = run_method("rotorcraft_historical_calibration", calc_inputs, include_intervals=True)

    # Out-of-sample Pre vs Post Calibration MAPE using hierarchical driver calibration
    val_ids = {r.quote_id for r in val_slice}
    train_pool = [r for r in matched_arch if r.quote_id not in val_ids] or list(train_slice)
    pool_ratios = [Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours) for r in train_pool]
    pool_mean = _mean_decimal(pool_ratios) or _ONE

    by_idp: dict[str, list[Decimal]] = {}
    by_cos: dict[str, list[Decimal]] = {}
    for r in train_pool:
        ratio = Decimal(r.actual_burned_hours) / Decimal(r.quoted_hours)
        by_idp.setdefault(r.idp_maturity, []).append(ratio)
        by_cos.setdefault(r.cosysmo_complexity, []).append(ratio)

    idp_mult = {k: _mean_decimal(vs) for k, vs in by_idp.items()}
    cos_rel = {k: _mean_decimal(vs) / pool_mean for k, vs in by_cos.items()}

    pre_errs: list[Decimal] = []
    post_errs: list[Decimal] = []
    for r in val_slice:
        act = Decimal(r.actual_burned_hours)
        q_base = Decimal(r.quoted_hours)
        pred_ratio = idp_mult.get(r.idp_maturity, pool_mean) * cos_rel.get(
            r.cosysmo_complexity, _ONE
        )
        cal_pred = q_base * pred_ratio
        pre_errs.append(((act - q_base).copy_abs() / act) * _HUNDRED)
        post_errs.append(((act - cal_pred).copy_abs() / act) * _HUNDRED)

    pre_mape = _mean_decimal(pre_errs)
    post_mape = _mean_decimal(post_errs)
    mape_gain = pre_mape - post_mape

    top_broken = [
        {"assumption_id": k, "occurrences": v}
        for k, v in sorted(broken_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    ]

    return {
        "status": "CALIBRATED_DETERMINISTIC",
        "corpus_origin": corpus_origin,
        "corpus_total_records": len(corpus),
        "archetype_id": archetype_id,
        "country_code": country_code,
        "scope_used": scope_used,
        "sample_size": len(active_slice),
        "train_split_count": len(train_slice),
        "validation_split_count": len(val_slice),
        "empirical_quantiles": {
            "p10_hours": format_quantum(emp_p10, _Q3),
            "p50_hours": format_quantum(emp_p50, _Q3),
            "p90_hours": format_quantum(emp_p90, _Q3),
            "median_overrun_ratio": format_quantum(median_overrun, _Q3),
            "broken_assumption_rate_pct": format_quantum(broken_rate_pct, _Q2),
        },
        "calibration_outputs": cal_res["outputs"],
        "calibration_arb_intervals": cal_res.get("exact_intervals", {}),
        "backtesting": {
            "pre_calibration_mape_pct": format_quantum(pre_mape, _Q2),
            "post_calibration_mape_pct": format_quantum(post_mape, _Q2),
            "mape_improvement_pct_points": format_quantum(mape_gain, _Q2),
        },
        "top_broken_assumptions": top_broken,
    }


def _read_attachment_text(
    attachments: dict[str, Any],
    text_key: str,
    path_key: str,
) -> tuple[str, str | None]:
    raw_text = attachments.get(text_key)
    if isinstance(raw_text, str) and raw_text.strip():
        return raw_text, f"inline:{text_key}"
    raw_path = attachments.get(path_key)
    if raw_path:
        p = Path(str(raw_path))
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="ignore"), str(p.name)
    return "", None


def extract_idp_physical_complexity(
    attachments: dict[str, Any] | None = None,
    *,
    default_cosysmo: str = "NOMINAL",
    default_idp_maturity: str = "COMPLETE",
) -> IDPPhysicalComplexityProfile:
    """Deterministically inspect Nastran .bdf/.f06, STEP, and DXF files for physical complexity."""
    att = attachments or {}
    bdf_txt, bdf_name = _read_attachment_text(att, "bdf_text", "bdf_path")
    f06_txt, f06_name = _read_attachment_text(att, "f06_text", "f06_path")
    step_txt, step_name = _read_attachment_text(att, "step_text", "step_path")
    dxf_txt, dxf_name = _read_attachment_text(att, "dxf_text", "dxf_path")

    artifacts: list[str] = []
    hashes: dict[str, str] = {}
    for label, txt in (
        (bdf_name, bdf_txt),
        (f06_name, f06_txt),
        (step_name, step_txt),
        (dxf_name, dxf_txt),
    ):
        if label and txt:
            artifacts.append(label)
            hashes[label] = hashlib.sha256(txt.encode("utf-8")).hexdigest()

    # Nastran .bdf parsing
    nodes = len(re.findall(r"(?m)^\s*GRID\*?\b", bdf_txt, re.IGNORECASE))
    elems = len(
        re.findall(
            r"(?m)^\s*(?:CQUAD4|CTRIA3|CHEXA|CTETRA|CPENTA|CBAR|CBEAM|CROD|CSHEAR)\b",
            bdf_txt,
            re.IGNORECASE,
        )
    )
    cbush = len(re.findall(r"(?m)^\s*(?:CBUSH|PBUSH|RBE2|RBE3|CGAP)\b", bdf_txt, re.IGNORECASE))
    pcomp = len(re.findall(r"(?m)^\s*PCOMP[G]?\b", bdf_txt, re.IGNORECASE))
    subcases = len(re.findall(r"(?im)^\s*SUBCASE\b", bdf_txt))
    load_cards = len(re.findall(r"(?im)^\s*(?:FORCE|MOMENT|PLOAD\d?|LOAD)\b", bdf_txt))
    load_cases = max(subcases, min(load_cards, 200))

    # STEP parsing
    step_solids = len(
        re.findall(r"MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS|CLOSED_SHELL", step_txt, re.IGNORECASE)
    )
    step_faces = len(re.findall(r"ADVANCED_FACE", step_txt, re.IGNORECASE))

    # DXF parsing
    dxf_entities = len(
        re.findall(r"(?m)^\s*(?:DIMENSION|INSERT|LWPOLYLINE|CIRCLE|LINE)\s*$", dxf_txt)
    )

    # Nastran .f06 health audit
    f06_upper = f06_txt.upper()
    has_gpwg = ("WEIGHT GENERATOR" in f06_upper) or (
        "G R I D   P O I N T   W E I G H T" in f06_upper
    )
    has_oload_spc = ("OLOAD" in f06_upper) and ("SPCFORCE" in f06_upper)
    has_fatal = ("FATAL MESSAGE" in f06_upper) or ("USER FATAL MESSAGE" in f06_upper)
    eps_matches = re.findall(
        r"EPSILON\s*(?:=|\s)\s*([+-]?\d+(?:\.\d+)?(?:[EeDd][+-]?\d+)?)",
        f06_upper,
    )
    eps_max_dec: Decimal | None = None
    for m in eps_matches:
        try:
            d = Decimal(m.replace("D", "E")).copy_abs()
        except InvalidOperation:
            continue
        if eps_max_dec is None or d > eps_max_dec:
            eps_max_dec = d
    eps_exceeded = eps_max_dec is not None and eps_max_dec > Decimal("1e-6")

    findings: list[str] = []
    if not artifacts:
        return IDPPhysicalComplexityProfile(
            artifacts_analyzed=(),
            artifact_hashes={},
            fem_nodes_count=0,
            fem_elements_count=0,
            cbush_joints_count=0,
            pcomp_laminates_count=0,
            load_cases_count=0,
            step_solids_count=0,
            step_faces_count=0,
            dxf_entities_count=0,
            f06_has_gpwg=False,
            f06_has_oload_spc=False,
            f06_has_fatal=False,
            f06_epsilon_max=None,
            f06_epsilon_exceeded=False,
            derived_cosysmo_complexity=default_cosysmo,
            derived_idp_maturity=default_idp_maturity,
            idp_feature_complexity_factor="1.000",
            complexity_index="1.000",
            quality_findings=("No physical CAD/FEM files attached; nominal priors retained.",),
        )

    # Determine objective IDP maturity
    if has_fatal:
        findings.append("Nastran .f06 contains FATAL MESSAGE.")
    if eps_exceeded:
        findings.append(f"Nastran .f06 EPSILON={eps_max_dec} exceeds 1e-6 equilibrium threshold.")
    if f06_txt and not (has_gpwg and has_oload_spc):
        findings.append("Nastran .f06 missing GPWG or OLOAD/SPCFORCE balance tables.")

    if has_fatal or eps_exceeded or (f06_txt and not (has_gpwg and has_oload_spc)):
        derived_maturity = "INCOMPLETE"
    elif (bdf_txt and f06_txt and nodes > 0) or (step_txt and step_solids > 0 and not bdf_txt):
        derived_maturity = "COMPLETE"
    else:
        derived_maturity = "PARTIAL"
        findings.append(
            "Partial IDP artifacts supplied (missing paired solver audit or solid BREP)."
        )

    # Exact Decimal feature complexity index
    with localcontext() as ctx:
        ctx.prec = 30
        score = (
            (Decimal(nodes) / Decimal("2000")) * Decimal("0.250")
            + (Decimal(cbush) / Decimal("25")) * Decimal("0.300")
            + (Decimal(load_cases) / Decimal("20")) * Decimal("0.200")
            + (Decimal(pcomp) / Decimal("10")) * Decimal("0.150")
            + ((Decimal(step_faces) / Decimal("80")) + (Decimal(dxf_entities) / Decimal("100")))
            * Decimal("0.100")
        )
        if score < Decimal("0.600"):
            derived_cosysmo = "LOW"
            raw_factor = Decimal("0.920")
        elif score < Decimal("1.250"):
            derived_cosysmo = "NOMINAL"
            raw_factor = Decimal("1.000")
        elif score < Decimal("2.200"):
            derived_cosysmo = "ELEVATED"
            raw_factor = Decimal("1.180")
        else:
            derived_cosysmo = "HIGH"
            raw_factor = Decimal("1.350")
        # Fine-grained factor bounded in [0.850, 1.650]
        feat_factor = min(Decimal("1.650"), max(Decimal("0.850"), raw_factor))

    return IDPPhysicalComplexityProfile(
        artifacts_analyzed=tuple(artifacts),
        artifact_hashes=hashes,
        fem_nodes_count=nodes,
        fem_elements_count=elems,
        cbush_joints_count=cbush,
        pcomp_laminates_count=pcomp,
        load_cases_count=load_cases,
        step_solids_count=step_solids,
        step_faces_count=step_faces,
        dxf_entities_count=dxf_entities,
        f06_has_gpwg=has_gpwg,
        f06_has_oload_spc=has_oload_spc,
        f06_has_fatal=has_fatal,
        f06_epsilon_max=str(eps_max_dec) if eps_max_dec is not None else None,
        f06_epsilon_exceeded=eps_exceeded,
        derived_cosysmo_complexity=derived_cosysmo,
        derived_idp_maturity=derived_maturity,
        idp_feature_complexity_factor=format_quantum(feat_factor, _Q3),
        complexity_index=format_quantum(score, _Q3),
        quality_findings=tuple(findings),
    )


def retrieve_nearest_historical_quotations(
    corpus: list[HistoricalQuotationRecord],
    *,
    archetype_id: str,
    country_code: str,
    cert_basis: str,
    material_family: str,
    cosysmo_complexity: str,
    idp_maturity: str,
    fem_nodes_count: int = 0,
    load_cases_count: int = 0,
    cbush_joints_count: int = 0,
    cad_drawings_count: int = 0,
    ply_count: int = 0,
    k: int = 3,
) -> list[dict[str, Any]]:
    """Deterministic weighted Decimal k-NN over 2,000+ historical quotations."""
    if not corpus or k <= 0:
        return []

    target_family = _ARCHETYPE_FAMILY_MAP.get(archetype_id, "STRESS")
    w_arch = Decimal("0.350")
    w_fam = Decimal("0.100")
    w_cert = Decimal("0.150")
    w_mat = Decimal("0.150")
    w_ctry = Decimal("0.100")
    w_idp = Decimal("0.050")
    w_cos = Decimal("0.050")
    w_num = Decimal("0.010")  # 5 numerical features x 0.01 = 0.050

    scored: list[tuple[Decimal, str, HistoricalQuotationRecord]] = []
    for rec in corpus:
        sim = _ZERO
        if rec.archetype_id == archetype_id:
            sim += w_arch
        if _ARCHETYPE_FAMILY_MAP.get(rec.archetype_id, "") == target_family:
            sim += w_fam
        if rec.cert_basis == cert_basis:
            sim += w_cert
        if rec.material_family == material_family:
            sim += w_mat
        if rec.country_code == country_code:
            sim += w_ctry
        if rec.idp_maturity == idp_maturity:
            sim += w_idp
        if rec.cosysmo_complexity == cosysmo_complexity:
            sim += w_cos

        for tv, rv, norm in (
            (fem_nodes_count, rec.fem_nodes_count, 50000),
            (load_cases_count, rec.load_cases_count, 100),
            (cbush_joints_count, rec.cbush_joints_count, 120),
            (cad_drawings_count, rec.cad_drawings_count, 40),
            (ply_count, rec.ply_count, 80),
        ):
            if tv == 0 and rv == 0:
                sim += w_num
            else:
                denom = max(norm, tv, rv, 1)
                closeness = _ONE - (Decimal(abs(tv - rv)) / Decimal(denom))
                if closeness > _ZERO:
                    sim += w_num * closeness

        scored.append((sim, rec.quote_id, rec))

    scored.sort(key=lambda item: (-item[0], item[1]))
    results: list[dict[str, Any]] = []
    for sim, _, rec in scored[:k]:
        q_h = Decimal(rec.quoted_hours)
        a_h = Decimal(rec.actual_burned_hours)
        overrun_pct = ((a_h - q_h) / q_h) * _HUNDRED
        row = asdict(rec)
        row["similarity_score"] = format_quantum(sim, _Q3)
        row["overrun_pct"] = format_quantum(overrun_pct, _Q2)
        results.append(row)
    return results


def run_historical_calibration_and_matching(
    *,
    archetype_id: str = "Q-STR-03",
    country_code: str = "EU_DEFAULT",
    cert_basis: str = "CS-29",
    material_family: str = "HYBRID_AL_CFRP",
    corpus_path: str | Path | None = None,
    records: list[dict[str, Any]] | None = None,
    synthetic_count: int = 2160,
    idp_attachments: dict[str, Any] | None = None,
    top_k: int = 3,
) -> dict[str, Any]:
    """Run unified bulk ingest, IDP physical inspection, PERT calibration & k-NN retrieval."""
    if records is not None:
        ing = ingest_historical_quotations(records)
        corpus = ing["records"]
        corpus_origin = ing["corpus_origin"]
        ingest_summary = {k: v for k, v in ing.items() if k != "records"}
    elif corpus_path is not None:
        ing = ingest_historical_quotations(corpus_path)
        corpus = ing["records"]
        corpus_origin = ing["corpus_origin"]
        ingest_summary = {k: v for k, v in ing.items() if k != "records"}
    else:
        corpus = generate_reference_historical_corpus(count=synthetic_count)
        corpus_origin = "SYNTHETIC_BENCHMARK_ASSUMPTION"
        ingest_summary = {
            "source": "reference_benchmark_generator",
            "corpus_origin": corpus_origin,
            "ingested_count": len(corpus),
            "rejected_count": 0,
        }

    idp_profile = extract_idp_physical_complexity(idp_attachments)
    calibration = calibrate_from_historical_corpus(
        corpus,
        archetype_id=archetype_id,
        country_code=country_code,
        idp_feature_factor=idp_profile.idp_feature_complexity_factor,
        corpus_origin=corpus_origin,
    )
    nearest = retrieve_nearest_historical_quotations(
        corpus,
        archetype_id=archetype_id,
        country_code=country_code,
        cert_basis=cert_basis,
        material_family=material_family,
        cosysmo_complexity=idp_profile.derived_cosysmo_complexity,
        idp_maturity=idp_profile.derived_idp_maturity,
        fem_nodes_count=idp_profile.fem_nodes_count,
        load_cases_count=idp_profile.load_cases_count,
        cbush_joints_count=idp_profile.cbush_joints_count,
        cad_drawings_count=idp_profile.dxf_entities_count,
        ply_count=idp_profile.pcomp_laminates_count,
        k=top_k,
    )
    return {
        "ingest_summary": ingest_summary,
        "idp_physical_extraction": asdict(idp_profile),
        "historical_calibration": calibration,
        "nearest_historical_quotes": nearest,
    }
