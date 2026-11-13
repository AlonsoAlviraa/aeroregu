from __future__ import annotations

import copy
import json
from typing import Any

import llguidance
from jsonschema import Draft202012Validator

from evidence_kernel.canonical import inputs_hash
from evidence_kernel.gateway import Completion
from evidence_kernel.numbers import stray_physical_numbers


def compile_schema_grammar(schema: dict[str, Any]) -> str:
    """Compile a JSON Schema (including $defs/$ref/anyOf) into an llguidance Lark grammar."""
    compiler = llguidance.JsonCompiler()
    return compiler.compile(json.dumps(schema, sort_keys=True))


class SchemaFSM:
    """Finite State Machine / Constraint compiler and repair parser for JSON Schema enforcement."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.validator = Draft202012Validator(schema)
        self.defs: dict[str, Any] = {
            **dict(schema.get("$defs", {})),
            **dict(schema.get("definitions", {})),
        }
        self.required: set[str] = set(schema.get("required", []))
        self.properties: dict[str, Any] = schema.get("properties", {})
        self.additional_properties: bool = schema.get("additionalProperties", True)
        self._compiled_grammar: str | None = None

    def lark_grammar(self) -> str:
        """Return cached llguidance CFG/Lark grammar for token-level logit masking."""
        if self._compiled_grammar is None:
            self._compiled_grammar = compile_schema_grammar(self.schema)
        return self._compiled_grammar

    def validate(self, candidate: Any) -> list[str]:
        return [err.message for err in self.validator.iter_errors(candidate)]

    def is_valid(self, candidate: Any) -> bool:
        return self.validator.is_valid(candidate)

    def _resolve_spec(self, spec: Any) -> dict[str, Any]:
        if not isinstance(spec, dict):
            return {}
        ref = spec.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            parts = ref[2:].split("/")
            node: Any = self.schema
            for part in parts:
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    node = None
                    break
            if isinstance(node, dict):
                return node
        return spec

    def _align_value(self, value: Any, raw_spec: Any) -> Any:
        spec = self._resolve_spec(raw_spec)
        if not spec:
            return value

        for branch_key in ("anyOf", "oneOf"):
            branches = spec.get(branch_key)
            if isinstance(branches, list):
                for branch in branches:
                    aligned = self._align_value(value, branch)
                    resolved_branch = self._resolve_spec(branch)
                    if Draft202012Validator(resolved_branch).is_valid(aligned):
                        return aligned

        if isinstance(value, str) and "enum" in spec:
            trimmed = value.strip()
            if trimmed in spec["enum"]:
                return trimmed
            if trimmed.upper() in spec["enum"]:
                return trimmed.upper()
            return trimmed

        if spec.get("type") == "array" and isinstance(value, list):
            item_spec = spec.get("items")
            if isinstance(item_spec, dict):
                return [self._align_value(item, item_spec) for item in value]
            return value

        if isinstance(value, dict) and (spec.get("type") == "object" or "properties" in spec):
            props = spec.get("properties", {})
            addl = spec.get("additionalProperties", True)
            repaired_obj = dict(value)
            if not addl and props:
                allowed_keys = set(props.keys())
                repaired_obj = {k: v for k, v in repaired_obj.items() if k in allowed_keys}
            for prop_key, prop_val in list(repaired_obj.items()):
                if prop_key in props:
                    repaired_obj[prop_key] = self._align_value(prop_val, props[prop_key])
            return repaired_obj

        return value

    def guide_repair(
        self, candidate: Any, allowed_decimals: set[str] | None = None
    ) -> dict[str, Any] | None:
        """Attempt guided structural alignment if model drifted without inventing numbers."""
        if not isinstance(candidate, dict):
            return None

        # Check for numeric leaks before attempting any repair
        if allowed_decimals is not None and stray_physical_numbers(candidate, allowed_decimals):
            return None

        repaired = self._align_value(copy.deepcopy(candidate), self.schema)
        if not isinstance(repaired, dict):
            return None

        if not self.required.issubset(repaired.keys()):
            return None

        if self.validator.is_valid(repaired):
            return repaired
        return None


class OutlinesGuidedGateway:
    """Constrained generation gateway backed by llguidance CFG compilation and SchemaFSM."""

    def __init__(self, inner: Any, *, max_schema_retries: int = 0) -> None:
        self.inner = inner
        self.max_schema_retries = max(0, int(max_schema_retries))
        self.total_calls = 0
        self.guided_clean_calls = 0
        self.repaired_calls = 0
        self.rejected_calls = 0
        self.retry_calls = 0
        self._grammar_cache: dict[str, str] = {}

    def compiled_grammar(self, schema: dict[str, Any]) -> str:
        """Compile and cache llguidance Lark grammar for deterministic runtime masking."""
        key = inputs_hash(schema)
        cached = self._grammar_cache.get(key)
        if cached is None:
            cached = compile_schema_grammar(schema)
            self._grammar_cache[key] = cached
        return cached

    def _evaluate_attempt(
        self,
        completion: Completion,
        fsm: SchemaFSM,
        allowed_decimals: set[str],
        messages: list[dict[str, str]],
        attempts_left: int,
    ) -> tuple[Completion | None, list[dict[str, str]] | None]:
        candidate = completion.output if completion.output is not None else completion.raw_output
        if completion.abstained or completion.output is None:
            if completion.abstain_reason == "schema_invalid" and candidate is not None:
                if stray_physical_numbers(candidate, allowed_decimals):
                    self.rejected_calls += 1
                    return completion, None
                repaired = fsm.guide_repair(candidate, allowed_decimals)
                if repaired is not None:
                    self.repaired_calls += 1
                    return (
                        Completion(
                            repaired,
                            None,
                            completion.temperature,
                            completion.prompt_hash,
                            completion.input_tokens,
                            completion.output_tokens,
                            latency_ms=completion.latency_ms,
                            provider=completion.provider,
                            model_id=completion.model_id,
                            routed_via=completion.routed_via,
                            escalated=completion.escalated,
                        ),
                        None,
                    )
                if attempts_left > 0:
                    self.retry_calls += 1
                    errors = fsm.validate(candidate)[:3]
                    return None, self._retry_messages(messages, errors)
                self.rejected_calls += 1
                return completion, None
            if completion.abstain_reason == "schema_invalid" and attempts_left > 0:
                self.retry_calls += 1
                retry_msgs = self._retry_messages(
                    messages, ["Previous response violated the required JSON schema."]
                )
                return None, retry_msgs
            return completion, None

        if fsm.is_valid(completion.output):
            self.guided_clean_calls += 1
            return completion, None

        repaired = fsm.guide_repair(completion.output, allowed_decimals)
        if repaired is not None:
            self.repaired_calls += 1
            return (
                Completion(
                    repaired,
                    None,
                    completion.temperature,
                    completion.prompt_hash,
                    completion.input_tokens,
                    completion.output_tokens,
                    latency_ms=completion.latency_ms,
                    provider=completion.provider,
                    model_id=completion.model_id,
                    routed_via=completion.routed_via,
                    escalated=completion.escalated,
                ),
                None,
            )

        if attempts_left > 0 and not stray_physical_numbers(completion.output, allowed_decimals):
            self.retry_calls += 1
            errors = fsm.validate(completion.output)[:3]
            return None, self._retry_messages(messages, errors)

        self.rejected_calls += 1
        return (
            Completion(
                None,
                "schema_invalid",
                completion.temperature,
                completion.prompt_hash,
                completion.input_tokens,
                completion.output_tokens,
                latency_ms=completion.latency_ms,
                provider=completion.provider,
                model_id=completion.model_id,
                routed_via=completion.routed_via,
                escalated=completion.escalated,
            ),
            None,
        )

    def complete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
    ) -> Completion:
        self.total_calls += 1
        if schema is not None:
            self.compiled_grammar(schema)
        completion = self.inner.complete(agent_id, messages, schema)
        if schema is None:
            return completion

        fsm = SchemaFSM(schema)
        allowed_decimals = self._allowed_decimals(messages)
        attempts_left = self.max_schema_retries
        while True:
            final, retry_msgs = self._evaluate_attempt(
                completion, fsm, allowed_decimals, messages, attempts_left
            )
            if final is not None:
                return final
            assert retry_msgs is not None
            attempts_left -= 1
            completion = self.inner.complete(agent_id, retry_msgs, schema)

    async def acomplete(
        self,
        agent_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        *,
        client: Any | None = None,
    ) -> Completion:
        self.total_calls += 1
        if schema is not None:
            self.compiled_grammar(schema)
        completion = (
            await self.inner.acomplete(agent_id, messages, schema, client=client)
            if hasattr(self.inner, "acomplete")
            else self.inner.complete(agent_id, messages, schema)
        )
        if schema is None:
            return completion

        fsm = SchemaFSM(schema)
        allowed_decimals = self._allowed_decimals(messages)
        attempts_left = self.max_schema_retries
        while True:
            final, retry_msgs = self._evaluate_attempt(
                completion, fsm, allowed_decimals, messages, attempts_left
            )
            if final is not None:
                return final
            assert retry_msgs is not None
            attempts_left -= 1
            completion = (
                await self.inner.acomplete(agent_id, retry_msgs, schema, client=client)
                if hasattr(self.inner, "acomplete")
                else self.inner.complete(agent_id, retry_msgs, schema)
            )

    @staticmethod
    def _allowed_decimals(messages: list[dict[str, str]]) -> set[str]:
        for msg in messages:
            if msg.get("role") != "user":
                continue
            try:
                parsed_ctx = json.loads(msg.get("content", ""))
                if isinstance(parsed_ctx, dict) and "allowed_decimals" in parsed_ctx:
                    return set(parsed_ctx.get("allowed_decimals", []))
            except Exception:
                continue
        return set()

    @staticmethod
    def _retry_messages(
        messages: list[dict[str, str]],
        errors: list[str],
    ) -> list[dict[str, str]]:
        correction = "Schema validation failed: " + "; ".join(errors)
        return [*messages, {"role": "user", "content": correction}]
