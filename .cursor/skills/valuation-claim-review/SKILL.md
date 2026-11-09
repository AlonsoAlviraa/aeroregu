---
name: valuation-claim-review
description: >-
  Reviews decks, README text, UI strings, and agent prompts that mention
  money, customers, or valuation. Use whenever a valuation or customer count
  might be stated as a forecast. Blocks that language in the product UI.
---

# Valuation claim review

## Steps

1. Read ADR-020.
2. Allow a mention only with label `ASSUMPTION` or `NOT_VERIFIED`.
3. Block a valuation figure, revenue, and customer counts in `apps/` and in product prompts.
4. Point the author at ADR-020. A valuation is a vision gate, not a forecast.

## Inputs and outputs

- Inputs: the diff.
- Outputs: pass or block.

## Validation

- The demo page fails CI if it contains the digits 100.
- Product prompts must not state a valuation as expected, likely, or supported by revenue.

## Example

A prompt that says the company will be worth a stated sum is a block even inside a fixture.
