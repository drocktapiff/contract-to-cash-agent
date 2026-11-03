"""Windows console launcher: no paid calls, credential echo, lock deletion, or auto-resume."""

from contextlib import contextmanager
import argparse
import ctypes
from ctypes import wintypes
import getpass
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
from threading import Event, Thread
import time
import webbrowser
import warnings

from . import windows_credentials
from .operator_auth import valid_operator_password

URL = "http://127.0.0.1:8000"
APPLICATION_ID = "ledgerline-contract-operations"
PROJECT = Path(__file__).resolve().parents[2]
SETUP = """First-time setup in Git Bash, from this project folder:
  py -3.13 -m venv .web-venv
  source .web-venv/Scripts/activate
  python -m pip install -r requirements-web.txt
  npm ci --prefix frontend
  npm --prefix frontend run build
  python -m scripts.build_agent_runtime ./agent-runtime-web
See docs/WINDOWS_LAUNCHER.md. Never delete run history to repair setup."""


class LaunchError(RuntimeError):
    pass


def credential_target(root):
    # Per checkout, stable across restarts, without putting local paths in the target name.
    digest = hashlib.sha256(str(root.resolve()).casefold().encode()).hexdigest()[:24]
    return "Ledgerline/Operator/" + digest


def valid_password(password):
    return valid_operator_password(password)


def secure_prompt(message, prompt=None):
    import sys

    if not sys.stdin.isatty():
        raise LaunchError("Open the launcher in a Windows console for secure password entry")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return (prompt or getpass.getpass)(message)
        except getpass.GetPassWarning:
            raise LaunchError(
                "Hidden console input is unavailable; no echoing fallback was used"
            ) from None


def operator_password(root, prompt=None, force_prompt=False):
    inherited = os.environ.get("CONTRACT_WEB_OPERATOR_TOKEN")
    if inherited is not None and not force_prompt:
        if not valid_password(inherited):
            raise LaunchError("The inherited operator password must contain 5–512 characters")
        return inherited
    stored = None if force_prompt else windows_credentials.read(credential_target(root))
    if stored is not None:
        if not valid_password(stored):
            raise LaunchError(
                "Stored operator password is invalid. Use --forget-credential, then save it again."
            )
        return stored
    # Do not let getpass silently fall back to an echoing stdin on a redirected console.
    import sys

    if not sys.stdin.isatty():
        raise LaunchError("Open the launcher in a Windows console for secure password entry")
    password = secure_prompt(
        "Operator password (5–512 characters, hidden; also used to sign in): ", prompt
    )
    if not valid_password(password):
        raise LaunchError("Operator password must contain 5–512 characters")
    return password


def installation_errors(root):
    errors = []
    if not (root / ".web-venv/Scripts/python.exe").is_file():
        errors.append("Missing .web-venv\\Scripts\\python.exe.")
    if any(importlib.util.find_spec(name) is None for name in ("fastapi", "uvicorn", "openai")):
        errors.append("Install requirements-web.txt in .web-venv; web dependencies are missing.")
    build = root / "frontend/dist"
    if (
        not (build / "index.html").is_file()
        or not list((build / "assets").glob("*.js"))
        or not list((build / "assets").glob("*.css"))
    ):
        errors.append(
            "Frontend build is missing or incomplete. Run npm ci and npm run build as shown below."
        )
    data = root / "agent-runtime-web/contract_to_cash/data"
    if (data / "sealed_answer_key.json").exists():
        errors.append(
            "The public runtime contains a sealed answer key. Rebuild in a new isolated destination."
        )
    else:
        try:
            from contract_to_cash.agent.tools import PublicData

            PublicData(data, "2026-04")
        except Exception:
            errors.append(
                "Isolated runtime is missing or failed integrity validation. Build agent-runtime-web as shown below."
            )
    if (root / "runs/web/.server.lock").exists():
        errors.append(
            "Run-store ownership lock exists. Do not delete it while any server is running. See safe recovery in docs/WINDOWS_LAUNCHER.md."
        )
    return errors


def probe():
    """Use loopback directly; never follow redirects or send credentials."""
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=0.5)
    connected = False
    try:
        connection.connect()
        connected = True
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        body = response.read(8192)
        if response.status != 200:
            return "occupied"
        try:
            identity = json.loads(body).get("application_id")
        except (ValueError, AttributeError):
            return "occupied"
        if identity != APPLICATION_ID:
            return "occupied"
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read(8192)
        return (
            "ready"
            if response.status == 200 and "text/html" in response.getheader("Content-Type", "")
            else "setup"
        )
    except (OSError, http.client.HTTPException):
        return "occupied" if connected else "starting"
    finally:
        connection.close()


def open_dashboard():
    try:
        if webbrowser.open(URL, new=2):
            return True
    except Exception:
        pass
    print("Browser could not open automatically. Open " + URL + " manually.")
    return False


def wait_for_existing(check=probe, timeout=30, sleep=time.sleep, clock=time.monotonic):
    deadline = clock() + timeout
    while clock() < deadline:
        state = check()
        if state == "ready":
            return 0 if open_dashboard() else 1
        if state in ("occupied", "setup"):
            break
        sleep(0.25)
    raise LaunchError(
        "Another launcher owns startup, but the dashboard is not ready. Check its console; no second server was started."
    )


@contextmanager
def singleton():
    if os.name != "nt":
        raise LaunchError(
            "This launcher requires Windows. Use python -m contract_to_cash.web on other systems."
        )
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateMutexW(None, True, "Local\\Ledgerline.Console.127.0.0.1.8000")
    if not handle:
        raise LaunchError("Windows could not create the launcher ownership mutex")
    owner = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    try:
        yield owner
    finally:
        if owner:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def serve(root):
    import uvicorn
    from .app import create_app
    from .store import Settings

    app = create_app(
        Settings(
            data=root / "agent-runtime-web/contract_to_cash/data",
            root=root / "runs/web",
            frontend=root / "frontend/dist",
            reviewer=os.environ.get("CONTRACT_WEB_REVIEWER", "Local operator"),
        )
    )
    store = app.state.store

    class Server(uvicorn.Server):
        draining = False

        def handle_exit(self, sig, frame):
            # Serialize against launch so an authorized request cannot race shutdown.
            with store.lock:
                store.accepting_launches = False
                if store.active:
                    if not self.draining:
                        print(
                            "Shutdown requested. Waiting for the bounded investigation to settle and close its journal. Do not close this window."
                        )
                    self.draining = True
                else:
                    self.should_exit = True

    server = Server(uvicorn.Config(app, host="127.0.0.1", port=8000, access_log=False))
    finished, startup_failed = Event(), Event()

    def monitor():
        opened = False
        deadline = time.monotonic() + 30
        while not finished.wait(0.25):
            if server.draining:
                with store.lock:
                    if store.active is None:
                        server.should_exit = True
            if not opened:
                if probe() == "ready":
                    opened = True
                    print(
                        "Ledgerline is ready: "
                        + URL
                        + "\nKeep this window open. Press Ctrl+C here for a clean shutdown."
                    )
                    open_dashboard()
                elif time.monotonic() >= deadline:
                    startup_failed.set()
                    server.should_exit = True
                    print(
                        "Dashboard did not become ready in 30 seconds. Check this console, port 8000 and the setup guide. History was not removed."
                    )

    watcher = Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        server.run()
    finally:
        finished.set()
        watcher.join(timeout=2)
    return 1 if startup_failed.is_set() or not server.started else 0


def launch(root=PROJECT, force_prompt=False):
    state = probe()
    if state == "ready":
        return 0 if open_dashboard() else 1
    if state == "occupied":
        raise LaunchError(
            "Port 8000 is occupied by an unrecognized or older service. Stop it explicitly; the launcher will not kill it."
        )
    if state == "setup":
        raise LaunchError(
            "Ledgerline is running but its frontend is unavailable. Build the frontend, then refresh the dashboard."
        )
    with singleton() as owner:
        if not owner:
            return wait_for_existing()
        # Recheck after acquiring ownership, including a manually started server.
        state = probe()
        if state == "ready":
            return 0 if open_dashboard() else 1
        if state != "starting":
            raise LaunchError("Port 8000 changed during startup. No additional server was started.")
        errors = installation_errors(root)
        if errors:
            raise LaunchError("\n".join(errors) + "\n\n" + SETUP)
        return serve(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--save-credential",
        action="store_true",
        help="Retired: local startup no longer uses operator passwords",
    )
    actions.add_argument(
        "--forget-credential",
        action="store_true",
        help="Remove only this checkout operator credential",
    )
    actions.add_argument(
        "--check",
        action="store_true",
        help="Check installation without starting a server or making API calls",
    )
    parser.add_argument(
        "--prompt-password",
        action="store_true",
        help="Retired: local startup no longer uses password prompts",
    )
    args = parser.parse_args(argv)
    try:
        if args.check:
            errors = installation_errors(PROJECT)
            print(
                "\n".join(errors) + "\n" + SETUP
                if errors
                else "Installation checks passed. No server or paid investigation started."
            )
            return 1 if errors else 0
        if args.forget_credential:
            windows_credentials.delete(credential_target(PROJECT))
            print("This checkout operator credential was removed. Run history was not changed.")
            return 0
        if args.save_credential:
            raise LaunchError("Passwordless local startup does not use saved passwords. No credential was written.")
        if args.prompt_password:
            raise LaunchError("Local startup no longer requires a password; omit --prompt-password")
        return launch()
    except (LaunchError, windows_credentials.CredentialError) as exc:
        print(str(exc))
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Startup cancelled. No run history was removed.")
        return 1
    except Exception:
        print(
            "Launcher failed safely. Check docs/WINDOWS_LAUNCHER.md and this console; no secrets or history were deleted."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
