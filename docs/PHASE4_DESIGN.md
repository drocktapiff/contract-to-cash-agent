# Phase 4 design

Inspected merged main f880912 before implementation. Extend the existing local app,
not three services or a multi-agent hierarchy. Operational tools and financial engine
remain unchanged. Persona switching is presentation context, not authentication/RBAC.

Use one selected originating investigation plus valid scoped continuations for current
case/exposure aggregation. Replace affected customers, deduplicate overlapping verified
comparisons and never sum repeated run totals. Retain all historical execution durations,
cost estimates and human contributions as explicitly single-operator measurements.
Unknown/stale/contradictory financial evidence is excluded and disclosed, not guessed.

A separate SQLite enterprise journal stores scenario versions, immutable analysis input
snapshots, analysis events/results and human decisions. Reuse the bounded Responses
runtime with a small read-only analytic toolset and a report hook. Only allowlisted
snapshot reference IDs can be retrieved/cited; no arbitrary files, evaluator access or
financial writes. Analyses share the worker, pricing, consent and launch throttle with
investigations. Stale inputs invalidate consequential decisions without deleting history.

ROI is a Decimal Python scenario, not measured savings: per-team recurring costs scale
by team count; one-time implementation cost is a total across teams. Workload reduction
is an optional assumption and does not independently discount employment costs again.
No FX conversion or realized revenue/savings is inferred from the prototype.

Reset is archive-only, confirmed and blocked during work. Move run journals/index and
enterprise history under an archive with a manifest; preserve dataset, admin/pricing,
registered source authority, credentials and the live store lock. Serialize readers so
all handles close before Windows renames. Roll back failures; block writes if recovery
is incomplete. Archived launches remain in shared rate accounting. No reset calls AI.
