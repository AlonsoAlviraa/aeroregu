---
name: coverage-map-update
description: >-
  Updates the coverage envelope, cell status, gap query, or a change-impact
  rule. Use when adding an axis, a cell status, a gap query, or mass-change
  invalidation.
---

# Coverage map update

## Steps

1. Read root AGENTS.md and ADR-007.
2. Change `schemas/coverage_cell.schema.json` only with the contracts owner.
3. Generate cells in `packages/coverage` from explicit axes.
4. Represent status as a new ledger event (`cell_status_set`) rather than an update.
5. A `+5%` mass change writes `invalidated` events for cells whose input hash no longer matches.
6. Tests assert cell count `3*3*3*3*(1+n_rotors)` for the default axes and assert a missing cell is a `gap`.

## Inputs and outputs

- Inputs: axis definitions and calc input hashes.
- Outputs: cell records and a gap list.

## Validation

- No status without a ledger hash.
- Expert exclusions use status `not_in_envelope` with a human actor, never a silent filter.

## Example

Failing unit 2 at max mass is `gap` until a calc event cites that cell id.
