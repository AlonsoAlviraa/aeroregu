from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from evidence_kernel.agents import require_mvp_agent
from evidence_kernel.paths import prompts_dir

logger = logging.getLogger("evidence_kernel.gateway")

MAX_TURNS = 4
MAX_INPUT_TOKENS = 8000
MAX_OUTPUT_TOKENS = 1000
TIMEOUT_SECONDS = 30.0


def estimate_tokens(text: str) -> int:
    """ASSUMPTION: four characters stand in for one token when enforcing the budget."""

    if not text:
        return 0
    return (len(text) + 3) // 4


def prompt_hash(agent_id: str) -> str:
    require_mvp_agent(agent_id)
    payload = (prompts_dir() / f"{agent_id}.md").read_bytes()
    return hashlib.sha256(payload).hexdigest()


@dataclass
class Completion:
    output: dict[str, Any] | None
    abstain_reason: str | None
    temperature: str
    prompt_hash: str
    input_tokens: int = 0
    output_tokens: int = 0

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
        context = json.loads(messages[-1]["content"])
        output = _fixture_output(agent_id, self.scenario, context)
        reason = _schema_problem(output, schema)
        digest = prompt_hash(agent_id)
        if reason:
            return Completion(None, reason, "0", digest)
        return Completion(output, None, "0", digest, estimate_tokens(messages[-1]["content"]), 32)


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

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        self.turns += 1
        digest = (
            prompt_hash(agent_id) if agent_id in {"reader", "checker", "refuter", "scribe"} else ""
        )
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
            return Completion(None, "budget_turns", "0", digest, input_tokens, 0)
        if input_tokens > self.max_input_tokens:
            return Completion(None, "budget_input_tokens", "0", digest, input_tokens, 0)
        completion = self.inner.complete(agent_id, messages, schema)
        if completion.output_tokens > self.max_output_tokens:
            return Completion(None, "budget_output_tokens", completion.temperature, digest)
        return completion


class OpenAICompatibleGateway:
    def __init__(
        self,
        base_url: str,
        model: str = "local",
        timeout_s: float = TIMEOUT_SECONDS,
        temperature: str = "0",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.temperature = temperature

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        require_mvp_agent(agent_id)
        digest = prompt_hash(agent_id)
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
        if input_tokens > MAX_INPUT_TOKENS:
            return Completion(
                None, "budget_input_tokens", self.temperature, digest, input_tokens, 0
            )
        payload = {
            "model": self.model,
            "temperature": float(self.temperature),
            "messages": messages,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException:
            return Completion(None, "timeout", self.temperature, digest, input_tokens, 0)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            return Completion(None, "transport", self.temperature, digest, input_tokens, 0)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return Completion(None, "invalid_json", self.temperature, digest, input_tokens, 0)
        usage = data.get("usage") or {}
        output_tokens = usage.get("completion_tokens")
        if output_tokens is None:
            output_tokens = estimate_tokens(content)
        if int(output_tokens) > MAX_OUTPUT_TOKENS:
            return Completion(
                None, "budget_output_tokens", self.temperature, digest, input_tokens, 0
            )
        try:
            output = json.loads(content)
        except json.JSONDecodeError:
            return Completion(None, "invalid_json", self.temperature, digest, input_tokens, 0)
        if not isinstance(output, dict):
            return Completion(None, "invalid_json", self.temperature, digest, input_tokens, 0)
        reason = _schema_problem(output, schema)
        if reason:
            return Completion(
                None, reason, self.temperature, digest, input_tokens, int(output_tokens)
            )
        return Completion(
            output,
            None,
            self.temperature,
            digest,
            input_tokens,
            int(output_tokens),
        )


def gateway_from_env(scenario: str = "happy") -> Any:
    base = os.environ.get("MODEL_BASE_URL")
    inner: Any
    if not base:
        inner = FixtureGateway(scenario=scenario)
    else:
        inner = OpenAICompatibleGateway(base)
    return BudgetedGateway(inner)


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
    if scenario == "bad_span" and agent_id == "reader":
        quotation = "this quotation is not in the block"
    decimals = [str(item) for item in context.get("allowed_decimals", [])]
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
    elif scenario == "scribe_only_bad":
        paragraph = "A stray value is 8.888."
    elif decimals:
        paragraph = f"The stored value is {decimals[0]}."
    else:
        paragraph = "No stored numeric value is available."
    return {"paragraph": paragraph}
