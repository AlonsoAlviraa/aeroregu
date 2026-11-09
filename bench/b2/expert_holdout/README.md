# B2 expert held-out

Cases here are written by someone who did not write `packages/eval/src/evidence_eval/b2.py` or `detect.py`.

`AUTHOR.md` must include: I did not write the checker in detect.py or b2.py.

Without that sentence, JSON files in this directory are not scored.

Do not generate this split from the dev scorer. A report that repeats a development report is rejected. Each case needs `case_id`, `report`, `gold_links`, and `provenance.author`. Scoring also needs `evidence` with an id and a hash. A case with no hash abstains and is not a detection. The author must not be `aeroregu`. `provenance.statement` must include "no employer" or "not employer".

Set `B2_EXPERT_DIR` to a folder outside this repository and run `uv run python -m evidence_eval score-blind-b2`. The command prints counts only. The procedure is `docs/benchmarks/blind_holdout_protocol.md`. Status on 2026-11-09: empty. The files are not scored.
