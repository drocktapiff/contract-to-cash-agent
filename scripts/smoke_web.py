"""Four-scene UX test with a simulated SDK, actual local tools/journals, and no paid calls."""

import argparse
import http.client
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect


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
            command = [
                args.server_python,
                "-m",
                "tests_web.smoke_server",
                "--port",
                "8124",
                "--slow-test-runner",
            ] + (["--recorded"] if recorded else [])
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
                        page = browser.new_page(
                            viewport={"width": 1440, "height": 1080},
                            locale="en-CA",
                            timezone_id="America/Toronto",
                        )
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto("http://127.0.0.1:8124", wait_until="networkidle")

                        def capture(name):
                            if not args.screenshots:
                                return
                            args.screenshots.mkdir(parents=True, exist_ok=True)
                            page.evaluate(
                                """() => {
                                if (document.getElementById('ux-capture-label')) return;
                                const note=document.createElement('div');note.id='ux-capture-label';note.className='ux-capture-note';
                                note.textContent='AUTOMATED UI TEST · SIMULATED SDK RESPONSES · REAL LOCAL TEST JOURNAL · NO PAID OPENAI CALLS';
                                document.body.appendChild(note);
                            }"""
                            )
                            page.screenshot(path=str(args.screenshots / name), full_page=True)

                        if recorded:
                            page.get_by_role(
                                "heading", name="No genuine recording has been imported."
                            ).wait_for()
                            assert (
                                page.get_by_role(
                                    "button", name=re.compile("^Start Billing Review")
                                ).count()
                                == 0
                            )
                            capture("07-recorded-empty.png")
                        else:
                            page.get_by_role(
                                "heading", name="Your April 2026 billing review is ready."
                            ).wait_for()
                            start = page.get_by_role(
                                "button", name=re.compile("^Start Billing Review")
                            )
                            assert start.is_disabled()  # No guessed rates on a clean install.
                            page.get_by_role("button", name="Advanced Settings", exact=True).click()
                            page.get_by_label("Input USD per million tokens", exact=True).fill("2")
                            page.get_by_label(
                                "Cached input USD per million tokens", exact=True
                            ).fill("0.1")
                            page.get_by_label("Output USD per million tokens", exact=True).fill(
                                "10"
                            )
                            page.get_by_role("checkbox").check()
                            page.get_by_role(
                                "button", name="Save pricing confirmation", exact=True
                            ).click()
                            page.get_by_text(
                                "Administrator confirmation saved for 24 hours.", exact=False
                            ).wait_for()
                            page.get_by_role(
                                "button", name="Billing review", exact=False
                            ).first.click()
                            assert (
                                page.get_by_label(
                                    "Input USD per million tokens", exact=True
                                ).count()
                                == 0
                            )
                            assert page.locator('input[type="password"]').count() == 0
                            capture("01-start-work.png")
                            page.get_by_role(
                                "button", name=re.compile("^Start Billing Review")
                            ).click()
                            begin = page.get_by_role(
                                "button", name=re.compile("^Begin authorized review")
                            )
                            assert begin.is_disabled()
                            page.get_by_label("I authorize this investigation.", exact=True).check()
                            begin.click()
                            page.get_by_role(
                                "heading", name="The agent is working through the records."
                            ).wait_for()
                            expect(page.locator(".coverage strong").first).to_have_text("3")
                            capture("02-agent-working.png")
                            page.get_by_role(
                                "heading", name=re.compile("evidence-verified")
                            ).wait_for()
                            page.locator(".summary-scene .badge.incomplete").wait_for()
                            capture("03-findings-summary.png")
                            run_id = parse_qs(urlparse(page.url).query)["run"][0]
                            result = page.request.get(
                                f"http://127.0.0.1:8124/api/runs/{run_id}"
                            ).json()
                            assert all(
                                review["status"] == "pending" for review in result["reviews"]
                            )
                            assert (
                                page.request.get(
                                    f"http://127.0.0.1:8124/api/runs/{run_id}/findings/finding-C005/export"
                                ).status
                                == 403
                            )
                            page.get_by_role(
                                "button", name=re.compile("^Review Items Needing My Attention")
                            ).click()
                            page.get_by_role(
                                "heading", name="Needs Your Attention", exact=True
                            ).wait_for()
                            capture("04-needs-your-attention.png")
                            conflict = page.locator("article").filter(
                                has=page.get_by_role(
                                    "heading", name="Signed amendments disagree", exact=True
                                )
                            )
                            conflict.get_by_role(
                                "button", name="Examine this item →", exact=True
                            ).click()
                            dialog = page.get_by_role("dialog")
                            dialog.get_by_role(
                                "heading", name="Signed amendments disagree", exact=True
                            ).wait_for()
                            assert dialog.locator("details.source[open]").count() >= 2
                            assert (
                                dialog.get_by_role("button", name="Approve evidence export").count()
                                == 0
                            )
                            capture("05-original-evidence.png")
                            dialog.get_by_role(
                                "button", name="Escalate for clarification", exact=True
                            ).click()
                            dialog.get_by_label(
                                "Who should provide clarification?", exact=True
                            ).fill("Contract Administration")
                            dialog.get_by_label("What information is missing?", exact=True).fill(
                                "Written confirmation of the governing amendment"
                            )
                            dialog.get_by_label("Explain your decision", exact=True).fill(
                                "Simulated UX test: retain unresolved terms and ask for authoritative clarification."
                            )
                            dialog.get_by_role(
                                "button", name="Save clarification request", exact=True
                            ).click()
                            dialog.locator(".decision-record").wait_for()
                            capture("06-human-decision-saved.png")
                            page.keyboard.press("Escape")
                            credit = page.locator("article").filter(
                                has=page.get_by_role(
                                    "heading",
                                    name="A customer may have been overcharged",
                                    exact=True,
                                )
                            )
                            credit.get_by_role(
                                "button", name="Examine this item →", exact=True
                            ).click()
                            dialog = page.get_by_role("dialog")
                            dialog.locator("details.source summary").first.click()
                            dialog.get_by_label("Decision rationale", exact=True).fill(
                                "Simulated UX test: source evidence reviewed; approve only the requested evidence export."
                            )
                            dialog.get_by_role(
                                "button", name="Approve evidence export", exact=True
                            ).click()
                            dialog.locator(".decision-record").wait_for()
                            with page.expect_download() as download:
                                dialog.get_by_role(
                                    "button", name="Download approved evidence package", exact=True
                                ).click()
                            assert download.value.suggested_filename == "review-package.json"
                            page.keyboard.press("Escape")
                            page.reload(wait_until="networkidle")
                            page.get_by_role(
                                "heading", name="Needs Your Attention", exact=True
                            ).wait_for()
                            page.get_by_role("button", name="Past reviews", exact=False).click()
                            page.locator(".history-row").first.click()
                            page.get_by_role(
                                "heading", name=re.compile("evidence-verified")
                            ).wait_for()
                            page.get_by_text("View Technical Activity", exact=True).click()
                            page.get_by_text("human_review.decided", exact=False).first.wait_for()
                        page.set_viewport_size({"width": 390, "height": 844})
                        page.wait_for_timeout(100)
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= window.innerWidth"
                        ), "Mobile page overflows"
                        if not recorded:
                            page.get_by_role(
                                "button", name="Billing review", exact=False
                            ).first.click()
                            capture("08-mobile-start.png")
                        assert not errors, errors
                    finally:
                        browser.close()
                print(
                    "PASS: "
                    + (
                        "recorded empty/read-only scene"
                        if recorded
                        else "four-scene UX, administrator pricing, real journal activity, explicit clarification/export, reload and mobile"
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
