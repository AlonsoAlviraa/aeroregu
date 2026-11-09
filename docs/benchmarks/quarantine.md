# Quarantine: duplicate citation

Date: 2026-11-03. ESTIMATE from one synthetic case.

A clean bolt-screen note was given two requirement ids, `VTOL.2210` and `VTOL.2215`, for the same quotation. The checker returned `clean`. `detect.py` does not contain the fault id `duplicate_citation`.

VERIFIED: `packages/eval/tests/test_quarantine.py` passed on that case.

This is a known miss. It is not in the frozen dev sets. Do not add a detector in the same change that relaxes this test. The expert held-out set was not used.
