from __future__ import annotations

import copy
from typing import Any

from jsonschema import Draft202012Validator

from evidence_kernel.gateway import Completion
from evidence_kernel.numbers import stray_physical_numbers


class SchemaFSM:
    """Finite State Machine / Constraint parser for JSON Schema enforcement."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema
        self.validator = Draft202012Validator(schema)
        self.required: set[str] = set(schema.get("required", []))
        self.properties: dict[str, Any] = schema.get("properties", {})
        self.additional_properties: bool = schema.get("additionalProperties", True)

    def validate(self, candidate: Any) -> list[str]:
        return [err.message for err in self.validator.iter_errors(candidate)]

    def is_valid(self, candidate: Any) -> bool:
        return self.validator.is_valid(candidate)

    def guide_repair(
        self, candidate: Any, allowed_decimals: set[str] | None = None
    ) -> dict[str, Any] | None:
        """Attempt guided structural alignment if model drifted without inventing numbers."""
        if not isinstance(candidate, dict):
            return None

        # Check for numeric leaks before attempting any repair
        if allowed_decimals is not None and stray_physical_numbers(candidate, allowed_decimals):
            return None

        repaired = copy.deepcopy(candidate)

        # 1. Prune additional properties if disallowed
        if not self.additional_properties and self.properties:
            allowed_keys = set(self.properties.keys())
            repaired = {k: v for k, v in repaired.items() if k in allowed_keys}

        # 2. Check if all top-level required keys are present
        if not self.required.issubset(repaired.keys()):
            return None

        # 3. Handle array items with restricted schemas (e.g., requirements arrays)
        for prop_name, prop_spec in self.properties.items():
            if prop_name not in repaired:
                continue
            value = repaired[prop_name]

            # Array item alignment
            if prop_spec.get("type") == "array" and isinstance(value, list):
                item_spec = prop_spec.get("items")
                if isinstance(item_spec, dict) and not item_spec.get("additionalProperties", True):
                    allowed_subkeys = set(item_spec.get("properties", {}).keys())
                    repaired_list = []
                    for item in value:
                        if isinstance(item, dict):
                            pruned_item = {k: v for k, v in item.items() if k in allowed_subkeys}
                            # Check enum alignment on subproperties
                            for sub_k, sub_spec in item_spec.get("properties", {}).items():
                                if sub_k in pruned_item and "enum" in sub_spec:
                                    val_str = str(pruned_item[sub_k]).strip().upper()
                                    if val_str in sub_spec["enum"]:
                                        pruned_item[sub_k] = val_str
                            repaired_list.append(pruned_item)
                        else:
                            repaired_list.append(item)
                    repaired[prop_name] = repaired_list

            # Enum alignment for scalar fields
            if "enum" in prop_spec and isinstance(value, str):
                trimmed = value.strip()
                if trimmed in prop_spec["enum"]:
                    repaired[prop_name] = trimmed
                elif trimmed.upper() in prop_spec["enum"]:
                    repaired[prop_name] = trimmed.upper()

        # Re-verify with Draft202012Validator
        if self.validator.is_valid(repaired):
            return repaired

        return None


class OutlinesGuidedGateway:
    """Outlines-inspired constrained generation gateway.

    Intercepts generation with FSM schema constraints, preventing structural failures.
    """

    def __init__(self, inner: Any, *, max_schema_retries: int = 0) -> None:
        self.inner = inner
        self.max_schema_retries = max(0, int(max_schema_retries))
        self.total_calls = 0
        self.guided_clean_calls = 0
        self.repaired_calls = 0
        self.rejected_calls = 0
        self.retry_calls = 0

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
        import json

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
