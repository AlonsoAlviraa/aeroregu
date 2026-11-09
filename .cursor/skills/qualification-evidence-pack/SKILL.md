---
name: qualification-evidence-pack
description: >-
  Assembles a release folder of tool evidence. Use in Phase 6 when cutting a
  release folder. The folder says the tool assists a human. It does not say
  the tool is qualified.
---

# Qualification evidence pack

Phase 6 only. Do not build the pack in the MVP.

## Steps

1. Copy SBOM, method versions, benchmark metrics, and the limits list into `dist/tool-pack/<version>/`.
2. Include the sentence that the tool assists and is not qualified.
3. Do not write a tool qualification level.
4. Do not mention DO-330 except as a reading item for counsel.

## Inputs and outputs

- Inputs: the git tag.
- Outputs: a folder and a hash manifest.

## Validation

- A grep test fails if the pack contains "qualified" or "TQL".
- The MVP does not create `tools/pack` or `docs/qualification`.

## Example

The pack may list a measured deterministic recall from a named test. It never presents that number as a certification credit. FAA AC 20-115D stays a reading item. This repository did not re-read that PDF.
