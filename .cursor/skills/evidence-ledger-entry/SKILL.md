---
name: evidence-ledger-entry
description: >-
  Appends an evidence or audit event to the hash-chained ledger. Use when
  recording a calc result, citation, coverage change, abstain, or human
  sign-off. Never update or delete prior events.
---

# Evidence ledger entry

## Steps

1. Read root AGENTS.md and ADR-006.
2. Build the event body without a hash. Required fields: `event_type`, `tenant_id`, `actor_id`, `created_at` (ISO-8601 UTC), `payload`, `envelope` (the standard output envelope).
3. Canonicalize the body with RFC 8785. Compute `event_hash` from the previous hash as ADR-006 states.
4. Insert one row. Do not provide an update API.
5. Human sign-off is event type `human_signoff` and stores only actor id, statement "reviewed this event", and the hash of the event being signed. The statement must not contain the word compliant.
6. Tests in `packages/kernel/tests/test_ledger.py` cover append, chain verification, rejected update, rejected delete, and a tampered row failing verification.
7. Re-open the same inputs and confirm `inputs_hash` is unchanged.

## Inputs and outputs

- Input: tenant database path, previous hash, event body.
- Output: new row and its `event_hash`.

## Validation

- `UPDATE` and `DELETE` fail at the database.
- Verification walks from genesis to the head.
- Abstain events have no numeric payload.
- Two tenants are two files. A test proves a query against tenant A cannot see tenant B.

## Example

A calc event for method `rigid_body_point_mass@1.0.0` stores the input document hash and the Decimal outputs. A later `human_signoff` points at that event hash. Deleting the calc event is impossible through the repository API.
