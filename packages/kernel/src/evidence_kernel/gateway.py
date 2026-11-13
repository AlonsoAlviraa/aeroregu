from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import httpx
from jsonschema import Draft202012Validator

from evidence_kernel.agents import MVP_AGENTS, require_mvp_agent
from evidence_kernel.edge import get_edge_preset
from evidence_kernel.paths import prompts_dir

logger = logging.getLogger("evidence_kernel.gateway")

MAX_TURNS = 4
MAX_INPUT_TOKENS = 8000
MAX_OUTPUT_TOKENS = 1000
TIMEOUT_SECONDS = 30.0
DEFAULT_EDGE_AGENTS = ("decision_gate", "reader", "scribe")
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL | re.IGNORECASE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def estimate_tokens(text: str) -> int:
    """ASSUMPTION: four characters stand in for one token when enforcing the budget."""

    if not text:
        return 0
    return (len(text) + 3) // 4


@lru_cache(maxsize=32)
def prompt_text(agent_id: str) -> str:
    """Return raw markdown system prompt text for an active agent."""
    require_mvp_agent(agent_id)
    return (prompts_dir() / f"{agent_id}.md").read_text(encoding="utf-8").strip()


@lru_cache(maxsize=32)
def prompt_hash(agent_id: str) -> str:
    require_mvp_agent(agent_id)
    payload = (prompts_dir() / f"{agent_id}.md").read_bytes()
    return hashlib.sha256(payload).hexdigest()


def extract_json_object(raw_text: str) -> dict[str, Any] | None:
    """Extract a JSON object from raw model output, stripping think tags or markdown fences."""
    cleaned = _THINK_RE.sub("", raw_text).strip()
    if not cleaned:
        return None
    fenced = _FENCE_RE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _ensure_system_message(agent_id: str, messages: list[dict[str, str]]) -> list[dict[str, str]]:
    if any(msg.get("role") == "system" for msg in messages):
        return messages
    sys_msg = {"role": "system", "content": prompt_text(agent_id)}
    return [sys_msg, *messages]


def _extract_user_context(messages: list[dict[str, str]]) -> dict[str, Any]:
    for msg in messages:
        if msg.get("role") == "user":
            try:
                parsed = json.loads(msg["content"])
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                continue
    return {}


@dataclass
class Completion:
    output: dict[str, Any] | None
    abstain_reason: str | None
    temperature: str
    prompt_hash: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    provider: str = "fixture"
    model_id: str = "fixture"
    routed_via: str = "local"
    escalated: bool = False
    raw_output: dict[str, Any] | None = None

    @property
    def abstained(self) -> bool:
        return self.abstain_reason is not None


class FixtureGateway:
    def __init__(self, scenario: str = "happy") -> None:
        self.scenario = scenario
        self.calls: list[str] = []

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        require_mvp_agent(agent_id)
        self.calls.append(agent_id)
        context = _extract_user_context(messages)
        output = _fixture_output(agent_id, self.scenario, context)
        reason = _schema_problem(output, schema)
        digest = prompt_hash(agent_id)
        if reason:
            return Completion(
                None,
                reason,
                "0",
                digest,
                provider="fixture",
                model_id=f"fixture:{self.scenario}",
                routed_via="local_fixture",
            )
        return Completion(
            output,
            None,
            "0",
            digest,
            estimate_tokens(messages[-1]["content"]),
            32,
            provider="fixture",
            model_id=f"fixture:{self.scenario}",
            routed_via="local_fixture",
        )

    async def acomplete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> Completion:
        del client
        return self.complete(agent_id, messages, schema)


class UnconfiguredGateway:
    """Fail-closed gateway used when an explicit live mode lacks a configured endpoint."""

    def __init__(self, reason: str, *, provider: str = "unconfigured") -> None:
        self.reason = reason
        self.provider = provider

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        del messages, schema
        require_mvp_agent(agent_id)
        return Completion(
            None,
            self.reason,
            "0",
            prompt_hash(agent_id),
            0,
            0,
            provider=self.provider,
            model_id="unconfigured",
            routed_via="fail_closed",
        )

    async def acomplete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> Completion:
        del client
        return self.complete(agent_id, messages, schema)


class BudgetedGateway:
    def __init__(
        self,
        inner: Any,
        max_turns: int = MAX_TURNS,
        max_input_tokens: int = MAX_INPUT_TOKENS,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> None:
        self.inner = inner
        self.max_turns = max_turns
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.turns = 0

    def _preflight(
        self, agent_id: str, messages: list[dict[str, str]]
    ) -> tuple[str, int, Completion | None]:
        self.turns += 1
        digest = prompt_hash(agent_id) if agent_id in MVP_AGENTS else ""
        text = json.dumps(messages, separators=(",", ":"))
        input_tokens = estimate_tokens(text)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        logger.info(
            "gateway_call agent=%s prompt_hash=%s content_hash=%s input_tokens=%s",
            agent_id,
            digest,
            content_hash,
            input_tokens,
        )
        if self.turns > self.max_turns:
            return (
                digest,
                input_tokens,
                Completion(None, "budget_turns", "0", digest, input_tokens, 0),
            )
        if input_tokens > self.max_input_tokens:
            return (
                digest,
                input_tokens,
                Completion(None, "budget_input_tokens", "0", digest, input_tokens, 0),
            )
        return digest, input_tokens, None

    def _postflight(self, digest: str, completion: Completion) -> Completion:
        if completion.output_tokens > self.max_output_tokens:
            return Completion(None, "budget_output_tokens", completion.temperature, digest)
        return completion

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        digest, _input_tokens, blocked = self._preflight(agent_id, messages)
        if blocked is not None:
            return blocked
        return self._postflight(digest, self.inner.complete(agent_id, messages, schema))

    async def acomplete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> Completion:
        digest, _input_tokens, blocked = self._preflight(agent_id, messages)
        if blocked is not None:
            return blocked
        if hasattr(self.inner, "acomplete"):
            completion = await self.inner.acomplete(agent_id, messages, schema, client=client)
        else:
            completion = self.inner.complete(agent_id, messages, schema)
        return self._postflight(digest, completion)


class OpenAICompatibleGateway:
    def __init__(
        self,
        base_url: str,
        model: str = "local",
        timeout_s: float = TIMEOUT_SECONDS,
        temperature: str = "0",
        *,
        api_key: str | None = None,
        provider: str = "openai_compatible",
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
        max_input_tokens: int = MAX_INPUT_TOKENS,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.api_key = api_key if api_key is not None else os.environ.get("MODEL_API_KEY", "")
        self.provider = provider
        self.max_output_tokens = max_output_tokens
        self.max_input_tokens = max_input_tokens
        self.extra_headers = dict(extra_headers or {})

    def _prepare_request(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> tuple[str, int, dict[str, Any], dict[str, str]] | Completion:
        require_mvp_agent(agent_id)
        digest = prompt_hash(agent_id)
        if agent_id == "decision_gate":
            return Completion(
                None,
                "decision_gate_fixture_only",
                self.temperature,
                digest,
                0,
                0,
                provider=self.provider,
                model_id=self.model,
            )
        wire_messages = _ensure_system_message(agent_id, messages)
        text = json.dumps(wire_messages, separators=(",", ":"))
        input_tokens = estimate_tokens(text)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        logger.info(
            "gateway_call agent=%s prompt_hash=%s content_hash=%s input_tokens=%s",
            agent_id,
            digest,
            content_hash,
            input_tokens,
        )
        if input_tokens > self.max_input_tokens:
            return Completion(
                None,
                "budget_input_tokens",
                self.temperature,
                digest,
                input_tokens,
                0,
                provider=self.provider,
                model_id=self.model,
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": float(self.temperature),
            "messages": wire_messages,
            "max_tokens": self.max_output_tokens,
        }
        if schema is not None:
            if self.provider == "llamacpp":
                payload["response_format"] = {"type": "json_object", "schema": schema}
            else:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": f"{agent_id}_response",
                        "strict": True,
                        "schema": schema,
                    },
                }
                if self.provider not in {"openai", "openrouter"}:
                    payload["guided_json"] = schema

        headers: dict[str, str] = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return digest, input_tokens, payload, headers

    def _finish_response(
        self,
        digest: str,
        input_tokens: int,
        elapsed: int,
        data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> Completion:
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return Completion(
                None,
                "invalid_json",
                self.temperature,
                digest,
                input_tokens,
                0,
                latency_ms=elapsed,
                provider=self.provider,
                model_id=self.model,
                routed_via="api_remote",
            )
        usage = data.get("usage") or {}
        output_tokens = usage.get("completion_tokens")
        if output_tokens is None:
            output_tokens = estimate_tokens(str(content))
        if int(output_tokens) > self.max_output_tokens:
            return Completion(
                None,
                "budget_output_tokens",
                self.temperature,
                digest,
                input_tokens,
                0,
                latency_ms=elapsed,
                provider=self.provider,
                model_id=self.model,
                routed_via="api_remote",
            )
        output = extract_json_object(str(content))
        if output is None:
            return Completion(
                None,
                "invalid_json",
                self.temperature,
                digest,
                input_tokens,
                0,
                latency_ms=elapsed,
                provider=self.provider,
                model_id=self.model,
                routed_via="api_remote",
            )
        reason = _schema_problem(output, schema)
        if reason:
            return Completion(
                None,
                reason,
                self.temperature,
                digest,
                input_tokens,
                int(output_tokens),
                latency_ms=elapsed,
                provider=self.provider,
                model_id=self.model,
                routed_via="api_remote",
                raw_output=output,
            )
        return Completion(
            output,
            None,
            self.temperature,
            digest,
            input_tokens,
            int(output_tokens),
            latency_ms=elapsed,
            provider=self.provider,
            model_id=self.model,
            routed_via="api_remote",
        )

    def _error_completion(
        self, reason: str, digest: str, input_tokens: int, elapsed: int
    ) -> Completion:
        return Completion(
            None,
            reason,
            self.temperature,
            digest,
            input_tokens,
            0,
            latency_ms=elapsed,
            provider=self.provider,
            model_id=self.model,
            routed_via="api_remote",
        )

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        prepared = self._prepare_request(agent_id, messages, schema)
        if isinstance(prepared, Completion):
            return prepared
        digest, input_tokens, payload, headers = prepared
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException:
            elapsed = int((time.perf_counter() - started) * 1000)
            return self._error_completion("timeout", digest, input_tokens, elapsed)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            elapsed = int((time.perf_counter() - started) * 1000)
            return self._error_completion("transport", digest, input_tokens, elapsed)
        elapsed = int((time.perf_counter() - started) * 1000)
        return self._finish_response(digest, input_tokens, elapsed, data, schema)

    async def acomplete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> Completion:
        prepared = self._prepare_request(agent_id, messages, schema)
        if isinstance(prepared, Completion):
            return prepared
        digest, input_tokens, payload, headers = prepared
        started = time.perf_counter()
        try:
            if client is not None:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_s,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_s) as owned_client:
                    response = await owned_client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException:
            elapsed = int((time.perf_counter() - started) * 1000)
            return self._error_completion("timeout", digest, input_tokens, elapsed)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            elapsed = int((time.perf_counter() - started) * 1000)
            return self._error_completion("transport", digest, input_tokens, elapsed)
        elapsed = int((time.perf_counter() - started) * 1000)
        return self._finish_response(digest, input_tokens, elapsed, data, schema)


class OllamaEdgeGateway:
    """Native local edge SLM runtime adapter speaking Ollama /api/chat structured outputs."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:3b",
        *,
        num_ctx: int = 4096,
        max_output_tokens: int = 512,
        timeout_s: float = TIMEOUT_SECONDS,
        temperature: str = "0",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.max_output_tokens = max_output_tokens
        self.timeout_s = timeout_s
        self.temperature = temperature

    def _prepare_request(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> tuple[str, int, dict[str, Any]] | Completion:
        require_mvp_agent(agent_id)
        digest = prompt_hash(agent_id)
        if agent_id == "decision_gate":
            return Completion(
                None,
                "decision_gate_fixture_only",
                self.temperature,
                digest,
                provider="ollama_edge",
                model_id=self.model,
                routed_via="edge_local",
            )
        wire_messages = _ensure_system_message(agent_id, messages)
        input_tokens = estimate_tokens(json.dumps(wire_messages, separators=(",", ":")))
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": wire_messages,
            "stream": False,
            "options": {
                "temperature": float(self.temperature),
                "num_ctx": self.num_ctx,
                "num_predict": self.max_output_tokens,
            },
        }
        if schema is not None:
            payload["format"] = schema
        return digest, input_tokens, payload

    def _finish_response(
        self,
        digest: str,
        input_tokens: int,
        elapsed: int,
        data: dict[str, Any],
        schema: dict[str, Any] | None,
    ) -> Completion:
        msg_obj = data.get("message") or {}
        content = str(msg_obj.get("content", ""))
        output_tokens = int(data.get("eval_count") or estimate_tokens(content))
        output = extract_json_object(content)
        if output is None:
            return Completion(
                None,
                "invalid_json",
                self.temperature,
                digest,
                input_tokens,
                output_tokens,
                latency_ms=elapsed,
                provider="ollama_edge",
                model_id=self.model,
                routed_via="edge_local",
            )
        reason = _schema_problem(output, schema)
        if reason:
            return Completion(
                None,
                reason,
                self.temperature,
                digest,
                input_tokens,
                output_tokens,
                latency_ms=elapsed,
                provider="ollama_edge",
                model_id=self.model,
                routed_via="edge_local",
                raw_output=output,
            )
        return Completion(
            output,
            None,
            self.temperature,
            digest,
            input_tokens,
            output_tokens,
            latency_ms=elapsed,
            provider="ollama_edge",
            model_id=self.model,
            routed_via="edge_local",
        )

    def _error_completion(
        self, reason: str, digest: str, input_tokens: int, elapsed: int
    ) -> Completion:
        return Completion(
            None,
            reason,
            self.temperature,
            digest,
            input_tokens,
            0,
            latency_ms=elapsed,
            provider="ollama_edge",
            model_id=self.model,
            routed_via="edge_local",
        )

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        prepared = self._prepare_request(agent_id, messages, schema)
        if isinstance(prepared, Completion):
            return prepared
        digest, input_tokens, payload = prepared
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException:
            return self._error_completion(
                "timeout", digest, input_tokens, int((time.perf_counter() - started) * 1000)
            )
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            return self._error_completion(
                "transport", digest, input_tokens, int((time.perf_counter() - started) * 1000)
            )
        elapsed = int((time.perf_counter() - started) * 1000)
        return self._finish_response(digest, input_tokens, elapsed, data, schema)

    async def acomplete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> Completion:
        prepared = self._prepare_request(agent_id, messages, schema)
        if isinstance(prepared, Completion):
            return prepared
        digest, input_tokens, payload = prepared
        started = time.perf_counter()
        try:
            if client is not None:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=self.timeout_s,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_s) as owned_client:
                    response = await owned_client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException:
            return self._error_completion(
                "timeout", digest, input_tokens, int((time.perf_counter() - started) * 1000)
            )
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            return self._error_completion(
                "transport", digest, input_tokens, int((time.perf_counter() - started) * 1000)
            )
        elapsed = int((time.perf_counter() - started) * 1000)
        return self._finish_response(digest, input_tokens, elapsed, data, schema)


class HybridAgentRouter:
    """Routes agents across Edge SLM and Remote API backends with safe failure escalation."""

    _ESCALATION_REASONS = frozenset({"schema_invalid", "invalid_json", "timeout", "transport"})

    def __init__(
        self,
        *,
        edge_gateway: Any | None,
        api_gateway: Any | None,
        gate_gateway: Any | None = None,
        edge_agents: tuple[str, ...] = DEFAULT_EDGE_AGENTS,
        allow_escalation: bool = True,
    ) -> None:
        self.edge_gateway = edge_gateway
        self.api_gateway = api_gateway
        self.gate_gateway = gate_gateway if gate_gateway is not None else FixtureGateway("happy")
        self.edge_agents = set(edge_agents)
        self.allow_escalation = allow_escalation

    def _select_primary(self, agent_id: str) -> tuple[bool, Any | None]:
        prefer_edge = agent_id in self.edge_agents and self.edge_gateway is not None
        primary = self.edge_gateway if prefer_edge else (self.api_gateway or self.edge_gateway)
        return prefer_edge, primary

    @staticmethod
    def _try_local_fsm_repair(
        res: Completion, messages: list[dict[str, str]], schema: dict[str, Any] | None
    ) -> Completion | None:
        if schema is None or res.abstain_reason != "schema_invalid" or res.raw_output is None:
            return None
        from evidence_kernel.constrained import SchemaFSM

        ctx = _extract_user_context(messages)
        allowed = {str(x) for x in ctx.get("allowed_decimals", [])}
        repaired = SchemaFSM(schema).guide_repair(res.raw_output, allowed)
        if repaired is None:
            return None
        return Completion(
            repaired,
            None,
            res.temperature,
            res.prompt_hash,
            res.input_tokens,
            res.output_tokens,
            latency_ms=res.latency_ms,
            provider=res.provider,
            model_id=res.model_id,
            routed_via=res.routed_via,
            escalated=res.escalated,
        )

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        require_mvp_agent(agent_id)
        if agent_id == "decision_gate" and self.gate_gateway is not None:
            gate_res: Completion = self.gate_gateway.complete(agent_id, messages, schema)
            gate_res.routed_via = "deterministic_gate"
            return gate_res
        prefer_edge, primary = self._select_primary(agent_id)
        if primary is None:
            digest = prompt_hash(agent_id)
            return Completion(None, "no_gateway_configured", "0", digest)

        res: Completion = primary.complete(agent_id, messages, schema)
        res.routed_via = "hybrid_edge" if prefer_edge else "hybrid_api"
        repaired = self._try_local_fsm_repair(res, messages, schema)
        if repaired is not None:
            return repaired

        if (
            prefer_edge
            and self.allow_escalation
            and self.api_gateway is not None
            and res.abstained
            and res.abstain_reason in self._ESCALATION_REASONS
        ):
            escalated: Completion = self.api_gateway.complete(agent_id, messages, schema)
            escalated.routed_via = "hybrid_escalated"
            escalated.escalated = True
            return escalated
        return res

    async def acomplete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> Completion:
        require_mvp_agent(agent_id)
        if agent_id == "decision_gate" and self.gate_gateway is not None:
            gate_res = (
                await self.gate_gateway.acomplete(agent_id, messages, schema, client=client)
                if hasattr(self.gate_gateway, "acomplete")
                else self.gate_gateway.complete(agent_id, messages, schema)
            )
            gate_res.routed_via = "deterministic_gate"
            return gate_res
        prefer_edge, primary = self._select_primary(agent_id)
        if primary is None:
            return Completion(None, "no_gateway_configured", "0", prompt_hash(agent_id))

        res = (
            await primary.acomplete(agent_id, messages, schema, client=client)
            if hasattr(primary, "acomplete")
            else primary.complete(agent_id, messages, schema)
        )
        res.routed_via = "hybrid_edge" if prefer_edge else "hybrid_api"
        repaired = self._try_local_fsm_repair(res, messages, schema)
        if repaired is not None:
            return repaired

        if (
            prefer_edge
            and self.allow_escalation
            and self.api_gateway is not None
            and res.abstained
            and res.abstain_reason in self._ESCALATION_REASONS
        ):
            escalated = (
                await self.api_gateway.acomplete(agent_id, messages, schema, client=client)
                if hasattr(self.api_gateway, "acomplete")
                else self.api_gateway.complete(agent_id, messages, schema)
            )
            escalated.routed_via = "hybrid_escalated"
            escalated.escalated = True
            return escalated
        return res


def _build_edge_gateway(edge_model: str | None = None, edge_preset: str | None = None) -> Any:
    edge_url = os.environ.get("EDGE_MODEL_URL", "").strip()
    if not edge_url:
        return None
    preset = get_edge_preset(edge_preset or os.environ.get("EDGE_PRESET"))
    chosen_model = (
        edge_model or os.environ.get("EDGE_MODEL_NAME") or str(preset["recommended_model"])
    )
    provider = os.environ.get("EDGE_MODEL_PROVIDER", "").strip().lower()
    if not provider:
        provider = "openai_compatible" if edge_url.rstrip("/").endswith("/v1") else "ollama"
    if provider == "ollama":
        return OllamaEdgeGateway(
            base_url=edge_url,
            model=chosen_model,
            num_ctx=int(preset["num_ctx"]),
            max_output_tokens=int(preset["max_output_tokens"]),
        )
    return OpenAICompatibleGateway(
        base_url=edge_url,
        model=chosen_model,
        provider=provider,
        api_key="",
        max_output_tokens=int(preset["max_output_tokens"]),
    )


def _build_api_gateway(model: str | None = None) -> Any:
    base = os.environ.get("MODEL_BASE_URL", "").strip()
    if not base:
        return None
    chosen_model = model or os.environ.get("MODEL_NAME") or "local"
    provider = os.environ.get("MODEL_PROVIDER", "openai_compatible").strip().lower()
    api_key = os.environ.get("MODEL_API_KEY", "")
    return OpenAICompatibleGateway(base, model=chosen_model, api_key=api_key, provider=provider)


def gateway_from_env(
    scenario: str = "happy",
    constrained: bool = False,
    *,
    runtime_mode: str = "auto",
    model: str | None = None,
    edge_model: str | None = None,
    edge_preset: str | None = None,
    max_schema_retries: int | None = None,
    max_turns: int = MAX_TURNS,
) -> Any:
    mode = (runtime_mode or "auto").strip().lower()
    api_gw = _build_api_gateway(model=model)
    edge_gw = _build_edge_gateway(edge_model=edge_model, edge_preset=edge_preset)

    inner: Any
    if mode == "fixture":
        inner = FixtureGateway(scenario=scenario)
    elif mode == "edge":
        inner = (
            edge_gw
            if edge_gw is not None
            else UnconfiguredGateway("edge_not_configured", provider="ollama_edge")
        )
    elif mode == "api":
        inner = (
            api_gw
            if api_gw is not None
            else UnconfiguredGateway("api_not_configured", provider="api")
        )
    elif mode == "hybrid":
        if edge_gw is not None or api_gw is not None:
            inner = HybridAgentRouter(
                edge_gateway=edge_gw,
                api_gateway=api_gw,
                gate_gateway=FixtureGateway(scenario=scenario),
            )
        else:
            inner = UnconfiguredGateway("hybrid_not_configured", provider="hybrid")
    elif mode == "auto":
        if edge_gw is not None and api_gw is not None:
            inner = HybridAgentRouter(
                edge_gateway=edge_gw,
                api_gateway=api_gw,
                gate_gateway=FixtureGateway(scenario=scenario),
            )
        elif edge_gw is not None:
            inner = edge_gw
        elif api_gw is not None:
            inner = api_gw
        else:
            inner = FixtureGateway(scenario=scenario)
    else:
        inner = UnconfiguredGateway("invalid_runtime_mode", provider="unconfigured")

    live_backend = not isinstance(inner, (FixtureGateway, UnconfiguredGateway))
    use_constrained = (
        constrained
        or live_backend
        or os.environ.get("OUTLINES_CONSTRAINED", "").lower() in ("1", "true", "yes")
    )
    if use_constrained:
        from evidence_kernel.constrained import OutlinesGuidedGateway

        retries = (
            max_schema_retries if max_schema_retries is not None else (2 if live_backend else 0)
        )
        inner = OutlinesGuidedGateway(inner, max_schema_retries=retries)
    return BudgetedGateway(inner, max_turns=max_turns)


def _safe_endpoint_label(raw_url: str) -> str:
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def describe_agent_runtime() -> dict[str, Any]:
    """Return masked configuration and registry metadata for API, Edge, and Fixture runtimes."""
    api_url = os.environ.get("MODEL_BASE_URL", "").strip()
    edge_url = os.environ.get("EDGE_MODEL_URL", "").strip()
    if api_url and edge_url:
        active_mode = "hybrid"
    elif edge_url:
        active_mode = "edge"
    elif api_url:
        active_mode = "api"
    else:
        active_mode = "fixture"

    return {
        "active_mode": active_mode,
        "api_backend": {
            "configured": bool(api_url),
            "endpoint": _safe_endpoint_label(api_url),
            "provider": os.environ.get("MODEL_PROVIDER", "openai_compatible"),
            "model": os.environ.get("MODEL_NAME", "local"),
            "api_key_present": bool(os.environ.get("MODEL_API_KEY")),
        },
        "edge_backend": {
            "configured": bool(edge_url),
            "endpoint": _safe_endpoint_label(edge_url),
            "provider": os.environ.get("EDGE_MODEL_PROVIDER", "ollama"),
            "model": os.environ.get("EDGE_MODEL_NAME", "qwen2.5:3b"),
            "preset": get_edge_preset(os.environ.get("EDGE_PRESET")),
        },
        "hybrid_default_edge_agents": list(DEFAULT_EDGE_AGENTS),
        "agents": [
            {
                "agent_id": agent_id,
                "prompt_hash": prompt_hash(agent_id),
                "prompt_preview": prompt_text(agent_id),
                "fixture_only": agent_id == "decision_gate",
            }
            for agent_id in MVP_AGENTS
        ],
    }


def probe_gateway_health(*, target: str = "all", timeout_s: float = 3.0) -> dict[str, Any]:
    """Probe pre-configured API and Edge model endpoints (no arbitrary URLs to prevent SSRF)."""
    results: dict[str, Any] = {}
    api_url = os.environ.get("MODEL_BASE_URL", "").strip().rstrip("/")
    edge_url = os.environ.get("EDGE_MODEL_URL", "").strip().rstrip("/")

    if target in {"all", "api"}:
        if not api_url:
            results["api"] = {"configured": False, "reachable": False, "models": []}
        else:
            headers: dict[str, str] = {}
            if os.environ.get("MODEL_API_KEY"):
                headers["Authorization"] = f"Bearer {os.environ['MODEL_API_KEY']}"
            started = time.perf_counter()
            try:
                resp = httpx.get(f"{api_url}/models", headers=headers, timeout=timeout_s)
                resp.raise_for_status()
                body = resp.json()
                models = [str(item.get("id", "")) for item in body.get("data", [])][:20]
                results["api"] = {
                    "configured": True,
                    "reachable": True,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "models": models,
                }
            except (httpx.HTTPError, ValueError, TypeError):
                results["api"] = {
                    "configured": True,
                    "reachable": False,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "models": [],
                }

    if target in {"all", "edge"}:
        if not edge_url:
            results["edge"] = {"configured": False, "reachable": False, "models": []}
        else:
            is_openai = edge_url.endswith("/v1")
            probe_path = f"{edge_url}/models" if is_openai else f"{edge_url}/api/tags"
            started = time.perf_counter()
            try:
                resp = httpx.get(probe_path, timeout=timeout_s)
                resp.raise_for_status()
                body = resp.json()
                raw_list = body.get("data", []) if is_openai else body.get("models", [])
                models = [str(item.get("id") or item.get("name") or "") for item in raw_list][:20]
                results["edge"] = {
                    "configured": True,
                    "reachable": True,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "models": models,
                }
            except (httpx.HTTPError, ValueError, TypeError):
                results["edge"] = {
                    "configured": True,
                    "reachable": False,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "models": [],
                }
    return results


def _schema_problem(output: dict[str, Any], schema: dict[str, Any] | None) -> str | None:
    if schema is None:
        return None
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(output))
    if errors:
        return "schema_invalid"
    return None


def _fixture_output(agent_id: str, scenario: str, context: dict[str, Any]) -> dict[str, Any]:
    quotation = str(context.get("quotation", ""))
    span_start = str(context.get("span_start", "0"))
    span_end = str(context.get("span_end", "0"))
    reader_label = str(context.get("reader_label", "NOT_VERIFIED"))
    checker_label = reader_label
    if scenario == "disagree":
        checker_label = "VERIFIED" if reader_label != "VERIFIED" else "NOT_VERIFIED"
    if agent_id == "decision_gate":
        if scenario == "gate_low":
            return {"decision": "continue", "gate_probability": "0.100"}
        if scenario == "gate_abstain":
            return {"decision": "abstain", "gate_probability": "0.950"}
        return {"decision": "continue", "gate_probability": "0.950"}
    if scenario == "schema_invalid" and agent_id == "reader":
        return {"unexpected": "bad"}
    if scenario == "bad_span" and agent_id == "reader":
        quotation = "this quotation is not in the block"
    if (
        scenario == "multi_block_second"
        and agent_id == "reader"
        and isinstance(context.get("blocks"), list)
        and len(context["blocks"]) >= 2
    ):
        block = context["blocks"][1]
        quotation = str(block.get("text", ""))
        span_start = str(block.get("span_start", 0))
        span_end = str(block.get("span_end", len(quotation)))
    decimals = [str(item) for item in context.get("allowed_decimals", [])]
    fault_kind = str(context.get("fault_kind") or "")
    if agent_id == "reader":
        return {
            "requirements": [
                {
                    "id": "ITEM-1",
                    "label": reader_label,
                    "quotation": quotation,
                    "span_start": span_start,
                    "span_end": span_end,
                }
            ]
        }
    if agent_id == "checker":
        if scenario == "stray_number":
            narrative = "The value is 9.999 which is invented."
        elif scenario == "integer_leak":
            narrative = "The safety factor is 3 in this note."
        elif decimals and fault_kind and fault_kind != "clean":
            narrative = (
                f"Recomputed value {decimals[0]} is on the calc event; fault {fault_kind} flagged."
            )
        elif decimals:
            narrative = f"Recomputed value {decimals[0]} is on the calc event."
        else:
            narrative = "No numeric result is present."
        return {
            "requirements": [{"id": "ITEM-1", "label": checker_label}],
            "narrative": narrative,
        }
    if agent_id == "refuter":
        attack = "hit" if scenario == "refuter_hit" else "miss"
        return {
            "attack": attack,
            "reason": "checked spans hashes coverage and inputs",
            "evidence_span": str(context.get("source_text", quotation)),
        }
    if scenario == "scribe_extra_number" and decimals:
        paragraph = f"The stored value is {decimals[0]}. A stray value is 8.888."
    elif scenario == "scribe_integer_leak" and decimals:
        paragraph = f"The stored value is {decimals[0]}. Count is 7."
    elif scenario == "scribe_only_bad":
        paragraph = "A stray value is 8.888."
    elif decimals and fault_kind and fault_kind != "clean":
        paragraph = f"The stored value is {decimals[0]} with fault {fault_kind}."
    elif decimals:
        paragraph = f"The stored value is {decimals[0]}."
    else:
        paragraph = "No stored numeric value is available."
    return {"paragraph": paragraph}
