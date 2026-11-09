---
name: add-product-agent
description: >-
  Adds an id to the product-agent registry. Use when a phase gate opens a new
  agent. The agent gets its own prompt file and no import of the calc
  implementation.
---

# Add a product agent

## Steps

1. Read ADR-015 and ADR-016.
2. Add the id only if the phase gate for that id is open. The MVP registry accepts only `reader`, `checker`, `refuter`, and `scribe`.
3. Create `packages/kernel/prompts/<agent_id>.md` as a different file from every other agent.
4. Hash the file in tests.
5. Declare the output schema.
6. Add a fixture turn.
7. Add a test that a stray physical number not copied from a calc event is rejected.
8. The agent does not import the calc implementation. Only the supervisor may call it.

## Inputs and outputs

- Inputs: agent id, prompt, output schema.
- Outputs: prompt file, registry row, tests.

## Validation

- CI fails if `reader.md` and `refuter.md` are byte-identical.
- Later ids listed in ADR-016 are rejected until their phase gate opens.

## Example

`scribe` may echo a decimal string only when that exact string is already on the referenced calc event.
