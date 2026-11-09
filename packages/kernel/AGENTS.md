# Kernel

Read the root `AGENTS.md` first. The hard constraints there apply here.

This package owns the ledger, the model gateway, and the supervisor. Tests live in `packages/kernel/tests`.

Forbidden: the domain vocabulary named in ADR-001. Forbidden: importing `evidence_domain`.

The supervisor is the only writer that appends product-agent output to the ledger. Reader and refuter prompts are different files.
