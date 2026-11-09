---
name: source-citation-and-labeling
description: >-
  Labels a claim VERIFIED, PARTIAL, NOT_VERIFIED, ASSUMPTION, or ESTIMATE.
  Use when writing prose, method cards, dataset records, UI strings, or PR
  text that states a fact.
---

# Source citation and labeling

## Steps

1. Choose one label per claim.
2. `VERIFIED` needs URL, access date, and content hash of the file read.
3. `PARTIAL` splits the sentence and says which part is which.
4. `NOT_VERIFIED` is the default when a source was not opened in this task.
5. `ASSUMPTION` names the choice. `ESTIMATE` shows the arithmetic.
6. Do not upgrade a label because a previous document used it.

## Inputs and outputs

- Inputs: the claim and the file that was read.
- Outputs: a citation object valid against `schemas/citation.schema.json`.

## Validation

- A unit test rejects `VERIFIED` without a 64-character content hash.

## Example

A price is `VERIFIED` only next to the vendor URL, the date it was fetched, and the hash of the page that was read. A URL copied from a plan without opening the file stays `NOT_VERIFIED`.
