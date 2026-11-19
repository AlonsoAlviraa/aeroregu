# Tool Verification & Qualification Aid Plan (TQP)

> This tool assists a human reviewer. It does not determine compliance.

## 1. Purpose
This document describes the Installation Verification (IQ) and Operational Verification (OQ) procedures bundled with aeroregu so customer quality & airworthiness engineering teams can audit deterministic software repeatability within an air-gapped or sovereign enterprise deployment.

## 2. Installation Qualification (IQ) Checks
- **IQ-01**: Verify host runtime matches Python >= 3.12 and pinned wheel/lockfile inventory (`uv.lock`).
- **IQ-02**: Verify availability of cryptographic and rigorous numerical dependencies (`cryptography`, `flint`, `pint`, `rfc8785`).
- **IQ-03**: Verify all >= 32 built-in structural & aerospace sizing cards are intact with verified SHA-256 catalog provenance (MMPDS-16 & CMH-17 Rev H).
- **IQ-04**: Verify bundled Qualification Aid artifacts (`TOR`, `TQP`, `RTM`) and Security Controls (`secret_scan.py`, `denylist_kernel.py`).

## 3. Operational Qualification (OQ) Checks
- **OQ-01**: Execute `margin_of_safety` and all 25 Stress Office manual cards with `flint.arb` enclosures and assert zero out-of-bounds quantization drift.
- **OQ-02**: Inject dimensional inhomogeneity (`N + mm`) and assert immediate `AbstainError`.
- **OQ-03**: Run the standalone offline dossier verifier (`verify_standalone_dossier_offline`) over exported ledger chains and RFC 6962 Merkle roots without runtime server imports.
- **OQ-04**: Execute HSM in-memory key signing + eIDAS QES LTV (`CAdES-B-LT`/`PAdES-B-LT`) verification roundtrip.
