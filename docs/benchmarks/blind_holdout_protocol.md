# Blind holdout protocol

Date: 2026-11-09. This is the procedure. It is not a result.

The person who writes these cases must not have written `detect.py`, `b2.py`, or `b3.py`. The agent that edits those files must not open the case files, the reports, or the answers. Send this repository only the JSON that the score commands print.

## Where the files go

Create one folder outside this repository for each benchmark. Do not put the cases under `bench/`. Set the variables to those folders before the commands:

```text
B1_EXPERT_DIR
B2_EXPERT_DIR
B3_EXPERT_DIR
```

Each folder needs an `AUTHOR.md`. B1 and B2 use this sentence: `I did not write the checker in detect.py or b2.py.` B3 uses: `I did not write the checker in b3.py.`

`provenance.author` must not be `aeroregu`. `provenance.statement` must include `no employer` or `not employer`. Do not use an employer's note, number, or geometry.

## What to write

B1. One JSON object per file. Required keys are `case_id`, `artifact_kind` (`note` or `matrix`), `faults`, `expected`, `artifact`, and `provenance`. The case may also have `agent_turns`. Any other key is rejected. `provenance` needs `origin` (`synthetic`, `public`, or `owned`), `author`, `generator_version`, `seed`, and `statement`. It may also have `label` (`VERIFIED`, `PARTIAL`, `NOT_VERIFIED`, `ASSUMPTION`, or `ESTIMATE`). `seed` is a JSON integer, not a string. Any other provenance key is rejected. `expected` is `clean` only when `faults` is empty, `abstain` only when `faults` is exactly `missing_input`, `detect:<fault>` for one fault, or `detect:compound` for two or more faults other than `missing_input`. The longer note is `docs/benchmarks/b1_expert_request.md`. The programme target is 150 valid cases and 12 fault types. A smaller set can be scored and stays not ready.

The checker runs only `bolt_screen` at `bolt_screen@1.0.0` and `rigid_body_point_mass` at `rigid_body_point_mass@1.0.0`. Any other `method_id` abstains. Numbers in `artifact` are decimal strings, not JSON numbers.

`bolt_screen` inputs are `shear_force_n`, `tensile_force_n`, `area_mm2`, `shear_allowable_mpa`, and `tensile_allowable_mpa`. Forces stay inside -1000000000 to 1000000000. Area is above 0 and at most 1000000. Both allowables are above 0 and at most 10000. A value outside that range is `outside_validity`.

`rigid_body_point_mass` inputs are `mass_kg` (1 to 5000), `gravity_m_s2` (9 to 11), `load_factor` (-2 to 4), `cg_x_m` (-5 to 5), `unit_x_m` (four decimal strings, each -10 to 10), and `unit_operative` (four JSON booleans, at least three `true`). A string `"true"` is not a boolean and is `outside_validity`.

`artifact.inputs_hash` is the canonical SHA-256 of `artifact.inputs`, not of the whole case. From the case file, outside this repository, and not pasted here:

```text
uv run python -m evidence_eval hash-inputs PATH --at artifact.inputs
```

Hashing the whole case file produces a different digest, and the checker then reports `broken_hash`. The command prints one SHA-256 line and does not print the file. For `document_sha256`, hash the raw document bytes:

```text
uv run python -m evidence_eval hash-file PATH
```

A different `method_version` is `stale_revision`. `source_text` and `quotation` (`text`, `span_start`, `span_end`) must satisfy `source_text[span_start:span_end] == text`, or the case is `bad_span`. `stated_outputs` must be the whole recomputed object, not one field. Each value is a decimal string quantized to 0.001. A missing key is not `clean`. Omit `coverage_status`. Setting it to `calc` without the canonical hash of the recomputed outputs is `false_coverage`. Do not send those numbers here.

`bolt_screen` output keys are `shear_stress_mpa`, `tensile_stress_mpa`, `shear_ratio`, `tensile_ratio`, and `interaction_ratio`. `rigid_body_point_mass` output keys are `weight_n`, `required_vertical_force_n`, `unit_force_n`, `vertical_residual_n`, and `moment_about_cg_n_m`. `unit_force_n` is four decimal strings.

B2. JSON cases with `case_id`, `report`, `gold_links`, `evidence`, and `provenance`. `gold_links` is a list of `[requirement_id, evidence_id]`, each a string. A list that is not those pairs is `gold_links`. An empty list is allowed. `evidence` is a list of objects with `id` and `hash`. An empty `evidence` list is an abstention, not a detection. A hash of 64 zeros is a bad hash and that pair is not linked. A missing `hash` is not a bad hash. The linker emits a link only when one of `CS-27.301`, `CS-29.301`, `VTOL.2200`, `VTOL.2210`, `VTOL.2215`, `VTOL.2220`, `VTOL.2225`, or `VTOL.2230` sits within 80 characters of an `ev-` id. Any other heading is not linked. A report that copies a development report is rejected.

B3. A document that is not NASA-TM-101040 and not NASA Technical Memorandum 101 061, plus a JSON case with `case_id`, `document_sha256`, `document_path`, `fields`, and `provenance`. `document_path` is relative to the expert folder. The file bytes must match `document_sha256`. A missing `document_path` is `path_missing`. A path that leaves the folder is `path_outside`. A missing file is `document_absent`. A byte hash that does not match is `hash_mismatch`. Those counts are in `abstain_reasons`. They are not detections, and they do not name the file. Each field needs `name` and `value_text`. A missing name or value is `fields`. `copied_dev_gold` means the whole set of name and value pairs equals a development gold set. One shared value is not that code. A hit needs the value as its own number in the document, not as digits inside a longer number. A unit other than `1`, an empty string, or `dimensionless` must follow that number within 16 characters and be the same unit.

Do not copy `bench/dev` or `bench/holdout`.

## Commands

From `C:\Users\Mariano\Documents\ALONSOO\AIRBUS\evidence-layer`, the repository that contains this file. The published name is aeroregu. The folder `C:\Users\Mariano\Documents\ALONSOO\evidence-layer` does not contain the scorer.

```text
uv run python -m evidence_eval validate-b1
uv run python -m evidence_eval score-blind-b1
uv run python -m evidence_eval score-blind-b2
uv run python -m evidence_eval score-blind-b3
```

The variable must point outside this repository. If it is unset, or if it points inside the repository, the matching command does not open that folder and exits 2. `validate-b1` prints counts and does not run the checker. Its `reject_reasons` are `json`, `unreadable`, `schema`, `provenance`, `author`, `statement`, and `expected`. B2 codes are `json`, `unreadable`, `schema`, `case_id`, `report`, `gold_links`, `evidence`, `provenance`, `author`, `statement`, and `copied_dev_report`, from `score-blind-b2` when that command refuses to score. `evidence` means the field is present and is not a list of objects with `id`. An empty list is not that code. B3 uses `json`, `unreadable`, `schema`, `case_id`, `document_sha256`, `dev_document`, `fields`, `provenance`, `author`, `statement`, and `copied_dev_gold`, from `score-blind-b3` in the same way. A `stopped` field is only the exception class. None of these reports print file names, exception messages, or case text. Fix the files from the code, and do not paste a rejected case here. `score-blind-b1` includes `fault_recall` and `fault_counts` (`hits/total`) for every fault id in the set, not only the five deterministic faults, and it does not include case ids. Exit 2 means the folder was not scored. Exit 0 means a score was printed. B3 still leaves `ready` false after a score. That flag is the programme state, not a hidden case.

## After the score

Do not commit the cases into this repository. With the same variables set, record the freeze digest:

```text
uv run python -m evidence_eval hash-blind-dirs
```

That command prints a file count and a SHA-256 for each folder that is set. It covers every file in the folder, including `AUTHOR.md` and a B3 document. It does not print file names or file text. Send that JSON with the score JSON. A later change to any file changes the digest.

Do not change the checker in the same week to chase misses. Failures stay in the report, including a recall of 0.
