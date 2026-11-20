# Phase 5 — Management intelligence and full demo preparation

Launch the existing Windows launcher or localhost FastAPI application as documented
in WINDOWS_LAUNCHER.md. The app must bind to 127.0.0.1. Passwordless local mode is
not public authentication; network/public deployment requires proper identity and
authentication. Persona selection is presentation context, not role-based access.

## Prepare and present

1. Open **Advanced Settings → Prepare Full Demo**.
2. Read the simulation confirmation and select **Confirm preparation — no API usage**.
3. Select **Start Full Demo / View Maya’s Results**. Open any finding and its original
   contract/invoice evidence. All prepared records are labeled **Simulated Demo Data**.
4. Select **Jump to Sarah**. The Department Overview shows current verified financial
   exposure and unknown cases. The shared pricing card compares the actual C008,
   C009 and C010 records; configuration root cause is explicitly a hypothesis.
5. Under **What Needs Your Attention**, select **Record management action**, assign
   an internal owner, priority and target date, enter rationale and closure criteria,
   then save the human decision. Reopen it to update status; inspect audit history.
6. Select **Jump to Robert**. The same root investigation, exposure, uncertainty and
   Sarah's human actions are available alongside the Python ROI assumption calculator.
   AI expansion analysis is optional and still requires separate paid authorization.
7. Use **Scenario overview / Maya’s Results** to return. Reload preserves the selected
   run in the URL. To prepare again, return to Advanced Settings. The archive-only
   Reset Demo remains a separate, explicitly confirmed action.

No key or current pricing confirmation is required for preparation or browsing.
Existing investigations, incomplete analyses, journals and human decisions are never
deleted or silently completed. The source dataset is never edited. Unchanged source
revision + fixture version maps to the same scenario identifier. If source evidence
changes, old history remains; stale amounts are excluded until current evidence is
reviewed. Repeating preparation creates a separate scenario for the new revision.

## Contracts and governance

Preparation uses production read-only Tools and Decimal financial calculations,
including all 40 comparisons, original document retrieval, supported findings and
pending real reviews. Fixture events use `demo_fixture` actors, `demo.tool.completed`
and explicit provenance. No fake Responses, provider IDs, request events, token usage
or billed cost is created. API counters are zero; fixture operation counts are separate.
Simulated review annotations do not grant real review/export approval. Actual billed
cost stays unknown/null; the no-request preparation estimate is zero.

The UI derives facts, patterns and suggested priorities from the same operational
snapshot used by the executive workflow. CAD receivables and credits are separate;
combined exposure is the sum of absolute known differences, not net recovery.
Administrative review, dismissal or task closure does not prove financial correction
or resolve conflicting signed authority. Unknown exposure stays unknown. No measured
time saving, labor reduction, productivity or realized ROI is asserted. Outcomes
without evidence remain **Not yet measured** and have explicit pilot measurement needs.
Robert's scenario is an assumption-based projection, not an approved investment.

Human management actions extend the enterprise SQLite/audit store. Each record binds
the root, issue, immutable case references and source revision; changes append reviewer,
rationale, criteria, timestamp and version history. Updates use optimistic version and
source checks. Closing a task requires supporting issue references and human review;
it remains administrative task closure, never financial correction. No action updates
invoices, settles contract authority, sends messages, authorizes export or records a
final strategic decision. The configured local reviewer is recorded; persona selection
does not authenticate Sarah/Robert. Existing strategic decisions retain their separate
human confirmation, citations, rationale, source/current version and authority checks.

Sarah's AI report is secondary under **AI Findings & Supporting Evidence**. The fixed
Phase 4 contract exposes management `validation_status`, not investment `stance`;
Robert alone receives executive `stance`. Every advertised enum choice has a successful
local-save regression. Financial, evidence, CSRF/Origin/session and paid-run safeguards
are unchanged. All simulated records remain distinguishable from real human actions
made later inside the simulated scenario.

## Persistence and recovery

Preparation holds the shared worker/store lock and refuses active jobs, recorded mode,
shutdown or recovery blocks. It writes to a unique `.demo-preparation` staging directory,
closes all SQLite handles, renames the complete journal directory, then atomically
publishes run metadata last. Before publication no incomplete seed is visible as a
completed run. An interruption after directory rename is recovered by repeating
preparation. Earlier interrupted staging directories remain retained for inspection;
they are not current scenarios or counted in totals. Do not manually edit SQLite files.
If retained published content fails revision/provenance checks, preparation refuses it
for administrator inspection. Existing reset recovery restrictions still apply.

Demo metadata is excluded from paid-launch quotas because it makes no API requests;
real investigations/analyses, including archived paid records, retain their shared
limits. Preparing a demo does not bypass current pricing, explicit paid consent, key
checks, or the one-worker limit for a later genuine run.

## Validation and screenshots

Run the existing unittest suites, frontend build/tests, schema check and browser smoke
scripts. The additional acceptance command is:

```
PLAYWRIGHT_BROWSERS_PATH=work/browsers .web-venv/bin/python -m scripts.smoke_full_demo --screenshots docs/screenshots/phase5
```

On Windows use `.web-venv\\Scripts\\python.exe` and set the browser path using the
shell's environment syntax, or omit the override for a default Playwright install.
The CI Ubuntu/Windows matrix runs this workflow without paid API calls. Captures show
Maya, Sarah's saved internal action and Robert using the same scenario, plus mobile.

Captured browser evidence:

- [Maya's prepared investigation](screenshots/phase5/01-maya-prepared-demo.png)
- [Sarah's Management Command Center](screenshots/phase5/02-sarah-management-command-center.png)
- [Robert's shared context and ROI assumptions](screenshots/phase5/03-robert-shared-context.png)
- [Sarah on mobile](screenshots/phase5/04-sarah-mobile.png)
