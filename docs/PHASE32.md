# Phase 3.2 · Human resolution and agent continuation

**The AI handles the workload. The human provides the judgment. Together, they
accomplish more.** Ledgerline now implements this as an auditable workflow: a human
can provide something the original evidence did not establish, then explicitly
authorize a new investigation of the affected customer.

Built from merged `main` at `e7de235`, on
`feature/phase32-human-agent-continuation`. This PR targets `main`; there are no
unmerged Phase 3/3.1 dependencies. No paid OpenAI calls, deployment or merge occurred.

## Employee workflow

1. Open a saved investigation and an ambiguous item in **Needs Your Attention**.
2. Read the recommendation, its cited sources and remaining uncertainty. **AI
   recommendation** means a model suggestion. **Evidence-based procedural suggestion**
   means a rule selected from the actual saved comparison, not model reasoning.
   Model prose and recommendations never establish contractual authority or money.
3. Inspect the original contract, contrary amendments and invoice records. Choose:
   - **Resolve with evidence:** reference an administrator-registered written authority
     record, inspect its original text/source/issuer authority, and explain your decision.
   - **Escalate for clarification:** record who should respond, what is missing and why.
     This is a persistent state; it sends no message and starts no calculation or run.
   - **Dismiss finding:** explain why. The hypothesis, original documents and prior
     decisions remain intact. This does not delete a finding or invalidate historical facts.
4. After a supported resolution is saved, choose **Continue investigation**. Read the
   bounded scope and spending notice, then explicitly check **I authorize this paid
   continuation**. Saving a resolution alone makes no model request.
5. Watch the actual journal activity. The agent chooses its own allowed tools and
   next steps within that customer's scope. Updated financial values come only from
   the existing Python engine and deterministic evidence verification.
6. Inspect the updated finding and **What your contribution enabled**. Any review or
   export authorization is new and explicit. No approval carries from the original
   case, and no operation changes an invoice, credit, payment or collection.

A clarification can later receive a documented resolution; both contributions remain
visible. A final resolution or dismissal is immutable for that original finding.
An incomplete continuation can be deliberately retried within the limits below.
Historical reports without recommendations offer **Prepare an evidence-based next
step**. It persists procedural guidance in a sidecar table/event without a model call,
a report rewrite or a claim that historical AI generated it.

## Supported resolution and trust boundary

This first implementation supports one precise calculation-changing case: **a single
customer with conflicting signed, same-effective-date set-price amendments**. Written
authority must identify which amendment governs, which competing amendments it
supersedes and the applicable customer, contract, April 2026 period and original
source revision. Selecting an amendment or typing a business rationale is insufficient.
Other ambiguity types can be escalated or dismissed. Missing usage quantities,
missing invoices and duplicate invoice authority are not inferred or corrected.

An administrator must verify the original document's source and the issuer's actual
authority **out of band** before registration. Ledgerline records this attestation;
it cannot independently authenticate the issuer or determine legal authority. This
is not a digital-signature validation service. A false administrative attestation
cannot be made truthful by a hash. Local access already implies operator authority;
these workflow roles are not separate authenticated identities.

Registration retains the original UTF-8 document text, its SHA-256, an exact quote,
source reference, issuer/authority explanation, verifier and timestamp in an immutable,
content-addressed envelope. Windows CRLF bytes are retained when hashing the source.
The quote must identify the relevant customer, contract, period and all selected and
superseded amendment IDs. Python validates structure, snapshot, relevance, active
signed terms, the complete competing set and resulting calculation compatibility.
Contradictory registered authority is rejected rather than arbitrarily chosen.

This validates the documented assertion and attested provenance, not the legal truth
of natural-language text. Do not register invented evidence for a demonstration.
Test authority documents below are explicitly simulated and never production defaults.

## Windows setup and administrator procedure

Use the existing [Windows launcher setup](WINDOWS_LAUNCHER.md). To update an installed
checkout, stop the original launcher console with **Ctrl+C**, pull this branch, then
run in Git Bash from the repository:

```bash
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
./Start\ Ledgerline.cmd
```

Or double-click **Start Ledgerline.cmd** after rebuilding. Keep the same isolated
runtime and runs directory. No database deletion, history reset or new runtime is
required. Python 3.13 and Node 22.12+ remain supported. No new dependency is needed.
Normal startup is passwordless, strictly **127.0.0.1:8000**, with existing local session,
Origin/Host, CSRF, rate-limit and server-only OpenAI credential protections.

Before a paid continuation, confirm current official pricing in **Advanced Settings**
as in [Phase 3.1](PHASE31.md). Pricing expires after 24 hours and is saved with each
new run. Do not treat configured credentials as proof of live OpenAI authorization.

To register genuine written confirmation, prepare an assertion JSON with these fields
(all identifiers, quote and authority statements must come from the actual case):

```json
{
  "customer_id": "<affected customer>",
  "contract_id": "<original contract ID>",
  "period": "2026-04",
  "base_revision": "<current 64-character source revision from Technical Details>",
  "governing_amendment_id": "<signed amendment confirmed to govern>",
  "superseded_amendment_ids": ["<each competing same-date signed amendment>"],
  "issuer": "<actual issuer>",
  "issuer_authority": "<documented basis for the issuer's authority>",
  "source_reference": "<traceable original record reference>",
  "confirmation_text": "<exact quote from the original document explicitly identifying the customer, contract, period and governing/superseded amendment IDs>"
}
```

Place the original written confirmation in a UTF-8 text file. The source must actually
contain that quote; a model summary is not an original document. No PDF/OCR upload or
external URL fetch is implemented. Preserve the external original and its provenance.
After verifying it, run:

```bash
python -m scripts.register_resolution_evidence \
  --data ./agent-runtime-web/contract_to_cash/data \
  --runs ./runs/web \
  --assertion ./private-evidence/assertion.json \
  --document ./private-evidence/original-confirmation.txt \
  --verified-by 'Your administrator display name' \
  --verified-source-and-authority
```

Paths are explicit administrator inputs, never model-supplied paths. Keep private
evidence outside version control. Registration makes no API call and writes only
under the runs folder. It prints the authority record ID. Close/reopen the case to
refresh the browser's registered-record list. Reference the record and save a human
resolution before separately authorizing continuation.

If no trustworthy supporting document exists, **escalate**. If the source snapshot
changes, obtain fresh evidence and start a separately authorized new investigation.
If an authority record is missing, corrupted, withdrawn from the active registry or
contradictory, dependent continuation/review/export is blocked. Preserve archived
copies for audit; do not edit a content-addressed envelope in place. This phase has
no authority-revocation UI or automated recovery/cleanup of administrative evidence.

## Architecture, persistence and limits

[Design inspection and boundaries](PHASE32_DESIGN.md) were recorded before code changes.
The app does **not** retain a checkpoint capable of exact Responses conversation
resumption. A continuation is a **new scoped Responses investigation**, provided the
original finding and human contribution as untrusted context. It has a separate run
ID, journal, report and fresh review requests. It is never labeled exact resumption.

The derived revision binds the original source hash, intervention ID and complete
registered authority envelope. The tools expose only the affected customer's records.
All original and contrary amendments remain retrievable and required for verification,
as does the authority document. Only the calculation view excludes explicitly
superseded amendments; the financial engine and original financial files are unchanged.
Source and authority are checked again before continuation and before decisions/exports.

Every continuation retains the existing **35 tools, 40 Responses requests, 180 seconds,
$1 estimated API cost**, single worker, **one paid launch/minute and three/hour**, and
fresh administrator pricing. It has a maximum of **three attempts per immutable
resolution**. Completed continuations cannot be relaunched under a fresh key. There
are no automatic paid retries. Exact launch-key replays return the retained run;
reusing a key for another request is rejected. API failures, partial responses, budget
stops and restarts retain honest incomplete/failed/interrupted states.

Existing SQLite journals gain these tables only on first use:

- `human_interventions`: immutable decisions, bound finding version/hash/revision,
  optimistic workflow version, reviewer, rationale, supporting evidence and idempotency.
- `finding_guidance`: version/hash-bound procedural guidance for historical findings.

The human record and its event commit together. Paid continuation authorization is
journaled before its worker can start; a journal failure prevents any API request. Original tables/reports remain intact;
there is no destructive migration. SQLite remains authoritative. JSONL is a secondary
mirror; if its append fails after a database commit, the operation remains committed
and a server warning identifies the mirror issue. Replay does not create another
intervention. Connections, cursors, source files and temporary files are explicitly
closed before cleanup. On restart, queued/running children become interrupted and
never resume paid work automatically. Do not remove a store lock without following
the existing recovery procedure.

The before/after response is computed from stored original findings, human rows and
linked child reports. It reports actual comparisons, verified findings, review state
and limits without fabricating progress, collection, savings or financial changes.
Recorded mode remains read-only; it does not claim a live collaborative outcome.

## API additions

All routes retain existing session/Origin/CSRF boundaries. Mutations require CSRF.
Recorded mode cannot invoke mutations or claim live outcomes.

| Route | Purpose |
| --- | --- |
| `GET /api/resolution-evidence` | Current validated administrator-registered authority records. |
| `GET /api/runs/{run}/findings/{finding}/recommendation` | Model/rule recommendation, or persisted legacy guidance. |
| `POST` to the same recommendation route | Explicit no-cost legacy procedural guidance, version/revision checked. |
| `POST /api/runs/{run}/findings/{finding}/interventions` | Resolve, escalate or dismiss with rationale, evidence and concurrency/idempotency checks. |
| `POST /api/runs/{run}/continue` | Explicitly acknowledge one paid bounded continuation of a saved resolution. |
| `GET /api/runs/{run}/outcome` | Original work, actual human contributions and linked continued results. |

`RunView` adds optional `continuation` metadata and `interventions` (default empty).
Legacy reports/recordings still parse. Public schemas are regenerated and drift-checked.
`recommend_next_action` is one additional model tool; it can only store cited suggestions
for an existing finding. It cannot establish authority, approve, export or change money.

## Validation and limitations

Automated tests use simulated SDK responses and source-labeled test authority only.
They exercise the actual orchestration, scoped tools, original financial engine and
SQLite persistence. No genuine model execution or live financial discovery is claimed.

Python 3.13 validation: **78 agent tests, 56 web tests, 18 portable launcher tests**
passed with ResourceWarning treated as error; two native Windows tests skip on Linux.
**13 frontend tests**, TypeScript/production build, schema drift and diff checks pass.
Desktop and 390px mobile Chromium walkthroughs cover the original four scenes and
new escalation → resolution → explicit paid continuation → deterministic finding →
separate export approval/download → refresh/history workflow. Windows CI now runs
both browser scripts; native Windows behavior still needs that execution/review.

Reproduce without paid calls:

```bash
python -W error::ResourceWarning -m unittest discover -s contract_to_cash/tests -v
python -W error::ResourceWarning -m unittest discover -s tests_web -v
python -W error::ResourceWarning -m unittest discover -s tests_launcher -v
python -m scripts.export_web_schema --check
npm --prefix frontend test
npm --prefix frontend run build
# In a test environment, install requirements-web-test.txt and Playwright Chromium.
python -m playwright install chromium --only-shell
python -m scripts.smoke_web
python -m scripts.smoke_continuation --screenshots ./work/phase32/screenshots
```

The continuation browser-test server explicitly advances the **test-only** launch
cooldown so the test does not wait a minute. Production has no cooldown override.
The independent API suite tests the actual launch throttle. No production fixtures,
sealed key or financial calculation rules were modified.

## Labeled screenshot gallery

**All screenshots are automated tests: simulated SDK, simulated authority document,
actual local tools/journal and an elapsed test cooldown. No paid OpenAI calls.** The
label is embedded in every capture; these are not genuine investigation results.

| Step | Screenshot |
| --- | --- |
| Recommendation and original evidence | [Open case](screenshots/phase32/01-recommendation-and-evidence.png) |
| Human escalation saved | [Clarification](screenshots/phase32/02-clarification-saved.png) |
| Registered source and authority | [Documented resolution](screenshots/phase32/03-documented-resolution.png) |
| Explicit separate paid consent | [Confirmation](screenshots/phase32/04-paid-continuation-confirmation.png) |
| Scoped real local tool execution | [Agent continues](screenshots/phase32/05-agent-continues.png) |
| Actual persisted before/after results | [Collaboration outcome](screenshots/phase32/06-collaboration-outcome.png) |
| Separate authorization remains required | [Export](screenshots/phase32/07-separate-export-authorization.png) |
| Responsive saved history/outcome | [Mobile](screenshots/phase32/08-mobile-outcome.png) |
| Responsive evidence resolution form | [Mobile resolution](screenshots/phase32/09-mobile-resolution.png) |

Passwordless mode remains a local convenience, unsuitable for public/network hosting.
Proper authentication, authorization and deployment security are mandatory before any
future network-accessible version. No public deployment or automatic merge is included.


## Changed files for review

| Area | Files and responsibility |
| --- | --- |
| Agent | `agent/tools.py`, `agent/INSTRUCTIONS.md`: cited recommendation tool/history and calculation-amendment hook; defaults preserve original calculations. |
| Evidence | `web/resolution_evidence.py`: strict authority assertions, immutable registration, source/hash checks, derived scoped data and tools. |
| Workflow | `web/workflow.py`: versioned/idempotent human decisions, transactional audit events, legacy guidance and persisted outcome projection. |
| Web lifecycle | `web/store.py`: linked paid runs, shared launch safeguards, attempt caps, current-authority checks and snapshot projections. |
| API | `web/app.py`, `web/models.py`, `web/presentation.py`: guarded routes, backward-compatible views and safe activity descriptions. |
| Employee interface | `CaseWorkflow.tsx`, `CaseDetail.tsx`, `App.tsx`, `types.ts`, `mapping.mjs`, `styles.css`: guided decisions, original authority text, separate paid consent, continued results and responsive history. |
| Administration | `scripts/register_resolution_evidence.py`: explicit source/authority attestation and byte-preserving Windows document registration. |
| Verification | `tests_web/test_workflow.py`, existing agent allowlist assertion, frontend mapping tests, simulated smoke server and browser scripts: full workflow and failure coverage with no paid requests. |
| Schema and CI | `scripts/export_web_schema.py`, `frontend/src/api-schema.json`, `.github/workflows/web.yml`: new input/view contracts and both browser workflows on Linux/Windows CI. |
| Documentation | README, Windows guide, this guide, pre-implementation design note and labeled screenshot gallery. |

The financial engine, financial fixtures, invoice records, sealed answer key, API
credential handling and Windows launcher implementation were not modified.
