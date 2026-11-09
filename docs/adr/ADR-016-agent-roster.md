# ADR-016 Agent roster and disagreement

- Status: accepted
- Date: 2026-11-03

## Context

The product is a supervised team. Adding agents without a protocol would hide the audit trail.

## Decision

MVP roster: `reader`, `checker`, `refuter`, `scribe`. Post-MVP roster, one agent per concern, each added only with the `add-product-agent` skill: `moc_drafter`, `envelope_critic`, `change_narrator`, `criterion_librarian`, `connector_exporter`, `qualification_clerk`, `bench_attacker`, `tenant_policy`. The bench attacker would write candidate faults into a quarantine directory. The frozen scorer would grade them. The attacker never writes the expected label. The envelope critic may propose `not_in_envelope` and cannot set that status. Only a human actor can. Disagreement or a refuter hit abstains. There is no majority vote.

## Alternatives

A confidence average or a third model as a tie-break was rejected.

## Consequences

The later agents are named and rejected by the registry. They are not implemented.
