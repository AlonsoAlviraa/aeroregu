# Deterministic Unit & Dimensional Benchmark (`unit_bench`)

> **Disclaimer**: This tool assists a human reviewer. It does not determine compliance.

## Epistemic Status & Provenance

- **Benchmark Label**: `ESTIMATE` — Curated 30-case deterministic unit conversion, dimensional signature, and calc-card unit mismatch suite.
- **Unit Registry Arithmetic**: `VERIFIED` — multiplicative intervals are evaluated in `Decimal` (`non_int_type=Decimal`) with `float_used == False`.
- **Screening Cards**: `ASSUMPTION` — `rigid_body_point_mass` and `bolt_screen` are project-defined screening illustrations.
- **External Held-Out Set**: `NOT_VERIFIED` — this suite is an internal deterministic verification benchmark, not an external blind holdout.

## Summary Metrics

- **Total Cases**: `30`
- **Passed**: `30` (`30/30`, rate `1.000`)
- **Wilson 95% CI**: `[0.886, 1.000]`
- **Float Used**: `False`
- **`llm_numeric_violation`**: `0`

## Category Breakdown

| Category | Passed / Total | Wilson 95% CI |
| --- | --- | --- |
| `multiplicative_interval` | `10/10` | `[0.722, 1.000]` |
| `compatibility_and_same_unit` | `8/8` | `[0.676, 1.000]` |
| `dimension_signature` | `5/5` | `[0.566, 1.000]` |
| `offset_unit_refusal` | `3/3` | `[0.438, 1.000]` |
| `calc_card_unit_enforcement` | `4/4` | `[0.510, 1.000]` |
