# B3 expert held-out

Cases here are written by someone who did not write `packages/eval/src/evidence_eval/b3.py`.

`AUTHOR.md` must include: I did not write the checker in b3.py.

Without that sentence, JSON files in this directory are not scored.

Do not copy the dev gold. Do not use the SHA-256 of NASA-TM-101040 or NASA Technical Memorandum 101 061. Those files were used to write the checker. Each case needs `case_id`, `document_sha256`, `document_path`, `fields`, and `provenance.author`. `document_path` is relative to the expert folder when `B3_EXPERT_DIR` is set, and relative to the repository root for the live directory. The file hash must match `document_sha256`. A missing file abstains and is not a detection. The author must not be `aeroregu`. `provenance.statement` must include "no employer" or "not employer". A case whose fields repeat the dev gold names and values is rejected.

Set `B3_EXPERT_DIR` to a folder outside this repository and run `uv run python -m evidence_eval score-blind-b3`. The command prints counts only. The procedure is `docs/benchmarks/blind_holdout_protocol.md`. Status on 2026-11-09: empty. The files are not scored.
