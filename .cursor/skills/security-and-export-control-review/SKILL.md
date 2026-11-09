---
name: security-and-export-control-review
description: >-
  Runs the founder security and export-control checklist before a merge or
  before any discussion of making the repo public. This is a checklist for
  founders, not legal advice.
---

# Security and export-control review

## Steps

1. Run the secret scan. Run gitleaks locally when the binary is installed.
2. Confirm no `.env` is tracked.
3. Confirm the diff contains no files from an employer workspace.
4. Confirm no CAD, no material allowables tables, and no real geometry.
5. Confirm the kernel denylist is clean.
6. Confirm new dependencies have a one-line reason.
7. If the PR mentions non-EU disclosure, military, or dual-use, stop and tell the founder to review Regulation (EU) 2021/821 and Ley 53/2007 with counsel. Reading item, not a legal conclusion: https://www.boe.es/buscar/act.php?id=BOE-A-2007-22437

## Inputs and outputs

- Inputs: the git diff.
- Outputs: a pass or block per checklist item.

## Validation

- A fixture secret in a test diff is a block.
- This skill does not clear export control and is not legal advice.

## Example

A PDF added under `packages/domain` without a provenance record is a block.
