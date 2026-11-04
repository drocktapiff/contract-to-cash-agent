"""Opt-in Chromium smoke test against a local, simulated-SDK server; no paid calls."""

import argparse
import http.client
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from playwright.sync_api import sync_playwright


def ready(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/api/health")
        return connection.getresponse().status == 200
    except OSError:
        return False
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-python", default=sys.executable)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    for recorded in (False, True):
        with tempfile.TemporaryFile(mode="w+") as log:
            command = [args.server_python, "-m", "tests_web.smoke_server", "--port", "8124"] + (
                ["--recorded"] if recorded else []
            )
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    if ready(8124):
                        break
                    if process.poll() is not None:
                        raise RuntimeError("Local test server exited")
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Local test server did not become ready")
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 1080})
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto("http://127.0.0.1:8124", wait_until="networkidle")
                        page.get_by_role("heading", name="From contract to clarity.").wait_for()
                        if recorded:
                            page.get_by_role("button", name="Audit History", exact=True).click()
                            page.get_by_role(
                                "heading", name="No genuine recording imported"
                            ).wait_for()
                            assert page.get_by_role(
                                "button", name="Run investigation", exact=True
                            ).is_disabled()
                        else:
                            page.get_by_role("button", name="Enter operator workspace").click()
                            page.get_by_label("Operator credential", exact=True).fill(
                                "smoke-operator-" + "x" * 32
                            )
                            page.get_by_role("button", name="Sign in securely", exact=True).click()
                            page.get_by_role("button", name="Run investigation", exact=True).click()
                            page.get_by_label("Input", exact=True).fill("2")
                            page.get_by_label("Cached input", exact=True).fill("0.1")
                            page.get_by_label("Output", exact=True).fill("10")
                            page.get_by_role("checkbox").check()
                            page.get_by_role(
                                "button", name="Start one investigation", exact=True
                            ).click()
                            page.get_by_text("Incomplete", exact=True).first.wait_for()
                            page.get_by_role("button", name="Findings", exact=True).click()
                            page.get_by_role("button", name="C005", exact=True).click()
                            page.get_by_role("heading", name="C005", exact=True).wait_for()
                            page.locator("details.source summary").first.click()
                            assert page.locator(".source pre").first.is_visible()
                            page.get_by_label("Decision rationale", exact=True).fill(
                                "Simulated browser test: original sources reviewed."
                            )
                            page.get_by_role("button", name="Approve export", exact=True).click()
                            page.locator(".badge.approved").first.wait_for()
                            with page.expect_download() as download:
                                page.get_by_role(
                                    "button", name="Download approved evidence package", exact=True
                                ).click()
                            assert download.value.suggested_filename == "review-package.json"
                            page.keyboard.press("Escape")
                            page.reload(wait_until="networkidle")
                            page.locator(".badge.approved").first.wait_for()
                            page.get_by_role("button", name="Audit History", exact=True).click()
                            page.get_by_role("button", name="Inspect run →", exact=True).wait_for()
                        if args.screenshots:
                            args.screenshots.mkdir(parents=True, exist_ok=True)
                            page.screenshot(
                                path=str(
                                    args.screenshots
                                    / (
                                        "recorded-empty.png"
                                        if recorded
                                        else "simulated-operator-test.png"
                                    )
                                ),
                                full_page=True,
                            )
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.wait_for_timeout(100)
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= window.innerWidth"
                        ), "Mobile page overflows"
                        assert not errors, errors
                    finally:
                        browser.close()
                print(
                    "PASS: "
                    + (
                        "recorded empty/read-only browser state"
                        if recorded
                        else "simulated SDK launch → SSE → evidence → export approval → reload history"
                    )
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


if __name__ == "__main__":
    main()
