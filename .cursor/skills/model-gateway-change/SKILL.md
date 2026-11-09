---
name: model-gateway-change
description: >-
  Changes the model gateway, a prompt, a timeout, or a token budget. Use when
  adding a provider or editing product-agent prompts. Keeps fixture as the
  default so CI makes no model network calls.
---

# Model gateway change

## Steps

1. Read ADR-009.
2. Keep `fixture` as the default.
3. Add a provider as a new module that speaks the OpenAI chat-completions subset.
4. Record prompt files under `packages/kernel/prompts` and hash them into `method_version`.
5. Enforce the budget and map timeout or invalid JSON to abstain.
6. CI must pass with `MODEL_BASE_URL` unset.
7. Do not log prompt bodies that might later contain customer text. MVP logs only hashes and token counts.

## Inputs and outputs

- Inputs: provider name and base URL from the environment.
- Outputs: adapter, tests with a local fake HTTP server, budget test.

## Validation

- The fake server is never contacted when the provider is `fixture`.
- A schema-invalid completion abstains and stores no number.
- Reader and refuter prompt files are not byte-identical.

## Example

An adapter test points at `http://127.0.0.1` from a local fake server. The budget is 4 turns, 8000 input tokens, 1000 output tokens, and 30 seconds.
