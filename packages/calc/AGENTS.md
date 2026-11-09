# Calc

Read the root `AGENTS.md` first. The hard constraints there apply here.

Pure functions only. Each method has a card in `packages/calc/cards/*.json` with validity limits, quantum, and sources. No I/O, no network, no LLM client.

Physical quantities are `decimal.Decimal` in code and strings in JSON. Quantize with the card quantum and `ROUND_HALF_EVEN`. A missing or out-of-range input abstains and emits no number.
