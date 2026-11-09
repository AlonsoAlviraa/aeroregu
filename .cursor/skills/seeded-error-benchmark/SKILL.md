---
name: seeded-error-benchmark
description: >-
  Adds seeded faults, clean controls, and metric checks for the evidence
  benchmark. Use when creating benchmark cases, fault injectors, recall
  metrics, or the holdout split.
---

# Seeded-error benchmark

## Steps

1. Read root AGENTS.md, ADR-010, and `packages/eval/AGENTS.md`.
2. Add cases only under `bench/dev` unless the founder has asked to create the holdout.
3. Each case is JSON valid against `schemas/benchmark_case.schema.json` with `case_id`, `artifact_kind` (`note` or `matrix`), `faults` (list, possibly empty), `expected` (`detect:<fault_id>` or `abstain` or `clean`), and `provenance.generator_version`.
4. Inject faults only through functions in `packages/eval/src/evidence_eval/faults.py`. Do not hand-edit expected numbers. Generate the correct note with the calc package, then apply one fault function.
5. Allowed fault ids: `unit_scale`, `arithmetic`, `wrong_input`, `sign`, `stale_revision`, `false_coverage`, `broken_hash`, `bad_span`, `outside_validity`, `missing_input`.
6. `missing_input` expects abstain and forbids a numeric `result`.
7. Score with `uv run python -m evidence_eval score --split dev`.
8. Do not open, edit, or cite `bench/holdout` while changing detectors.

## Inputs and outputs

- Input: a fault id and a clean calc result.
- Output: a benchmark case file and a passing scorer assertion for that fault on the dev split.

## Validation

- The clean parent and the faulty child both validate against the schema.
- Deterministic faults `unit_scale`, `arithmetic`, `wrong_input`, `sign`, and `outside_validity` score recall 1.0 on the cases you added.
- The scorer reports `llm_numeric_violation` separately and the new case contributes 0.

## Example

Start from a bolt check whose true interaction is `0.500`. The `unit_scale` injector multiplies the stated force by 1000 and tags `unit_scale`. The checker recomputes `0.500` and flags the stated value. The expected field is `detect:unit_scale`.
