---
name: agent-disagreement-abstain
description: >-
  Abstains when two product agents label the same field differently. Use when
  comparing labels. There is no vote and no confidence average.
---

# Agent disagreement abstain

## Steps

1. Compare labels only, never numeric magnitudes the agents invented.
2. On mismatch write `abstain` with `reason: agent_disagreement` and both turn hashes.
3. Do not implement a vote, a confidence average, or a third model as a tie-break.

## Inputs and outputs

- Inputs: two agent turns.
- Outputs: one abstain event.

## Validation

- A test with `VERIFIED` versus `NOT_VERIFIED` on the same source id abstains.
- The abstain event has no numeric payload and no result.

## Example

The reader marks a title `VERIFIED` and the checker marks it `NOT_VERIFIED` because the title was not in the span. The supervisor abstains.
