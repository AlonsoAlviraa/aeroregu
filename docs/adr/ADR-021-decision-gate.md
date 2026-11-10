# ADR-021 Decision gate

- Status: accepted
- Date: 2026-11-10

## Context

Jev and Microsoft-Decision-1 score a fixed set of options. They do not recompute a physical quantity, and they are not a certification method. The four drafting agents stay the MVP roster. A fifth role may only choose a state the supervisor already knows.

## Decision

`decision_gate` is registered beside `reader`, `checker`, `refuter`, and `scribe`. It is off unless `CaseSpec.use_decision_gate` is true. The fixture returns `decision` (`continue` or `abstain`) and `gate_probability` as a decimal string. The supervisor abstains when the decision is not `continue` or when the probability is below `0.800`. That abstain envelope has no `result`. The OpenAI-compatible adapter does not call the network for this id; the reason is `decision_gate_fixture_only`. Later ids in ADR-016 stay rejected. This ADR does not assign a tool qualification level.

## Alternatives

Putting the gate on every case was rejected because the budget is still four drafting turns. Treating the score as a load was rejected.

## Consequences

CI stays on the fixture gateway. A hosted decision model is a later measurement, not this commit.
