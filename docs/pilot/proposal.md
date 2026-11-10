# Pilot proposal draft

The S1 rates of 100000 cases, 7000/7000 scored faults, and zero false positives are the generator scoring itself and must not be shown as external performance.

Date: 2026-11-03. This draft is not ready to send. It names no design partner. It is not an offer, a certification claim, or legal advice.

## What would be shown

`make bench` on 2026-11-09 exited 0, one process, elapsed 2436016 ms. One command scores the smoke set, S1, and the B1–B4 status. `B2 public headings only` is true. S1 is generator `s1@1.0.0`, 100000 invented cases. The seed label is `20261103`. It does not drive a random sampler. The rates below are ESTIMATE counts from that run. They are not an external result. They match the earlier 2026-11-09 runs and the 2026-11-03 run. `docs/benchmarks/s1_latest.md`, written 2026-11-10 by `run_s1`, repeats the 100000-case counts and adds false alarms of 0/4000 on each shift. `docs/benchmarks/make_bench_latest.md` is the later 2026-11-10 `make bench`, exit 0, elapsed 582382 ms, with the NASA files present. An earlier local run the same day took 414319 ms. This draft is still not ready to send.

- Scored single faults: 7000/7000, and 3500/3500 on both the in-distribution and shifted halves.
- Difficulty: 29000/29000 easy, 49000/49000 medium, 22000/22000 hard.
- False alarms: 0 of 8000 clean cases. `llm_numeric_violation`: 0. Abstention correctness: 1.000.
- Naive baseline: 0/7000 on the deterministic faults.
- B2 dev, 8 synthetic reports: the hash check beat the hash-blind linker. The specialist chain was 8/8 and ties that check, so it does not beat the deterministic verifier. The chain ledger `llm_numeric_violation` is 0. `beats_single_llm` is NOT VERIFIED.
- B3 dev, local NASA-TM-101040: 8/8 fields on the full text, 2/8 on the first two pages. A no-read baseline is 0/8, so beating it is trivial. The load-factor column abstains and stores no value. The gold was written in this project. This is not a held-out set.
- B3 second memorandum, local NASA Technical Memorandum 101 061: 5/5 on the full text, 0/5 on the first two pages, Wilson 95% 0.566 to 1.000. Four ledger events store the parsed decimal and the unit that was checked. `llm_numeric_violation` is 0. The word three is a field label and was not written as a number. The flight table under V3101 abstains. No table magnitude is stored. Same-session gold. Not a held-out set.

The tool assists a human reviewer. It does not determine compliance.

## What would not be claimed

NOT VERIFIED: B1. The expert held-out directory has 0 cases. The checker author must not fill it.

NOT VERIFIED: B4 as a scored benchmark. VERIFIED on 2026-11-04: Zenodo record 10.5281/zenodo.22170310 has license.id cc-by-4.0, and the local zip is registered. The 2026-11-09 command also left B4 not ready. The stored numbers have no unit, so the series abstains with reason `unit_not_in_file`. No exceedance count was computed. It is not a rotorcraft HUMS set. A later `b4_status` the same evening read a local CC BY 4.0 AS365-K2 UFF. The header states acceleration in m/s^2. The header length at 8192 Hz is 90 seconds, and the cited article says 60 seconds. No sample was stored. The file is not scored. CODE CHECK: the unrecomputed-integer abstain, the B4 live-file abstain, and the recall gate were code checks after the 2436016 ms `make bench`, not part of that run.

NOT VERIFIED: a live single-LLM baseline. `beats_no_agent` on B2 is false because the chain ties the verifier. Two external engineers have not reviewed these results. Five legal rows are open. The programme gate is false.

The employment-contract items in `docs/legal/open_items.md` are open. This draft does not close them. Do not send it to a design partner while those rows are open. That limit is an ASSUMPTION about sequencing.

A later proposal can name two or three design partners only after those partners exist. None are named here.
