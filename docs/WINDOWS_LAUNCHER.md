# Windows one-click launcher · passwordless local workspace

After the one-time setup below, double-click **Start Ledgerline.cmd** or its optional
desktop shortcut. It uses `.web-venv\Scripts\python.exe`, starts the existing FastAPI
application **strictly on 127.0.0.1:8000**, and opens the operations dashboard once the
API and built frontend respond. **No operator password, Credential Manager lookup or
browser login is required.** Startup never makes an OpenAI call, starts a paid run,
approves a finding, authorizes an export or deletes history.

## One-time setup (Windows Git Bash / Python 3.13)

Install Python 3.13 and Node.js 22.12+. From the checkout:

```bash
py -3.13 -m venv .web-venv
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
python -m scripts.build_agent_runtime ./agent-runtime-web
```

The runtime builder requires a new destination and excludes the sealed answer key.
Missing/incomplete prerequisites print setup instructions and keep the launcher window
open for inspection. No financial data or journals are automatically repaired/deleted.
The launcher uses the explicit venv executable, so daily startup needs no shell activation.

After pulling an update, run `npm ci --prefix frontend` and
`npm --prefix frontend run build` to refresh the browser assets. The launcher checks
that a build exists; it does not automatically rebuild stale assets.

Restart an existing server once after upgrading: a running Python process still uses
its previously loaded code. Subsequent launches open the dashboard directly. Choose
**Run investigation** only when you intend to authorize one paid run; the confirmation
checkbox, token rates, limits and review/export controls remain mandatory.

## Local sessions, attribution and API credentials

The browser automatically receives an eight-hour random HttpOnly/SameSite=Strict
session cookie and separate CSRF token. New session creation is rate-limited. Allowed
Origin/Host checks, cross-site restrictions and explicit loopback peer/server checks
remain enforced. Mutating actions require a valid session and matching CSRF header.
The frontend renews expired sessions but never automatically retries a paid action or
human decision. Local access is implicit operator authority, not verified identity.

Reviewer attribution still comes from server-side `CONTRACT_WEB_REVIEWER` (default
`Local operator`) and is stored with the human decision and rationale. To choose a
name when launching from Git Bash:

```bash
export CONTRACT_WEB_REVIEWER='Your display name'
./Start\ Ledgerline.cmd
```

Explorer inherits its own environment, not variables exported only in a shell. The
OpenAI API key remains server-side in the existing secure environment/binding; the
launcher does not store it, send it to the browser or change its validation. Without
a configured API credential, history/review is available but paid launch is disabled.
Do not put keys in `.cmd` files, shortcut arguments, frontend variables or committed files.
See [Phase 3](PHASE3.md) for server setup and the distinction between configured
credentials and actual OpenAI authorization.

Old `CONTRACT_WEB_OPERATOR_TOKEN` values and saved operator credentials are ignored
by normal startup. Nothing deletes existing Credential Manager entries automatically.
If desired, remove only this checkout's old entry from Command Prompt:

```bat
"Start Ledgerline.cmd" --forget-credential
```

`--save-credential` and `--prompt-password` are retired and return guidance without
prompting or storing a password. Removing an old credential neither stops a server nor
changes journals. Do not confuse operator credentials with the OpenAI API credential.

## One instance and clean shutdown

A ready Ledgerline instance is reused without starting another process. A Windows
named mutex coordinates simultaneous clicks; the second waits up to 30 seconds for
startup. The existing run-store lock still protects journals. Foreign/older/unresponsive
services on port 8000 and stale store locks are never killed or deleted. A failed
browser open prints the URL; startup failures keep the console visible.

Keep the original console open. **Press Ctrl+C there for clean shutdown.** New paid
launches are disabled immediately; any active bounded investigation is allowed to
settle and close its journal before FastAPI exits and releases ownership. Repeated
Ctrl+C does not force-kill the writer. If Command Prompt asks whether to terminate
the batch job after Python exits, confirm it then.

Do not use the window X or Task Manager during an investigation: Windows can force
termination without cleanup. For a leftover `.server.lock`, first confirm no process
owns/writes the store, then follow [safe recovery](PHASE3.md#interruptions-and-recovery).
Never delete `runs/web` or a SQLite journal to repair startup.

## Optional desktop shortcut

From PowerShell in the checkout:

```powershell
.\scripts\windows\install_shortcut.ps1
# To remove only this checkout's shortcut:
.\scripts\windows\install_shortcut.ps1 -Remove
```

The helper creates `Ledgerline Operations Console.lnk` on the actual current-user
desktop, including redirected/OneDrive desktops. It stores no secrets and creates no
auto-start entry. `-Force` is required to overwrite an existing shortcut;
`-Destination <folder>` supports other folders/testing. Removal refuses another
checkout's shortcut. If execution policy blocks the script, follow organizational
policy or create a manual shortcut to `Start Ledgerline.cmd` instead of disabling
machine-wide security. Moving the checkout requires recreating its shortcut.

## Deployment boundary

**Passwordless mode is only for the local 127.0.0.1 application and is not suitable
for public deployment. Proper authentication is mandatory before any network-accessible
or publicly hosted version, including recorded/replay mode.** Add real identity/RBAC,
HTTPS, Secure cookies, durable sessions and the controls described in [Phase 3](PHASE3.md)
before designing such a version. Do not expose this service through a proxy, tunnel,
port forwarding or a changed host binding. Any local process/user able to connect is
trusted as operator; CSRF protections do not turn local implicit trust into identity.

## Troubleshooting and safe tests

- Missing Python/modules: run the venv setup and install `requirements-web.txt`.
- Frontend unavailable: run `npm ci --prefix frontend` and `npm --prefix frontend run build`.
- Runtime invalid: build a new isolated public runtime with correct source hashes and no sealed key.
- An old login page appears: rebuild the frontend, stop the previous server cleanly,
  restart the updated version, and refresh the browser.
- Session/access error: use http://127.0.0.1:8000 directly, refresh once, then deliberately
  retry any intended action. Do not route the console through a public/network address.
- Port occupied/readiness timeout: inspect the original console/process; no automatic killing occurs.
- No paid launch: configure the server API credential. Readiness is not a paid API authentication test.

```bash
python -W error::ResourceWarning -m unittest discover -s tests_launcher -v
python -W error::ResourceWarning -m unittest discover -s tests_web -v
python -W error::ResourceWarning -m unittest discover -s contract_to_cash/tests -v
python -m scripts.export_web_schema --check
```

`"Start Ledgerline.cmd" --check` validates installation without starting a server.
Tests use simulated SDK responses and temporary local journals, not paid OpenAI calls.
Native Windows console/Explorer behavior cannot be established by Linux tests; native
Credential Manager cleanup compatibility and shortcut tests run in Windows CI.
