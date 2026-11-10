# External review request

This tool assists a human reviewer. It does not determine compliance.

NOT VERIFIED: signed reviews are 0. No external engineer has reviewed this repository. This file is a request. It names the subset. It does not name a reviewer. It is not a completed review. It does not claim certification, authority acceptance, or a qualified tool. The 12-month programme is not complete. `programme_complete` is false. The repository is https://github.com/AlonsoAlviraa/aeroregu. That remote is not a signed review.

Date opened: 2026-11-04. Not legal advice.

## What to review

A subset, not the whole programme.

`make bench` on 2026-11-09 exited 0 in one process, elapsed 2436016 ms. The lines in `docs/benchmarks/make_bench_latest.md` come from that run. The counts in that file stay as written. This request does not replace them.

Read:

- `docs/reports/2026-11-03-interim.md`, current status section dated 9 November 2026
- `docs/benchmarks/make_bench_latest.md`, written by that `make bench`
- `docs/benchmark_spec.md`
- `docs/data_register.md`, including the Zenodo bearing zip row, the AS365-K2 row, and the HUMS2025 row

From that run:

- B1 has 0 expert cases. Not scored.
- B2: the specialist chain ties the hash-checking verifier at 8/8 and does not beat it, so `beats_no_agent` is false. The chain ledger `llm_numeric_violation` is 0. Single-LLM is NOT_VERIFIED.
- B3: the gold is same-session. `ready` is false. Both NASA gold sets were written in this project and are not held-out sets.
- B4 is not ready. `data_SSF.zip` abstains because the stored numbers have no unit (`unit_not_in_file`). The AS365-K2 UFF header states m/s^2, is 90 seconds at 8192 Hz against an article figure of 60 seconds, and is not scored. No sample from that file was stored.
- Duplicate citation on that run remains recall 0/1. That line is the recorded count. It is not a detection.

## Code checks after that run

Later items are code checks after the 2436016 ms `make bench`. They are not a new 100000-case run:

- An unrecomputed integer abstains.
- A present fault with recall 0 fails the bench. That gate does not replace the recorded recall 0/1 from the run that exited 0.
- B4 `unit_mismatch` abstains, does not convert, and stores no samples.
- The temporary same-unit count of 2 is not the public B4 result.
- HUMS2025 was opened on 2026-11-09, was not downloaded, and does not make B4 ready.

## What a review must not say

- That the tool determines compliance or certification
- That the 12-month programme is complete, or that B4 is ready
- That B1, B2, B3, or B4 is an expert-authored held-out result
- That a single-LLM baseline was run, or any LLM score
- That `data_SSF.zip` was scored, or that an in-file B4 exceedance limit was found
- That the temporary same-unit count of 2 is the public B4 result
- That opening HUMS2025 makes B4 ready
- That the later code checks are a new 100000-case `make bench`
- That folder names `Ball`, `CA`, `IN`, and `OU` are the published codes `BF`, `CF`, `IRF`, and `ORF`
- That this request has been sent, or that any review is signed

## Before asking someone

Five rows in `docs/legal/open_items.md` are OPEN, including the expert's contract and export control. This request must not be sent outside the EU while the export-control row is OPEN. Do not ask a domain expert to author `bench/b1/expert_holdout` while that contract row is OPEN, unless the expert accepts the risk in writing. B1 stays at 0 expert cases. The checker author does not fill that directory.

Two reviewers are required. Both must be outside the two founders. This file does not name them. A review is closed only when each person writes their name, the date, and which files they read. Signed reviews: 0.
