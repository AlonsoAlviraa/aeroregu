# Threat model

Not legal advice. Not a certification claim. Not an export-control clearance.

## Threats

- Spoofing a sign-off actor. Mitigation: local password hash and actor id on the event. Residual: anyone with the database file can forge a row if they also rebuild the hash chain. Disk encryption of the tenant directory is a founder responsibility for a pilot.
- Tampering with evidence. Mitigation: append-only triggers and chain verification at export.
- Repudiation. Mitigation: the sign-off event stores the actor and the target hash. This is not a qualified electronic signature.
- Information disclosure. Mitigation: no telemetry, model off by default, one SQLite file per tenant, private repo, kernel denylist.
- Denial of service. Out of scope for the MVP beyond request timeouts.
- Elevation. There is no admin role beyond the local reviewer actor.

## Data classes

- C0: requirement ids, official URLs, hashes of public files. The local PDF hash in this repo is a placeholder, label `NOT_VERIFIED`.
- C1: synthetic aircraft and benchmark. Private repo until a checklist is signed. That signature is not in this repo.
- C2: `docs/legal/` stays private and out of any public extract.
- C3: customer data. No code path in the MVP.
- Forbidden: employer confidential material and export-controlled technical data.

## What the MVP claims

The MVP stores inputs, runs a named method, hashes the record, and records who pressed sign-off. It does not claim DO-330 qualification, a tool qualification level, a finding of compliance, acceptance by an authority, or a smaller mandatory review.
