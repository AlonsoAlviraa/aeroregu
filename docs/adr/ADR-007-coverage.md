# ADR-007 Coverage

- Status: accepted
- Date: 2026-11-03

## Context

A coverage claim needs a grid a human can recompute. The axes are an **ASSUMPTION** pending an expert.

## Decision

Code generates the cartesian grid. Axes: mass min/mid/max, longitudinal CG forward/mid/aft, load factor nominal/limit-positive/limit-negative, and unit state all-operative plus one failed unit at a time. Four units give `3*3*3*5 = 135` cells. Altitude is not an axis: the load method does not use it. Status is `calc`, `justified_not_critical`, `gap`, or `not_in_envelope`. A gap list is a query. A mass change of 5 percent writes `invalidated` events for cells whose input hash no longer matches. `not_in_envelope` is set only by a human actor.

## Alternatives

An expert hand-picking 20 cases with no grid is a weaker demo. That fallback is kill-scope, not the start.

## Consequences

The grid is a defined illustration. It is not a claim that every critical condition of a real aircraft was analyzed.
