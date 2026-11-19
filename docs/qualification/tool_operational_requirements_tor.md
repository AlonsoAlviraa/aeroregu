# Tool Operational Requirements (TOR) — Qualification Aid Pack

> This tool assists a human reviewer. It does not determine compliance.
> Structural-analysis tool certification and authority approval remain the applicant's responsibility (`ADR-018`).

## 1. Operational Scope
The aeroregu verification assistance system parses engineering requirement documents, 3D B-Rep STEP geometry (`cad_brep.py`), binary FEM solution files (`.op2`/`.h5`), and executes deterministic Decimal + FLINT/Arb structural stress methods (`packages/calc`). All artifacts are committed into an append-only, hash-chained, RFC-6962 Merkle-indexed ledger (`evidence_kernel`).

## 2. Core Tool Operational Requirements
- **TOR-01 Deterministic Calculation & Interval Enclosure**: Every built-in stress calculation method shall execute using fixed-precision `Decimal` inputs/outputs with `flint.arb` interval verification confirming half-ULP bounding and bit-for-bit identical replay across repeated runs.
- **TOR-02 Dimensional Homogeneity Enforcement**: Declarative user formula cards shall be verified statically at load time via AST dimensional analysis (`check_expression_dimensional_homogeneity`) and abstain on incompatible physical additions or non-integer root dimensions.
- **TOR-03 Immutable Audit Trail & Cryptographic Binding**: Every calculation, ingestion, review comment, and CVE signoff shall append to an immutable SHA-256 hash chain with RFC 6962 Merkle inclusion proofs verifiable offline without server access.
- **TOR-04 Abstention on Out-of-Envelope or Unverified Inputs**: The tool shall abstain cleanly with explicit machine-readable reasons rather than extrapolating past card limits, fabricated bboxes, or unverified OCR spans.
- **TOR-05 Separation of Duties & Review Thread Gate**: Human CVE signoff shall enforce distinct reviewer separation of duties, reject unresolved `OPEN`/`CHANGES_REQUESTED` review threads, and support HSM/QES LTV signatures and WebAuthn step-up verification.
