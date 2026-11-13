import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from evidence_kernel.agents import AgentRegistryError, require_mvp_agent
from evidence_kernel.gateway import (
    BudgetedGateway,
    FixtureGateway,
    OpenAICompatibleGateway,
    gateway_from_env,
)


def test_registry_rejects_later_agents() -> None:
    require_mvp_agent("reader")
    try:
        require_mvp_agent("moc_drafter")
    except AgentRegistryError:
        return
    raise AssertionError("later agent ids must be rejected")


def test_fifth_turn_abstains() -> None:
    gateway = BudgetedGateway(FixtureGateway(), max_turns=4)
    schema = {"type": "object"}
    message = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "quotation": "Alpha",
                    "span_start": "0",
                    "span_end": "5",
                    "source_text": "Alpha",
                    "allowed_decimals": [],
                }
            ),
        }
    ]
    for _ in range(4):
        done = gateway.complete("reader", message, schema)
        assert done.abstain_reason is None
    fifth = gateway.complete("reader", message, schema)
    assert fifth.abstain_reason == "budget_turns"
    assert fifth.output is None


def test_input_budget_abstains() -> None:
    gateway = BudgetedGateway(FixtureGateway(), max_input_tokens=10)
    huge = [{"role": "user", "content": "word " * 500}]
    done = gateway.complete("reader", huge, {"type": "object"})
    assert done.abstain_reason == "budget_input_tokens"


def test_default_gateway_is_fixture(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    gateway = gateway_from_env()
    assert isinstance(gateway.inner, FixtureGateway)


def test_fixture_does_not_contact_a_server() -> None:
    hits = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            hits["count"] += 1
            self.send_response(200)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        gateway = FixtureGateway()
        gateway.complete(
            "scribe",
            [
                {
                    "role": "user",
                    "content": json.dumps({"allowed_decimals": [], "source_text": "Alpha"}),
                }
            ],
            {"type": "object"},
        )
        assert hits["count"] == 0
    finally:
        server.shutdown()
        server.server_close()


def test_openai_adapter_accepts_a_fake_server() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            content = json.dumps({"paragraph": "Stored text only."})
            payload = json.dumps(
                {"choices": [{"message": {"content": content}}], "usage": {"completion_tokens": 8}}
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
        gateway = OpenAICompatibleGateway(f"http://{host}:{port}", timeout_s=2)
        done = gateway.complete(
            "scribe",
            [{"role": "user", "content": "{}"}],
            {
                "type": "object",
                "required": ["paragraph"],
                "properties": {"paragraph": {"type": "string"}},
            },
        )
        assert done.output == {"paragraph": "Stored text only."}
        assert done.abstain_reason is None
    finally:
        server.shutdown()
        server.server_close()


def test_invalid_json_abstains_without_a_number() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            payload = json.dumps(
                {
                    "choices": [{"message": {"content": "not-json"}}],
                    "usage": {"completion_tokens": 1},
                }
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
        gateway = OpenAICompatibleGateway(f"http://{host}:{port}", timeout_s=2)
        done = gateway.complete("scribe", [{"role": "user", "content": "{}"}], None)
        assert done.output is None
        assert done.abstain_reason == "invalid_json"
    finally:
        server.shutdown()
        server.server_close()


def test_timeout_abstains() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            import time

            time.sleep(1.2)
            self.send_response(200)
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        gateway = OpenAICompatibleGateway(f"http://{host}:{port}", timeout_s=0.2)
        done = gateway.complete("reader", [{"role": "user", "content": "{}"}], None)
        assert done.abstain_reason == "timeout"
        assert done.output is None
    finally:
        server.shutdown()
        server.server_close()


def test_fixture_schema_invalid_abstains() -> None:
    gateway = FixtureGateway("schema_invalid")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["requirements"],
        "properties": {"requirements": {"type": "array"}},
    }
    done = gateway.complete(
        "reader",
        [{"role": "user", "content": json.dumps({"quotation": "Alpha"})}],
        schema,
    )
    assert done.output is None
    assert done.abstain_reason == "schema_invalid"
