# Ledgerline 2.0 Stage 3.1 — Human Review and Operational Activity

Automation now prepares administrative results; it does **not** close them. Maya
must explicitly review a result before it becomes **Reviewed & Closed**. Sarah’s
Operational Activity graph traces those same persisted cases through preparation,
human verification and management oversight. No OpenAI request is needed for this
workflow, the graph, its drill-downs or recorded replay.

## Windows Git Bash update and launch

Stop the server with **Ctrl+C** before updating. Preserve the existing checkout,
`.web-venv`, `agent-runtime-web`, `runs/web`, `runs/web-documents`, PDFs and journals.
Do not delete SQLite files, rebuild an existing runtime or reset paid history.

```bash
git fetch origin
git switch feature/ledgerline2-human-review-analytics
git pull --ff-only
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
python -m contract_to_cash.web
```

Or, after building, double-click **Start Ledgerline.cmd** or its installed shortcut.
Open `http://127.0.0.1:8000/`. Python 3.13 and Node 22.12+ are required. First-time
installation is documented in [Stage 2 setup](LEDGERLINE2_STAGE2.md). Linux/macOS
activate `.web-venv/bin/activate`. Restart after updating; an existing server continues
to use its previously loaded code.

The application remains strictly bound to **127.0.0.1**. Passwordless local mode is
unsuitable for public/network deployment. Verified authentication and authorization
are prerequisites for any such deployment. Persona selection and typed attribution
are not authenticated role-based access control.

## Presenter walkthrough — entirely free

1. **Load Sample Documents** and confirm the isolated import. On the unchanged
   sample, 149 actual fictional PDFs produce 102 work items, initially unprocessed.
2. **Select All Matching → AI Powered Close**. Confirm administrative-only scope.
   Supporting text explains that this is deterministic Python PDF validation and
   reconciliation, not live model reasoning. The 73 eligible checks become
   **Awaiting Maya Review**. **Reviewed & Closed remains zero.** The 29 financial,
   contractual or evidence exceptions remain unresolved.
3. Choose **Awaiting My Review** and open one item. Select **Review Automated
   Result**. Inspect the automated finding, calculation, original PDF links and
   extracted fields. Review provenance includes the preparation event/operation,
   captured item version and every source hash.
4. Select **Approve & Close**, enter attribution and rationale, and explicitly
   acknowledge reviewing the presented result and evidence. One human-attributed
   decision closes this administrative case. It authorizes no financial transaction.
   **Reject Automated Result**, **Request Additional Evidence**, and **Escalate to
   Sarah** record separate decisions instead of closing the case.
5. Close the item. Click **Review All** for the remaining pending results. Without a
   selection this captures all pending items across pages; with a selection it reviews
   only that captured selection. The dialog reports selected, eligible, excluded,
   changed-evidence, previously rejected and individual-investigation counts. The
   untouched demonstration has 72 eligible remaining results after step 4.
6. Inspect the listed checks. Enter attribution/rationale and explicitly attest the
   bulk review. It is labeled **bulk-attested**, not individually inspected. Each
   item receives its own immutable decision tied to the shared operation. Inspect
   per-item exclusions or failures before treating the batch as complete.
7. On the unchanged scenario, **Reviewed & Closed** now shows 73. Use **Select All
   Remaining Work → Escalate to Sarah** for the 29 exceptions. Existing Finance and
   evidence authority is preserved; escalation is management oversight, not approval.
8. Switch to **Sarah — Management Command Center**. **Operational Activity** appears
   above the existing management dashboard. Blue circles show Ledgerline preparation;
   green diamonds/squares show Maya’s individual/bulk reviews; orange triangles show
   management handoffs received. A receipt is not a resolution.
9. Select a blue point to inspect the actual prepared work and events. Open a case
   and its original PDFs, calculations and recorded human review. Select a green
   point to distinguish individual approval from bulk attestation. Select an orange
   point to inspect the real escalation records and outstanding decision ownership.
10. Use the series checkboxes, outcome, cumulative/interval view, second/minute/hour
    grouping, recorded-time range and operation zoom. The accessible recorded-point
    list provides another way to select coincident points. Tab to an SVG marker and
    use Enter or Space to open it. Mobile layouts and the graph’s dark palette retain
    labels, markers, contrast and point-to-case navigation.

Maya’s **Needs My Attention**, **Awaiting My Review**, **Review Rejected**,
**Awaiting Others**, **Reviewed & Closed**, and **All Work** views retain selection,
pagination, sticky actions, Show Me the Work, escalation and evidence interfaces.
A rejected automated result remains blocked from automatic preparation/closure;
retrying AI Powered Close never turns it into an approval.

## What the graph measures

The chart uses the selected session’s immutable workflow events and exact source
work-item IDs. It never seeds a separate analytics dataset or invents historical
activity. The X-axis uses recorded timestamps, including milliseconds. An operation
point uses its latest contributing event time and exposes its actual first/last
range. Other intervals group actual events by second, minute or hour. A short demo
may legitimately have coincident timestamps and only one point in a series; no
synthetic spacing, starting points or illustrative sequence numbers are added.

Each point exposes its mechanism/actor, real events, statuses, decisions, evidence
hashes and source operation IDs. Work buttons show the current state; contributing
events retain the state transition at the time of that activity. The event and work
lists remain scrollable so a large batch does not overwhelm the dashboard.

- **Cumulative** counts distinct work IDs per actor among the selected events and
  time range. **Interval** counts distinct work IDs in each selected group.
- Stage contributions overlap. The same case can be prepared, reviewed, closed and
  escalated; those contributions must not be added into a completed-work total.
- **Reviewed & Closed** counts distinct currently closed items with actual approval
  records. Legacy closures are reported separately without invented human approval.
- **Approved individually** and **Bulk approved** use the recorded attestation, not
  assumptions about how much attention a person gave each item.
- **Awaiting review** is a filter for the current pending cohort, not a fabricated
  historical backlog curve. Quality metrics below the chart cover the whole session
  independently of the chart’s filters.
- **Review acceptance rate** is approved decisions divided by approved plus rejected
  decisions. Pending results are excluded. Without decisions it is **Not Measured**.
- **Review turnaround** uses actual preparation-to-decision timestamps. It is elapsed
  wall-clock time, never hands-on labor or claimed hours saved. Missing or invalid
  intervals are not represented as measured labor or a fabricated baseline.
- Escalations received and management reviews completed have separate filters and
  markers. Receiving a case never implies resolving it.

The retained Stage 3 workload/flow charts still partition current work. Automation
preparation rate now means prepared checks / total work. Closure is separately
human-reviewed or explicitly legacy. Financial exposure remains separate Python
Decimal categories; no net recovery, issued credits or realized savings are claimed.

## Persistence, migration and safeguards

The migration is additive. New sessions record
`completion_policy=mandatory_human_review_v1`. Existing session databases receive an
immutable `human_review_decisions` table and triggers; existing work bodies,
financial values and event history are not rewritten into fabricated approvals.
Any historical Closed item without a recorded human review is visibly labeled:

**Legacy automated closure — no recorded human review**

New processing in either an existing or fresh session follows the two-stage model.
Historical closed records are not reopened or silently re-attested.

Prepared results retain their immutable event ID, operation, source/prepared versions,
evidence hashes, deterministic comparison and mechanism. Approval requires a matching
real preparation event, current low-risk reconciliation, current captured work version,
all original source hashes, actor, rationale and explicit acknowledgement. Changed,
uncertain, high-risk, rejected, already closed, foreign or stale items cannot be
bulk-approved. An integrity failure must be investigated and valid source evidence
restored/revalidated; a new session can import new authoritative source records.

Review decisions retain individual/bulk provenance, source versions/hashes, the
associated preparation event/operation, rationale, actor and prior/resulting status.
Database triggers reject updates/deletes. The existing workflow journal remains
append-only. Unique preparation references prevent duplicate decisions; operation
fingerprints make same-request retries idempotent and reject conflicting reuse.
Per-item savepoints preserve accurate partial results. Interrupted uncommitted batches
roll back, retain interrupted operation state, and can retry the same request safely.

Human decisions are never emitted as deterministic-automation actions. Browser test
interactions carry simulated-fixture provenance and are not genuine employee approvals.
The software does not claim a bulk attestation is an individual inspection.

Restart Demo creates a fresh unprocessed active session and preserves previous source
PDFs, reviews, management actions, journals and paid history. Retained sessions remain
readable and read-only. Recorded replay and chart navigation issue no new decisions.
The shared worker guard blocks conflicting mutations while another operation runs.
All database connections/cursors and journals close explicitly, including on failures.

No review operation changes invoices, resolves contractual authority, issues credits,
moves cash, approves exports or sends external messages. Sarah’s existing priorities,
coordination, returns, evidence/Finance requests, corrective actions and rule-based
operational overview remain available. The Stage 3 advisor receives accurate workflow
statuses and review provenance; pending preparation cannot be reported as completed
work. Its explicit paid authorization, current pricing, shared rolling limits, bounded
runtime/tool/cost controls and credential handling are unchanged.

## APIs and validation

- `POST /api/document-workspace/sessions/{sid}/review-preview`: current selection,
  evidence-integrity, low-risk eligibility and exclusion details; no decision writes.
- `POST .../human-reviews`: explicitly acknowledged individual decision or bulk
  approval. Captured IDs, versions and evidence hashes are mandatory.
- `GET .../activity`: read-only chart/quality projections. Query fields include
  `mode`, `group`, `outcome`, `series`, timezone-aware `start`/`end`, and `operation`.

All routes retain local sessions, CSRF/Origin checks for writes, session isolation and
server-side eligibility enforcement. A successful preview cannot bypass a subsequent
version/source check. API keys never enter the frontend or the analytics inputs.

```bash
python -m pip install -r requirements-documents-test.txt
python -W error::ResourceWarning -m unittest discover -s contract_to_cash/tests -v
python -W error::ResourceWarning -m unittest discover -s tests_web -v
python -W error::ResourceWarning -m unittest discover -s tests_launcher -v
python -W error::ResourceWarning -m unittest discover -s tests_documents -v
python -W error::ResourceWarning -m unittest discover -s tests_workspace -v
python -m scripts.export_web_schema --check
npm --prefix frontend run build
npm --prefix frontend test
python -m playwright install chromium --only-shell
python -m scripts.smoke_human_review_activity --screenshots docs/screenshots/stage31
```

Windows/Ubuntu CI runs all suites, the alternate-seed document evaluator and all eleven
browser workflows. Tests use actual fixture PDFs and mocked providers; no paid requests
are made. [Stage 3’s separately authorized live advisor acceptance procedure](LEDGERLINE2_STAGE3.md#explicitly-authorized-local-live-analysis-acceptance)
remains available, but live requests are not needed to validate Stage 3.1.

## Browser evidence

These screenshots show actual deterministic PDF processing, real persisted fixture
reviews and shared analytics in an ephemeral browser-test session. Human interactions
are explicitly simulated test actions; no live OpenAI run is implied.

- [73 prepared, zero reviewed closures](screenshots/stage31/01-prepared-awaiting-human-review.png)
- [Individual evidence review](screenshots/stage31/02-individual-evidence-review.png)
- [Bulk attestation](screenshots/stage31/03-bulk-attested-review.png)
- [Sarah’s operational activity](screenshots/stage31/04-sarah-operational-activity.png)
- [Automation contribution drill-down](screenshots/stage31/05-automation-point-drilldown.png)
- [Individual approval and evidence](screenshots/stage31/06-individual-approval-point.png)
- [Escalation received, not resolved](screenshots/stage31/07-management-received-point.png)
- [Mobile activity](screenshots/stage31/08-mobile-activity.png)
- [Dark activity](screenshots/stage31/09-dark-activity.png)
