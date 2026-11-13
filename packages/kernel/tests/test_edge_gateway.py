from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from evidence_kernel.edge import (
    EDGE_PRESETS,
    compact_blocks_for_edge,
    edge_deployment_recipe,
    preflight_edge_screening,
)
from evidence_kernel.gateway import (
    Completion,
    FixtureGateway,
    HybridAgentRouter,
    OllamaEdgeGateway,
    OpenAICompatibleGateway,
    describe_agent_runtime,
    extract_json_object,
    gateway_from_env,
    probe_gateway_health,
)
from evidence_kernel.ledger import Ledger
from evidence_kernel.supervisor import CaseAbstain, CaseSpec, invoke_single_agent, run_case


class _FakeHttpxResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict[str, Any]:
        return self._payload


def test_extract_json_object_handles_think_and_fences() -> None:
    raw = '<think>reasoning...</think>\n```json\n{"paragraph": "Valid output."}\n```'
    assert extract_json_object(raw) == {"paragraph": "Valid output."}
    assert extract_json_object("no json here") is None


def test_edge_compaction_and_preflight_preserve_spans() -> None:
    blocks = [
        {
            "text": "SL-1.REQ-01 Maximum thrust shall not exceed 9800.000 N.",
            "span_start": 0,
            "span_end": 53,
        },
        {
            "text": "General background note without requirement numbers.",
            "span_start": 54,
            "span_end": 106,
        },
        {
            "text": "SL-1.REQ-02 Factor of safety 1.500 minimum applies.",
            "span_start": 107,
            "span_end": 157,
        },
    ]
    compacted = compact_blocks_for_edge(blocks, max_chars=120)
    assert len(compacted) == 2
    assert compacted[0]["text"].startswith("SL-1.REQ-01")
    assert compacted[1]["text"].startswith("SL-1.REQ-02")

    report = preflight_edge_screening(blocks, preset_id="offline-wasm-webgpu")
    assert report["preset"]["preset_id"] == "offline-wasm-webgpu"
    assert report["signal_block_count"] == 2
    assert "laptop-cpu-16gb" in EDGE_PRESETS
    assert edge_deployment_recipe(runtime_kind="ollama")["env"]["EDGE_MODEL_PROVIDER"] == "ollama"


def test_openai_provider_dialects_and_bearer_auth(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float):
        captured.append({"url": url, "json": json, "headers": headers})
        return _FakeHttpxResponse(
            {
                "choices": [{"message": {"content": '{"paragraph": "Stored 9800.000 N."}'}}],
                "usage": {"completion_tokens": 9},
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    schema = {
        "type": "object",
        "required": ["paragraph"],
        "properties": {"paragraph": {"type": "string"}},
    }

    openai_gw = OpenAICompatibleGateway(
        "https://api.example.local/v1",
        model="gpt-demo",
        api_key="bearer-demo-value",
        provider="openai",
    )
    res_openai = openai_gw.complete("scribe", [{"role": "user", "content": "{}"}], schema)
    assert res_openai.output == {"paragraph": "Stored 9800.000 N."}
    assert res_openai.provider == "openai"
    assert res_openai.model_id == "gpt-demo"
    assert captured[0]["headers"]["Authorization"] == "Bearer bearer-demo-value"
    assert captured[0]["json"]["messages"][0]["role"] == "system"
    assert "guided_json" not in captured[0]["json"]

    llama_gw = OpenAICompatibleGateway(
        "http://127.0.0.1:8080/v1",
        model="qwen-edge",
        provider="llamacpp",
    )
    res_llama = llama_gw.complete("scribe", [{"role": "user", "content": "{}"}], schema)
    assert res_llama.output == {"paragraph": "Stored 9800.000 N."}
    assert captured[1]["json"]["response_format"] == {"type": "json_object", "schema": schema}


def test_ollama_edge_gateway_parses_fenced_json(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, *, json: dict[str, Any], timeout: float):
        captured["url"] = url
        captured["json"] = json
        return _FakeHttpxResponse(
            {
                "message": {"content": '```json\n{"paragraph": "Edge summary."}\n```'},
                "eval_count": 7,
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    gw = OllamaEdgeGateway("http://127.0.0.1:11434", model="qwen2.5:3b", num_ctx=4096)
    res = gw.complete(
        "scribe",
        [{"role": "user", "content": "{}"}],
        {
            "type": "object",
            "required": ["paragraph"],
            "properties": {"paragraph": {"type": "string"}},
        },
    )
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["json"]["options"]["num_ctx"] == 4096
    assert res.output == {"paragraph": "Edge summary."}
    assert res.provider == "ollama_edge"
    assert res.routed_via == "edge_local"
    assert res.output_tokens == 7


def test_hybrid_router_splits_edge_api_and_escalates_only_safe_errors() -> None:
    class StubEdge:
        def __init__(self, res: Completion) -> None:
            self.res = res
            self.calls = 0

        def complete(
            self, agent_id: str, messages: list[dict[str, str]], schema: Any
        ) -> Completion:
            self.calls += 1
            return self.res

    class StubApi:
        def __init__(self, res: Completion) -> None:
            self.res = res
            self.calls = 0

        def complete(
            self, agent_id: str, messages: list[dict[str, str]], schema: Any
        ) -> Completion:
            self.calls += 1
            return self.res

    edge_ok = StubEdge(Completion({"paragraph": "ok"}, None, "0", "h1", provider="ollama_edge"))
    api_ok = StubApi(Completion({"attack": "miss"}, None, "0", "h2", provider="openai"))
    router = HybridAgentRouter(edge_gateway=edge_ok, api_gateway=api_ok)

    r_scribe = router.complete("scribe", [{"role": "user", "content": "{}"}], None)
    assert r_scribe.routed_via == "hybrid_edge"
    assert edge_ok.calls == 1
    assert api_ok.calls == 0

    r_refuter = router.complete("refuter", [{"role": "user", "content": "{}"}], None)
    assert r_refuter.routed_via == "hybrid_api"
    assert api_ok.calls == 1

    # Schema/timeout failure on edge escalates to API
    edge_bad = StubEdge(Completion(None, "schema_invalid", "0", "h1", provider="ollama_edge"))
    api_recover = StubApi(
        Completion({"paragraph": "recovered"}, None, "0", "h1", provider="openai")
    )
    router_esc = HybridAgentRouter(edge_gateway=edge_bad, api_gateway=api_recover)
    r_esc = router_esc.complete("scribe", [{"role": "user", "content": "{}"}], None)
    assert r_esc.escalated is True
    assert r_esc.routed_via == "hybrid_escalated"
    assert r_esc.output == {"paragraph": "recovered"}

    # Stray number abstention MUST NOT escalate
    edge_leak = StubEdge(Completion(None, "stray_number", "0", "h1", provider="ollama_edge"))
    api_unused = StubApi(Completion({"paragraph": "unused"}, None, "0", "h1", provider="openai"))
    router_no_esc = HybridAgentRouter(edge_gateway=edge_leak, api_gateway=api_unused)
    r_blocked = router_no_esc.complete("scribe", [{"role": "user", "content": "{}"}], None)
    assert r_blocked.abstain_reason == "stray_number"
    assert api_unused.calls == 0


def test_runtime_descriptor_masks_secret_and_probe_works(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_BASE_URL", "https://user:secret@api.example.local/v1")
    monkeypatch.setenv("MODEL_API_KEY", "placeholder-token-value")
    monkeypatch.setenv("EDGE_MODEL_URL", "http://127.0.0.1:11434")

    desc = describe_agent_runtime()
    assert desc["active_mode"] == "hybrid"
    assert desc["api_backend"]["api_key_present"] is True
    assert "placeholder-token-value" not in json.dumps(desc)
    assert desc["edge_backend"]["configured"] is True

    gw = gateway_from_env(runtime_mode="hybrid")
    assert isinstance(gw.inner.inner, HybridAgentRouter)

    def fake_get(url: str, *, headers: dict[str, str] | None = None, timeout: float = 3.0):
        if url.endswith("/models"):
            return _FakeHttpxResponse({"data": [{"id": "api-model-1"}]})
        return _FakeHttpxResponse({"models": [{"name": "qwen2.5:3b"}]})

    monkeypatch.setattr(httpx, "get", fake_get)
    probed = probe_gateway_health(target="all")
    assert probed["api"]["reachable"] is True
    assert probed["api"]["models"] == ["api-model-1"]
    assert probed["edge"]["reachable"] is True
    assert probed["edge"]["models"] == ["qwen2.5:3b"]


def test_invoke_single_agent_and_supervisor_telemetry(tmp_path: Path) -> None:
    gw = gateway_from_env(runtime_mode="fixture")
    text = "SL-1.REQ-01 Design load requirement."
    res = invoke_single_agent(
        gw,
        "reader",
        {
            "quotation": text,
            "span_start": "0",
            "span_end": str(len(text)),
            "source_text": text,
            "allowed_decimals": [],
        },
    )
    assert res["output"]["requirements"][0]["id"] == "ITEM-1"
    assert res["telemetry"]["agent_id"] == "reader"
    assert res["telemetry"]["provider"] == "fixture"

    try:
        invoke_single_agent(gw, "unknown_agent", {"source_text": "hello"})
        raise AssertionError("expected CaseAbstain")
    except CaseAbstain as exc:
        assert exc.reason == "unknown_agent"

    ledger = Ledger(tmp_path / "edge_sup.sqlite3", "demo")
    outcome = run_case(
        ledger,
        gateway_from_env(runtime_mode="fixture", max_turns=5),
        CaseSpec(
            tenant_id="demo",
            actor_id="author",
            created_at="2026-11-12T10:00:00Z",
            blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
            use_decision_gate=True,
            compact_for_edge=True,
            edge_preset="laptop-cpu-16gb",
        ),
    )
    assert outcome.envelope["confidence"] == "draft"
    assert len(outcome.agent_telemetry) == 5


def test_gateway_from_env_fails_closed_when_live_mode_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("EDGE_MODEL_URL", raising=False)

    for mode, expected_reason in (
        ("api", "api_not_configured"),
        ("edge", "edge_not_configured"),
        ("hybrid", "hybrid_not_configured"),
        ("nonexistent_mode", "invalid_runtime_mode"),
    ):
        gw = gateway_from_env(runtime_mode=mode)
        done = gw.complete("reader", [{"role": "user", "content": "{}"}], None)
        assert done.abstained is True
        assert done.abstain_reason == expected_reason

    auto_gw = gateway_from_env(runtime_mode="auto")
    auto_done = auto_gw.complete(
        "reader",
        [{"role": "user", "content": json.dumps({"quotation": "Alpha"})}],
        None,
    )
    assert auto_done.abstained is False
    assert auto_done.provider == "fixture"


def test_hybrid_router_resolves_decision_gate_and_live_skips_cleanly(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_post(
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: float = 3.0,
    ):
        del headers, timeout
        messages = json["messages"]
        sys_text = messages[0]["content"]
        ctx = json_loads(messages[-1]["content"])
        quote = ctx.get("quotation", "")
        if "Reader" in sys_text:
            body = {
                "requirements": [
                    {
                        "id": "ITEM-1",
                        "label": "NOT_VERIFIED",
                        "quotation": quote,
                        "span_start": "0",
                        "span_end": str(len(quote)),
                    }
                ]
            }
        elif "Checker" in sys_text:
            body = {
                "requirements": [{"id": "ITEM-1", "label": "NOT_VERIFIED"}],
                "narrative": "Checked span cleanly.",
            }
        elif "Refuter" in sys_text:
            body = {
                "attack": "miss",
                "reason": "verified against source text",
                "evidence_span": ctx.get("source_text", quote),
            }
        else:
            body = {"paragraph": "No stored numeric value is available."}
        import json as _json

        if url.endswith("/api/chat"):
            return _FakeHttpxResponse({"message": {"content": _json.dumps(body)}, "eval_count": 12})
        return _FakeHttpxResponse(
            {
                "choices": [{"message": {"content": _json.dumps(body)}}],
                "usage": {"completion_tokens": 12},
            }
        )

    json_loads = json.loads
    monkeypatch.setattr(httpx, "post", fake_post)

    # 1) HybridAgentRouter resolves decision_gate deterministically
    monkeypatch.setenv("MODEL_BASE_URL", "https://api.example.local/v1")
    monkeypatch.setenv("EDGE_MODEL_URL", "http://127.0.0.1:11434")
    hybrid_gw = gateway_from_env(runtime_mode="hybrid", max_turns=5)
    ledger_h = Ledger(tmp_path / "hybrid_gate.sqlite3", "demo")
    text = "SL-1.REQ-01 Primary structural frame check."
    out_h = run_case(
        ledger_h,
        hybrid_gw,
        CaseSpec(
            tenant_id="demo",
            actor_id="author",
            created_at="2026-11-13T12:00:00Z",
            blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
            use_decision_gate=True,
        ),
    )
    assert out_h.envelope["confidence"] == "draft"
    assert [t["agent_id"] for t in out_h.agent_telemetry] == [
        "decision_gate",
        "reader",
        "checker",
        "refuter",
        "scribe",
    ]
    assert out_h.agent_telemetry[0]["routed_via"] == "deterministic_gate"

    # 2) Direct OpenAICompatibleGateway keeps ADR-021 guard; supervisor skips decision_gate cleanly
    direct_api = OpenAICompatibleGateway("https://api.example.local/v1", model="gpt-demo")
    direct_gate = direct_api.complete("decision_gate", [{"role": "user", "content": "{}"}], None)
    assert direct_gate.abstain_reason == "decision_gate_fixture_only"

    monkeypatch.delenv("EDGE_MODEL_URL", raising=False)
    api_gw = gateway_from_env(runtime_mode="api", max_turns=5)
    ledger_a = Ledger(tmp_path / "api_gate.sqlite3", "demo")
    out_a = run_case(
        ledger_a,
        api_gw,
        CaseSpec(
            tenant_id="demo",
            actor_id="author",
            created_at="2026-11-13T12:00:00Z",
            blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
            use_decision_gate=True,
        ),
    )
    assert out_a.envelope["confidence"] == "draft"
    assert [t["agent_id"] for t in out_a.agent_telemetry] == [
        "decision_gate",
        "reader",
        "checker",
        "refuter",
        "scribe",
    ]


def test_async_httpx_acomplete_and_astream_case(tmp_path: Path) -> None:
    import asyncio

    from evidence_kernel.constrained import OutlinesGuidedGateway
    from evidence_kernel.gateway import BudgetedGateway
    from evidence_kernel.supervisor import arun_case, astream_case

    async def _run_async() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            sys_text = payload["messages"][0]["content"]
            ctx = json.loads(payload["messages"][-1]["content"])
            quote = ctx.get("quotation", "")
            if "Reader" in sys_text:
                out = {
                    "requirements": [
                        {
                            "id": "ITEM-1",
                            "label": "NOT_VERIFIED",
                            "quotation": quote,
                            "span_start": "0",
                            "span_end": str(len(quote)),
                        }
                    ],
                    "extra_noise": "pruned_by_fsm",
                }
            elif "Checker" in sys_text:
                out = {
                    "requirements": [{"id": "ITEM-1", "label": "NOT_VERIFIED"}],
                    "narrative": "Async checker clean.",
                }
            elif "Refuter" in sys_text:
                out = {
                    "attack": "miss",
                    "reason": "verified",
                    "evidence_span": ctx.get("source_text", quote),
                }
            else:
                out = {"paragraph": "Async verified summary without invented values."}

            if request.url.path.endswith("/api/chat"):
                return httpx.Response(
                    200, json={"message": {"content": json.dumps(out)}, "eval_count": 9}
                )
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(out)}}],
                    "usage": {"completion_tokens": 9},
                },
            )

        transport = httpx.MockTransport(handler)
        router = HybridAgentRouter(
            edge_gateway=OllamaEdgeGateway("http://edge.mock", model="qwen2.5:3b"),
            api_gateway=OpenAICompatibleGateway("https://api.mock/v1", model="remote-demo"),
        )
        async with httpx.AsyncClient(transport=transport) as client:
            res_edge = await router.acomplete(
                "scribe",
                [{"role": "user", "content": "{}"}],
                {
                    "type": "object",
                    "required": ["paragraph"],
                    "properties": {"paragraph": {"type": "string"}},
                },
                client=client,
            )
            assert res_edge.output == {
                "paragraph": "Async verified summary without invented values."
            }
            assert res_edge.routed_via == "hybrid_edge"

        # Stream full case asynchronously with OutlinesGuidedGateway + BudgetedGateway
        ledger = Ledger(tmp_path / "async_stream.sqlite3", "demo")
        gw = BudgetedGateway(
            OutlinesGuidedGateway(FixtureGateway("happy"), max_schema_retries=1),
            max_turns=5,
        )
        text = "SL-1.REQ-09 Async SSE verification check."
        events: list[dict[str, Any]] = []
        async for ev in astream_case(
            ledger,
            gw,
            CaseSpec(
                tenant_id="demo",
                actor_id="author",
                created_at="2026-11-13T12:00:00Z",
                blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
                use_decision_gate=True,
            ),
        ):
            events.append(ev)

        ev_types = [e["event"] for e in events]
        assert ev_types == [
            "stage",
            "agent_turn",
            "agent_turn",
            "calc",
            "agent_turn",
            "agent_turn",
            "agent_turn",
            "done",
        ]
        assert events[-1]["data"]["envelope"]["confidence"] == "draft"
        ledger2 = Ledger(tmp_path / "async_run.sqlite3", "demo")
        outcome = await arun_case(
            ledger2,
            gateway_from_env(runtime_mode="fixture", max_turns=5),
            CaseSpec(
                tenant_id="demo",
                actor_id="author",
                created_at="2026-11-13T12:00:00Z",
                blocks=[{"text": text, "span_start": 0, "span_end": len(text)}],
                use_decision_gate=True,
            ),
        )
        assert outcome.envelope["confidence"] == "draft"
        assert ledger2.verify()

    asyncio.run(_run_async())
