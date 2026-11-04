# Phase 3.2 design and boundaries

Inspection of main (e7de235) found stateless Responses orchestration with transient
conversation history, per-run SQLite journals and immutable source snapshot hashes.
Review decisions are separate from model tools and bind exports to finding hashes.
There is no retained conversation checkpoint suitable for exact resumption.

The smallest extension is a new bounded, customer-scoped Responses investigation,
linked to a durable human intervention and its parent finding. It reuses Investigator,
Tools and the unchanged financial engine. Original invoices, amendments and findings
remain intact. A derived evidence revision binds the original snapshot, intervention
and supporting authority record. All original contrary documents remain available.

Initial calculation-changing resolutions support conflicting, signed same-date
set-price amendments for a single customer. Other ambiguity types can be escalated or
dismissed but cannot be resolved by guessing missing quantities or invoice authority.
An employee references an immutable administrator-registered authority record. The
administrator must verify its original source and issuer's authority out of band;
this local application cannot independently authenticate external legal documents.
Registration is an explicit attestation, not a model-generated legal conclusion or
cryptographic proof of the issuer. A mere selection, upload or rationale is insufficient.

Validation checks source hashes, customer/contract/period, original snapshot, exact
conflicting amendment set and asserted governing amendment. Contradictory registered
authority is rejected. Registration is a local administrative CLI, not a model or web
write tool. Local access already implies operator authority, so this is not role-based
authentication. Network deployment remains unsupported.

SQLite migration is additive: existing per-run journals gain human_interventions and optional historical finding_guidance on
first use. Legacy reports need no rewrite; recommendation/history fields are optional.
Human events and intervention state commit together. SQLite is authoritative; JSONL
is a secondary mirror. Original review/export approval cannot carry to a continuation.
Continuation attempts share launch throttles and are capped at three per original case.
No paid API requests, public deployment, automatic merge or financial writes are allowed
while implementing/testing this phase.
