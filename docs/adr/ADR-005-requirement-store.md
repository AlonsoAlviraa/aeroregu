# ADR-005 Requirement store

- Status: accepted
- Date: 2026-11-03

## Context

The demo needs a small public identifier list, not a copy of a regulation.

## Decision

Requirement rows carry id, title, source URL, source file hash, and review label. The demo seeds eight ids: VTOL.2200, VTOL.2205, VTOL.2210, VTOL.2215, VTOL.2220, VTOL.2225, VTOL.2230, and a non-computable Subpart C parent node. Official URLs are stored. The local file hash is a placeholder with label `NOT_VERIFIED` because this repo did not hash a downloaded PDF. Titles that were not taken from a hashed local file are `NOT_VERIFIED`. Paragraph text is not copied into git.

## Alternatives

Modelling an entire regulatory document is out of the 8-week scope.

## Consequences

A parser may mark a title `VERIFIED` only relative to a synthetic fixture whose bytes were hashed. That label is not a claim about an authority file.
