# ADR-008 Supervisor

- Status: accepted
- Date: 2026-11-03

## Context

Product agents draft and attack text. The transition that appends to the ledger must be auditable. Build agents that write this repository are a different population.

## Decision

A Python state machine. States: `ingest -> reader -> validate_schema -> check_spans -> maybe_compute -> checker -> refuter -> scribe -> append -> stop`. Any state may go to `abstain`. No LangGraph, CrewAI, or AutoGen in the product runtime. Reader and refuter use different prompt files. A refuter hit does not append the draft. Label disagreement abstains. There is no vote. The scribe may only paraphrase ledger fields.

## Alternatives

One prompt that reads, checks, and refutes was rejected because the refuter would share the drafter's context.

## Consequences

CI fails if the reader and refuter prompts are byte-identical. Fixture mode runs the same graph with canned turns and zero model network calls. The calc step still runs for real.
