---
name: pr-review-adversarial
description: >-
  Reviews a change as an independent reviewer with no commits on the branch.
  Use on every PR. The reviewer does not push fixes onto the author's branch.
---

# Adversarial PR review

## Steps

1. Read `docs/workstreams.md`. Reject edits outside the workstream.
2. Run pytest.
3. For calc changes, add one Hypothesis example that tries to break the stated invariant.
4. For ledger changes, attempt an update.
5. For ingest changes, feed a text-less PDF fixture and require abstain.
6. For gateway changes, search the diff for numeric literals inside prompt strings that look like engineering results.
7. Run the security checklist skill.
8. Comment with labelled findings. The result is approve or block.

## Inputs and outputs

- Inputs: the diff and the test command output.
- Outputs: an approve or block review.

## Validation

- The reviewer does not push fixes onto the author's branch.
- A red review blocks merge. Only the founder overrides it, with a written reason.

## Example

A parser that fills a missing thickness with a guessed quantity is a block.
