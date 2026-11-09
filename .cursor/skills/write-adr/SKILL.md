---
name: write-adr
description: >-
  Writes an architecture decision record under docs/adr. Use when a
  dependency, service, schema break, storage choice, or model provider
  is introduced or changed.
---

# Write an ADR

## Steps

1. Read root AGENTS.md and the existing files in `docs/adr`.
2. Copy `docs/adr/0000-template.md`.
3. Name the file `docs/adr/NNNN-short-title.md` with the next number.
4. Fill status (`proposed` or `accepted`), date, context, decision, alternatives, consequences.
5. Label each external fact `VERIFIED` with URL and access date, or `ASSUMPTION`, or `ESTIMATE`.
6. State what was considered and why the decision fits one developer and the numeric rule.
7. If the decision adds a running service, include the reason a function or SQLite is not enough.
8. Link the ADR from the PR handoff. Do not mark it accepted unless the founder has accepted it. Agents may mark status `proposed`.

## Inputs and outputs

- Input: the decision, the alternatives, the constraints it touches.
- Output: one markdown file.

## Validation

- No unlabeled external numbers.
- No secrets.
- The decision does not contradict root AGENTS.md. If it must, stop and escalate.

## Example

A proposal to add Postgres lists SQLite-per-tenant as the current decision, states the measured limit that was hit, and stays `proposed` until the founder accepts it.
