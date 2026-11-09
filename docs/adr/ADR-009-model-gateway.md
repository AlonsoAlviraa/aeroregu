# ADR-009 Model gateway

- Status: accepted
- Date: 2026-11-03

## Context

A model may draft text. It must not be the source of a number. CI must not call a network model.

## Decision

Interface `complete(agent_id, messages, schema)`. Implementations: `fixture` (default, used in CI) and `openai_compatible` behind `MODEL_BASE_URL`. Weights are not committed. Each agent has its own prompt file. The prompt hash is the method version of that turn. Temperature is stored and is not determinism. MVP budget per case: 4 turns, each at most 8000 input tokens, 1000 output tokens, and 30 seconds, then abstain. Agents do not get tools that execute calculations. The only calculation call is the supervisor invoking the method registry.

Token counts in the budget use a 4-character estimate. That estimator is an **ASSUMPTION**, not a model tokenizer.

## Alternatives

A tool-calling framework is deferred until a fifth agent needs a tool loop. Pydantic AI is not in the MVP runtime.

## Consequences

CI leaves `MODEL_BASE_URL` unset. Invalid JSON, timeout, and budget exhaustion abstain and store no number. LLM draft confidence cannot be `deterministic`.
