---
name: add-requirement-parser
description: >-
  Adds or changes parsing of requirement identifiers from ingested blocks
  into requirement records. Use when working on requirement extraction,
  regulatory paragraph ids, or the requirement store. Does not copy
  regulatory PDFs into git.
---

# Add a requirement parser

## Steps

1. Read root AGENTS.md, ADR-004, and ADR-005.
2. Extend `schemas/requirement.schema.json` only if the contracts workstream has approved the field. Otherwise stop and write a schema request.
3. Parser input is ingest blocks (`text`, `span`, `source_hash`), never a model completion.
4. Match requirement ids with an explicit pattern such as `VTOL\.\d{4}`.
5. Store id, title only if the title string was found in the block, source url, source hash, and label.
6. If the id is found and the title is not, write the id and set the title label to `NOT_VERIFIED`. Do not generate a title.
7. Tests use synthetic blocks in `packages/ingest/tests/fixtures`, not EASA PDFs.
8. A fixture that contains no id returns an empty list, not a guessed requirement.

## Inputs and outputs

- Input: blocks with spans and a source hash.
- Output: requirement records valid against the schema.

## Validation

- Every stored quotation is an exact slice of a fixture block.
- The EASA PDF is not added to git.
- Kernel tests still pass the domain denylist.

## Example

Block text `VTOL.2210 Structural design loads` yields id `VTOL.2210`, title taken from that slice, label `VERIFIED` relative to that fixture only. The provenance note says the fixture is synthetic text shaped like an id, unless the hash matches the founder's recorded public PDF.
