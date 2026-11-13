from __future__ import annotations

import json
from typing import Any

import httpx
from evidence_eval.agent_live_bench import LIVE_EVAL_CASES, evaluate_gateway
from evidence_kernel.constrained import OutlinesGuidedGateway
from evidence_kernel.gateway import (
    BudgetedGateway,
    FixtureGateway,
    HybridAgentRouter,
    OllamaEdgeGateway,
    OpenAICompatibleGateway,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict[str, Any]:
        return self._payload


def test_live_bench_fixture_passes_zero_leaks() -> None:
    report = evaluate_gateway(
        lambda: BudgetedGateway(
            OutlinesGuidedGateway(FixtureGateway("happy"), max_schema_retries=1),
            max_turns=5,
        ),
        label="fixture-constrained",
    )
    assert report["total_cases"] == len(LIVE_EVAL_CASES)
    assert report["expected_outcome_rate"] == 1.0
    assert report["schema_valid_rate"] == 1.0
    assert report["citation_accuracy"] == 1.0
    assert report["ledger_verified_rate"] == 1.0
    assert report["stray_number_leaks"] == 0


def test_live_bench_measures_slm_recovery_via_fsm_and_whitespace_spans(monkeypatch) -> None:
    """Measure OutlinesGuidedGateway + Hybrid escalation accuracy gain on noisy SLM."""

    def slm_and_api_post(
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float = 3.0,
    ):
        del headers, timeout
        sys_prompt = json["messages"][0]["content"]
        ctx = json_loads(json["messages"][-1]["content"])
        quote = ctx.get("quotation", "")
        normalized_quote = " ".join(quote.split())
        decimals = ctx.get("allowed_decimals", [])

        if url.endswith("/api/chat"):
            # Simulated noisy Edge SLM: markdown fences, normalized whitespace quotes,
            # extra disallowed field names, and schema drift resolved via local FSM + escalation.
            if "Reader" in sys_prompt:
                body = {
                    "requirements": [
                        {
                            "id": "ITEM-1",
                            "label": " not_verified ",
                            "quotation": normalized_quote,
                            "span_start": "0",
                            "span_end": str(len(normalized_quote)),
                            "slm_debug": "prune-me",
                        }
                    ]
                }
                return _FakeResponse(
                    {
                        "message": {
                            "content": f"<think>trace</think>\n```json\n{json_dumps(body)}\n```"
                        },
                        "eval_count": 21,
                    }
                )
            # Scribe omits schema-disallowed noise on edge
            summary = (
                f"Stored value {decimals[0]} recorded."
                if decimals
                else "No stored numeric value is available."
            )
            return _FakeResponse(
                {"message": {"content": json_dumps({"paragraph": summary})}, "eval_count": 14}
            )

        # Fallback API model handles checker/refuter cleanly
        if "Checker" in sys_prompt:
            return _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json_dumps(
                                    {
                                        "requirements": [{"id": "ITEM-1", "label": "NOT_VERIFIED"}],
                                        "narrative": f"Verified {decimals[0]}."
                                        if decimals
                                        else "Clean.",
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"completion_tokens": 12},
                }
            )
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json_dumps(
                                {
                                    "attack": "miss",
                                    "reason": "verified citation and calc",
                                    "evidence_span": ctx.get("source_text", quote),
                                }
                            )
                        }
                    }
                ],
                "usage": {"completion_tokens": 12},
            }
        )

    json_loads = json.loads
    json_dumps = json.dumps
    monkeypatch.setattr(httpx, "post", slm_and_api_post)

    # 1. Baseline unconstrained OllamaEdgeGateway (no FSM repair, abstains on schema drift)
    raw_edge_report = evaluate_gateway(
        lambda: BudgetedGateway(
            OllamaEdgeGateway("http://127.0.0.1:11434", model="qwen2.5:3b"),
            max_turns=5,
        ),
        label="raw-edge-unconstrained",
    )
    assert raw_edge_report["citation_accuracy"] == 0.0

    # 2. Improved stack (HybridAgentRouter + OutlinesGuidedGateway + normalized real-offset spans)
    improved_report = evaluate_gateway(
        lambda: BudgetedGateway(
            OutlinesGuidedGateway(
                HybridAgentRouter(
                    edge_gateway=OllamaEdgeGateway("http://127.0.0.1:11434", model="qwen2.5:3b"),
                    api_gateway=OpenAICompatibleGateway(
                        "https://api.example.local/v1", model="remote-verifier"
                    ),
                ),
                max_schema_retries=2,
            ),
            max_turns=5,
        ),
        label="hybrid-edge-constrained",
    )
    assert improved_report["expected_outcome_rate"] == 1.0
    assert improved_report["schema_valid_rate"] == 1.0
    assert improved_report["citation_accuracy"] == 1.0
    assert improved_report["stray_number_leaks"] == 0
    assert improved_report["ledger_verified_rate"] == 1.0
