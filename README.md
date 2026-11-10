# aeroregu

This tool assists a human reviewer. It does not determine compliance.

It stores inputs, runs a named screening method, hashes the record, and records who pressed sign-off. Product agents draft and attack text. Deterministic code recomputes every number. A supervisor written in ordinary code is the only writer to the ledger. The system abstains when a check fails or agents disagree.

The load methods are project-defined screening illustrations. They are not certification methods. This repository does not claim authority acceptance, DO-330 qualification, or a tool qualification level. It does not claim certification.

## Status, 9 November 2026

`docs/benchmarks/make_bench_latest.md` was written by `make bench` on 2026-11-10, exit 0, one process, elapsed 582382 ms. The local NASA files were present, so B3 was scored. An earlier run the same day took 414319 ms. The 2026-11-09 run took 2436016 ms. The counts below are ESTIMATE from the current file. This is not the 12-month goal. The programme is not complete.

- S1: 100000 synthetic cases. Scored single faults 7000/7000. The seed label `20261103` does not sample the cases. The generator and the checker are the same package.
- B1: 0 expert cases. Not scored. Another engineer has to write that set. The agent does not.
- External public files, scored 9 Nov 2026 by `external-public`, are not that set. UnitSafe (Apache-2.0, SHA-256 f7ba395958f70cfb80ff3a2559f9a428dc038cac06d35bf15a71d94f4ce92a8a): 500 rows. Parsed answer-unit dimensions agreed with the published signature on 334/361. 15 unit tokens did not parse. Numeric answers scored: 0. Kind-of-quantity rows scored: 0. Dronology (MIT): the eight-heading linker hit 0 of 1063 published positive traces. JCS outhex: the UTF-8 bytes of `arrays`, `french`, `unicode`, and `weird` match the published image, and the ledger hashes those bytes. `structures` and `values` were not scored. NIST SP 811 Appendix B.8: 106 printed interval factors agree within half the last digit, 7 disagree (`bbl>L`, `Btu>J`, `kcal>J`, `lb>kg`). QuRE v1.0.1: 2187 rows, 651 defect, not scored. The weak-word token is not the defect label, and the requirement text is not copied. Detail: `docs/benchmarks/external_public_latest.md`.
- B2: the specialist chain ties the verifier at 8/8 and does not beat it. `public_headings_only` is true. An identifier that was not seen as a public heading is not linked. Clause paragraphs were not copied. A single-LLM baseline was not run (`NOT_VERIFIED`).
- B3: the local NASA PDF was scored. `ready` is false. The gold was written in the same session. It is not a held-out set.
- B4: not ready. No public series has been scored. HUMS2025 was opened on 2026-11-09, was not downloaded, and does not make B4 ready.
- Five legal rows in `docs/legal/open_items.md` are OPEN, including export control. Signed reviews: 0. The private remote is `https://github.com/AlonsoAlviraa/aeroregu`. Notes outside this folder are not in that remote.

Later code checks, after that 2436016 ms `make bench` and not a new 100000-case run: an unrecomputed integer abstains; recall 0 on a present fault fails the bench; B4 `unit_mismatch` abstains and does not convert or store samples; the temporary same-unit count of 2 is not the public B4 result. The 12-month programme is not complete. VERIFIED on 2026-11-10: GitHub Actions run 42862445978 on commit `ca4921d` completed successfully, including `make bench` on a clean checkout. That run is not a new 100000-case snapshot. VERIFIED the same day from Actions run 42865671580 on commit `3d760a1`: S1 scored 100000 cases, false alarms 0/4000 on each shift, and abstention correctness 1.000 on each shift. That log does not replace the checked-in snapshot.

## Layout

- `packages/kernel` is public-safe. It must not import `packages/domain`.
- `packages/domain` holds the synthetic aircraft SL-1 and public requirement identifiers. Titles were not copied from a hashed regulatory PDF, so they are `NOT_VERIFIED`.
- Phases 4–7 (criterion cards, connectors, qualification pack, extra agents) are specified in ADR-016 through ADR-020 and are not built.

## Commands

```text
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python -m evidence_eval score --split dev
uv run python -m evidence_eval external-public
uv run python -m evidence_eval score-blind-b1
uv run python -m evidence_eval score-blind-b2
uv run python -m evidence_eval score-blind-b3
uv run python -m evidence_eval hash-blind-dirs
uv run python -m evidence_eval hash-inputs PATH --at artifact.inputs
uv run python -m evidence_eval hash-file PATH
make bench
```

Set `EVIDENCE_SESSION_SECRET` to a random string of at least 24 characters, then:

```text
uv run python -m evidence_api
```

Open `http://127.0.0.1:8000`. Leave `MODEL_BASE_URL` unset. The gateway then stays on fixtures and does not call a network model.

Smoke without a model URL:

```text
uv run python infra/smoke.py
```

Verify an exported chain:

```text
uv run python -m evidence_kernel verify chain.json
```

## Local secret scan

CI runs `tools/security/secret_scan.py` and the gitleaks GitHub Action with the default `GITHUB_TOKEN`. That token is not a paid license secret. If the action cannot run, install gitleaks locally and run:

```text
gitleaks detect --source . --config .gitleaks.toml
uv run python tools/security/secret_scan.py
```

## Gate

`docs/legal/gate.md` records that the founder ordered this implementation. It is not a record that employment counsel was consulted. It is not legal advice and not a clearance.
