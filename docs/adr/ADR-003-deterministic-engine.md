# ADR-003 Deterministic engine

- Status: accepted
- Date: 2026-11-03

## Context

Every numeric claim must be recomputable. JSON floats make hashes depend on formatting.

## Decision

Methods are pure functions. Inputs and outputs are `decimal.Decimal`, serialized as strings, quantized half-even to the increment on the method card. No `float` in calc modules. CPython `decimal` is the reference runtime. The same vectors run on Windows and Ubuntu and the input hashes are compared.

The point-mass card is a project-defined screening illustration. Label `ASSUMPTION`. Newton's laws are written by this project, not attributed to a handbook. The bolt card is a screening illustration, not a certification method. Its interaction ratio is `sqrt(rs^2 + rt^2)` quantized to `0.001`. Area zero abstains.

## Alternatives

Binary float with a tolerance was rejected because hashes then depend on formatting. Integer millinewton arithmetic was dropped because area divisions need a recorded scale. Decimal with an explicit quantum is the single rule.

## Consequences

A missing input or a value outside the card abstains and emits no number. The vertical force balance must stay within one quantum. This is not a loads certification method.
