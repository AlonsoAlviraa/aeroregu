---
name: synthetic-data-generator
description: >-
  Creates invented aircraft, load inputs, notes, or matrices with provenance.
  Use when generating synthetic domain data. Refuses real aircraft names and
  employer paths.
---

# Synthetic data generator

## Steps

1. Set provenance `origin=synthetic`, `author=aeroregu`, `generator_version`, and a statement that the object is invented.
2. Refuse inputs that name a real aircraft, a real operator, or a file under an employer workspace.
3. Build loads by calling the calc package.
4. Record the seed integer `20261103` for any random choice.
5. Write JSON under `packages/domain/data`.

## Inputs and outputs

- Inputs: seed and generator version.
- Outputs: versioned JSON plus provenance.

## Validation

- Provenance schema passes.
- A test fails if a forbidden real-world name appears.
- Rerunning the generator yields the same file hash.

## Example

Aircraft `SL-1`, four lifting units, masses chosen in the generator file, label `ASSUMPTION` on the mass values.
