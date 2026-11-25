# aeroregu

This tool assists a human reviewer. It does not determine compliance.

It stores inputs, runs a named screening method, hashes the record, and records who pressed sign-off. Product agents draft and attack text. Deterministic code recomputes every number. A supervisor written in ordinary code is the only writer to the ledger. The system abstains when a check fails or agents disagree.

The load methods are project-defined screening illustrations. They are not certification methods. This repository does not claim authority acceptance, DO-330 qualification, or a tool qualification level. It does not claim certification.

## Status, 9 November 2026

`docs/benchmarks/make_bench_latest.md` was written by `make bench` on 2026-11-10, exit 0, one process, elapsed 605050 ms. The local NASA files were present, so B3 was scored. The snapshot lists dev per-case B2 lines and per-field B3 lines. An earlier run the same day took 582382 ms and 414319 ms. The 2026-11-09 run took 2436016 ms. The counts below are ESTIMATE from the current file. This is not the 12-month goal. The programme is not complete.

- S1: 100000 synthetic cases. Scored single faults 7000/7000. The seed label `20261103` does not sample the cases. The generator and the checker are the same package.
- B1: 0 expert cases. Not scored. Another engineer has to write that set. The agent does not.
- External public files, scored 9 Nov 2026 by `external-public`, are not that set. UnitSafe (Apache-2.0, SHA-256 f7ba395958f70cfb80ff3a2559f9a428dc038cac06d35bf15a71d94f4ce92a8a): 500 rows. Parsed answer-unit dimensions agreed with the published signature on 334/361. 15 unit tokens did not parse. Numeric answers scored: 0. Kind-of-quantity rows scored: 0. Dronology (MIT): the eight-heading linker hit 0 of 1063 published positive traces. JCS outhex: the UTF-8 bytes of `arrays`, `french`, `unicode`, and `weird` match the published image, and the ledger hashes those bytes. `structures` and `values` were not scored. NIST SP 811 Appendix B.8: 106 printed interval factors agree within half the last digit, 7 disagree (`bbl>L`, `Btu>J`, `kcal>J`, `lb>kg`). QuRE v1.0.1: 2187 rows, 651 defect, not scored. The weak-word token is not the defect label, and the requirement text is not copied. Detail: `docs/benchmarks/external_public_latest.md`.
- B2: the specialist chain ties the verifier at 8/8 and does not beat it. `public_headings_only` is true. An identifier that was not seen as a public heading is not linked. Clause paragraphs were not copied. A single-LLM baseline was not run (`NOT_VERIFIED`).
- B3: the local NASA PDF was scored. `ready` is false. The gold was written in the same session. It is not a held-out set.
- B4: not ready. No public series has been scored. HUMS2025 was opened on 2026-11-09, was not downloaded, and does not make B4 ready.
- Five legal rows in `docs/legal/open_items.md` are OPEN, including export control. Signed reviews: 0. The private remote is `https://github.com/AlonsoAlviraa/aeroregu`. Notes outside this folder are not in that remote.

Later code checks, after that 2436016 ms `make bench` and not a new 100000-case run: an unrecomputed integer abstains; recall 0 on a present fault fails the bench; B4 `unit_mismatch` abstains and does not convert or store samples; the temporary same-unit count of 2 is not the public B4 result. The 12-month programme is not complete. VERIFIED on 2026-11-10: GitHub Actions run 42862445978 on commit `ca4921d` completed successfully, including `make bench` on a clean checkout. That run is not a new 100000-case snapshot. VERIFIED the same day from Actions run 42865671580 on commit `3d760a1`: S1 scored 100000 cases, false alarms 0/4000 on each shift, and abstention correctness 1.000 on each shift. That log does not replace the checked-in snapshot. VERIFIED the same evening from Actions run 42895462269 on commit `6cfd436`: all four CI jobs passed on a GitHub-only checkout, including pytest on Ubuntu and Windows. That run still does not score B3 or B4 without local `/data` files.

## Layout

- `packages/kernel` is public-safe. It must not import `packages/domain`.
- `packages/domain` holds the synthetic aircraft SL-1 and public requirement identifiers. Titles were not copied from a hashed regulatory PDF, so they are `NOT_VERIFIED`.
- Phases 4–7 (criterion cards, connectors, qualification pack, extra agents) are specified in ADR-016 through ADR-020 and are not built.

## Automated Aerospace & Rotorcraft Quotation Engine

Full documentation and module map: [`docs/quotation/README.md`](docs/quotation/README.md)

![AeroRegu Rotorcraft Quotation Architecture](docs/quotation/aeroregu_architecture_chalkboard.png)

- **Zero LLM math & Z3 SMT Formal Proofs (Q1 + Sprints 2–4):** `52` deterministic `Decimal` calculation cards (`5` quotation costing cards + `47` engineering & rotorcraft stress cards including 4-ply CLT `[A,B,D]`, rotor blade CF/Goodman fatigue, Coleman ground resonance, `CS 29.561/562` crashworthiness, 3-row Huth elastic splice load sharing, NASA LaRC04 composite failure, `CS 29.631` bird-strike penetration, Campbell 1P/bP/2bP/3bP harmonic clearance, tailboom box-beam combined stress, CMH-17 A/B-basis bounds, T-flange bolt prying, Goland-Reissner adhesive peel/shear, orthotropic panel buckling, skin-stringer crippling, and Walker R-ratio crack growth) with 50-digit `FLINT/Arb` intervals, Z3 SMT continuous envelope proofs (`PROVED_UNSAT`), `8` MMPDS-16 / CMH-17 materials, and hardened plugin-shadowing protection.
- **Composite WBS DAG + 18 Archetypes + 9 Country Profiles & Multi-Currency FX (Q1 + Sprints 3–4):** Builds multi-archetype acyclic WBS DAGs across `Q-DES-01..Q-TST-02` and `EU_DEFAULT`, `FR`, `DE`, `ES`, `IT`, `UK`, `US`, `PL`, `IN` (plus Onshore-CVE + Nearshore hybrid), computing deterministic Critical Path Method schedules (`ES/EF/LS/LF/Float`), GFEM/loads reuse synergy (preserving the mandatory CVE floor), multi-currency FX forward hedging & continuous Z3 SMT margin floor proofs (`quotation_fx_hedging.py`), and calibration against 6 aerospace studies (`NASA NDARC`, `RAND NAFCOM`, `USC COSYSMO`, `Curran/Scanlan/Roy MDO`, `GARTEUR PVT`, `EASA AI / Part 21.A.239 CVE`).
- **Deep Physical IDP & NAFEMS V&V Inspector (Q2 + Sprints 3–4):** Resolves multi-level nested Nastran & Abaqus `*INCLUDE` trees (with `*SHELL SECTION, COMPOSITE` ply-book extraction), local `CORD1/2` coordinate systems, structural vs. `CBUSH` element/DOF counts (`SPC/RBE2/RBE3/MPC`), binary `.op2`/`.h5` & `.f06` diagnostics (`SOL 103` modal, `SOL 105` linear buckling margins, `GPFORCE` freebody equilibrium via `nafems_audit.py`), STEP B-Rep surface area / PCA OBB geometric Buy-to-Fly ratios, and PDF (`bbox`)/XLSX/DOCX BOM & Drawing Lists.
- **Clause-by-Clause Contractual Auditor, Change Orders (CCN) & Hardened OEM Exports (Q3 + Sprints 2–4):** Classifies RFQ clauses deterministically (`SUPPORTED`, `PARTIALLY_SUPPORTED_WITH_ASSUMPTION`, `CHANGE_ORDER_REQUIRED`, `REJECT_OR_ABSTAIN`), detects 6 high-risk poison clauses (including Unicode homoglyph / zero-width anti-bypass normalization), computes closed-loop Rev A -> Rev B Change-Order delta quotes (`quotation_change_order.py`), and exports CWE-1236 formula-injection-hardened native `.xlsx` workbooks + Ed25519 DSSE & ISO QR signed `.pdf` dossiers for quotes, CCNs, and EVM+FX post-mortems (`quotation_exporter.py`).
- **2,000+ Historical Bids, Bid-to-Actual EVM Post-Mortem, K-Fold CV & RCPSP Leveling (Q4 + Sprints 2–4):** CSV/JSON/JSONL/XLSX ingestion, closed-loop Bid-to-Actual ERP Earned Value Management (`bid_actual_postmortem.py` computing `CPI/SPI/EAC/VAC/TCPI`, broken `ASM-*` attribution, ledger sealing, and `.xlsx`/signed `.pdf` exports), IQR/MAD outlier isolation, stratified K-Fold backtesting (`18.59% -> 3.66%` MAPE on the 2,160-bid corpus), Win-Rate vs. `P50..P90` calibration, multi-RFQ 7-role Stress Office RCPSP capacity leveling (`portfolio_capacity_leveler.py`), ERP/SAP templates, k-NN matching, Interactive Hub option `10`, and `#tab-quote` (`Alt+7`) Web Cockpit v3 (all commercial/financial figures labeled as `ESTIMATE` / `ASSUMPTION`).

```text
uv run python -m evidence_api.cli quote archetypes
uv run python -m evidence_api.cli quote helicopter --text "CS-29 HEMS rescue hoist STC" --country ES
uv run python -m evidence_api.cli quote composite --archetypes Q-DES-02,Q-DES-04,Q-STR-01,Q-STR-02,Q-STR-03,Q-FDT-01,Q-DOA-02,Q-TST-01 --country ES
uv run python -m evidence_api.cli quote change-order --baseline-text "CS-29 frame static" --revised-text "CS-29 frame static + F&DT + STC" --country ES
uv run python -m evidence_api.cli quote portfolio-level --rfq-count 2 --country ES --lead-cve 1
uv run python -m evidence_api.cli quote fx-hedge --billing-currency USD --hedge-pct 90
uv run python -m evidence_api.cli quote evm-postmortem --project-id POST-H145 --ecn-actual 3 --xlsx-out evm.xlsx --pdf-out evm.pdf
uv run python -m evidence_api.cli quote fem-vv-audit --f06-file sol105.f06 --abaqus-file model.inp
uv run python -m evidence_api.cli quote audit-contract --text "Payment contingent on EASA approval without long-stop date"
uv run python -m evidence_api.cli quote kfold-calibrate --country ES --synthetic-count 2160 --k-folds 5
uv run python -m evidence_api.cli quote erp-template --output erp_historical_template.xlsx
```

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
