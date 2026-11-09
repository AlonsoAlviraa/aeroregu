# ADR-019 Connectors

- Status: accepted
- Date: 2026-11-03

## Context

A buyer may already have a requirements tool. Replacing it in eight weeks was rejected.

## Decision

A future Phase 5 export may emit requirement, evidence, and gap rows as ReqIF or as CSV/JSON a human imports. The connector does not write back, does not become the customer's requirements tool, and does not receive a live token in the MVP. There is no connector package in this commit.

## Alternatives

Two-way sync is deferred until a pilot contract names the system of record.

## Consequences

The MVP has a zip of its own hash chain. That zip is not a vendor connector.
