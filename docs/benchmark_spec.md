# Benchmark specification

Date: 2026-11-03. This file is the contract for B1, B2, B3, B4, and S1. It is not a result.

Claim labels: VERIFIED means a file in this repo or a page opened on the stated date. ASSUMPTION is a choice. NOT VERIFIED means the source was not opened for this file. ESTIMATE is a quantity computed from stated inputs.

## What is already in the repo

The package `evidence_eval` scores JSON cases under `bench/dev` and `bench/holdout`. Those files are produced by `evidence_eval.generate` from the same fault injector that the checker knows. **ASSUMPTION:** that pair is a smoke harness, not B1. It is not an expert-authored held-out set. Count on 2026-11-03: the generator writes a small dev set and a small holdout, not 150 cases. Treating the current holdout as B1 would violate the freeze rule below.

`pint` 0.26.2 is a dependency of `evidence-calc`. Numeric code uses `decimal.Decimal`. Declared dimensions are checked with pint when an input unit is set. A quantity with no declared unit is not checked. B1 is not complete.

## Splits

| Split | Who may write it | Who may read it while changing a checker or prompt | Role |
| --- | --- | --- | --- |
| `dev` | The person or agent who writes the check | That same person or agent | Tune thresholds, prompts, and fault injectors |
| `held-out` | Someone who did not write the check. Target: the domain expert | Scoring only, after the freeze commit. Never while editing detectors or prompts | The number that is reported |

A case is held-out only if its author is recorded and that author is not the author of the checker that is being scored. The current `bench/holdout` directory fails that test. New expert cases go in `bench/b1/expert_holdout/` and stay empty until the expert writes them.

## Freezing

1. The expert (or other non-author) adds cases and a one-line author statement in `bench/b1/expert_holdout/AUTHOR.md`.
2. A commit records the directory hash. The hash command is the same canonical hash used by `evidence_eval.generate.directory_hash`, excluding nothing inside that directory.
3. After that commit, a change to a file under `bench/b1/expert_holdout/` fails CI.
4. Detector and prompt edits that cite an expert case id, or that branch on `expert_holdout`, fail review.
5. Dev cases may change. They are not the reported number.
6. If a fault type is added after the freeze, the new type is a new split. The frozen split is not edited to "make room" for it.

## Metrics

Reported per fault type, on the frozen held-out split only:

- **Recall.** Hits divided by cases whose gold label is that fault. A hit is an exact verdict match (`detect:<fault_id>`).
- **False-alarm rate.** Cases with gold `clean` whose verdict is not `clean`, divided by the number of clean cases.
- **Abstention correctness.** Cases with gold `abstain` whose envelope has `confidence=abstain` and no `result`, divided by gold abstain cases.
- **llm_numeric_violation.** Count of agent turns that contain a physical number that is not an exact copy of a Decimal string produced by deterministic code. Required value: 0.
- **95% Wilson interval** on recall, false-alarm rate, and abstention correctness. The interval is a statement about the finite sample, not about certification performance. Method: Wilson score interval with z = 1.96, endpoints clipped to [0, 1]. **ASSUMPTION:** z = 1.96 is the usual normal approximation for a 95% interval. It is a poor description of very small samples; the report must still print `n`.

A run that omits a fault type, drops a failure, or reports only the dev split is not a benchmark result.

## Benchmarks

Sizes and dates are targets. Missing them is a result to report, not a reason to relabel a smaller set.

| Id | Target month | Population | Minimum size | Gold | Metrics |
| --- | --- | --- | --- | --- | --- |
| B1 | Month 3 (Feb 2027) | Seeded-error calculation notes in a public style | 150 cases, at least 12 fault types, expert-authored held-out | Known fault id per case | Recall per fault, false-alarm rate, abstention correctness, Wilson intervals |
| B2 | Month 5 | Public CS-27, CS-29, and EASA SC-VTOL clause ids against synthetic compliance reports | Not set until the clause list is frozen. **NOT VERIFIED** which edition text may be quoted | Hand-labelled links and false-coverage traps | Matching precision and recall, false-coverage detection, citation span accuracy |
| B3 | Month 8 | Public rotorcraft reports (candidates in `docs/data_register.md`) | Not set until a licence is VERIFIED | Hand-labelled fields | Field-level accuracy, unit-error detection, abstention on unreadable tables |
| B4 | Month 10 | Public vibration or HUMS-type series, or a documented substitute | Not set until access and licence are VERIFIED | Dataset's own labels, or labels we add and mark as such | Exceedance or anomaly evidence metrics written down before the first training run |
| S1 | Month 6, extended month 12 | Seeded generator | At least 100,000 notes and packs | Generator ground truth | A naive baseline must fail on the fault types it is not supposed to see. Difficulty levels and a distribution-shift split are required in v2 |

Fault ids already implemented in the checker, as of 2026-11-04: `unit_scale`, `arithmetic`, `wrong_input`, `sign`, `outside_validity`, `stale_revision`, `false_coverage`, `broken_hash`, `bad_span`, `bad_citation`, `contradictory_requirements`, `unit_mismatch`, and `missing_input` (an abstention). `duplicate_citation` is a known miss, recall 0/1. The expert chooses any further types. Do not copy `bench/dev`.

## Baselines

Before any agent prompt is changed against a benchmark:

- **Naive baseline.** Trust the stated number. Abstain only when a required input is missing. Do not recompute. On the smoke dev set this baseline is expected to score recall 0 on deterministic faults. A recall above 0 means the baseline is no longer naive and the comparison is void.
- **No-agent baseline.** Deterministic verifier only, no reader, extractor, mapper, challenger, or scribe.
- **Single-LLM baseline.** One model call, no challenger, still forbidden from emitting a number that deterministic code did not produce.

B2 and B3 are the comparisons that must show the agent system ahead of the no-agent and single-LLM baselines, or the report must say plainly that it does not.

## Measured status on 2026-11-03

`make bench` exited 0 on 2026-11-03. `docs/benchmarks/s1_latest.md` was rewritten on 2026-11-10 by `run_s1`, not by that `make bench`. The process took about 6 minutes. The rates below are ESTIMATE counts from that 2026-11-10 file, not a certification result. False alarms were 0/4000 in distribution and 0/4000 shifted. Abstention correctness was 1.000 on each shift. This file does not replace `docs/benchmarks/make_bench_latest.md`.

S1 generator `s1@1.0.0`, seed `20261103`, 100000 of 100000 invented cases. Each scored single fault was 7000/7000, and 3500/3500 on both the in-distribution and shifted halves. Difficulty recall was 29000/29000 easy, 49000/49000 medium, and 22000/22000 hard. False alarms were 0 of 8000 clean cases. `llm_numeric_violation` was 0. Abstention correctness was 1.000. `missing_input` is in that abstention count, so its detect-recall line is 0/0. The naive baseline was 0/7000 on every deterministic fault. Compound complete was 1.000. The expert held-out directory was not read.

B1 is NOT VERIFIED. `bench/b1/expert_holdout` has 0 cases and no author statement.

On the B2 dev split, the hash-blind baseline precision was 0.750 and its false-coverage recall was 0.000. The verifier that drops a zero hash had precision 1.000, recall 1.000, and false-coverage recall 1.000, so it beat the hash-blind linker on these 8 dev cases. The specialist chain also scored 8/8 and does not beat that verifier. `beats_single_llm` is NOT VERIFIED. A live single-LLM baseline was not run. `bench/b2/expert_holdout` is empty.

B3, when the local NASA-TM-101040 file matches SHA-256 `5ee682caf7d0ce2f95f327fcb3f9ea2ba5ff7ab25d79f8f4aba08a9a6f79fbed`, scored 8/8 fields on the full text and 2/8 on the first two pages. A no-read baseline scores 0/8, so the reader beats it, and that comparison is trivial. `beats_single_llm` is NOT_VERIFIED. The quote path matched 8/8, with 0 false alarms. The gold was written in the same project as the checker. This is not a held-out set. The NTRS citation page, retrieved 2026-11-03, says public use is permitted. One author is listed at Aerospatiale, so the licence row is PARTIAL. The load-factor column abstains and stores no value. A ledger event for that abstain is in the 2026-11-04 `make bench` JSON. Docling 2.146.0 was run on pages 1–8; `make bench` does not call it, and that run did not show a gain over pypdf. See `docs/benchmarks/b3_docling.md`.

A second local file, `data/ntrs/NASA-19890004039.pdf`, SHA-256 `9f924ea50e0068013825354ec43d6b41ff28c2e24dac67bb6de577ef83d8e779`, is NASA Technical Memorandum 101 061. `make bench` on 2026-11-04, exit 0, scored five same-session fields 5/5 on the full text and 0/5 on the first two pages. Wilson 95% for the full text was 0.566 to 1.000, with 5 ledger events. A later `score_second` the same evening wrote 4 decimal ledger events: rotor radius 5.25 m, lift-curve slope 5.7, and advance ratios 0.14 and 0.37. Each event stores that parsed decimal and its unit. `llm_numeric_violation` was 0. The word three stayed a field label and was not written as a number. The field score stayed 5/5. The file shares flight ids V3101, V3103, V3105, and V3106 with the first memorandum. V3109 and V3111 are absent. No table magnitude was stored. This is not a held-out set. The citation page says public use is permitted, and authors are listed at Aerospatiale and Johnson Aeronautics, so the row stays PARTIAL. A checkout without the PDF reports the memorandum as not scored.

B4 is NOT VERIFIED. The HUMS2023 description PDF, retrieved 2026-11-03, says the vibration files go to participants who accept the release terms. No HUMS file was downloaded. The ETH Airbus accelerometer record names Airbus SAS as rights holder, so it is rejected for this repo. The CMAPSS zip resource page, retrieved 2026-11-04, says License not specified. No CMAPSS zip was downloaded. On 2026-11-04 the Zenodo API record 10.5281/zenodo.22170310 stated license.id cc-by-4.0. The local file data_SSF.zip is registered, 16579962 bytes, SHA-256 816ccb70e9866692276bc3ab2095c885bdb39fe69b146e4163072d177d5aab0f. All 150 acceleration files have 80128 lines and a bare first line, so the series abstains with reason unit_not_in_file. The path tokens are Ball, CA, H, IN, and OU. Only H is a published class code, 30 files. The other tokens were not mapped. The path grid is 15 cells of 10 files at speeds 1000, 1500, and 2000. That matches the record's count of records and does not supply a unit. The article page for DOI 10.1088/1361-6501/aeafc4, retrieved 2026-11-04, does not state the unit of the stored numbers. The description states a sensor range of plus or minus 80 g. That range is not applied. No exceedance count was computed. Compiled Python files in that zip were not executed. A local file under `data/b4` is not scored unless its SHA-256 is in the data register. This zip does not make B4 ready. A local AS365-K2 UFF under `data/as365/`, CC BY 4.0, states acceleration in m/s^2. Three records, P11X, P11Y, and P11Z, each declare 737280 values and the value-token counts match. The Springer page https://doi.org/10.1007/s40430-026-06481-9, retrieved 2026-11-04, says the second flight used 8192 Hz. The header step `1.22070E-04` matches 1/8192 printed to six figures. Dividing each declared count by 8192 gives 90 seconds. The same page says acceleration data were recorded for 60 seconds. Those durations do not match. The fetched article text does not state 90 seconds. That page fetch did not state a time-domain sample limit, so no exceedance count was computed. The article licence was not in that fetch. This file does not make B4 ready. VERIFIED from the HUMS2025 pages opened on 2026-11-09: the set was not downloaded and does not make B4 ready. CODE CHECK: a mismatched unit abstains with `unit_mismatch` and does not convert, as a code check after the 2436016 ms `make bench`, not a new 100000-case run.

Duplicate citation is a known miss. The checker verdict is `clean`. The system abstains, recall 0/1, Wilson 95% 0.000 to 0.793. That abstain does not match the gold label and is not a detection. It does not by itself fail `make bench`.

`pint` 0.26.2 checks declared input dimensions. That version was resolved by `uv lock` on 2026-11-03 (VERIFIED as the lockfile result, not as a benchmark outcome).

From a clean checkout, after `uv sync`:

```text
make bench
```

`make bench` runs `uv run python -m evidence_eval bench`. That command scores the smoke dev split with the deterministic checker and with the naive baseline, then scores all 100,000 S1 cases, B2, B3, the second NASA memorandum when its PDF is present, the quote path, and B4 status. It does not read `bench/b1/expert_holdout`. It does not tune prompts.

Exit status is 0 only when all of these hold. The smoke checker has deterministic recall 1 on every scored fault, trace recall 1 on every trace fault the split actually contains, `llm_numeric_violation` 0, no false alarms, and abstention matching the missing-input cases. A trace fault with no cases in the split does not fail the command. The smoke naive baseline still misses every deterministic fault. Every S1 single-fault hit count equals its case count, the S1 naive baseline still misses those faults, S1 `llm_numeric_violation` is 0, and compound complete is a pass. The quote gate passes when the NASA file is present. The B2 chain ledger has `llm_numeric_violation` 0. B2 `public_headings_only` is true. A scored second memorandum and a scored B3 holdout also have `llm_numeric_violation` 0. A naive baseline that starts catching faults is a failed harness, not a successful detector. B1 and B4 staying unready does not by itself fail the command. That is a gap in the programme, not a pass of those benchmarks.

## Report rules

Every sentence in a benchmark report is labelled VERIFIED, ASSUMPTION, or NOT VERIFIED, with source and date. Negative results stay in the report. A missed size target stays in the report. `llm_numeric_violation` is printed even when it is zero.

The tool assists a human reviewer. It does not determine compliance.
