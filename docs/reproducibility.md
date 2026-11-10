# Reproducibility

Date: 2026-11-03. This is the command and the pins. It is not a claim that B1–B4 are complete.

## Command

From a clean checkout, after `uv sync`, in a shell where `make` is on `PATH`:

```text
make bench
```

GNU make 4.4.1 was installed on this Windows machine from ezwinports on 2026-11-03. VERIFIED by `Get-Command make` in that session. A new terminal is required before `make` is visible.

`make bench` runs `uv run python -m evidence_eval bench`. That scores the smoke dev split, the naive baseline, S1 (100,000 cases, generator `s1@1.0.0`, seed label 20261103, which does not drive a random sampler), B2, both NASA memoranda when their PDFs are present, the quote path, and B4 status. It also writes `docs/reproducibility/manifest.json` and `docs/benchmarks/make_bench_latest.md`.

The workflow file `.github/workflows/ci.yml` runs that same command on `ubuntu-latest` after `uv sync --frozen`. VERIFIED on 2026-11-10: GitHub Actions run 42862445978, commit `ca4921d`, completed with `make-bench`, `test-ubuntu-latest`, `test-windows-latest`, and `supply-chain` successful. `make-bench` took 2 minutes 16 seconds. The NASA PDFs, the bearing zip, and the AS365 UFF are not in git, so that clean checkout reports those files as not scored and still runs S1. That run does not replace the checked-in snapshot from the local 2436016 ms `make bench`, and it does not complete the programme.

VERIFIED on 2026-11-10 from GitHub Actions run 42865671580, commit `3d760a1`, `make-bench` 2 minutes 17 seconds: S1 scored 100000 cases. False alarms were 0/4000 in distribution and 0/4000 shifted, Wilson 95% 0.000 to 0.001 on each. Abstention correctness was 1.000 on both splits, Wilson 95% 0.999 to 1.000. The scorer's own date field still says 2026-11-03. This log does not replace `docs/benchmarks/make_bench_latest.md`, and `programme_complete` stayed false.

CODE CHECK on 2026-11-09, not a new 100000-case run: a checkout without the gitignored NASA PDFs, the bearing zip, and the AS365 UFF does not crash the bench path, B3 and B4 are not scored, and S1 does not need those files. The Actions run above is the 2026-11-10 verification of that job.

## What is pinned

- Python package versions and the SHA-256 of `uv.lock` are recorded in the manifest when the command runs. Those values are VERIFIED only for the environment that wrote the file. The manifest `date` is the day that process ran, not the retrieval date of each file. `make bench` on 2026-11-09 wrote `date` `2026-11-09`.
- S1 seed `20261103` and planned size 100000 are constants in `packages/eval/src/evidence_eval/s1.py`.
- NASA-TM-101040, if present at `data/ntrs/NASA-TM-101040.pdf`, must match SHA-256 `5ee682caf7d0ce2f95f327fcb3f9ea2ba5ff7ab25d79f8f4aba08a9a6f79fbed`. The PDF is not in git. The NTRS citation page, retrieved 2026-11-03, says public use is permitted. One author is listed at Aerospatiale, so the data-register row is PARTIAL.
- NASA Technical Memorandum 101 061, if present at `data/ntrs/NASA-19890004039.pdf`, must match SHA-256 `9f924ea50e0068013825354ec43d6b41ff28c2e24dac67bb6de577ef83d8e779`. It is not in git. The citation page, retrieved 2026-11-04, says public use is permitted. Authors are listed at Aerospatiale and Johnson Aeronautics, so that row is PARTIAL.
- The bearing zip `data/b4/data_SSF.zip`, if present, is pinned by SHA-256 and must appear in `docs/data_register.md`. The local file matches `816ccb70e9866692276bc3ab2095c885bdb39fe69b146e4163072d177d5aab0f`. It is not scored, because the samples have no unit.
- The AS365-K2 UFF `data/as365/DataFiles_Type58UFF_AS365K2_AccelData.uff`, if present, must match SHA-256 `b8f1a54300f12b05bb7f4f4802cd2d3f89b9aae6cf9fda81f4c287a263fb3c41` and that hash must appear in `docs/data_register.md`. The header states acceleration in m/s^2. It is not scored, because the header states no exceedance limit. The file is not in git.
- Frozen dev hashes for the B2 cases, both B3 gold sets, and the B4 drill must match the code. The manifest records that check. A mismatch means the freeze moved.

## What this command does not reproduce

- B1 expert held-out cases. That directory is empty. NOT VERIFIED as a benchmark result.
- A live single-LLM baseline. NOT VERIFIED.
- A Docling parse inside `make bench`. Docling 2.146.0 did parse pages 1–8 of the local NASA-TM-101040 on 2026-11-03, outside that command. See `docs/benchmarks/b3_docling.md`. The reader still abstains with `docling_unavailable` when the import fails.
- The HUMS2023 vibration files. The description PDF, retrieved 2026-11-03, says they go to participants who accept the release terms. NOT VERIFIED as a copied dataset. No file was downloaded. The CWRU bearing page states no licence either.
- Employment-contract clearance. Those items in `docs/legal/open_items.md` are open. This file is not legal advice.
- A win of the specialist chain over the deterministic verifier on B2. On the dev split they tie at 8/8, so `beats_no_agent` is false. ESTIMATE from that comparison.
