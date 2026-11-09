# ADR-002 Language

- Status: accepted
- Date: 2026-11-03

## Context

The MVP has to serve JSON, one HTML page, and deterministic numeric code. A second language would slow the first weeks.

## Decision

Python 3.12 only. FastAPI serves JSON and one static HTML file. There is no React UI.

## Alternatives

A Rust core plus a Python shell is stronger for numeric parity later and too much toolchain for week 1. A React UI is a second language for a 5-minute demo.

## Consequences

Numeric parity is CPython `decimal` on Ubuntu and Windows CI, compared by hash. The demo page is static HTML.
