# Phase 3 · local Contract Operations console

This is a runnable local application over the existing Phase 2.6 agent, not a new
investigation engine. The UI is branded Ledgerline, with overview, investigations,
findings, review queue and audit history in one workspace. React/TypeScript + Vite
serve the client; a small FastAPI adapter owns sessions, run workers and source access.

No paid investigation ran during implementation. No deployment or merge was made.
The source financial fixtures, billing engine, sealed key and calculation results
are unchanged. Existing agent tests remain separate from the optional web dependencies.

## Evidence and honest states

The supplied successful live baseline (40 screened, 33.633 seconds, 8 Responses,
35 tools, 6/8 exact groups, two ambiguous escalations) is context provided by the
operator, not a recording checked into this repository. It is not seeded into the UI.
The old Phase 2.5 authentication-failure document remains a historical record, not a
statement about the current key. Actual live API authorization must be established
by an approved run; readiness only checks whether a server credential is configured.

The source inventory (40 customers and 41 April invoice records) comes from the
validated, isolated public dataset. It is explicitly separate from investigation
results. No financial exposure is invented before a report exists. Potential
receivables and credits are the backend's deduplicated verified totals, never cash
recovered or staff savings. Candidates, proposed findings, verified findings,
retracted findings, pending reviews, invalidated reviews and approved export packages
have distinct labels. Incomplete, failed and interrupted runs never become completed.

The duplicate-invoice case displays multiple invoice records without asserting a
confirmed payable amount or duplicate exposure. Signed-amendment conflicts display
the deterministic guard and require judgment; no term is chosen automatically.
Hypotheses remain explicitly labeled model interpretations, not legal conclusions.

For one-click startup after setup, see [the Windows launcher guide](WINDOWS_LAUNCHER.md).

## Windows Git Bash · Python 3.13

Install Python 3.13 with the Windows Python launcher and Node.js **22.12 or newer**
(a current LTS is recommended). Commands below are for Git Bash, from this checkout:

```bash
py -3.13 -m venv .web-venv
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build

# The destination must be new. This copies public source bytes, excluding the key.
python -m scripts.build_agent_runtime ./agent-runtime-web
```

No operator password is needed. Start the loopback-only application and open the
dashboard directly. Optionally configure the server-side reviewer display name;
this attribution is recorded with decisions but is **not verified user identity**.

```bash
export CONTRACT_WEB_REVIEWER='Local operator'
# Retain OPENAI_API_KEY if it is already securely bound. If needed, enter it
# without echo; it stays on the server and is never sent to the browser.
read -rsp 'OpenAI API key (server only, if needed): ' OPENAI_API_KEY
printf '\n'
export OPENAI_API_KEY

python -m contract_to_cash.web \
  --data ./agent-runtime-web/contract_to_cash/data \
  --runs ./runs/web \
  --frontend ./frontend/dist
```

Open **http://127.0.0.1:8000**. The dashboard obtains a random, HttpOnly local session
and CSRF token automatically; there is no password or login screen. A key is not needed
to inspect retained history. Each paid launch still requires current token rates and
an explicit confirmation for **one** bounded investigation. No investigation, review
approval or export authorization occurs on startup, refresh or session renewal.

For Linux/macOS, use `python3.13 -m venv .web-venv` and
`source .web-venv/bin/activate`; the remaining commands are the same.

For frontend development, keep the backend on port 8000 and run in a second terminal:

```bash
npm --prefix frontend run dev
```

Use http://127.0.0.1:5173. Vite proxies `/api` to the loopback backend. No `VITE_*`
secret is required or supported. For review, prefer the built same-origin application;
the development server is not a production host.

## API and lifecycle

The canonical typed models are in `contract_to_cash/web/models.py`; the public schema
snapshot is `frontend/src/api-schema.json`, with explicit frontend view types and pure
status/event mapping tests. `python -m scripts.export_web_schema --check` checks drift;
a deliberate API change requires regeneration and review of the frontend types.
The adapter and its schemas are not copied into the model's allowlisted runtime.

| Resource | Behavior |
| --- | --- |
| `GET /api/health` | Configuration readiness only; returns no credential values. |
| `GET/POST/DELETE /api/session` | Automatic loopback session bootstrap; legacy credential POST is not used by normal startup. |
| `GET /api/dataset` | Validated source inventory, never a batch financial audit. |
| `GET/POST /api/runs` | Persisted runs / one controlled bounded launch. |
| `GET /api/runs/{id}` | Run state, report checkpoint, real metrics and screening candidates. |
| `GET /api/runs/{id}/events` | SQLite-backed SSE with sequence IDs and `Last-Event-ID`/`after` replay. |
| `GET /api/runs/{id}/findings/{finding}/evidence` | Only original documents/invoices actually retrieved in that run. |
| `POST /api/runs/{id}/findings/{finding}/review` | Rationale + expected revision/version; supported local decision only. |
| `GET /api/runs/{id}/findings/{finding}/export` | Current verified finding with explicit approved export scope only. |
| `GET /api/schema` | Authenticated API schema (read-only in recorded mode). |

Run IDs are generated UUID hex values, not filesystem paths. Each worker creates its
own existing `Journal`, with that run ID before emitting its first event, and its
own SDK client; both close through context managers. No SQLite connection crosses a
thread boundary. Events are read using short-lived read-only SQLite connections and
explicitly closed cursors. Reports use the existing atomic replace mechanism.

The only agent changes are additive: report checkpoints include their committed
`journal_sequence`, an `api.requested` event marks each actual request before dispatch,
and local review decisions persist their action binding, optional rationale and journal sequence.
The report sequence may lag the last event during a request; the UI exposes both.
A final worker state is published only after journal/report closure. Report checkpoints
remain the authority for financial totals; the adapter does not recompute money.
Actual call counters come from committed events while a run is active. Token counters
are returned usage only. Interrupted/failed workers explicitly have incomplete cost
accounting; actual billed cost remains unknown.

The model still selects tools, customers, source follow-ups, hypotheses, patterns,
findings and review/export requests. Python still owns arithmetic, evidence integrity,
verification checks, version validity, financial categories and total deduplication.
The adapter never reads evaluation answers or runs a scripted investigation.

Only one worker is active per local store. A process-level exclusive `.server.lock`
prevents a second adapter process from sharing that store, and an in-process lock
serializes adapter launches/reviews. All paid launch limits are server-enforced:
`gpt-6.1-sol`, at most 35 tools, 40 Responses, 180 seconds and US$1 estimated cost;
one launch per minute, three per hour. A launch UUID is an idempotency key: retrying
that request returns the retained run rather than spending again. Rates are operator
inputs, not a verified current price catalog; the spend cap is cooperative, not a
provider-enforced billing ceiling. Independent runs cannot be launched concurrently.

SSE projects allowlisted activity fields and never sends raw provider errors, tool
arguments, encrypted reasoning or hidden reasoning. Full source text is fetched only
through the protected evidence endpoint. Cookies accompany EventSource; tokens are
never put into stream URLs. Native reconnect uses original sequence IDs and the UI
deduplicates them. A disconnected browser does not stop or restart the worker.

## Human review is not a billing approval

The adapter retains `approved`, `rejected` and `needs_information` from `review.py`.
It does not invent a resume transition. Decisions require a pending matching finding
version and report revision, matching current integrity-validated public data, a
loopback operator session, CSRF token and rationale. Reviews are locked while a worker runs.
Proposed/unresolved findings may be rejected or marked needs-information, but cannot
be approved by the web adapter. No operation modifies an invoice or chooses a signed
term to resolve a legal conflict.

An ordinary `action=review` approval is **not** an export authorization. Only an
existing `action=export` request, approved for a verified/current finding, unlocks the
package download. The durable SQLite decision must match the approved scope and finding
hash; a legacy decision without an action binding stays viewable but is not eligible
for web export. The UI does not silently upgrade the model's review request to
export, and it cannot manufacture an export request. If no export was requested,
that control stays disabled. The download is an evidence review package only, not
an instruction to issue an invoice/credit or collect funds.

A needs-information decision is terminal for that version, as in the CLI. Fresh
sources require an operator-prepared, validated public runtime snapshot and a new
investigation; there is no pretend intervention or automatic agent continuation.
The new run has a new identity. Historical evidence continues to come from the old
journal, not whatever happens to be in the current source directory. Existing review
rationales and reviewer attribution are visible in the finding and audit timeline.
Do not run the CLI review command concurrently against an adapter-owned run store.

## Recorded portfolio mode · intentionally empty until import

No genuine safe recording is bundled. Recorded mode is therefore intentionally empty,
not seeded with test results or the supplied baseline. It never grants anonymous paid
execution, privileged review decisions or exports, even if server API credentials exist.
Operator journals and curated recordings use separate directories.

An operator with a genuine settled run may create a curated artifact **offline**:

```bash
python -m contract_to_cash.web.recording \
  ./path-to-genuine-run ./recordings \
  --confirm-genuine-and-manually-reviewed

python -m contract_to_cash.web --mode recorded \
  --recordings ./recordings --frontend ./frontend/dist
```

The importer reads the original report and read-only SQLite journal, verifies identity
and basic API provenance, preserves sequence IDs/timestamps and projects a strict
recording format. It excludes raw journals, provider content, arbitrary metadata and
internal evaluation files. It redacts common credential literals, email addresses,
local paths and reviewer identity. Known simulated/test model artifacts are rejected.
**This is not cryptographic proof of provenance or a comprehensive PII detector.**
The attestation is an operator responsibility: manually inspect every hypothesis,
source text, invoice record and field both before import and before public use. Do
not import a simulated test as a real investigation. The loader rejects known
unsanitized private fields. Recordings remain gitignored until intentionally curated;
no raw journal or key should ever be force-added. This implementation does not upload
or deploy recordings. Recorded events are read as retained history, not relabeled as
new live work or artificially generated discoveries.

## Authentication and deployment boundary

This is a **passwordless, loopback-only local application**, not a public authentication
system. Both launchers bind strictly to 127.0.0.1. The API rejects non-loopback clients;
passwordless mode also requires a loopback server address, trusted Host and allowed
Origin, and rejects cross-site session access. Do not expose it through a reverse proxy,
port forwarding or a network tunnel. Local processes/users who can reach this service
are trusted as the operator: reviewer attribution is not proof of identity.

`GET /api/session` issues a random eight-hour HttpOnly/SameSite=Strict cookie and a
separate 32-byte random CSRF token. Session bootstrap is limited to five new sessions
per minute; existing-cookie reuse is not throttled. Mutating actions still require
that session and matching CSRF header. Sessions expire on restart and can be renewed
without repeating a failed action. The frontend shares in-flight bootstrap requests
and never automatically retries a paid launch or human decision. Paid-run quotas,
explicit confirmation, rationale, revision checks and durable export scope are unchanged.
There is no wildcard CORS, browser API key or automatic approval.

The retained legacy credential endpoint/model exists only for compatibility tests and
explicit old integrations. It is not used by the default launcher/UI and does not make
a network deployment safe. There is no CLI option to bind to a public/network address.

**Proper authentication is mandatory before any future network-accessible or publicly
hosted version, including recorded mode.** It must use real user identity/RBAC, HTTPS
and Secure cookies, durable sessions, authenticated artifact storage, transactional
workers, per-tenant authorization, stronger quotas, monitoring and billing reconciliation.
Removing the loopback check or setting a shared password is not a supported public
configuration. Passwordless local mode must never be publicly deployed. No public
hosting or network-accessible deployment is configured by this change.

## Interruptions and recovery

Navigation or refresh is safe: the backend worker continues and persisted history is
listed after reconnection. There is no cancel/resume endpoint. Let a paid worker settle
before stopping the server. If shutdown interrupts a request, its usage may be unknown.
A graceful stop releases the exclusive store lock after the worker settles. If a process
was killed while a worker was active, the lock is deliberately retained. Confirm that
**no process owns or writes that store** before manually removing `runs/web/.server.lock`;
never remove a live process's lock. On restart retained queued/running requests become
`interrupted / server_restart_no_resume`, preserving partial findings and unknown
accounting. They are never automatically replayed as paid calls.

## Validation

No OpenAI credit is spent by any test below. API tests use real temporary journals and
simulated SDK responses; the browser server always injects that simulated runner and
a placeholder credential, never the production SDK path.

```bash
python -W error::ResourceWarning -m unittest discover -s contract_to_cash/tests -v
python -W error::ResourceWarning -m unittest discover -s tests_web -v
python -m scripts.export_web_schema --check
npm ci --prefix frontend
npm --prefix frontend run build
npm --prefix frontend test

# Optional real Chromium smoke test, still using simulated SDK responses:
python -m pip install -r requirements-web-test.txt
python -m playwright install chromium --only-shell
python -m scripts.smoke_web
```

A GitHub Actions matrix runs these safe checks on Ubuntu and Windows/Python 3.13.
Local verification used Linux/Python 3.13.5 and Chromium headless shell 151; actual
Windows behavior must be verified by that matrix or on a Windows workstation. Browser
smoke covers direct dashboard access, bounded launch, SSE activity, evidence, rationale, export
approval/download, reload/history persistence, recorded empty/read-only mode and a
390-pixel mobile layout. Model simulations do not establish live model performance,
financial discovery recall or API authorization. There is no paid live-run result
for this phase and no assertion that the supplied baseline was reproduced.

Observed local results: **77 existing agent tests, 29 adapter tests and six UI mapping
tests passed** on Linux/Python 3.13.5. Clean `npm ci`, TypeScript checking and the Vite
production build passed. The Chromium smoke test passed both the simulated operator
workflow and the recorded empty/read-only workflow, including mobile overflow checks.
No known npm vulnerabilities were reported by the registry audit at validation time.
These are local results; the new Windows CI job is proposed validation until it runs.
