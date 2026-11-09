# ADR-013 On-prem

- Status: accepted
- Date: 2026-11-03

## Context

The MVP runs on the founder's machine. A paid server is not required. Whether that machine is personally owned was **NOT VERIFIED** by this implementation. If it is an employer machine, stop.

## Decision

`infra/compose.yaml` runs the API with telemetry off and the gateway defaulting to fixture. `MODEL_BASE_URL` is not set. A smoke script passes with the network model unset.

## Alternatives

Kubernetes, SSO, and a hosted log vendor are omitted. Jobs finish inside one request.

## Consequences

Compose is the on-prem path. The smoke check used in CI calls the app in-process so it does not require a local Docker daemon.
