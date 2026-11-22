# Ledgerline 2.0 Stage 3.2 — Work Lifecycle & Accountability

Sarah’s Overview now opens with a read-only lifecycle diagram of the same persisted
work Maya processes. **Lifecycle Flow** explains the journey; **Current State**
answers where each case is now. **Activity Over Time** retains Stage 3.1’s interactive
time-series analysis in an expandable section below the diagram. No API key,
pricing confirmation or OpenAI usage is needed for these views.

## Windows update and launch (Git Bash)

Stop Ledgerline with **Ctrl+C**, or close its launcher console cleanly, before updating.
Preserve `.web-venv`, `agent-runtime-web`, `runs/web`, `runs/web-documents`, original
PDFs, SQLite journals and all historical sessions. No migration deletes or rewrites
investigation history, financial fixtures or review records.

```bash
git fetch origin
git switch feature/ledgerline2-lifecycle-accountability
git pull --ff-only
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
python -m contract_to_cash.web
```

Alternatively, after rebuilding, double-click **Start Ledgerline.cmd** or the existing
desktop shortcut. Open `http://127.0.0.1:8000/`. Python 3.13 and Node 22.12+ are
required. First-time setup remains in [Stage 2](LEDGERLINE2_STAGE2.md). On Linux/macOS,
activate `.web-venv/bin/activate`. Restart after updates; an old process retains its
loaded code. If the new diagram is missing, confirm the branch, rebuild and refresh.

Ledgerline remains bound strictly to **127.0.0.1**. Passwordless local mode is unsuitable
for public or network deployment; verified authentication and authorization are
required before any such deployment. Persona selection and typed attribution are
not authenticated role-based access control.

## Present the complete workflow without paid calls

1. In Maya, **Load Sample Documents**, confirm the isolated import, and inspect a case.
   The unchanged sample contains 149 fictional PDFs and produces 102 work items.
2. **Select All Matching → AI Powered Close**, confirm the administrative operation.
   It prepares 73 deterministic checks and closes **zero** work items.
3. Open **Awaiting My Review**, inspect one result and its original PDF, then
   **Review Automated Result → Approve & Close** with attribution, rationale and
   explicit acknowledgement. This records an individual approval, not a model action.
4. **Review All**, inspect the exact eligible set and exclusions, then explicitly
   bulk-attest the remaining 72. Bulk attestation never claims individual inspection.
5. **Select All Remaining Work → Escalate to Sarah**, confirm the 29 actual handoffs.
6. Switch to **Sarah — Management Command Center → Overview**. The default diagram
   shows intake, preparation, human review, individual/bulk decisions and handoffs.
   The counts change if you take different actions; they are not application constants.
7. Click **Work items created**, **Automated checks prepared**, **Individually approved**,
   **Bulk-attested** and **Escalated to Sarah**. Search cases, filter current status and
   page through the drawer. Expand source evidence and open an original PDF; open the
   original work item to use the existing evidence and review interfaces.
8. Click **Source documents received** for actual documents and their supported work
   relationships. A PDF is not the same unit as a work item.
9. Expand **Inspect recorded transitions**, or click a desktop connector, to inspect
   the exact case IDs and event references supporting that transition.
10. Switch to **Current State**. On this unchanged completed workflow, **102 of 102
    work items accounted for** means the partition has validated, not that 102 cases
    are closed. Only 73 have human-reviewed administrative closure. Finance, evidence
    and Sarah’s remaining decisions are separate unresolved buckets.
11. Use Sarah’s existing Escalations and Corrective Actions to coordinate work.
    Completing management review does not approve Finance decisions or close cases.
    Return to Overview to see the actual new contributions and current ownership.
12. Expand **Activity Over Time** for the original actor/outcome/time/operation controls
    and keyboard-accessible event points. None of this navigation modifies the journal
    or invokes an LLM. Paid Management Intelligence remains a separately authorized flow.

On mobile, the stages become a vertical hierarchy and transitions remain available
through the accessible list. Native buttons support Tab/Enter/Space. The native modal
drawer traps focus, supports Escape and restores focus to its triggering control.
Search and status filters apply only within the exact selected case set; pages hold
at most 15 cases or documents. Light and dark modes retain distinct stage accents.

## Data and counting contract

`GET /api/document-workspace/sessions/{sid}/lifecycle` uses the existing reader gate.
The endpoint reads work, documents, immutable events and any corrective actions in
**one SQLite read transaction**. Its connection and all cursors close explicitly.
There are no schema changes or writes, and no dependency on a paid advisor analysis.

`contract_to_cash/web/work_lifecycle.py` centrally defines graph stages, event mappings,
node/edge memberships, supporting metrics and current-state precedence. The frontend
renders these returned sets; it does not recalculate business counts.

- Nodes include stable IDs, category, stage, owner, counts, actual work/document IDs
  and supporting event IDs. Edges include ordered event support and distinct case IDs.
- The document node counts source documents. Document-to-work relationships require
  actual saved source associations and matching evidence hashes; they do not claim a
  one-to-one conversion. Missing references are diagnosed, never silently invented.
- Preparation requires a recorded preparation event. Human approvals require an
  attributed human or explicitly simulated-fixture review, a matching earlier
  preparation event for that case, a recognized attestation and a recorded Closed
  result. Rejections are not approvals. System routing is not manual triage.
- **Manual Investigation Started** requires a recorded human disposition such as
  review, rejection of a recommendation, evidence request or actual Maya follow-up.
  Receiving escalation is insufficient. The initial exception branch means
  **Requires Human Investigation**, not that Maya individually investigated it.
- Duplicate sent/received handoff events in the same operation count one case.
  Management coordination and corrective work remain distinct from case resolution.
  No node implies invoices changed, credits issued, cash recovered or contract
  authority granted.
- Lifecycle contributions intentionally overlap. For example, the same work appears
  in prepared, queued, individually approved and closed stages. Never sum those into
  total throughput. Supporting metrics use the very same case sets, including zero
  counts without inventing transitions.
- Current-state precedence is: recognized Closed with review provenance (otherwise
  explicit legacy/unclassified); outstanding Finance; evidence; returned to Maya;
  rejected review; pending Maya review; management oversight (pending/completed but
  unresolved); ready for processing; investigation; other unresolved; unclassified. Unknown/missing status
  is unclassified. Finance/evidence authority takes precedence over completed
  management review or coordination owner. Every persisted case gets one bucket.
- Current closure with an apparent approval but no supporting valid journal approval
  is unclassified. Old automated-only closures retain **Legacy automated closure —
  no recorded human review**. No historical approval or timestamp is fabricated.
- Reconciliation checks distinct current case IDs against all work items. Missing
  creation/review/document references, foreign-session events and ambiguous approval
  events appear in **Counting, authority and integrity**. A reconciled partition is
  not a claim that the historical evidence is complete.
- Source links use the existing integrity-checked PDF endpoint. If an original file
  is missing or altered, the endpoint blocks it; saved extracted facts remain
  historical, not new financial authority. Existing item review performs its own
  current source/version validation. Chart navigation never bypasses it.

The projection carries session provenance and retained-session status. Drill-downs
show actual actor kind and explicitly label simulated fixture actions. A demo browser
fixture is not genuine employee approval. No events, IDs, timestamps, costs or tool
calls are synthesized for visualization.

## Verification and screenshots

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
python -m scripts.smoke_work_lifecycle --screenshots docs/screenshots/stage32
python -m scripts.smoke_human_review_activity
```

The CI matrix runs all Python suites, frontend tests/build, alternate-seed document
evaluation and all twelve browser workflows on Windows and Ubuntu. The new browser
check follows the actual complete UI sequence above, inspects PDF bytes and exact
edge memberships, reconciles 102 distinct IDs, checks keyboard/mobile/dark behavior,
replays the retained timeline and proves graph navigation adds no POSTs or events.
The original eleven browser workflows remain enabled.

Backend regression coverage includes real PDF intake/preparation/review/handoff,
current partitions, overlap and ordered edge membership, review provenance,
manual-triage distinctions, rejected results, Finance authority after management
completion, corrective-action links, missing/ambiguous/foreign history, read-only
session isolation, evidence navigation, restart and retained history. Existing tests
continue to cover financial arithmetic, paid gates, CSRF/Origin, immutable journals
and explicit human review. No paid provider requests are used by any of these checks.

Representative screenshots use real fictional PDFs and explicitly simulated browser
interactions, not live model execution or genuine employee decisions:

- [Lifecycle overview](screenshots/stage32/04-lifecycle-overview.png)
- [Prepared-work evidence drawer](screenshots/stage32/05-prepared-drilldown.png)
- [Individual accountability](screenshots/stage32/06-individual-accountability.png)
- [Sarah’s actual handoff history](screenshots/stage32/07-management-handoff.png)
- [Reconciled current state](screenshots/stage32/08-current-state.png)
- [Mobile lifecycle](screenshots/stage32/09-mobile-lifecycle.png)
- [Dark lifecycle](screenshots/stage32/10-dark-lifecycle.png)
