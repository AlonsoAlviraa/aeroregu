---
name: release-and-ci
description: >-
  Changes GitHub Actions, Compose, dependency pins, or the SBOM. Use when
  editing CI or the on-prem smoke path. CI stays on the fixture gateway.
---

# Release and CI

## Steps

1. Keep CI on the fixture gateway. Do not set `MODEL_BASE_URL` in the workflow.
2. Run Ubuntu and Windows for the hash vectors.
3. Fail the job on ruff, pytest, or the secret scan. Run `pip-audit` where the advisory database is reachable.
4. Upload `sbom.cdx.json` generated from the lockfile.
5. Do not cache secrets.
6. Tag releases `v0.x.y` only from main after the founder asks.

## Inputs and outputs

- Inputs: the workflow diff.
- Outputs: a description of what CI runs.

## Validation

- A pull request from a fork cannot receive repository secrets. Do not override that GitHub default.
- The Compose smoke path exports no `MODEL_BASE_URL` and still gets a healthy `/health` response.

## Example

`infra/smoke.py` unsets `MODEL_BASE_URL`, loads the app, and checks `/health`.
