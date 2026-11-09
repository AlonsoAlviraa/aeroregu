# ADR-018 Qualification pack

- Status: accepted
- Date: 2026-11-03

## Context

A customer might later want a folder about the tool. The folder must not be mistaken for a qualification.

## Decision

A future Phase 6 folder may contain tool requirements we wrote, test names, benchmark metrics, method versions, an SBOM, and known limits. The folder says the tool assists a human. It does not say the tool is qualified under DO-330, and it does not assign a tool qualification level. FAA AC 20-115D remains a reading item: https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC_20-115D.pdf . This implementation did not re-read that PDF. Structural-analysis tool qualification is **NOT VERIFIED** and out of scope.

## Alternatives

Writing a tool qualification level in the MVP was rejected.

## Consequences

`tools/pack` is not created. A grep gate against "qualified" and "TQL" applies when the pack exists, not before.
