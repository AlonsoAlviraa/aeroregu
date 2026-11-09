# ADR-011 Audit

- Status: accepted
- Date: 2026-11-03

## Context

Two logs that can disagree destroy the point of a hash chain.

## Decision

Audit is the ledger. Application logs are operational and are not evidence. Export includes the chain and a verifier command.

## Alternatives

A separate audit table was rejected.

## Consequences

A sign-off that is not in the chain did not happen. Operational stdout is not a finding.
