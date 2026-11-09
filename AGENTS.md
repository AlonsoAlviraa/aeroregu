# AGENTS.md

## Mission

Build a verifiable evidence layer for rotorcraft, eVTOL, and drone certification work.
Product agents read, draft, and attack text. Deterministic code recomputes every number.
A supervisor written in ordinary code is the only component that appends to the ledger.
A human engineer signs. The system abstains when agents disagree or a check fails.
The tool assists. It does not certify, comply, or approve.
Build agents that write this repository are not the product agents. Do not merge the two roles.

## Hard constraints

- No employer or third-party confidential data, documents, code, CAD, or export-controlled material. Only public data (for example EASA public texts), synthetic data, or data we own. Every dataset has a provenance record.
- Numbers never come from an LLM. Every numeric claim is produced by tested deterministic code and is re-checkable from stored inputs.
- Every output carries: source, method version, inputs hash, confidence, and an abstain/escalate path.
- Never claim automatic compliance; the tool assists, a human signs.
- No secrets in the repo; `.env` only; secret scanning in CI.
- The repository may be public: keep a clear split between the public generic layer and the private core.

## Repo map

- `packages/kernel` — ledger, hash chain, citation labels, supervisor, agent registry, model gateway. Public-safe. No domain imports.
- `packages/calc` — pure deterministic methods and method cards.
- `packages/ingest` — PDF, DOCX, XLSX to blocks.
- `packages/coverage` — envelope grid and gap queries.
- `packages/eval` — seeded-error benchmark runner.
- `packages/domain` — private synthetic aircraft, requirement ids, validity judgements.
- `apps/api` — FastAPI and the single demo page.
- `schemas` — JSON Schema and OpenAPI. Contract owner only.
- `bench/dev` — visible benchmark. `bench/holdout` — frozen later by the founder.
- `docs/adr` — decision records.
- `infra` — Compose and smoke script.
- `.cursor/skills` — project skills.
- `.github` — CI.

## Commands

From the repo root, with uv:

- `uv sync`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `uv run pytest packages/calc packages/kernel -q`
- `uv run python -m evidence_eval score --split dev`
- `make bench` writes `docs/benchmarks/make_bench_latest.md`. The 9 November 2026 run exited 0. The programme is not complete. See the README status section.
- `uv run python -m evidence_api` then open `http://127.0.0.1:8000`

CI runs ruff, pytest, the schema contract tests, gitleaks, `pip-audit`, and a CycloneDX SBOM upload. CI uses the fixture model gateway and must make zero network calls to a model.

## Definition of done

- Tests added for the behavior, and `uv run pytest` passes.
- New numeric behavior has a Hypothesis property or an exact Decimal vector.
- Every new output field is in the envelope schema.
- Provenance exists for any new dataset.
- Public-safe packages still pass the kernel denylist.
- A human can recompute the result from the stored inputs and the method version.
- README and UI copy do not say the tool certifies, complies, or is accepted by an authority.

## Coding standards

- Python 3.12. Type hints on public functions. Ruff line length 100.
- Physical quantities are `decimal.Decimal` in code and strings in JSON. No JSON floats for quantities.
- Schemas change only through `schemas/` with a version bump and an ADR note.
- Dependencies are pinned. A PR that adds one includes a one-line reason.
- Prefer the standard library. No new service for a problem SQLite and a function can solve.

## Uncertainty

If a fact is not in the repo or a cited source, label it `NOT VERIFIED` and do not invent it.
Use `ASSUMPTION` for a choice we are making, `ESTIMATE` for a quantity we computed from assumptions, `PARTIAL` when only part of a statement was checked.
If the task cannot be finished without guessing a number, a regulation's effect, or a missing input: stop, write an abstain note in the PR, and escalate to the human engineer.

## Citations

Every dataset, requirement row, and method card has a source id.
`VERIFIED` requires a URI plus the content hash of the file that was actually read, and the date it was read.
Do not commit copyrighted regulatory PDFs. Commit the hash and the official URL.
Do not describe employer material. Do not copy paywalled standards into the repo.

## Forbidden

- Pasting or uploading employer documents, CAD, methods, templates, or export-controlled data.
- Computing or "correcting" a number inside a prompt or an agent turn.
- Letting the reader and the refuter share a prompt file.
- Letting the bench attacker write the expected label it will be scored against.
- Stating a €100M valuation, a revenue forecast, or a customer count as anything other than `ASSUMPTION`, and never in the product UI.
- Claiming compliance, certification, authority acceptance, tool qualification, or a reduction in mandatory review.
- Disabling CI hooks, committing `.env`, or putting secrets in code, fixtures, or docs.
- Importing `packages/domain` from `packages/kernel`.
- Editing another workstream's files. Open a contract PR instead.
- Tuning prompts or code against `bench/holdout` after the freeze commit.
- Vendoring model weights or copying the WhyBroke repository. Reimplement generic ideas. The hackathon license question stays with counsel (**ASSUMPTION** that a clean reimplementation is the safe path).

## Handoff

Use this heading in the PR body:

- Workstream, branch, schemas touched
- Done / not done
- Tests run and the actual result
- Uncertainties, each labelled
- Files the next agent may read and must not edit

## Conflicts

The file-ownership map in `docs/workstreams.md` wins.
Schema conflicts: both PRs stop; the contracts owner lands one change.
A red adversarial review blocks merge. The authoring agent cannot override it.
Only the founder overrides a block, with a written reason on the PR.
If two technical options remain, write both in the PR and wait. Do not pick silently.
