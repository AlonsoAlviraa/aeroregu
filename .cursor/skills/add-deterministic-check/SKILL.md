---
name: add-deterministic-check
description: >-
  Adds a pure deterministic engineering check with a method card, Decimal
  vectors, and property tests. Use when adding a calculation, margin,
  load case, unit check, or any code that emits a number.
---

# Add a deterministic check

## Steps

1. Read root AGENTS.md and `packages/calc/AGENTS.md`.
2. Read `docs/adr/ADR-003-deterministic-engine.md`.
3. Create `packages/calc/cards/<method_id>.json` with `method_version`, equation description, input units, output quantum, validity limits, and sources labelled `VERIFIED` or `ASSUMPTION`.
4. If no public source has been read, set the formula's source label to `ASSUMPTION` and the card title to "project-defined screening check". Do not attribute it to a handbook.
5. Write failing tests first in `packages/calc/tests/test_<method_id>.py`:
   - one exact vector with inputs and outputs as decimal strings
   - one input outside the validity card that raises `Abstain`
   - one Hypothesis test for an invariant named in the card (for the point-mass load method: vertical force balance within one quantum)
6. Implement `packages/calc/src/evidence_calc/<method_id>.py` as a pure function. Use `decimal.Decimal` only. Quantize with the card's quantum, rounding `ROUND_HALF_EVEN`.
7. Register the method in `packages/calc/src/evidence_calc/registry.py`.
8. Run `uv run pytest packages/calc/tests/test_<method_id>.py`.
9. Confirm the result envelope can carry `method_version` and `inputs_hash`.

## Inputs and outputs

- Input: method id, equation, units, quantum, validity limits, source notes.
- Output: card JSON, pure function, tests, registry entry.

## Validation

- No `float` in the new module.
- Re-running the exact vector produces the same output strings.
- An out-of-range input abstains and emits no number.
- The card's source labels are present.

## Example

A project-defined bolt screening check computes shear stress and tensile stress and an interaction ratio `sqrt(rs^2 + rt^2)` quantized to `0.001`. A vector with area zero abstains. The card says the check is a screening illustration, not a certification method.
