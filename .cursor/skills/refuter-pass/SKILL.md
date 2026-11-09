---
name: refuter-pass
description: >-
  Changes the refuter or the supervisor's handling of an attack. Use when a
  hit or miss decision, a bad span, or a missing input should abstain instead
  of storing a draft finding.
---

# Refuter pass

## Steps

1. The refuter output is `{attack: hit|miss, reason, evidence_span}`.
2. `hit` on a bad span, a broken hash, a coverage claim with no cell id, or a missing input forces abstain.
3. `miss` allows append.
4. The refuter must not call the model gateway a second time.
5. Tests include one hit and one miss fixture.

## Inputs and outputs

- Inputs: draft turn and calc event hash.
- Outputs: one refuter turn and the supervisor decision.

## Validation

- A hit leaves no draft result on the ledger.
- The evidence span must be an exact slice or the turn is dropped.

## Example

A quotation that is not an exact slice is a hit. The supervisor writes an abstain event and does not append the draft.
