---
name: criterion-card
description: >-
  Records an expert criticality or method-selection rule as data. Use from
  Phase 4, not in the 8-week build. A card without a human author is rejected.
---

# Criterion card

Phase 4 only. Do not add cards during the MVP.

## Steps

1. Write JSON against `schemas/criterion_card.schema.json` with author actor, requirement ids, applicability, and a label.
2. The card is data. A prompt may cite the card id. The prompt must not be the only copy of the rule.
3. Reject a card with no human author.
4. Reject a card that contains a customer or employer file path.
5. Customer dossiers may contribute structure only under a contract that allows it. That contract does not exist in the MVP.

## Inputs and outputs

- Inputs: the expert's written rule.
- Outputs: one card and, later, a ledger event `criterion_accepted`.

## Validation

- An envelope-critic proposal does not change cell status.
- The MVP does not ship a criteria directory.

## Example

A rule that a failed unit at minimum mass is not critical for SL-1 would be a card, status `ASSUMPTION`, author `expert`, and it would not apply to any other aircraft. That card is not created in this MVP.
