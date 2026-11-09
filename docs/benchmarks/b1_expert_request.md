# Request to the domain expert: B1 held-out set

Date: 2026-11-03. This is a request, not a completed benchmark.

## What we are asking

Please author the held-out half of B1 yourself, from public-style calculation notes that you write for this purpose. The person who wrote the checker in `packages/eval/src/evidence_eval/detect.py` must not write these cases and must not look at them while changing that checker.

Target, from the 12-month goal: at least 150 cases and at least 12 fault types. Those numbers are a target. A smaller delivery is still useful if the author statement and the freeze rules are kept. Do not pad the set with copies of `bench/dev`.

## What the checker already knows

The checker in `detect.py` already has these ids: `unit_scale`, `arithmetic`, `wrong_input`, `sign`, `outside_validity`, `stale_revision`, `false_coverage`, `broken_hash`, `bad_span`, `bad_citation`, `contradictory_requirements`, `unit_mismatch`, and `missing_input` (an abstention, not a detection). `unexplained` is returned when a stated output does not match the recomputed output and is not `unit_scale` at 1000 or 0.001, `sign`, `wrong_input`, or a stated output equal to twice the recomputed output. `unexplained` is not one of the twelve S1 scored faults. The validator does not count it toward the twelve types. Do not use it to pad the twelve types. If more than one fault is returned, the verdict is `detect:compound`. On S1, a compound case passes only when the returned set equals the injected set.

`duplicate_citation` is a known miss. The checker verdict is `clean`. On 2026-11-04 the system abstained, recall 0/1, and that abstain did not match the gold label. That abstain is not a detection. Do not write cases whose only purpose is to teach that detector. A later change may add it, in a separate commit from the cases.

Your cases need at least 12 fault types in total. You choose the numbers, the wording, and any extra type the list above does not have. Do not copy `bench/dev` or `bench/holdout`.

Each file must match `schemas/benchmark_case.schema.json`. Required fields are `case_id`, `artifact_kind` (`note` or `matrix`), `faults`, `expected`, `artifact`, and `provenance`. `expected` is `clean` only when `faults` is empty, `abstain` only when `faults` is exactly `missing_input`, `detect:<fault>` only when `faults` is that one id, or `detect:compound` only when `faults` has at least two ids and does not include `missing_input`. The checker stops on a missing input, so that id is not a compound fault. A mismatch is rejected and is not counted. Do not put a final number in an agent turn. Numbers in `artifact` are decimal strings.

Please use public physical reasoning you are willing to put in a repo that may later be shown to outsiders. Do not use an employer's note, template, number, or geometry.

## Where the files go

Put the cases in a folder outside this repository and set `B1_EXPERT_DIR` to that folder. One JSON object per file. Add `AUTHOR.md` there with your name or role, the date, and the sentence "I did not write the checker in detect.py or b2.py." Do not commit the cases into this repository, and do not paste them into a chat with the agent that edits the checker. The in-repo directory `bench/b1/expert_holdout/` stays without case files. The steps are `docs/benchmarks/blind_holdout_protocol.md`.

`provenance` requires `origin` (`synthetic`, `public`, or `owned`), `author`, `generator_version`, `seed`, and `statement`. `seed` is a JSON integer, not a string. The case may also have `agent_turns`. `provenance` may also have `label` (`VERIFIED`, `PARTIAL`, `NOT_VERIFIED`, `ASSUMPTION`, or `ESTIMATE`). Any other key on the case or on `provenance` is rejected as `schema`. `author` must be you, not `aeroregu`. `statement` must include the words "no employer" or "not employer".

Check the files without scoring them:

```text
uv run python -m evidence_eval validate-b1
```

The command prints counts only. It is ready only at 150 valid files, at least 12 fault types, and the author sentence. Exit 2 means not ready. It does not run the checker.

Until those files exist, the directory stays empty apart from its README. An empty directory is the honest state. Generating this split with `evidence_eval.generate` does not count.

## After you hand them over

We freeze the directory hash in one commit before any further edit to detectors or prompts. From that commit on, the cases are not a development set. Failures on them are reported, including a recall of 0.

## What we will not do

- We will not score these cases and then change the checker to chase the misses in the same week.
- We will not describe the current `bench/holdout` directory as your set. That directory is developer-generated.
- We will not claim the tool finds compliance.

The legal items in `docs/legal/open_items.md` are still open. If your employment contract does not allow this review, do not start the cases.
