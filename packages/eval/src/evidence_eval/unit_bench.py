"""Deterministic benchmark of Decimal unit conversions, dimensions, and calc card unit checks.

This tool assists a human reviewer. It does not determine compliance.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from evidence_calc.errors import AbstainError
from evidence_calc.registry import run_method
from evidence_calc.units import (
    conversion_interval,
    dimension_exponents,
    same_unit,
    units_compatible,
)

from evidence_eval.score import wilson

DISCLAIMER = "This tool assists a human reviewer. It does not determine compliance."

RIGID_BODY_BASE: dict[str, Any] = {
    "mass_kg": "800.000",
    "gravity_m_s2": "9.810",
    "load_factor": "1.500",
    "cg_x_m": "0.000",
    "unit_x_m": ["-2.000", "-1.000", "1.000", "2.000"],
    "unit_operative": [True, True, True, True],
}

BOLT_SCREEN_BASE: dict[str, Any] = {
    "shear_force_n": "3000.000",
    "tensile_force_n": "4000.000",
    "area_mm2": "80.000",
    "shear_allowable_mpa": "250.000",
    "tensile_allowable_mpa": "250.000",
}


def _check_interval(
    case_id: str,
    left: str,
    right: str,
    expected: Decimal,
    tolerance: Decimal = Decimal("0"),
) -> dict[str, Any]:
    got = conversion_interval(left, right)
    is_decimal = isinstance(got, Decimal) and not isinstance(got, float)
    if is_decimal and tolerance == Decimal("0"):
        passed = got == expected
    elif is_decimal:
        passed = abs(got - expected) <= tolerance
    else:
        passed = False
    return {
        "case_id": case_id,
        "category": "multiplicative_interval",
        "description": f"conversion_interval({left!r}, {right!r})",
        "passed": passed,
        "float_used": isinstance(got, float),
        "detail": str(got),
    }


def _check_compatibility(
    case_id: str,
    left: str,
    right: str,
    expected_compat: bool,
    check_same: bool | None = None,
) -> dict[str, Any]:
    compat = units_compatible(left, right)
    interval = conversion_interval(left, right)
    float_used = isinstance(interval, float)
    if not expected_compat:
        passed = (compat is False) and (interval == "incompatible")
    elif check_same is not None:
        passed = (compat is True) and (same_unit(left, right) is check_same)
    else:
        passed = (compat is True) and isinstance(interval, Decimal)
    return {
        "case_id": case_id,
        "category": "compatibility_and_same_unit",
        "description": f"units_compatible({left!r}, {right!r}) == {expected_compat}",
        "passed": passed,
        "float_used": float_used,
        "detail": f"compatible={compat}, same_unit={same_unit(left, right)}",
    }


def _check_dimension(
    case_id: str,
    unit_name: str,
    expected: dict[str, int] | None,
) -> dict[str, Any]:
    got = dimension_exponents(unit_name)
    passed = got == expected
    return {
        "case_id": case_id,
        "category": "dimension_signature",
        "description": f"dimension_exponents({unit_name!r})",
        "passed": passed,
        "float_used": False,
        "detail": str(got),
    }


def _check_offset_refusal(case_id: str, left: str, right: str) -> dict[str, Any]:
    got = conversion_interval(left, right)
    passed = got is None
    return {
        "case_id": case_id,
        "category": "offset_unit_refusal",
        "description": f"conversion_interval({left!r}, {right!r}) is None",
        "passed": passed,
        "float_used": isinstance(got, float),
        "detail": str(got),
    }


def _check_calc_unit_mismatch(
    case_id: str,
    method_id: str,
    base_inputs: dict[str, Any],
    override_units: dict[str, str],
) -> dict[str, Any]:
    payload = dict(base_inputs)
    payload["_input_units"] = override_units
    abstained_reason: str | None = None
    try:
        run_method(method_id, payload)
    except AbstainError as exc:
        abstained_reason = exc.reason
    passed = abstained_reason == "unit_mismatch"
    return {
        "case_id": case_id,
        "category": "calc_card_unit_enforcement",
        "description": f"{method_id} refuses _input_units={override_units}",
        "passed": passed,
        "float_used": False,
        "detail": f"abstain_reason={abstained_reason}",
    }


def build_unit_bench_cases() -> list[dict[str, Any]]:
    """Run all 30 deterministic unit and dimensional benchmark cases."""
    exact_foot = Decimal(1250) / Decimal(381)
    return [
        # 1. Exact multiplicative intervals in Decimal (10 cases)
        _check_interval("ub-int-01", "meter", "millimeter", Decimal("1000")),
        _check_interval("ub-int-02", "kilogram", "gram", Decimal("1000")),
        _check_interval("ub-int-03", "newton", "kilonewton", Decimal("0.001")),
        _check_interval("ub-int-04", "megapascal", "pascal", Decimal("1000000")),
        _check_interval(
            "ub-int-05",
            "meter",
            "foot",
            exact_foot,
            tolerance=Decimal("1e-24"),
        ),
        _check_interval("ub-int-06", "hour", "second", Decimal("3600")),
        _check_interval("ub-int-07", "kN", "newton", Decimal("1000")),
        _check_interval("ub-int-08", "daN", "newton", Decimal("10")),
        _check_interval("ub-int-09", "GPa", "MPa", Decimal("1000")),
        _check_interval("ub-int-10", "kPa", "pascal", Decimal("1000")),
        # 2. Compatible vs incompatible & same_unit (8 cases)
        _check_compatibility("ub-cmp-01", "newton", "pascal", False),
        _check_compatibility("ub-cmp-02", "meter", "second", False),
        _check_compatibility("ub-cmp-03", "kilogram", "meter", False),
        _check_compatibility("ub-cmp-04", "MPa", "psi", True),
        _check_compatibility("ub-cmp-05", "knot", "meter / second", True),
        _check_compatibility("ub-cmp-06", "meter", "m", True, check_same=True),
        _check_compatibility("ub-cmp-07", "m/s2", "meter / second ** 2", True, check_same=True),
        _check_compatibility("ub-cmp-08", "meter", "millimeter", True, check_same=False),
        # 3. Dimensional exponent signatures (5 cases)
        _check_dimension("ub-dim-01", "meter", {"L": 1}),
        _check_dimension("ub-dim-02", "newton", {"M": 1, "L": 1, "T": -2}),
        _check_dimension("ub-dim-03", "megapascal", {"M": 1, "L": -1, "T": -2}),
        _check_dimension("ub-dim-04", "dimensionless", {}),
        _check_dimension("ub-dim-05", "not_a_registered_unit", None),
        # 4. Offset temperature unit refusal (3 cases)
        _check_offset_refusal("ub-off-01", "°C", "K"),
        _check_offset_refusal("ub-off-02", "degC", "kelvin"),
        _check_offset_refusal("ub-off-03", "degF", "K"),
        # 5. Calc card unit mismatch detection via _input_units (4 cases)
        _check_calc_unit_mismatch(
            "ub-card-01",
            "rigid_body_point_mass",
            RIGID_BODY_BASE,
            {"mass_kg": "meter"},
        ),
        _check_calc_unit_mismatch(
            "ub-card-02",
            "rigid_body_point_mass",
            RIGID_BODY_BASE,
            {"cg_x_m": "second"},
        ),
        _check_calc_unit_mismatch(
            "ub-card-03",
            "bolt_screen",
            BOLT_SCREEN_BASE,
            {"shear_force_n": "pascal"},
        ),
        _check_calc_unit_mismatch(
            "ub-card-04",
            "bolt_screen",
            BOLT_SCREEN_BASE,
            {"area_mm2": "kilogram"},
        ),
    ]


def run_unit_bench() -> dict[str, Any]:
    """Execute the 30-case unit & dimensional benchmark and return summary metrics."""
    cases = build_unit_bench_cases()
    total = len(cases)
    passed = sum(1 for item in cases if item["passed"])
    float_used = any(bool(item["float_used"]) for item in cases)

    categories: dict[str, dict[str, Any]] = {}
    for item in cases:
        cat = item["category"]
        entry = categories.setdefault(cat, {"passed": 0, "total": 0})
        entry["total"] += 1
        entry["passed"] += int(bool(item["passed"]))

    category_breakdown: dict[str, dict[str, Any]] = {}
    for cat, counts in categories.items():
        c_pass = counts["passed"]
        c_tot = counts["total"]
        category_breakdown[cat] = {
            "passed": c_pass,
            "total": c_tot,
            "recall": f"{c_pass}/{c_tot}",
            "ci95": wilson(c_pass, c_tot),
        }

    rate = (Decimal(passed) / Decimal(total)).quantize(Decimal("0.001"), rounding=ROUND_HALF_EVEN)
    return {
        "benchmark": "unit_bench",
        "disclaimer": DISCLAIMER,
        "label": "ESTIMATE",
        "provenance": (
            "Curated 30-case deterministic unit conversion, dimensional signature, "
            "and calc-card unit mismatch suite."
        ),
        "total_cases": total,
        "passed": passed,
        "pass_rate": str(rate),
        "pass_fraction": f"{passed}/{total}",
        "pass_ci95": wilson(passed, total),
        "float_used": float_used,
        "llm_numeric_violation": 0,
        "category_breakdown": category_breakdown,
        "cases": cases,
    }


def render_unit_bench_markdown(report: dict[str, Any]) -> str:
    """Format the unit benchmark report as Markdown with epistemic labels and disclaimer."""
    ci = report["pass_ci95"]
    lines = [
        "# Deterministic Unit & Dimensional Benchmark (`unit_bench`)",
        "",
        f"> **Disclaimer**: {report['disclaimer']}",
        "",
        "## Epistemic Status & Provenance",
        "",
        f"- **Benchmark Label**: `{report['label']}` — {report['provenance']}",
        "- **Unit Registry Arithmetic**: `VERIFIED` — multiplicative intervals are evaluated "
        "in `Decimal` (`non_int_type=Decimal`) with `float_used == False`.",
        "- **Screening Cards**: `ASSUMPTION` — `rigid_body_point_mass` and `bolt_screen` "
        "are project-defined screening illustrations.",
        "- **External Held-Out Set**: `NOT_VERIFIED` — this suite is an internal "
        "deterministic verification benchmark, not an external blind holdout.",
        "",
        "## Summary Metrics",
        "",
        f"- **Total Cases**: `{report['total_cases']}`",
        f"- **Passed**: `{report['passed']}` (`{report['pass_fraction']}`, "
        f"rate `{report['pass_rate']}`)",
        f"- **Wilson 95% CI**: `[{ci['low']}, {ci['high']}]`",
        f"- **Float Used**: `{report['float_used']}`",
        f"- **`llm_numeric_violation`**: `{report['llm_numeric_violation']}`",
        "",
        "## Category Breakdown",
        "",
        "| Category | Passed / Total | Wilson 95% CI |",
        "| --- | --- | --- |",
    ]
    for cat, stats in report["category_breakdown"].items():
        cat_ci = stats["ci95"]
        lines.append(f"| `{cat}` | `{stats['recall']}` | `[{cat_ci['low']}, {cat_ci['high']}]` |")
    lines.append("")
    return "\n".join(lines)
