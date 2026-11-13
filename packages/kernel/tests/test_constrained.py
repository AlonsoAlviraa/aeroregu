from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from evidence_kernel.constrained import OutlinesGuidedGateway, SchemaFSM
from evidence_kernel.gateway import (
    Completion,
    FixtureGateway,
    OpenAICompatibleGateway,
    gateway_from_env,
)

TEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["requirements"],
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "label"],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"enum": ["VERIFIED", "PARTIAL", "NOT_VERIFIED"]},
                },
            },
        }
    },
}


class MockInnerGateway:
    def __init__(self, raw_output: Any) -> None:
        self.raw_output = raw_output

    def complete(
        self, agent_id: str, messages: list[dict[str, str]], schema: dict[str, Any] | None
    ) -> Completion:
        return Completion(self.raw_output, None, "0", "mockhash", 10, 10)


def test_schema_fsm_validates_clean() -> None:
    fsm = SchemaFSM(TEST_SCHEMA)
    clean = {"requirements": [{"id": "ITEM-1", "label": "VERIFIED"}]}
    assert fsm.is_valid(clean)
    assert fsm.validate(clean) == []


def test_schema_fsm_guide_repairs_extra_keys_and_enum_casing() -> None:
    fsm = SchemaFSM(TEST_SCHEMA)
    drifted = {
        "requirements": [{"id": "ITEM-1", "label": "verified", "extra_debug_note": "ignore"}],
        "model_commentary": "Here is the extraction",
    }
    assert not fsm.is_valid(drifted)
    repaired = fsm.guide_repair(drifted, set())
    assert repaired is not None
    assert fsm.is_valid(repaired)
    assert repaired == {"requirements": [{"id": "ITEM-1", "label": "VERIFIED"}]}


def test_schema_fsm_rejects_unrepairable_structure() -> None:
    fsm = SchemaFSM(TEST_SCHEMA)
    bad = {"unexpected": "bad"}
    assert fsm.guide_repair(bad, set()) is None


def test_schema_fsm_rejects_numeric_injection() -> None:
    fsm = SchemaFSM(TEST_SCHEMA)
    leaked = {
        "requirements": [{"id": "ITEM-1", "label": "VERIFIED"}],
        "leaked_number": "9.999",
    }
    # 9.999 is not in allowed_decimals
    assert fsm.guide_repair(leaked, {"1.000"}) is None


def test_outlines_guided_gateway_cleans_drift() -> None:
    drifted = {
        "requirements": [{"id": "ITEM-1", "label": "verified", "debug": True}],
        "unauthorized_wrapper": True,
    }
    inner = MockInnerGateway(drifted)
    guided = OutlinesGuidedGateway(inner)

    res = guided.complete("reader", [{"role": "user", "content": "{}"}], TEST_SCHEMA)
    assert res.output == {"requirements": [{"id": "ITEM-1", "label": "VERIFIED"}]}
    assert res.abstain_reason is None
    assert guided.repaired_calls == 1
    assert guided.guided_clean_calls == 0


def test_outlines_guided_gateway_rejects_irrecoverable_bad_schema() -> None:
    inner = MockInnerGateway({"irrelevant": 123})
    guided = OutlinesGuidedGateway(inner)

    res = guided.complete("reader", [{"role": "user", "content": "{}"}], TEST_SCHEMA)
    assert res.output is None
    assert res.abstain_reason == "schema_invalid"
    assert guided.rejected_calls == 1


def test_gateway_from_env_constrained(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    gw = gateway_from_env(constrained=True)
    assert isinstance(gw.inner, OutlinesGuidedGateway)
    assert isinstance(gw.inner.inner, FixtureGateway)


def test_openai_gateway_sends_response_format_and_guided_json() -> None:
    captured: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            captured.update(json.loads(body))
            content = json.dumps({"paragraph": "Test output."})
            payload = json.dumps(
                {"choices": [{"message": {"content": content}}], "usage": {"completion_tokens": 5}}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        schema = {
            "type": "object",
            "required": ["paragraph"],
            "properties": {"paragraph": {"type": "string"}},
        }
        gw = OpenAICompatibleGateway(f"http://{host}:{port}", timeout_s=2)
        done = gw.complete("scribe", [{"role": "user", "content": "{}"}], schema)
        assert done.output == {"paragraph": "Test output."}
        assert "response_format" in captured
        assert captured["response_format"]["type"] == "json_schema"
        assert captured["response_format"]["json_schema"]["strict"] is True
        assert captured["guided_json"] == schema
    finally:
        server.shutdown()
        server.server_close()


def test_outlines_guided_gateway_bounded_retry_recovers_and_exhausts() -> None:
    class SequenceGateway:
        def __init__(self, responses: list[Any]) -> None:
            self.responses = list(responses)
            self.calls = 0

        def complete(
            self, agent_id: str, messages: list[dict[str, str]], schema: dict[str, Any] | None
        ) -> Completion:
            self.calls += 1
            out = self.responses.pop(0)
            return Completion(out, None, "0", f"hash-{self.calls}", 10, 10)

    inner = SequenceGateway(
        [
            {"bad": "first"},
            {"requirements": [{"id": "ITEM-2", "label": "VERIFIED"}]},
        ]
    )
    guided = OutlinesGuidedGateway(inner, max_schema_retries=2)
    res = guided.complete("reader", [{"role": "user", "content": "{}"}], TEST_SCHEMA)
    assert res.abstain_reason is None
    assert res.output == {"requirements": [{"id": "ITEM-2", "label": "VERIFIED"}]}
    assert inner.calls == 2

    always_bad = SequenceGateway([{"bad": "one"}, {"bad": "two"}, {"bad": "three"}])
    exhausted = OutlinesGuidedGateway(always_bad, max_schema_retries=1)
    fail = exhausted.complete("reader", [{"role": "user", "content": "{}"}], TEST_SCHEMA)
    assert fail.output is None
    assert fail.abstain_reason == "schema_invalid"
    assert always_bad.calls == 2

    leaked = SequenceGateway(
        [{"bad": "9.999"}, {"requirements": [{"id": "ITEM-2", "label": "VERIFIED"}]}]
    )
    blocked = OutlinesGuidedGateway(leaked, max_schema_retries=2)
    fail_leak = blocked.complete("reader", [{"role": "user", "content": "{}"}], TEST_SCHEMA)
    assert fail_leak.output is None
    assert fail_leak.abstain_reason == "schema_invalid"
    assert leaked.calls == 1
