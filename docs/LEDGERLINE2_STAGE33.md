# Ledgerline 2.0 Stage 3.3 — Management Performance Dashboard

Sarah’s Overview now opens with four KPIs, **Current Work Distribution** and
**Work Handled by Each Function**. It is a presentation and read-only analytics
improvement; Maya’s workflow, Sarah’s decisions and financial calculations are unchanged.

## Windows update and launch — Git Bash

Stop Ledgerline with **Ctrl+C** in its server/launcher console before updating.
Preserve `.web-venv`, `agent-runtime-web`, `runs/web`, `runs/web-documents`, PDFs,
SQLite journals and retained sessions. Do not delete or replace runtime/history files.

```bash
git fetch origin
git switch feature/ledgerline2-management-dashboard-polish
git pull --ff-only
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
python -m contract_to_cash.web
```

After rebuilding, you can instead use **Start Ledgerline.cmd** or the existing
shortcut. Open `http://127.0.0.1:8000/`. Python 3.13 and Node 22.12+ are required.
For first-time installation use [Stage 2 setup](LEDGERLINE2_STAGE2.md); on Linux/macOS
activate `.web-venv/bin/activate`. Restart after updating: an old process retains its
loaded Python code. If the new dashboard is missing, verify the branch, stop the old
server, rebuild, restart and refresh the browser.

The application remains bound strictly to **127.0.0.1**. Passwordless local mode is
unsuitable for public/network deployment. Proper authentication and authorization
are prerequisites for future public deployment. Persona selection and typed reviewer
attribution are not authenticated role-based access control.

## Free presentation walkthrough

Use 1920 × 1080 at 100% browser zoom for the recording. The default Overview fits the
four KPIs, current distribution and all three contribution rows in that viewport.
Laptop and mobile layouts remain usable; mobile stacks the cards and legends.
Light/dark themes use the browser’s colour-scheme preference. No animated bar fills
or delayed transitions are used in the primary dashboard.

1. In Maya, **Load Sample Documents** and confirm the isolated intake. The unchanged
   sample produces 102 work items from 149 original fictional PDFs.
2. **Select All Matching → AI Powered Close** and confirm. This prepares 73 checks;
   it closes zero cases. No OpenAI request is involved.
3. Inspect and approve one result through **Review Automated Result** with attribution,
   rationale and acknowledgement. **Review All** then explicitly bulk-attests the
   remaining 72 eligible results. Bulk attestation is not individual inspection.
4. **Select All Remaining Work → Escalate to Sarah**, confirming the actual 29 handoffs.
   Alternatively, hand off a subset to demonstrate partial escalation; the dashboard
   reflects the saved actions rather than assuming every exception was escalated.
5. Switch to **Sarah — Management Command Center → Overview**. On that unchanged
   fully reviewed scenario, the KPIs show 102 identified, 73 reviewed/closed, 29 open,
   and 71.6% preparation. These are fixture expectations, not application constants.
6. Click **Reviewed & Closed** to inspect its exact cases. Click a current distribution
   segment or legend entry to inspect an unresolved queue, such as **Awaiting Finance**.
   Search/filter/page within that exact set. Open source PDFs and the original case.
7. Click each function row. Ledgerline opens preparation evidence; Maya opens recorded
   review attribution; Sarah opens actual management handoffs. Breakdown buttons open
   their subsets. The same Stage 3.2 drawer serves every selection, preserving keyboard
   access, focus restoration and protection against delayed native close events.
8. Use the existing **Escalations**, **Management Intelligence** and **Corrective Actions**
   tabs as before. Returning to Overview reads the actual saved state. A completed
   management review does not close the case or grant Finance/contract authority.
9. Expand **Detailed Lifecycle & Accountability**, **Activity Over Time**, or
   **Operational metrics & exposure** for the earlier analysis tools. They are retained
   but collapsed by default. The free rule-based operational overview and internal
   corrective-action entry points remain below them.
10. Restart Demo only when intentionally creating a new retained session. Existing
    sessions, original PDFs and decisions remain preserved and browsable.

The free workflow, dashboard, tooltips, evidence navigation and screenshots require
neither an API key nor paid pricing confirmation. Management Intelligence and legacy
paid workflows keep their separate consent, pricing, limit and authorization gates.
Nothing in chart navigation starts an analysis or approves an export.

## How the numbers work

The existing read-only endpoint
`GET /api/document-workspace/sessions/{sid}/lifecycle` now includes `performance`.
It reads the same work, documents and immutable events in one SQLite transaction.
There is no new endpoint, migration, invoice arithmetic or workflow mutation.

- **Work Items Identified:** all distinct persisted work-item IDs in the session.
- **Reviewed & Closed:** the existing Stage 3.2 closed bucket, requiring valid attributed
  review/preparation provenance and administrative closure. An apparent approval without
  a valid matching journal event is unclassified, not counted as verified closure.
- **Open Work:** current cases outside valid reviewed closure and historical legacy
  closure. A separate banner identifies legacy closures without recorded human review;
  they are never presented as reviewed or fabricated as newly open cases.
- **Automation Preparation Rate:** distinct cases with a recorded preparation divided
  by all work items. Its click opens the preparation case set; no cases means no measured
  rate, displayed as a dash rather than invented throughput.
- **Source documents:** actual saved PDF records, counted separately from work. The
  context link opens original documents and their recorded case relationships.

**Current Work Distribution** reuses the exact Stage 3.2 mutually exclusive partition
and ownership precedence. Its case sets reconcile to all distinct work IDs. Finance
and evidence authority remain unresolved after management coordination; returns,
rejections, pending review, unprocessed work and unknown records retain their own
buckets. Small categories remain available in the labelled legend and keyboard controls.
Displayed percentages are rounded for readability; backend shares use exact counts
against the session total. No segment is manufactured by subtracting historical stages.

**Work Handled by Each Function** measures contributions, which intentionally overlap:

- Ledgerline counts cases with actual completed preparation events.
- Maya counts unique cases with valid recorded approval, rejection, evidence request
  or review-escalation decisions bound to a prior preparation. The individual and bulk
  subsets retain attestation provenance. A rejection is review activity, not closure.
  Ordinary system routing is not counted as human review or manual investigation.
- Sarah counts actual distinct management handoffs, deduplicating sent/received records
  for one operation. Awaiting action, current returns and pending Finance/evidence
  authority are current subsets; completed coordination comes from actual completed
  management-review events. Completed coordination can overlap another pending authority.
  Neither these breakdowns nor the function totals should be added as independent cases.

The information control, hover details and drawer retain these distinctions without
putting long methodology paragraphs in the default chart. Drawers show supporting
contribution events first, with original timestamps and the rest of the case history
still available. No history is rewritten or synthetic approval created.

The dashboard keeps using session/revision updates and fresh reads after workflow
changes and persona/tab navigation; it has no independent cache or fixture totals.
All original source-integrity, immutable journal, human-review/version, session,
CSRF/Origin, localhost, financial and paid-use safeguards remain enforced server-side.
No labor savings, recovered revenue, issued credits or completed financial transactions
are claimed. Historical escalation is kept separate from current decision ownership.

## Validation and screenshots

The CI matrix runs all Python suites, schema checks, frontend tests/builds,
alternate-seed document evaluation and all thirteen browser workflows on Windows and
Ubuntu. The original twelve remain enabled. The new browser flow processes actual PDFs,
performs real simulated UI reviews/handoffs, checks all KPI/segment/contribution sets,
opens original PDF bytes and cases, checks pagination/search and keyboard focus,
exercises the delayed-close regression, verifies a 1080p layout, mobile/dark themes,
retained advanced analytics and proves navigation adds no POSTs or journal events.
All providers are mocked; no paid requests are used.

```bash
python -W error::ResourceWarning -m unittest discover -s contract_to_cash/tests -v
python -W error::ResourceWarning -m unittest discover -s tests_web -v
python -W error::ResourceWarning -m unittest discover -s tests_launcher -v
python -W error::ResourceWarning -m unittest discover -s tests_documents -v
python -W error::ResourceWarning -m unittest discover -s tests_workspace -v
python -m scripts.export_web_schema --check
npm --prefix frontend run build
npm --prefix frontend test
python -m playwright install chromium --only-shell
python -m scripts.smoke_management_performance --screenshots docs/screenshots/stage33
```

Screenshots were generated and visually inspected in the real browser flow, with
light/dark contrast, 1080p hierarchy, mobile overflow and drawer readability checked.
They use real fictional PDFs and explicitly simulated test interactions, not live
model execution or genuine employee approvals:

- [Desktop light](screenshots/stage33/01-desktop-light.png)
- [Desktop dark](screenshots/stage33/02-desktop-dark.png)
- [Current distribution / Finance evidence](screenshots/stage33/03-distribution-evidence.png)
- [Maya review contribution](screenshots/stage33/04-maya-review-contribution.png)
- [Sarah handoff contribution](screenshots/stage33/05-sarah-handoff-contribution.png)
- [Laptop layout](screenshots/stage33/06-laptop.png)
- [Mobile dashboard](screenshots/stage33/07-mobile-dashboard.png)
