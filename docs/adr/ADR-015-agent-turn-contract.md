# ADR-015 Agent turn contract

- Status: accepted
- Date: 2026-11-03

## Context

A demo has to show who said what. The turn has to be data, not a hidden framework state.

## Decision

`schemas/agent_turn.schema.json` is in the repo even though only four agents run. Fields: `agent_id`, `prompt_hash`, `input_event_hashes`, `output`, `envelope`. Temperature is stored as a string. Allowed MVP ids: `reader`, `checker`, `refuter`, `scribe`. Later ids are listed in ADR-016 and rejected by the MVP registry. A turn can be a ledger event on the success path. A refuter hit does not store the draft as a finding.

An agent turn is invalid if its JSON contains a physical number that is not an exact copy of a Decimal string already stored on a calc event.

## Alternatives

Letting the model return the envelope confidence `deterministic` was rejected.

## Consequences

LLM method versions look like `llm_extract@<prompt-hash>` and their confidence is `quoted` or `draft`, never `deterministic`.
