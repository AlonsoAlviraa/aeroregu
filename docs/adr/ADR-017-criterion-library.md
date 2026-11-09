# ADR-017 Criterion library

- Status: accepted
- Date: 2026-11-03

## Context

Expert rules for "not critical" and for which method applies are the moat an LLM does not bring with it. That statement is an **ASSUMPTION**. The rules are not built in the MVP.

## Decision

The future home is `packages/domain/criteria/`. Each card has an author actor, applicability limits, requirement ids, and a label. The schema is `schemas/criterion_card.schema.json`. Prompts may quote a card by id. Prompts may not be the only copy of a rule. Customer dossiers may contribute structure only under a contract that allows it. That contract does not exist. Reuse of customer geometry or numbers is forbidden even then. A card with no human author is invalid.

## Alternatives

Storing the rule only in a prompt was rejected.

## Consequences

Phase 4 is specified and not started. The criteria directory is not in this commit.
