from __future__ import annotations

from decimal import Decimal

from evidence_calc.units import conversion_interval
from evidence_eval.__main__ import main
from evidence_eval.unit_bench import (
    DISCLAIMER,
    render_unit_bench_markdown,
    run_unit_bench,
)


def test_unit_bench_metrics_and_decimal_exactness() -> None:
    report = run_unit_bench()
    assert report["total_cases"] == 30
    assert report["passed"] == 30
    assert report["pass_rate"] == "1.000"
    assert report["pass_fraction"] == "30/30"
    assert report["float_used"] is False
    assert report["llm_numeric_violation"] == 0
    assert report["label"] == "ESTIMATE"
    assert report["disclaimer"] == DISCLAIMER
    assert report["pass_ci95"]["method"] == "wilson"

    # Verify exact Decimal intervals
    mm = conversion_interval("meter", "millimeter")
    assert isinstance(mm, Decimal)
    assert mm == Decimal("1000")
    assert conversion_interval("°C", "K") is None
    assert conversion_interval("degF", "K") is None


def test_unit_bench_markdown_and_cli() -> None:
    report = run_unit_bench()
    md = render_unit_bench_markdown(report)
    assert DISCLAIMER in md
    for label in ("ESTIMATE", "ASSUMPTION", "VERIFIED", "NOT_VERIFIED"):
        assert label in md
    assert main(["unit-bench"]) == 0
