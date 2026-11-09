---
name: docs-and-demo-script
description: >-
  Edits the README, the demo page copy, or docs/demo/storyboard.md. Use when
  changing words a human will read in the demo. Keeps the assistance sentence
  and blocks compliance claims.
---

# Docs and demo script

## Steps

1. Keep the sentence "This tool assists a human reviewer. It does not determine compliance."
2. Walk the 5-minute script in `docs/demo/storyboard.md`.
3. List what is synthetic.
4. List what was not verified.
5. Do not use "certified", "compliant", or "EASA accepted" except inside a forbidden-claims section.

## Inputs and outputs

- Inputs: the features that actually pass tests.
- Outputs: storyboard and README limits.

## Validation

- A grep test fails if the demo template contains "compliant".
- The demo template does not state a valuation.

## Example

Minute marks: banner, requirement ids, one load case, coverage with a calc cell and a gap, a unit-scale note flagged by recomputation, a missing-thickness note that abstains, zip export, reviewer sign-off.
