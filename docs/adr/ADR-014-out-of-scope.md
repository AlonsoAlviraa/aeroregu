# ADR-014 Out of the 8-week build

- Status: accepted
- Date: 2026-11-03

## Context

The company path needs schemas so later work has a boundary. Building that work now would miss the 8-week proof.

## Decision

Not in this build, and not cancelled: criterion-card content, ReqIF and requirements-tool export, a qualification evidence pack, extra agents, CS-27, CS-29, SORA, customer hosting, and billing. They are specified in ADR-016 through ADR-020 and blocked until a later phase. Still refused until a method card exists: Nastran, CAD, CFD, FEA, OCR, flight-test reduction, and any claim of authority acceptance.

## Alternatives

Building connectors or a qualification kit in the MVP was rejected.

## Consequences

`packages/connectors`, `packages/domain/criteria`, and `tools/pack` are absent on purpose. Their schemas and ADRs are present.
