---
name: connector-export
description: >-
  Exports requirement, evidence, and gap rows for a human to import elsewhere.
  Use in Phase 5. The connector is one-way and is not built in the MVP.
---

# Connector export

Phase 5 only. Do not build connectors in the MVP.

## Steps

1. Read ADR-019.
2. Export from ledger rows only.
3. One-way. No write-back.
4. No network call to an external requirements tool in tests.
5. A golden file asserts requirement id, evidence hash, and gap id survive the export.

## Inputs and outputs

- Inputs: a tenant ledger.
- Outputs: a file the human imports.

## Validation

- The export contains no Decimal that is absent from the ledger.
- The MVP does not create `packages/connectors` and does not store a live vendor token.

## Example

A gap cell would export as a row with status `gap` and an empty evidence hash. That exporter is specified here and not implemented.
