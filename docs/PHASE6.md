# Phase 6 — Executive AI reasoning and guided persona demo

## Present the connected workflow

1. Open Maya. **Demo Controls → Complete Maya Demo** asks for confirmation, then
   creates or reuses Phase 5's deterministic simulated scenario. It does not alter
   the selected genuine investigation. Genuine work, even if incomplete, stays in
   history. You can separately demonstrate a real investigation interaction using
   the existing explicitly authorized paid review.
2. Inspect the completed simulated findings and original evidence, then select
   **Continue to Sarah**. The selected scenario identifier remains shared.
3. On Sarah's screen select **Complete Sarah Demo** and confirm. Missing proposed
   internal actions receive illustrative owners, priorities, source citations and
   target dates based on the April fixture period (not real current commitments).
   The shared discrepancy, contractual conflict and invoice ambiguity remain.
   Real actions already recorded for any issue are preserved unchanged. Seeded
   records say **Simulated Demo Data** and name a simulated fixture reviewer, never
   impersonating a genuine decision. Use **Record management action** for an actual
   local human decision; its separate attribution/history is retained.
4. Select **Continue to Robert**. The executive workspace can browse the same Maya
   facts, Sarah actions, simulated handoff and Python ROI assumptions without a key
   or a paid Maya/Sarah analysis. Handoff readiness is checked against current source
   and action versions; repeat Sarah's shortcut to refresh a stale handoff.
5. With server credentials and fresh administrator pricing, select **Generate
   Executive Decision Brief**. Read and explicitly accept the existing paid-run
   confirmation. It launches the existing bounded executive investigator, not another
   agent. Limits remain 35 tools, 40 Responses requests, 180 seconds and US$1 estimated
   per authorized run, plus shared frequency/one-worker limits. No model request
   occurs merely from switching personas or either demo-completion shortcut.
6. Inspect **Executive Assessment**, **What Maya Demonstrated**, **What Sarah Changed**,
   **Financial Opportunity**, **Risks & Missing Evidence**, and **AI Recommendation**.
   Caution and deferral are valid recommendations. Citations open the saved immutable
   references. Full observations, hypotheses and limitations remain expandable.
7. Record **Executive Decision** separately with the local reviewer attribution,
   rationale, recommendation selection and citation acknowledgement. The decision
   never allocates a budget, executes staffing/deployment changes or approves exports.
   Every regeneration requires new explicit consent; no background or unbounded
   follow-up workflow has been introduced.

Advanced Settings → **Prepare Full Demo** remains the Phase 5 global preparation
shortcut. Stage completion on the persona screens supplies the additional simulated
management handoff; Advanced Settings is not required for either stage control.

## Grounding, provenance and stale results

The executive input snapshot includes the selected root/scoped continuations,
verified comparisons, original evidence, incomplete-run limitations, known/unknown
exposure, shared patterns, management analyses (including incomplete/stale status),
management actions/history, human decisions and the saved Python ROI scenario.
Sarah's generated interpretations are not described as independently verified facts.
The model is instructed to challenge weak assumptions, relate actions to supported
risks, identify pilot measurements and avoid assuming expansion is always warranted.

The strict executive schema requires five concise cited brief sections and an advisory
stance. Local validation retains uniqueness/bounds, allowlisted references and
read-before-cite checks, and requires reading the overview, management context,
scenario, an operational case and original source evidence when those are available.
Server calculations remain the only financial authority. Model prose is an untrusted
interpretation; it cannot change financial totals. Current deterministic amounts are
visually distinct from narrative and from assumption-based scenario projections.
Detected receivables are not cash recovered; credits are not savings; administrative
closure does not establish a corrected invoice. Unknown exposure is not zero.

Saved briefs show timestamp, scenario, analysis identifier, provenance and revision.
Upstream evidence, action versions/histories, management analyses, human decisions,
handoff or ROI changes invalidate the prior source hash. Stale/incomplete analyses
cannot authorize a new human strategic decision. Prior successful results and their
original references remain selectable after a failed replacement. Older pre-brief
analyses remain readable in full; no structured AI reasoning is fabricated for them.
The mocked-provider screenshots explicitly say they are not live AI. Production
OpenAI results and mocked test responses carry separate provenance.

Sarah's missing fixture actions and handoff commit in one SQLite transaction. Failure
rolls them all back; repeating is safe. Both shortcuts reject active workers, reset
recovery, shutdown and recorded-mode writes. Sarah's shortcut refuses genuine or stale
investigation roots. A human edit to a seed record retains the simulated original in
history and becomes an explicitly human-attributed current version; future preparation
never overwrites it. No financial fixtures, old investigations, journals or approvals
are deleted or rewritten. Persona selection is presentation context, not authenticated
RBAC. All localhost, session, CSRF/Origin, export and paid pricing/credential gates remain.

## Exact Windows Git Bash update and launch

Stop any running Ledgerline server with **Ctrl+C** in its launcher console first. From
your existing checkout, inspect local edits before switching; preserve any local work.

```bash
cd /c/path/to/contract-to-cash-agent
# Replace the path above with your actual existing checkout.
git status --short
git fetch origin feature/phase6-executive-guided-demo
git switch feature/phase6-executive-guided-demo
git pull --ff-only origin feature/phase6-executive-guided-demo
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
MSYS_NO_PATHCONV=1 cmd.exe /c '"Start Ledgerline.cmd"'
```

If the local branch does not yet exist, after fetching use:

```bash
git switch --create feature/phase6-executive-guided-demo --track origin/feature/phase6-executive-guided-demo
```

If your existing remote has a restricted fetch refspec, fetch an explicit remote ref:

```bash
git fetch origin feature/phase6-executive-guided-demo:refs/remotes/origin/feature/phase6-executive-guided-demo
```

For first-time setup, see [Windows launcher setup](WINDOWS_LAUNCHER.md). Keep your
existing `agent-runtime-web`, `runs/web`, SQLite journals, pricing and credentials.
The frontend build and server restart are required after update. Do not delete or
rebuild an existing runtime/data folder in place. The launcher opens only
`http://127.0.0.1:8000`; no startup API call is made. No key is needed for browsing or
deterministic completion. Passwordless local mode is not suitable for network/public
hosting; such deployment requires proper authentication and identity controls.

## Test and screenshot evidence

All provider responses in automated tests are mocked. The CI Ubuntu/Windows matrix
runs the original suites and five browser workflows. The additional browser command:

```bash
PLAYWRIGHT_BROWSERS_PATH=work/browsers .web-venv/bin/python -m scripts.smoke_guided_demo --screenshots docs/screenshots/phase6
```

Use `.web-venv/Scripts/python.exe` on Windows and omit the browser-path override for
a default Playwright installation. Captured evidence:

- [Maya's visible controls](screenshots/phase6/01-maya-demo-controls.png)
- [Completed simulated Maya investigation](screenshots/phase6/02-maya-completed-simulation.png)
- [Sarah's visible controls](screenshots/phase6/03-sarah-demo-controls.png)
- [Simulated management actions](screenshots/phase6/04-sarah-prepared-management-actions.png)
- [Robert's executive workspace](screenshots/phase6/05-robert-executive-workspace.png)
- [Rendered mocked executive brief — not live provider output](screenshots/phase6/06-robert-mocked-executive-brief.png)
