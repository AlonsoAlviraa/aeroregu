from __future__ import annotations

from evidence_eval.__main__ import main
from evidence_eval.agent_bench import (
    CATEGORIES,
    DISCLAIMER,
    render_agent_bench_markdown,
    run_agent_bench,
)


def test_agent_bench_metrics_and_gates() -> None:
    report = run_agent_bench()
    assert report["total_cases"] == 24
    assert report["clean_cases"] == 4
    assert report["adversarial_cases"] == 20
    assert report["beats_no_agent"] is True
    assert report["beats_single_llm"] is True
    assert report["ledger_verified"] is True
    assert report["label"] == "ESTIMATE"
    assert report["disclaimer"] == DISCLAIMER

    ma = report["multi_agent"]
    na = report["no_agent"]
    sl = report["single_llm"]

    assert ma["clean_accept_recall"] == "4/4"
    assert ma["adversarial_catch_recall"] == "20/20"
    assert ma["overall_correct"] == "24/24"
    assert ma["false_alarms"] == "0/4"
    assert ma["llm_numeric_violation"] == 0

    assert na["clean_accept_recall"] == "4/4"
    assert na["adversarial_catch_recall"] == "0/20"
    assert na["overall_correct"] == "4/24"

    assert sl["clean_accept_recall"] == "4/4"
    assert sl["adversarial_catch_recall"] == "0/20"
    assert sl["overall_correct"] == "4/24"
    assert sl["llm_numeric_violation"] > 0

    for cat in CATEGORIES:
        assert ma["per_category_recall"][cat]["recall"] == "4/4"
        assert ma["per_category_recall"][cat]["ci95"]["method"] == "wilson"


def test_agent_bench_markdown_and_cli() -> None:
    report = run_agent_bench()
    md = render_agent_bench_markdown(report)
    assert DISCLAIMER in md
    for label in ("ESTIMATE", "ASSUMPTION", "VERIFIED", "NOT_VERIFIED"):
        assert label in md
    assert main(["agent-bench"]) == 0
