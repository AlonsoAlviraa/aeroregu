# ADR-006 Ledger

- Status: accepted
- Date: 2026-11-03

## Context

The audit product is a hash chain. A second log that can disagree with the chain is not evidence.

## Decision

Append-only SQLite table. Triggers reject `UPDATE` and `DELETE`. `event_hash` is the hex SHA-256 of the ASCII concatenation of `prev_hash` and the hex SHA-256 of the RFC 8785 canonical body. Genesis `prev_hash` is 64 zero hex characters. One database file per tenant.

Human sign-off stores the actor id, the statement "reviewed this event", and the target event hash. The statement must not contain the word compliant. Abstain events have no numeric payload and the envelope omits `result`.

## Alternatives

Postgres from day one is the same SQL later and more operations now. A blockchain is unnecessary. A hash chain in SQLite is the audit product.

## Consequences

Anyone who can rewrite the file and rebuild the chain can forge rows. Disk encryption of the tenant directory is a founder responsibility for a pilot. Verification walks from genesis to the head.
