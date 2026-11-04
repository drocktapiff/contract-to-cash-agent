# Phase 3.1 · Ledgerline human + AI workflow

Ledgerline now follows four scenes: **Start Billing Review**, genuine investigation
activity, saved findings, and **Needs Your Attention**. The employee sees the workload
and makes decisions; the existing agent chooses its own tools and investigation path.
Technical configuration and the full event trace remain available on demand.

This branch is stacked on **Windows launcher PR #5**, which depends on **Phase 3
PR #4**. Review in that order. This change does not merge either dependency or deploy
an application.

## Windows startup and updates

Follow [the Windows setup guide](WINDOWS_LAUNCHER.md) for Python 3.13, `.web-venv`,
Node.js 22.12+, and the isolated `agent-runtime-web` dataset. For an existing checkout,
stop the running server cleanly before updating, then run in Git Bash:

```bash
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
./Start\ Ledgerline.cmd
```

Or double-click **Start Ledgerline.cmd** after rebuilding. It opens
**http://127.0.0.1:8000** directly, with no operator password. A second launch opens
the existing instance. Use the launcher's normal stop mechanism before replacing
loaded code. Keep existing runtime files and `runs/web` journals; do not rebuild over
or delete them to resolve a UI problem. A stale-looking page usually needs a frontend
rebuild and server restart, not a history reset.

No OpenAI request occurs at startup. Keep the API key in the existing server-side
environment/binding. Never put it in frontend variables, screenshots or launcher files.
Reviewer attribution comes from `CONTRACT_WEB_REVIEWER`; it is a local display name,
not independently verified identity.

## Administrator pricing setup

An administrator opens **Advanced Settings**, follows the official OpenAI pricing
link, verifies that current pricing is published for **gpt-6.1-sol, default service
tier, USD per million tokens**, and enters the input, cached-input and output rates.
They must explicitly attest that they checked the current official rates. If the
model or rates cannot be verified, leave paid investigations disabled.

The application ships no assumed rates and makes no paid pricing-check request.
Verification is explicitly a **local administrator attestation**, not an automated
pricing feed or independent validation of OpenAI's current prices. The server records
the source, model, tier, reviewer, confirmation time and 24-hour expiry in
`runs/web/admin/pricing.json`. Missing, invalid, future-dated or expired configuration
blocks a new paid run. The local administrator can renew it after checking again.
Local passwordless access is implicit operator authority; Advanced Settings is a
workflow distinction, not a separate authenticated administrator role.

Employees use **Start Billing Review** and confirm **I authorize this investigation**.
The browser sends only an idempotency key and explicit paid acknowledgement. The
server supplies verified configuration and existing limits: **35 tool calls, 40
Responses requests, 180 seconds, $1 estimated API cost**. A normal local caller of
the older advanced launch endpoint must also have fresh pricing and matching rates;
it cannot bypass setup by supplying arbitrary prices. The web runner explicitly
requests the default service tier. The agent CLI retains its prior behavior.

Each run stores its pricing provenance. Cost estimates remain estimates; actual
billed cost is unknown unless independently obtained. No automatic paid retry occurs.

## What each scene shows

1. **Start Billing Review:** validated source inventory, the AI/employee division of
   work and one primary action. Inventory counts are not investigation results.
2. **Investigation activity:** business descriptions of actual journal events and
   tool selections. Repeated adjacent updates are grouped for readability. No fake
   progress percentage, synthetic timestamps or scripted discovery sequence appears.
   **View Technical Activity** retains the full underlying event sequence.
3. **Saved findings:** persisted report counts, distinct potential receivables and
   customer credits, and links to evidence. Incomplete work is labeled incomplete;
   no amount is described as recovered cash, issued credit or measured staff savings.
4. **Needs Your Attention:** real pending requests and unresolved proposals. Open a
   case to read the hypothesis, deterministic comparisons and original retrieved
   source text. Conflicting amendments are shown together; multiple invoice records
   alone never prove a duplicate charge or establish a payable amount.

Human actions retain mandatory rationale, reviewer attribution, finding version,
current evidence revision and persisted audit events. Proposed/conflicted items cannot
be approved as verified findings. A clarification decision is retained but does not
pretend to resume an investigation. Ordinary review approval never authorizes export;
export requires its own current, explicit authorization. No finding or export is
approved automatically. Billing records are never modified.

History, SSE reconnection, SQLite journals, recorded/live separation and original
source integrity checks remain in place. Empty recorded mode says no recording is
available; it does not invent one. Technical IDs, hashes, tokens and raw JSON are
available in optional details rather than the normal employee flow.

## Presentation runbook

Allow roughly three to five minutes of narration, excluding variable API runtime:

1. Show the monthly workload and explain who investigates and who decides.
2. With administrator pricing already verified, explicitly authorize one paid review.
3. Follow genuine activity; open Technical Activity if the audience asks for proof.
4. Explain the saved results and any incomplete coverage using the actual report.
5. Open an actual item needing attention, inspect original evidence, and record a
   genuine decision with rationale. Demonstrate export only if separately authorized.
6. Explain potential business exposure, without claiming collection or correction.

A live presentation requires separate authorization for its paid run. This phase did
not run a paid investigation or compare live findings to the sealed answer key.

## Validation and screenshot gallery

Python 3.13: **78 agent tests passed, 37 web tests passed, 18 launcher tests passed**;
two native Windows launcher tests skipped on Linux. Resource warnings were treated
as errors. Native Windows behavior still needs Windows execution/CI. The schema drift
check, **11 frontend tests**, TypeScript check and production build passed.

The Playwright workflow passed desktop and 390px mobile checks: missing setup blocks
launch, administrator confirmation, explicit paid acknowledgement, actual test journal
activity, incomplete results, original conflicting sources, persisted clarification,
separate approved export/download, reload/history, human audit events and empty
recorded mode. The SDK is injected only by the test server; production does not use
simulated responses. Deterministic Python tools and the local SQLite journal execute
normally in this walkthrough. No paid OpenAI calls were made.

**Every screenshot below is an automated test with simulated SDK responses, not a
genuine OpenAI investigation or benchmark.** Each image carries that label. Displayed
findings and amounts come from that test run, not hardcoded production UI outcomes.

| Scene | Screenshot |
| --- | --- |
| Start Billing Review | [Desktop start](screenshots/phase31/01-start-work.png) |
| Agent activity | [Actual local test journal updates](screenshots/phase31/02-agent-working.png) |
| Saved findings | [Incomplete test report](screenshots/phase31/03-findings-summary.png) |
| Needs Your Attention | [Pending test cases](screenshots/phase31/04-needs-your-attention.png) |
| Original evidence | [Conflicting source documents](screenshots/phase31/05-original-evidence.png) |
| Saved human decision | [Persisted clarification decision](screenshots/phase31/06-human-decision-saved.png) |
| Recorded separation | [No recording available](screenshots/phase31/07-recorded-empty.png) |
| Mobile | [390px start screen](screenshots/phase31/08-mobile-start.png) |

## Local security boundary

The application remains strictly bound to **127.0.0.1**, with loopback peer checks,
Origin/Host restrictions, CSRF, random HttpOnly/SameSite session cookies, session and
paid-launch rate limits, a single worker and bounded spending. Keys stay server-side.
Passwordless local mode is **not suitable for public or network deployment**. Proper
authentication, authorization, transport and deployment security are mandatory before
any future network-accessible version. Do not expose this server through a tunnel or
change its bind address to demonstrate it remotely.
