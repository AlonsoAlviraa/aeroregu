# Workstreams

Ownership is exclusive. Schema conflicts stop until the contracts owner lands one change.

| Workstream | Scope |
| --- | --- |
| contracts | `schemas/**` |
| core-calc | `packages/calc/**` |
| ingestion | `packages/ingest/**` |
| evidence-ledger | `packages/kernel` ledger |
| coverage-engine | `packages/coverage/**` |
| agent-orchestrator | supervisor, gateway, prompts |
| eval-harness | `packages/eval/**`, `bench/dev/**` |
| domain-data | `packages/domain/**` |
| api-demo | `apps/**` |
| infra-ci | `pyproject.toml`, `uv.lock`, `.github/**`, `infra/**` |
| security-guardrails | `tools/security/**`, `docs/security/**`, `docs/legal/**` |
| docs | `docs/**`, `AGENTS.md`, `.cursor/skills/**` |

Not in this build: criterion library content, connectors, qualification pack, and the extra agents named in ADR-016. Their schemas and ADRs are the boundary.

The file-ownership map in this file wins when two edits conflict.
