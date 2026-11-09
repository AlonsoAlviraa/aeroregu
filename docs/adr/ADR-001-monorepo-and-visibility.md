# ADR-001 Monorepo and visibility

- Status: accepted
- Date: 2026-11-03

## Context

One developer is building an evidence product. A public generic layer and a private domain layer must not be mixed. Employer material must not enter the repo.

## Decision

One private git repo. `packages/kernel` has zero domain vocabulary and must not import `packages/domain`. A denylist fails if kernel sources match `VTOL`, `EASA`, `rotor`, `helicopter`, `eVTOL`, `Airbus`, or `SC-VTOL`. The repo stays private until an export-control checklist is signed. That signature does not exist. This ADR is not that signature.

## Alternatives

Two repositories from day one. The cost is higher for one developer, so the split is by package and import direction first. A public repo in week 1 is rejected until that checklist is signed.

## Consequences

Kernel tests scan the kernel tree. Domain code may name the public requirement ids. Making the repo public is a later decision, not a current fact.
