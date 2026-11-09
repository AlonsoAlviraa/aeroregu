# ADR-012 Auth and tenancy

- Status: accepted
- Date: 2026-11-03

## Context

The demo needs two human actors and a tenant boundary. It does not need an identity provider.

## Decision

Tables `actors` on the tenant SQLite file. Demo seed is one tenant and two actors (`author`, `reviewer`), both role `human`. Passwords are hashed with PBKDF2 for the local demo only. A session cookie is an HMAC of the actor id. `tenant_id` is on every event. Isolation is a separate SQLite file per tenant. SSO is post-MVP. A sign-off event is not an eIDAS qualified signature. **ASSUMPTION:** a recorded human acknowledgement is enough for the demo.

The local demo passwords are fixtures, not deployment credentials.

## Alternatives

A real IdP in week 1 was rejected.

## Consequences

Anyone with the database file can forge a row if they also rebuild the hash chain. The threat model records that residual.
