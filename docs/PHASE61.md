# Phase 6.1 — Visible evidence and paid-launch availability

## Evidence navigation

On Sarah's shared pricing card, **View Supporting Evidence** opens a right-side
modal drawer immediately. It shows loading before retrieval finishes, then the
selected account's saved comparison, original contract/amendment text, invoice
records, document IDs and hashes. Switch between C008, C009 and C010 using **Selected
customer account**. The figures come from the existing immutable snapshot; the
matching discrepancies do not establish a common configuration defect.

The native modal makes the background inert. Focus enters at **Close evidence**,
Tab/Shift+Tab wrap within visible controls, Escape closes it, and focus returns to
the opening button. On mobile it fills the viewport. Loading, errors and retry stay
inside the drawer. Closing aborts Sarah's pending fetch; stale responses cannot
replace a later selection. There is no duplicate evidence section farther down the
management page. Invoice fields use structured labels, not raw JSON.

Robert's brief citations and operational source inspection now use the same visible
drawer. Maya retains her existing immediately visible case/evidence drawer. No
source text, evidence authority, calculation, finding or historical journal is changed.

## Shared paid-launch status

Maya, Sarah, Robert and scoped continuations use **Paid launch availability** or
**Analysis availability** before offering paid authorization. Available means the
server's shared admission requirements are satisfied; current source/scope checks
still run on submission. Each launch still needs explicit consent and the existing
bounded budget. Availability is refreshed every five seconds, on browser focus,
after relevant mutations, manually, and at a server-calculated rate-limit deadline.
No UI timer independently declares capacity available.

`GET /api/paid-launch-availability` is a read-only, session-protected endpoint (recorded
mode reports read-only). It returns an allowlisted reason code/message list, server
check time, usage counts, limits and optional `next_eligible_at` in ISO timezone-aware
format. The UI renders this exact instant in the browser's local timezone.

The same `Store.paid_rate_status` calculation is used by display and launch-time
rate enforcement. It reads persisted current and archived investigation/analysis
admissions. Real Maya, Sarah and Robert requests share one launch per rolling minute
and three per rolling hour. Previously failed/incomplete admitted attempts retain
the existing conservative accounting. Explicit `simulated_demo` preparation records
and stage actions do not consume capacity. History is never edited to release quota.

For a rate-limited snapshot, minute capacity returns at the most recent admission
plus 60 seconds. Hour capacity returns when the third most recent admission ages
out of the 3,600-second window (important when more than three records are retained).
The deadline is the later of both release times. Exact boundaries are eligible
because the rules use strict less-than windows. Archived history is included.

An active worker, missing credentials, missing/expired/invalid pricing, recorded mode,
shutdown/recovery or unverifiable history has its own explanation. When any non-rate
blocker remains, no launch time is promised. Credential presence is checked locally;
this endpoint does not contact OpenAI or claim that provider permissions are valid.

The display is informational. A new launch rechecks concurrency, key configuration,
pricing, rate capacity, explicit paid consent and source/scope on the server. A race
rejection uses the existing HTTP status with `code: paid_launch_rejected`, the refreshed
availability snapshot and `paid_run_created: false`. No paid run is inserted for that
rejection. The UI closes the unsuccessful authorization flow, shows the rejection,
refreshes status and never automatically retries paid work. Successful idempotent
replays continue to return their original run without starting another one.

**Complete Maya Demo**, **Complete Sarah Demo** and the global preparation shortcut
remain free and deterministic, independent of key/pricing/quota. They retain their
existing worker, source, recorded-mode and recovery safeguards. Human management and
executive decisions remain separate audited records, not AI-executed changes.

## Windows Git Bash update and launch

Stop the running server with **Ctrl+C** in its launcher console. From your existing
checkout, preserve any local edits reported by `git status` before switching:

```bash
cd /c/path/to/contract-to-cash-agent
git status --short
git fetch origin feature/phase6-1-demo-ux-fixes
git switch feature/phase6-1-demo-ux-fixes
git pull --ff-only origin feature/phase6-1-demo-ux-fixes
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
MSYS_NO_PATHCONV=1 cmd.exe /c '"Start Ledgerline.cmd"'
```

Replace the checkout path with your actual path. If your remote has a restricted
fetch refspec, first fetch an explicit remote-tracking ref:

```bash
git fetch origin feature/phase6-1-demo-ux-fixes:refs/remotes/origin/feature/phase6-1-demo-ux-fixes
```

For a new local branch, use `git switch --create feature/phase6-1-demo-ux-fixes
--track origin/feature/phase6-1-demo-ux-fixes`. See [Windows setup](WINDOWS_LAUNCHER.md)
for first-time installation. Keep the existing runtime/data and `runs/web` journals;
do not reset/rebuild them in place. Restart Python and rebuild the frontend after
updating. The application remains bound to **127.0.0.1**; passwordless local mode is
not suitable for public deployment. Public/network hosting requires proper identity
and authentication. Persona selection is not authenticated RBAC.

## Regression evidence

The complete Python/frontend suites and six browser workflows run on Windows and
Ubuntu CI. New tests use deterministic clocks for rolling minute/hour boundaries,
shared/archive history, simulated exemption, uncertain eligibility and structured
race rejection. The new browser workflow holds an evidence request until loading is
visible, verifies all three accounts against original saved records, tests errors,
retry, inert background, keyboard loop/Escape/focus restoration and mobile layout.
It also verifies shared blocked paid controls, enabled free stage controls, exact
server deadline display and a stale-availability race rejected by the real backend.

The browser server's `--paid-ux-limit` option is test-only, in a temporary directory.
It inserts three explicitly labeled admission fixtures to exercise the real quota
calculation; it makes no provider calls and cannot affect production history. For
existing phase32/phase4 browser fixtures, the already documented simulated cooldown
override is mirrored in the informational display. Production admission is tested
without these overrides by unit tests and the dedicated UX browser workflow.

```bash
PLAYWRIGHT_BROWSERS_PATH=work/browsers .web-venv/bin/python -m scripts.smoke_paid_ux --screenshots docs/screenshots/phase61
```

[Blocked paid Maya launch with free preparation available](screenshots/phase61/01-maya-paid-blocked-free-preparation.png) ·
[Sarah's desktop evidence drawer](screenshots/phase61/02-sarah-desktop-evidence-drawer.png) ·
[Mobile evidence](screenshots/phase61/03-sarah-mobile-evidence.png) ·
[Robert's server-calculated eligibility time](screenshots/phase61/04-robert-server-authoritative-rate-limit.png) ·
[Race rejection without new history](screenshots/phase61/05-race-rejection-preserves-history.png)

A worker-start or continuation-authorization-journal failure that already retained an
audit record is instead reported as `paid_launch_retained_failure` with
`paid_run_created: true`. This does not assert that a provider request occurred or
that money was billed. The existing retained-failure history and conservative quota
accounting are preserved.
