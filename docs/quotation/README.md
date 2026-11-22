# AeroRegu — Aerospace & Rotorcraft Multi-Agent Quotation Engine

![AeroRegu Rotorcraft Quotation Architecture](./aeroregu_architecture_chalkboard.png)

> **Advisory & Regulatory Boundary:** Every rate card, parametric effort multiplier, PERT triple, and cost estimate produced by this engine is explicitly labeled `ASSUMPTION` or `ESTIMATE`. The system assists engineering managers and independent **Part 21J Compliance Verification Engineers (CVEs)**; it **never** determines regulatory compliance or certifies airworthiness artifacts autonomously.

---

## Core Capabilities

1. **Zero LLM Math (`Decimal` + 50-Digit `FLINT/Arb` Intervals):**
   - Certified deterministic calculation cards compute every price, labor cost, overhead, contingency, PERT percentile (`P50 / P80 / P90`), and margin with zero floating-point arithmetic:
     - [`aerospace_quotation_costing.json`](../../packages/calc/cards/aerospace_quotation_costing.json)
     - [`engineering_workpackage_quote.json`](../../packages/calc/cards/engineering_workpackage_quote.json)
     - [`rotorcraft_archetype_quote.json`](../../packages/calc/cards/rotorcraft_archetype_quote.json)
     - [`rotorcraft_historical_calibration.json`](../../packages/calc/cards/rotorcraft_historical_calibration.json)
   - Implemented in [`quotation_costing.py`](../../packages/calc/src/evidence_calc/quotation_costing.py) with 50-digit unrounded ball enclosures in [`intervals.py`](../../packages/calc/src/evidence_calc/intervals.py).

2. **18 Rotorcraft Engineering Archetypes (`Q-DES-01` .. `Q-TST-02`):**
   - Covers airframe concept & cabin layout, metallic detail design, CFRP ply-books, Weight & Balance, CS-27/CS-29 Subpart C loads, full-airframe GFEM & `.f06` audits, DFEM static stress dossiers, supplier stress gatekeeping, airframe F&DT, dynamic components (`MRB/MRH/MGB`), modal/`SOL 103`/ground resonance, `CS 29.561/562` crashworthiness, SPH/ALE bird-strike & ditching, MRB repairs & Service Bulletins, HEMS/Hoist/Cargo-Hook STCs, propulsion mounts/1100C firewalls/HIRF, structural test rigs, and FTI / Permit to Fly (`Part 21J Subpart P`).
   - Orchestrated across 8 supervised agent steps mapped to kernel `ACTIVE_AGENTS` in [`rotorcraft_quotation_catalog.py`](../../packages/coverage/src/evidence_coverage/rotorcraft_quotation_catalog.py) and [`quotation_multiagent.py`](../../packages/coverage/src/evidence_coverage/quotation_multiagent.py).

3. **Default EU + 8 Country Rate Profiles & 6 Scientific Costing Models:**
   - Benchmarks every quote across **`EU_DEFAULT`** and **`FR`, `DE`, `ES`, `IT`, `UK`, `US`, `PL`, `IN`** plus an **Onshore CVE + Nearshore Execution** hybrid model.
   - Incorporates parametric drivers from **NASA NDARC**, **RAND NAFCOM**, **USC COSYSMO**, **Curran/Scanlan/Roy Design-to-Cost MDO**, **GARTEUR HELIX/FELIX/PVT**, and **EASA AI Concept Paper / Part 21.A.239(b)** (`8%–20%` non-waivable independent CVE review floor).

4. **10-Dimension Standardized Assumptions (45 Clauses) + Z3 SMT Margin Gate:**
   - Locks assumptions and Change-Order triggers across `TECHNICAL_SCOPE`, `ROTORCRAFT_LOADS_SPECTRA`, `DYNAMICS_VIBRATION_AEROELASTIC`, `DOA_CERTIFICATION_PRIVILEGES`, `DATA_AND_IDP`, `SCHEDULE_AND_ITERATIONS`, `COMMERCIAL_AND_RATES`, `LEGAL_IP_AND_EXPORT`, `TOOLING_AND_COMPUTE`, and `RISK_AND_ABSTAIN_TRIGGERS`.
   - Proves formally via **Z3 SMT (`PROVED_UNSAT`)** (`prove_quotation_margin_envelope`) that gross margin on the `P80` bid remains above the contractual floor across `[0.950, 1.080]` direct cost drift; triggers fail-closed `ABSTAIN` on CVE waivers, invalid margins, unsupported countries, or out-of-domain requests.

5. **2,000+ Historical Quotation Calibration, Physical IDP Inspector & k-NN Matching:**
   - [`historical_quotation_calibrator.py`](../../packages/coverage/src/evidence_coverage/historical_quotation_calibrator.py) provides:
     - Bulk CSV/JSON/JSONL ingestion with SHA-256 dataset hashing + reproducible `2,160`-bid reference benchmark corpus (`SYNTHETIC_BENCHMARK_ASSUMPTION`), Buhlmann-PERT credibility calibration, and out-of-sample `80/20` backtesting (reducing MAPE from `18.04%` to `3.49%` on the benchmark slice).
     - Automated physical complexity inspection (`extract_idp_physical_complexity`) of Nastran `.bdf` (`GRID`, `CBUSH`, `PCOMP`, `SUBCASE`), `.f06` (`GPWG`, `OLOAD`/`SPCFORCE`, `EPSILON`, `FATAL MESSAGE`), STEP `.stp`, and DXF files.
     - Deterministic weighted `Decimal` k-NN retrieval (`retrieve_nearest_historical_quotations`) surfacing the closest past As-Bid vs. As-Burned bids and historically broken assumptions.

6. **Global Quoting Repository & Web Intelligence Scraper:**
   - [`repo_web_scraper.py`](../../packages/coverage/src/evidence_coverage/repo_web_scraper.py) (`QuotationIntelligenceScraper`) benchmarks 32 GitHub repositories and 18 commercial quoting web platforms plus public EASA/FAA/NASA rotorcraft sources across 8 capability axes.

---

## Documentation & Research Catalogs

- [Global Multi-Agent RFQ Repositories & Web Platforms Benchmark (32 GitHub Repos, 18 Platforms)](./07-cotizaciones-multiagente-github-webs.md)
- [Helicopter Engineering Rate Cards (EU + 8 Countries), 18 Archetypes, 6 Studies, 10 Assumption Dimensions & 2,000+ Calibration](./08-catalogo-cotizaciones-supuestos-helicopteros.md)

---

## Quickstart (CLI, FastAPI & MCP)

### CLI

```text
# List all 18 helicopter archetypes, 9 country rate profiles, and 6 research studies
uv run python -m evidence_api.cli quote archetypes

# Generate a full helicopter quotation (with optional .bdf/.f06 IDP & historical corpus)
uv run python -m evidence_api.cli quote helicopter \
  --text "CS-29 HEMS rescue hoist STC structural and F&DT justification" \
  --country ES \
  --cert-basis CS-29

# Run 80/20 historical backtest calibration & top-3 k-NN matching over 2,160 bids
uv run python -m evidence_api.cli quote calibrate \
  --archetype Q-STR-03 \
  --country ES \
  --synthetic-count 2160

# Run general 8-agent RFQ quotation & global GitHub/Web scraper benchmark
uv run python -m evidence_api.cli quote generate --text "Supply 12 Ti-6Al-4V lugs (1.5 kg) with 3 calc notes"
uv run python -m evidence_api.cli quote scrape --offline
```

### FastAPI Endpoints ([`app.py`](../../apps/api/src/evidence_api/app.py))

- `GET /quotations/catalog` & `POST /quotations/generate` & `POST /quotations/sensitivity`
- `GET /quotations/repos-benchmark` & `POST /quotations/scrape-repos`
- `GET /quotations/rotorcraft/catalog` & `POST /quotations/rotorcraft/generate`
- `POST /quotations/rotorcraft/calibrate-historical`

### MCP Tools ([`mcp_server.py`](../../apps/api/src/evidence_api/mcp_server.py))

- `generate_multiagent_quotation`
- `scrape_global_quotation_repos`
- `generate_rotorcraft_archetype_quotation`
- `calibrate_and_match_historical_quotations`

### Test Suites

- [`test_quotation_multiagent_and_scraper.py`](../../tests/test_quotation_multiagent_and_scraper.py)
- [`test_rotorcraft_18_archetypes_and_countries.py`](../../tests/test_rotorcraft_18_archetypes_and_countries.py)
- [`test_historical_2000_calibration_idp_knn.py`](../../tests/test_historical_2000_calibration_idp_knn.py)
