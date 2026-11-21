# Ledgerline 2.0 Stage 3 — Management Command Center

Maya and Sarah use the same saved session, original PDFs, work items and immutable
workflow events. Sarah now manages operational coordination and corrective actions.
The new advisor is a genuine, bounded OpenAI Responses integration; development and
CI use explicitly labeled simulated SDK responses. No genuine analysis is bundled.
Robert’s new executive workspace is deferred to Stage 4; `/legacy` is preserved.

## Windows Git Bash: update and launch

Stop Ledgerline with **Ctrl+C** before updating. Keep the existing checkout,
`agent-runtime-web`, `runs/web`, `runs/web-documents`, PDFs and SQLite journals.
Do not delete history or regenerate an existing isolated runtime.

```bash
git fetch origin
git switch feature/ledgerline2-management-intelligence
git pull --ff-only
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
python -m contract_to_cash.web
```

Alternatively, after building, double-click **Start Ledgerline.cmd** or its existing
desktop shortcut. Open `http://127.0.0.1:8000/`. Python 3.13 and Node 22.12+ are
required. For first installation only:

```bash
py -3.13 -m venv .web-venv
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
python -m scripts.build_agent_runtime ./agent-runtime-web
python -m contract_to_cash.web
```

Skip environment/runtime creation if already installed. Linux/macOS activate
`.web-venv/bin/activate`. The server remains strictly bound to **127.0.0.1**.
Passwordless local mode is unsuitable for public/network deployment. Proper
verified authentication and authorization are prerequisites for any such deployment;
persona selection and typed reviewer attribution are not identity verification/RBAC.

## Free presentation: Maya → Sarah

1. **Load Sample Documents**, confirm administrative import. The actual 149 PDFs
   produce 102 work items on the unchanged sample; completed starts at zero.
2. **Select All Matching → AI Powered Close**. Confirm administrative-only scope.
   The adjacent explanation makes clear this is deterministic Python validation,
   not an LLM. The unchanged sample completes 73 checks and retains 29 exceptions.
3. **Select All Remaining Work → Escalate to Sarah**. Confirm attribution/rationale.
   Finance and contractual decision authority remain separate from oversight.
4. Select **Sarah — Management Command Center**. Overview shows persisted totals,
   workload/category/ownership distributions, actual timestamp aging and measured
   command duration. Chart bars open the actual supporting work, including completed
   checks. Categories partition handoffs; flow outcome branches partition workload.
   Do not add incoming volume to its outcome branches.
5. Use **Escalations** to select one row, the visible page, or **Select All Matching**.
   The sticky toolbar applies prioritization, internal coordination assignment,
   return-to-Maya, evidence requests, Finance coordination or management completion.
   Every operation requires rationale, attribution and confirmation. Inspect per-row
   results; stale versions or changed source evidence are blocked.
6. Use the free **Rule-based operational overview** to inspect real category groups.
   Similarity does not establish a common configuration defect. Choose **Create
   corrective action**, select an owner, priority and optional due date, and record
   acceptance criteria. This is a human-confirmed internal task, not a financial
   approval. **Corrective Actions** supports updates, outcomes and audit history.
7. Switch back to **Maya — Revenue Operations** without reimporting. Returned cases
   retain their original handoff and prescribed next action. Evidence follow-ups
   preserve the pending financial/contractual decision and record the human note.

Sarah’s **Complete management review** closes only her management coordination task.
It never resolves a disputed contract, closes a financial case, issues a credit or
changes an invoice. **Auto Complete Selected** deterministically routes Finance and
missing-evidence work and assigns other internal follow-ups; it never blanket-closes
exceptions. No command sends external messages or executes financial transactions.

## Financial and measurement boundaries

Amounts are computed with Python `Decimal` from current re-extracted source PDFs.
Duplicate references to a work item or billing object are not counted twice.
Underbilling, overbilling, draft credits and payment-review balances remain separate;
credits may overlap discrepancies, so these categories must not be summed or netted.
Payment balances are included only for unique single-receipt invoice scopes;
ambiguous multi-receipt scopes are not inferred. Unknown financial exposure remains
separately identified. No cash recovery, issued credit or realized saving is claimed.

Case age uses actual saved state transitions and is never aged artificially for a
demo. The adjustable SLA target is an explicit prospective assumption, not an
observed benchmark. Command processing duration is measured system time. Human labor
and savings are **Not Measured**. A future pilot needs measured reviewer time,
baselines, recurring-case history, authorized resolution evidence and actual outcomes.

## Explicitly authorized local live-analysis acceptance

**This procedure incurs OpenAI charges. It is not run by startup, preparation,
navigation, automated tests or CI. Only perform it after a person explicitly opts in.**
Mocked SDK tests establish orchestration/validation, not real-world reasoning accuracy.

1. On your private local machine, configure a valid `OPENAI_API_KEY` in the server
   environment using your existing secure setup. Never put it in source code, a URL,
   browser storage, screenshots, Git history or frontend configuration. Restart the
   server so it reads the environment. No key is returned by an application endpoint.
2. In **Advanced / Legacy workspace**, open administrator pricing and independently
   verify the current official USD default-tier `gpt-6.1-sol` input, cached-input and
   output rates at <https://developers.openai.com/api/docs/pricing>. Confirm them.
   No fixed production price is shipped; confirmation expires after 24 hours.
3. Return to Sarah, inspect the actual current handoffs, then open **Management
   Intelligence**. Choose all handoffs, selected cases, or one category. Click
   **Analyze Team Performance** to gather source evidence and display a free preview.
4. Inspect scope, model, estimated evidence-pass cost, local maximum budget and launch
   restrictions. The byte/framing estimate is conservative, not a provider billing
   guarantee. Cancel safely if undesired. The launch remains blocked until current
   pricing, server credentials, worker capacity and shared rate allowance are valid.
5. Enter attribution/rationale, check explicit paid consent, and click **Begin
   authorized management analysis** once. One advisor uses the existing stateless
   Responses runtime with at most **12 tools, 8 responses, 180 seconds and USD 1
   estimated cost**. Each request reserves budget and time; SDK retries are disabled.
   These are local bounds/estimates, not a guarantee of final billed provider cost.
6. Inspect the real resulting state. Successful cards carry exact case/document/span
   references, Python-attached financial facts, unproven hypotheses, alternatives,
   missing evidence and proposed actions. Open original PDFs and supporting cases.
   Inspect actual model/tool events under the expandable technical section.
7. Check original timestamp, model, provenance, scope, actual reported tokens and
   usage-priced estimate. Billed cost remains unverified. Missing/failed usage is
   labeled unknown/incomplete, never a zero-cost success. Unsupported citations or
   malformed outputs cannot publish a validated analysis. Failed/interrupted runs
   do not automatically retry; examine safe diagnostics before authorizing again.
8. Accept a current recommendation into a separately confirmed corrective action or
   dismiss it with rationale. Neither operation executes a recommendation or confers
   Finance/legal authority. Repeated acceptance cannot create duplicate actions.
9. Refresh/revisit. Recorded validated results replay without provider calls, retain
   their timestamp and provenance, and become visibly historical/stale if their
   scoped evidence changes. New actions cannot be created from stale AI insights.

Paid admission is shared with legacy investigations, continuations and enterprise
analyses: one launch/minute, three/hour, including retained/archived history.
Restart Demo never resets that history. It creates a new active document session,
leaving prior documents, decisions, management actions, analysis traces and usage
retained. Prior sessions are read-only; they cannot authorize current-session work.
A server restart marks unfinished analyses interrupted without resuming them.

## Persistence and implementation

- Management records extend each session’s existing `journal.sqlite3`: work metadata,
  `management_operations`, `corrective_actions`, and append-only `workflow_events`.
  Commands use current row versions and atomic transactions; failures roll back.
- Corrective actions retain immutable case/document bindings, version checks, explicit
  outcomes, provenance and human change history. Existing actions can be updated
  after their original insight becomes historical, provided source integrity holds.
- `runs/web-documents/management-ai.sqlite3` retains authorizations, bounded snapshots,
  structured results, usage and provenance independently of a document-session restart
  or legacy archive-only reset. Genuine traces are stored in
  `runs/web-documents/analysis-traces/<analysis-id>/`.
- Tools expose only bounded authorized case evidence and saved events. They cannot
  read an answer manifest, credentials, other sessions or mutate business records.
  System instructions treat source text/user notes as untrusted data. Citation
  uniqueness and semantic/evidence checks remain strict server-side; API-facing
  function schemas use the supported strict subset without `uniqueItems`.
- Provider diagnostics reuse the sanitized classification for schema, credential,
  permission, rate-limit and transport errors; raw provider exceptions are not shown.
- All SQLite connections/cursors and runtime journals close explicitly; no cleanup
  exceptions are ignored. Existing financial rules and `/legacy` behavior are retained.

## Offline development validation

```bash
python -m pip install -r requirements-documents-test.txt
python -W error::ResourceWarning -m unittest discover -s contract_to_cash/tests -v
python -W error::ResourceWarning -m unittest discover -s tests_web -v
python -W error::ResourceWarning -m unittest discover -s tests_launcher -v
python -W error::ResourceWarning -m unittest discover -s tests_documents -v
python -W error::ResourceWarning -m unittest discover -s tests_workspace -v
python -m scripts.demo_documents --output work/stage3-alternate --seed 781902
python -m scripts.export_web_schema --check
npm --prefix frontend run build
npm --prefix frontend test
python -m playwright install chromium --only-shell
python -m scripts.smoke_management --screenshots docs/screenshots/stage3
```

CI runs these suites and all ten browser workflows on Windows and Ubuntu. The new
browser test uses an ephemeral, explicitly simulated SDK fixture (test server flag
`--management-ai`); production startup never enables it. No fake live history is
bundled, and no provider requests are made by the tests.

## Browser evidence

These screenshots show real fixture-PDF processing and persisted management actions
in an ephemeral browser-test session. The insight screenshots are explicitly
**simulated SDK responses**, not evidence of a genuine paid run.

- [Maya’s completed handoff](screenshots/stage3/01-maya-completed-handoff.png)
- [Sarah’s observed management overview](screenshots/stage3/02-management-overview.png)
- [Management completion preserves Finance authority](screenshots/stage3/03-finance-authority-preserved.png)
- [Internal corrective action](screenshots/stage3/04-corrective-action.png)
- [Simulated SDK insight and actual trace](screenshots/stage3/05-simulated-sdk-insights.png)
- [Mobile overview](screenshots/stage3/06-mobile-overview.png)
- [Mobile queue](screenshots/stage3/07-mobile-management-queue.png)
- [Mobile recorded simulated insight](screenshots/stage3/08-mobile-recorded-insight.png)

If the old UI appears, rebuild the frontend and restart the existing server. A missing
pricing/key/cooldown does not block the free overview or corrective actions. A stale
source/version/session requires refreshing and reviewing current evidence, not
bypassing validation. If analysis fails, inspect its safe diagnostic and retained
trace; do not repeatedly authorize calls to work around an invalid tool contract.
