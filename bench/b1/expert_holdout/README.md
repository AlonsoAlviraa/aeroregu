# B1 expert held-out

This directory is not a citable benchmark.

Cases must be written by someone who did not write the checker. Until that person writes them, the benchmark must not be cited. The person who wrote the checker must not fill this directory.

Do not run the smoke generator into this directory. Do not copy `bench/dev` or `bench/holdout` here. Do not add JSON cases or gold labels from the checker author.

`AUTHOR.md` must include: I did not write the checker in detect.py or b2.py.

Check without scoring: `uv run python -m evidence_eval validate-b1`. Ready means 150 schema-valid cases, at least 12 fault types, and that sentence. While this directory has no case files, `cite_expert_holdout()` reports `ready` false and `reason` empty.

The request is `docs/benchmarks/b1_expert_request.md`. The freeze rule is `docs/benchmark_spec.md`.

Put the files here, or set `B1_EXPERT_DIR` to a folder outside this repository. A folder outside the repo is the one an agent will not open while editing the checker. `validate-b1` and `score-blind-b1` read that variable when it is set.

```text
uv run python -m evidence_eval validate-b1
uv run python -m evidence_eval score-blind-b1
```

`score-blind-b1` prints counts only. It does not print case ids, artifacts, or stated numbers. It does not score until `AUTHOR.md` contains the sentence above and every JSON file passes the schema. An agent that edits `detect.py` or `b2.py` must not open the JSON files.

Status: no expert cases yet. That empty state is not a benchmark result. Do not cite it. UnitSafe and Dronology, scored by `external-public`, are someone else's data. They are not this directory.
