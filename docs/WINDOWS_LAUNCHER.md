# Windows one-click launcher

After the one-time setup below, double-click **Start Ledgerline.cmd** in the project
folder (or the optional desktop shortcut). The launcher uses this checkout's
`.web-venv\Scripts\python.exe`, starts the existing FastAPI application on loopback
port 8000, and opens http://127.0.0.1:8000 only after its API and frontend respond.
It never starts an investigation, spends API credits, installs software automatically,
or deletes history to repair startup.

## One-time setup (Windows Git Bash / Python 3.13)

Install Python 3.13 and Node.js 22.12+ first. From the project checkout:

```bash
py -3.13 -m venv .web-venv
source .web-venv/Scripts/activate
python -m pip install -r requirements-web.txt
npm ci --prefix frontend
npm --prefix frontend run build
python -m scripts.build_agent_runtime ./agent-runtime-web
```

The builder requires a **new** destination and copies public data without the sealed
answer key. If that destination already exists, inspect/keep it rather than deleting
run history. Missing or invalid prerequisites produce actionable instructions and a
paused console so the error remains visible. The frontend assets and source-integrity
manifest are checked; the launcher never regenerates or modifies financial records.

The normal double-click path requires no Git Bash activation or Python on PATH:
it uses the project's explicit virtual-environment executable. Keep the console open.
You still sign into the browser with the same operator password; startup does not
bypass operator authentication or approve billing/export actions.

## Operator password: hidden prompt or Credential Manager

For a new server the selection order is:

1. Inherited `CONTRACT_WEB_OPERATOR_TOKEN`, if configured and valid.
2. This checkout's current-user Windows Credential Manager entry.
3. Hidden console password entry (32–512 characters).

There is no plaintext password file, secret command argument or browser URL. Hidden
entry is refused if the console cannot guarantee it; an echoing `getpass` fallback
is never accepted. `--prompt-password` ignores inherited/stored operator credentials
when starting a new server. It does not change the password of an already-running server.

To save a password in **Windows Credential Manager** from Command Prompt:

```bat
"Start Ledgerline.cmd" --save-credential
```

You enter and confirm it without echo. Windows stores it as a current-user generic
credential, persistent on this machine. The target is `Ledgerline/Operator/<checkout
hash>`; no local path or secret appears in the target name. A different checkout or
moved folder has a different target. The launcher never saves an OpenAI API key.
The password remains available to the current Windows account; this is not protection
against processes already running as that account. Python strings/process memory are
not guaranteed to be securely erasable.

To remove only this checkout's saved operator password:

```bat
"Start Ledgerline.cmd" --forget-credential
```

You may also inspect/remove its generic credential through Windows Credential Manager.
Removing a credential neither stops a server nor changes journals. If Credential Manager
is unavailable under local policy, use `--prompt-password` instead. No third-party
credential module or administrator privilege is required.

API credentials remain server-side in the existing environment. A double-click from
Explorer inherits Explorer's environment, **not** variables exported only in a Git Bash
window. To inherit an existing securely configured shell environment, invoke
`./Start\ Ledgerline.cmd` from that shell, or use the normal managed credential binding.
Never put API keys in the `.cmd`, shortcut arguments, frontend configuration or a
committed file. Without an API credential the console still opens for history/review,
but paid investigation launch stays disabled. See [Phase 3](PHASE3.md) for server setup.

## One instance and shutdown

Before prompting, the launcher probes the loopback health identity and dashboard.
If Ledgerline is ready, it opens the existing dashboard without changing credentials
or starting another server. A Windows named mutex coordinates concurrent launcher
clicks across checkouts in the same Windows session. A second click during startup
waits up to 30 seconds for the first launcher. The existing store lock continues to
protect SQLite/run ownership, including manually started servers.

A foreign/older service on port 8000 is never killed. A health response without the
new Ledgerline application identity is treated conservatively as an unrecognized
service; stop an older manually started Ledgerline instance once and relaunch it
with this version. A startup timeout reports failure rather than opening a broken page.
If the default browser fails to open, the console prints the URL for manual use.

For **clean shutdown**, press **Ctrl+C in the original launcher console**. New paid
launches are disabled immediately. If an investigation is active, the launcher waits
for that bounded run to settle and close its journal before stopping FastAPI and
releasing ownership. Repeated Ctrl+C does not force-terminate an active journal writer.
This wait may last up to the remaining investigation limit. If Command Prompt asks
whether to terminate the batch job after Python exits, confirm it then.

Do not close the console with its window X or use Task Manager to stop a running
investigation: Windows may terminate it without graceful cleanup. A crash/forced stop
can leave `.server.lock`. The launcher **never** removes that file automatically.
Confirm no process owns/writes the run store before following the recovery procedure
in [Phase 3](PHASE3.md#interruptions-and-recovery). SQLite journals and `runs/web` are
preserved; neither reinstalling a shortcut nor launcher startup clears them.

## Optional desktop shortcut

From PowerShell, in the project folder:

```powershell
.\scripts\windows\install_shortcut.ps1
```

This installs `Ledgerline Operations Console.lnk` on the current user's actual desktop
(including redirected/OneDrive desktops), with this checkout as its working directory.
It stores no secrets, starts no server and installs no auto-start entry. An existing
shortcut is not overwritten without `-Force`. To uninstall:

```powershell
.\scripts\windows\install_shortcut.ps1 -Remove
```

`-Destination <folder>` is available for a different shortcut folder or automated tests.
Removal refuses a shortcut pointing to another checkout. If Windows execution policy
blocks the helper, follow your organization's policy or manually create a shortcut
to `Start Ledgerline.cmd`; do not disable machine-wide script security. Moving the
checkout requires recreating the shortcut and optionally saving its new credential.

## Troubleshooting and validation

- **Window reports missing Python:** run the one-time setup. Installing global Python
  alone does not create `.web-venv`.
- **Missing modules:** run `.web-venv\Scripts\python.exe -m pip install -r requirements-web.txt`.
- **Frontend missing:** run `npm ci --prefix frontend` and `npm --prefix frontend run build`.
- **Runtime invalid:** the isolated dataset must include unchanged public documents and
  matching hashes, and must exclude the sealed answer key. No financial data is repaired
  by this launcher.
- **Password rejected:** sign in using the password selected when that server started.
  Changing environment/Credential Manager entries does not change a running session's
  server password. Stop cleanly and restart if you intend to change it.
- **Port 8000 occupied / 30-second timeout:** inspect the original server console and
  Windows processes; do not kill an unknown service or delete its lock blindly.
- **Readiness succeeds but browser stays closed:** manually open the printed local URL.
- **Credential entry fails:** use `--prompt-password` in a normal interactive console.
- **No paid launch:** configure the API credential on the server. Neither startup nor
  readiness checks verify OpenAI authorization, and neither makes an API request.

Safe checks after installing web requirements:

```bash
python -W error::ResourceWarning -m unittest discover -s tests_launcher -v
python -W error::ResourceWarning -m unittest discover -s tests_web -v
python -W error::ResourceWarning -m unittest discover -s contract_to_cash/tests -v
python -m scripts.export_web_schema --check
```

On Windows, `"Start Ledgerline.cmd" --check` checks prerequisites without starting a
server. Tests use mocks and local HTTP/journal fixtures, never paid OpenAI calls.
Actual Windows console/Credential Manager/Explorer behavior must be verified on Windows;
Linux tests cannot establish native desktop integration behavior.

Local validation on Linux/Python 3.13.5: 16 portable launcher tests passed; two native
Windows integration tests were skipped by platform. All 77 agent tests, 17 web-adapter
tests, six UI mapping tests, the production frontend build and both existing Chromium
smoke workflows also passed. The Windows CI matrix includes the native credential
round-trip and shortcut install/remove tests; its result is not claimed as local
verification. No paid OpenAI requests were made.
