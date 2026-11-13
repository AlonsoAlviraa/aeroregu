# Multi-Agent Architecture Benchmark (`agent_bench`)

> **Disclaimer**: This tool assists a human reviewer. It does not determine compliance.

## Epistemic Status & Provenance

- **Benchmark Label**: `ESTIMATE` — Synthetic fixture benchmark across 24 deterministic cases (6 categories x 4 cases). Not an expert held-out set.
- **Hash-Chain Verification**: `VERIFIED` (`ledger.verify() == True`, `44` events recorded in temporary SQLite ledger).
- **Card & Prompt Sources**: `ASSUMPTION` — project-defined screening cards (`rigid_body_point_mass`, `bolt_screen`) and fixture agent prompts.
- **External Held-Out Authority Set**: `NOT_VERIFIED` — this synthetic benchmark does not replace a blind domain-expert holdout.

## Architecture Comparison Summary (24 Cases)

| Metric | `no_agent` (Regex/Hash + Calc) | `single_llm` (Single Reader Turn) | `multi_agent` (Supervised Chain) |
| --- | --- | --- | --- |
| Clean Accept Recall (`4` cases) | `4/4` (`[0.510, 1.000]`) | `4/4` (`[0.510, 1.000]`) | `4/4` (`[0.510, 1.000]`) |
| Adversarial Catch Recall (`20` cases) | `0/20` (`[0.000, 0.161]`) | `0/20` (`[0.000, 0.161]`) | `20/20` (`[0.839, 1.000]`) |
| Overall Correct (`24` cases) | `4/24` (`[0.067, 0.359]`) | `4/24` (`[0.067, 0.359]`) | `24/24` (`[0.862, 1.000]`) |
| False Alarms on Clean (`4` cases) | `0/4` | `0/4` | `0/4` |
| `llm_numeric_violation` | `0` | `6` | `0` |

## Per-Category Recall (Wilson 95% CI)

| Category | `no_agent` | `single_llm` | `multi_agent` | Multi-Agent 95% CI |
| --- | --- | --- | --- | --- |
| `clean_verified` | `4/4` | `4/4` | `4/4` | `[0.510, 1.000]` |
| `corrupted_span` | `0/4` | `0/4` | `4/4` | `[0.510, 1.000]` |
| `label_disagreement` | `0/4` | `0/4` | `4/4` | `[0.510, 1.000]` |
| `refuter_contradiction` | `0/4` | `0/4` | `4/4` | `[0.510, 1.000]` |
| `stray_number_injection` | `0/4` | `0/4` | `4/4` | `[0.510, 1.000]` |
| `decision_gate_low_confidence` | `0/4` | `0/4` | `4/4` | `[0.510, 1.000]` |

## Gate Checks

- `beats_no_agent`: `True`
- `beats_single_llm`: `True`
- `multi_agent.llm_numeric_violation == 0`: `True`
- `ledger_verified`: `True`
