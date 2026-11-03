"""Offline launcher coverage. No API client or paid investigation is created."""

from contextlib import contextmanager
import ctypes
import getpass
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
import warnings

from contract_to_cash.web import windows_credentials as credentials
from contract_to_cash.web import windows_launcher as launcher
from scripts.build_agent_runtime import build

PASSWORD = "offline-test-password-" + "x" * 32


@contextmanager
def ownership(owner):
    yield owner


class LauncherTests(unittest.TestCase):
    def test_existing_dashboard_skips_checks_and_passwords(self):
        with patch.object(launcher, "probe", return_value="ready"), patch.object(
            launcher, "open_dashboard"
        ) as browser, patch.object(launcher, "operator_password") as password, patch.object(
            launcher, "installation_errors"
        ) as checks:
            self.assertEqual(launcher.launch(), 0)
        browser.assert_called_once()
        password.assert_not_called()
        checks.assert_not_called()

    def test_foreign_port_is_never_killed_or_opened(self):
        with patch.object(launcher, "probe", return_value="occupied"), patch.object(
            launcher, "serve"
        ) as serve, patch.object(launcher, "open_dashboard") as browser:
            with self.assertRaisesRegex(launcher.LaunchError, "unrecognized"):
                launcher.launch()
        serve.assert_not_called()
        browser.assert_not_called()

    def test_second_launcher_waits_without_prompt_or_new_server(self):
        with patch.object(launcher, "probe", return_value="starting"), patch.object(
            launcher, "singleton", return_value=ownership(False)
        ), patch.object(launcher, "wait_for_existing", return_value=0) as wait, patch.object(
            launcher, "serve"
        ) as serve, patch.object(
            launcher, "operator_password"
        ) as password:
            self.assertEqual(launcher.launch(), 0)
        wait.assert_called_once()
        serve.assert_not_called()
        password.assert_not_called()

    def test_missing_prerequisites_are_actionable_without_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            errors = launcher.installation_errors(root)
            self.assertTrue(any("python.exe" in e for e in errors))
            self.assertTrue(any("Frontend build" in e for e in errors))
            self.assertTrue(any("Isolated runtime" in e for e in errors))
            self.assertFalse(list(root.iterdir()))
            with patch.object(launcher, "probe", return_value="starting"), patch.object(
                launcher, "singleton", return_value=ownership(True)
            ), patch.object(launcher, "operator_password") as password:
                with self.assertRaisesRegex(launcher.LaunchError, "npm ci"):
                    launcher.launch(root)
            password.assert_not_called()

    def test_valid_installation_and_stale_lock_leave_journals_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build(root / "agent-runtime-web")
            python = root / ".web-venv/Scripts/python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            assets = root / "frontend/dist/assets"
            assets.mkdir(parents=True)
            (assets.parent / "index.html").write_text("<html></html>")
            (assets / "app.js").write_text("")
            (assets / "app.css").write_text("")
            self.assertEqual(launcher.installation_errors(root), [])
            run = root / "runs/web"
            run.mkdir(parents=True)
            lock = run / ".server.lock"
            lock.write_text("existing ownership")
            journal = run / "preserved.sqlite3"
            journal.write_bytes(b"retained journal bytes")
            self.assertTrue(any("ownership lock" in e for e in launcher.installation_errors(root)))
            self.assertEqual(lock.read_text(), "existing ownership")
            self.assertEqual(journal.read_bytes(), b"retained journal bytes")
            key = root / "agent-runtime-web/contract_to_cash/data/sealed_answer_key.json"
            key.write_text("{}")
            self.assertTrue(any("sealed answer" in e for e in launcher.installation_errors(root)))

    def test_owner_starts_existing_application_with_selected_password(self):
        with patch.object(launcher, "probe", return_value="starting"), patch.object(
            launcher, "singleton", return_value=ownership(True)
        ), patch.object(launcher, "installation_errors", return_value=[]), patch.object(
            launcher, "operator_password", return_value=PASSWORD
        ), patch.object(
            launcher, "serve", return_value=0
        ) as serve:
            self.assertEqual(launcher.launch(), 0)
        serve.assert_called_once_with(launcher.PROJECT, PASSWORD)

    def test_inherited_and_stored_passwords_are_never_echoed(self):
        with patch.dict(os.environ, {"CONTRACT_WEB_OPERATOR_TOKEN": PASSWORD}), patch.object(
            credentials, "read"
        ) as stored, patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(launcher.operator_password(launcher.PROJECT), PASSWORD)
            self.assertEqual(output.getvalue(), "")
            stored.assert_not_called()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            credentials, "read", return_value=PASSWORD
        ), patch.object(launcher, "secure_prompt") as prompt:
            self.assertEqual(launcher.operator_password(launcher.PROJECT), PASSWORD)
        prompt.assert_not_called()

    def test_hidden_prompt_and_force_prompt_bypass_stored_password(self):
        with patch.dict(os.environ, {"CONTRACT_WEB_OPERATOR_TOKEN": "inherited"}), patch.object(
            credentials, "read"
        ) as read, patch("sys.stdin.isatty", return_value=True):
            self.assertEqual(
                launcher.operator_password(
                    launcher.PROJECT, prompt=lambda _: PASSWORD, force_prompt=True
                ),
                PASSWORD,
            )
        read.assert_not_called()

    def test_echoing_fallback_and_noninteractive_input_are_refused(self):
        def unsafe(message):
            warnings.warn("hidden input unavailable", getpass.GetPassWarning)
            self.fail("Warning should have become an error before fallback input")

        with patch("sys.stdin.isatty", return_value=True), self.assertRaisesRegex(
            launcher.LaunchError, "no echoing fallback"
        ):
            launcher.secure_prompt("hidden", unsafe)
        with patch("sys.stdin.isatty", return_value=False), self.assertRaisesRegex(
            launcher.LaunchError, "Windows console"
        ):
            launcher.secure_prompt("hidden")

    def test_save_requires_confirmation_and_never_outputs_password(self):
        with patch.object(
            launcher, "secure_prompt", side_effect=[PASSWORD, PASSWORD]
        ), patch.object(credentials, "write") as write, patch(
            "sys.stdin.isatty", return_value=True
        ), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output:
            self.assertEqual(launcher.main(["--save-credential"]), 0)
            self.assertNotIn(PASSWORD, output.getvalue())
        write.assert_called_once_with(launcher.credential_target(launcher.PROJECT), PASSWORD)
        with patch.object(
            launcher, "secure_prompt", side_effect=[PASSWORD, "different"]
        ), patch.object(credentials, "write") as write, patch(
            "sys.stdin.isatty", return_value=True
        ), patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            self.assertEqual(launcher.main(["--save-credential"]), 1)
        write.assert_not_called()

    def test_credential_target_is_per_checkout_without_raw_paths(self):
        a = launcher.credential_target(Path("/checkout-one"))
        self.assertEqual(a, launcher.credential_target(Path("/checkout-one")))
        self.assertNotEqual(a, launcher.credential_target(Path("/checkout-two")))
        self.assertNotIn("checkout-one", a)

    def test_duplicate_wait_timeout_and_browser_failure(self):
        clock = iter([0, 0, 31])
        with patch.object(launcher, "open_dashboard") as browser, self.assertRaises(
            launcher.LaunchError
        ):
            launcher.wait_for_existing(
                check=lambda: "starting", clock=lambda: next(clock), sleep=lambda _: None
            )
        browser.assert_not_called()
        with patch.object(launcher.webbrowser, "open", return_value=False), patch(
            "sys.stdout", new_callable=io.StringIO
        ) as output:
            launcher.open_dashboard()
        self.assertIn(launcher.URL, output.getvalue())

    def test_probe_checks_application_identity_and_frontend(self):
        connection = MagicMock()
        health = MagicMock(status=200)
        health.read.return_value = json.dumps({"application_id": launcher.APPLICATION_ID}).encode()
        page = MagicMock(status=200)
        page.getheader.return_value = "text/html"
        page.read.return_value = b"<html>"
        connection.getresponse.side_effect = [health, page]
        with patch.object(
            launcher.http.client, "HTTPConnection", return_value=connection
        ) as client:
            self.assertEqual(launcher.probe(), "ready")
        client.assert_called_once_with("127.0.0.1", 8000, timeout=0.5)
        connection.close.assert_called_once()
        connection = MagicMock()
        health.read.return_value = b'{"application_id":"another-service"}'
        connection.getresponse.return_value = health
        with patch.object(launcher.http.client, "HTTPConnection", return_value=connection):
            self.assertEqual(launcher.probe(), "occupied")

    def test_connected_but_unresponsive_port_is_not_treated_as_free(self):
        connection = MagicMock()
        connection.request.side_effect = TimeoutError("local response timed out")
        with patch.object(launcher.http.client, "HTTPConnection", return_value=connection):
            self.assertEqual(launcher.probe(), "occupied")
        connection.close.assert_called_once()

    def test_clean_shutdown_disables_launch_and_waits_for_active_worker(self):
        import uvicorn
        from contract_to_cash.web import app as application

        store = MagicMock()
        store.active = "active-run"
        store.accepting_launches = True
        fake_app = MagicMock()
        fake_app.state.store = store
        seen = []

        class FakeServer:
            started = True
            should_exit = False

            def __init__(self, config):
                pass

            def run(self):
                self.handle_exit(2, None)
                seen.append((self.draining, self.should_exit, store.accepting_launches))
                store.active = None
                self.handle_exit(2, None)
                seen.append(self.should_exit)

        with patch.object(uvicorn, "Server", FakeServer), patch.object(
            uvicorn, "Config"
        ), patch.object(application, "create_app", return_value=fake_app), patch.object(
            launcher, "Thread"
        ) as thread, patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            self.assertEqual(launcher.serve(launcher.PROJECT, PASSWORD), 0)
        self.assertEqual(seen, [(True, False, False), True])
        thread.return_value.join.assert_called_once()

    def test_credential_native_blob_encoding_and_free(self):
        blob = ctypes.create_string_buffer(PASSWORD.encode("utf-16-le"))
        record = credentials.Credential()
        record.CredentialBlobSize = len(PASSWORD.encode("utf-16-le"))
        record.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))

        def read(target, kind, flags, out):
            ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(credentials.Credential)))[0] = (
                ctypes.pointer(record)
            )
            return True

        dll = MagicMock()
        dll.CredReadW.side_effect = read
        with patch.object(credentials, "api", return_value=dll):
            self.assertEqual(credentials.read("test-target"), PASSWORD)
        dll.CredFree.assert_called_once()

        def write(pointer, flags):
            value = ctypes.cast(pointer, ctypes.POINTER(credentials.Credential)).contents
            self.assertEqual(value.Type, 1)
            self.assertEqual(value.Persist, 2)
            self.assertEqual(
                ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode(
                    "utf-16-le"
                ),
                PASSWORD,
            )
            return True

        dll.CredWriteW.side_effect = write
        with patch.object(credentials, "api", return_value=dll):
            credentials.write("test-target", PASSWORD)


@unittest.skipUnless(os.name == "nt", "Native Windows integration requires Windows")
class NativeWindowsTests(unittest.TestCase):
    def test_credential_manager_current_user_roundtrip(self):
        target = "Ledgerline/LauncherTests/" + uuid4().hex
        try:
            credentials.write(target, PASSWORD)
            self.assertEqual(credentials.read(target), PASSWORD)
        finally:
            credentials.delete(target)
        self.assertIsNone(credentials.read(target))

    def test_desktop_shortcut_install_and_remove_in_temporary_folder(self):
        script = launcher.PROJECT / "scripts/windows/install_shortcut.ps1"
        with tempfile.TemporaryDirectory() as tmp:
            command = ["powershell.exe", "-NoProfile", "-File", str(script), "-Destination", tmp]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            link = Path(tmp) / "Ledgerline Operations Console.lnk"
            self.assertTrue(link.is_file())
            result = subprocess.run(
                command + ["-Remove"], capture_output=True, text=True, timeout=30
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(link.exists())
