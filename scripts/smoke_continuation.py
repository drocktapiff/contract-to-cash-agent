"""Human/AI browser workflow with simulated SDK and elapsed test cooldown; never paid."""

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect
from scripts.smoke_web import ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-python", default=sys.executable)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryFile(mode="w+") as log:
        process = subprocess.Popen(
            [
                args.server_python,
                "-m",
                "tests_web.smoke_server",
                "--port",
                "8125",
                "--phase32",
                "--slow-test-runner",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if ready(8125):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Simulated continuation server did not become ready")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1080},
                        locale="en-CA",
                        timezone_id="America/Toronto",
                    )
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.goto("http://127.0.0.1:8125", wait_until="networkidle")

                    def capture(name):
                        if not args.screenshots:
                            return
                        args.screenshots.mkdir(parents=True, exist_ok=True)
                        page.evaluate(
                            """() => {if(document.getElementById('ux-capture-label')) return;
                            const note=document.createElement('div');note.id='ux-capture-label';note.className='ux-capture-note';
                            note.textContent='AUTOMATED TEST · SIMULATED SDK & AUTHORITY DOCUMENT · ELAPSED TEST COOLDOWN · NO PAID OPENAI CALLS';document.body.appendChild(note);} """
                        )
                        page.screenshot(path=str(args.screenshots / name), full_page=True)

                    page.get_by_role("button", name="Advanced Settings", exact=True).click()
                    page.get_by_label("Input USD per million tokens", exact=True).fill("2")
                    page.get_by_label("Cached input USD per million tokens", exact=True).fill("0.1")
                    page.get_by_label("Output USD per million tokens", exact=True).fill("10")
                    page.get_by_role("checkbox").check()
                    page.get_by_role("button", name="Save pricing confirmation", exact=True).click()
                    page.get_by_text(
                        "Administrator confirmation saved for 24 hours.", exact=False
                    ).wait_for()
                    page.get_by_role("button", name="Billing review", exact=False).first.click()
                    page.get_by_role("button", name=re.compile("^Start Billing Review")).click()
                    page.get_by_label("I authorize this investigation.", exact=True).check()
                    page.get_by_role("button", name=re.compile("^Begin authorized review")).click()
                    page.locator(".summary-scene .badge.incomplete").wait_for()
                    parent_id = parse_qs(urlparse(page.url).query)["run"][0]
                    page.get_by_role(
                        "button", name=re.compile("Review Items Needing My Attention")
                    ).click()
                    page.locator("article").filter(
                        has=page.get_by_role(
                            "heading", name="Signed amendments disagree", exact=True
                        )
                    ).get_by_role("button", name="Examine this item →", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    expect(
                        dialog.get_by_role("heading", name="Your decision is needed", exact=True)
                    ).to_be_visible()
                    assert dialog.locator("details.source[open]").count() >= 2
                    assert (
                        dialog.get_by_role(
                            "button", name="Approve evidence export", exact=True
                        ).count()
                        == 0
                    )
                    dialog.locator(".recommendation-card").scroll_into_view_if_needed()
                    capture("01-recommendation-and-evidence.png")
                    dialog.get_by_role(
                        "button", name="Escalate for clarification", exact=True
                    ).click()
                    dialog.get_by_label("Who should provide clarification?", exact=True).fill(
                        "Contract Administration"
                    )
                    dialog.get_by_label("What information is missing?", exact=True).fill(
                        "Written confirmation of the governing amendment"
                    )
                    dialog.get_by_label("Explain your decision", exact=True).fill(
                        "SIMULATED TEST: ask the responsible authority before choosing terms."
                    )
                    dialog.get_by_role(
                        "button", name="Save clarification request", exact=True
                    ).click()
                    dialog.locator(".decision-record").get_by_text(
                        "Awaiting clarification", exact=True
                    ).wait_for()
                    assert (
                        dialog.get_by_role(
                            "button", name="Continue investigation", exact=True
                        ).count()
                        == 0
                    )
                    capture("02-clarification-saved.png")
                    dialog.get_by_role("button", name="Resolve with evidence", exact=True).click()
                    select = dialog.get_by_label("Authoritative supporting record", exact=True)
                    expect(select.locator("option")).to_have_count(2)
                    select.select_option(index=1)
                    dialog.get_by_text("Read original written confirmation", exact=True).click()
                    dialog.get_by_label("Explain your decision", exact=True).fill(
                        "SIMULATED TEST: reviewed the registered original confirmation and recorded issuer authority; apply only the documented governing term."
                    )
                    capture("03-documented-resolution.png")
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    assert dialog.evaluate(
                        "element => element.scrollWidth <= element.clientWidth + 1"
                    )
                    capture("09-mobile-resolution.png")
                    page.set_viewport_size({"width": 1440, "height": 1080})
                    dialog.get_by_role(
                        "button", name="Save documented resolution", exact=True
                    ).click()
                    dialog.get_by_text("Resolution saved with evidence", exact=True).wait_for()
                    dialog.get_by_role("button", name="Continue investigation", exact=True).click()
                    begin = dialog.get_by_role(
                        "button", name="Begin authorized continuation", exact=True
                    )
                    assert begin.is_disabled()
                    capture("04-paid-continuation-confirmation.png")
                    dialog.get_by_label("I authorize this paid continuation.", exact=True).check()
                    begin.click()
                    page.get_by_role(
                        "heading", name="The agent is working through the records.", exact=True
                    ).wait_for()
                    page.get_by_text("Continuing only C007", exact=False).wait_for()
                    capture("05-agent-continues.png")
                    page.get_by_role(
                        "heading", name="The review is ready for your judgment.", exact=True
                    ).wait_for()
                    expect(
                        page.get_by_role(
                            "heading", name="What your contribution enabled", exact=True
                        )
                    ).to_be_visible()
                    capture("06-collaboration-outcome.png")
                    child_id = parse_qs(urlparse(page.url).query)["run"][0]
                    assert child_id != parent_id
                    child = page.request.get(f"http://127.0.0.1:8125/api/runs/{child_id}").json()
                    assert child["customers_compared"] == ["C007"]
                    assert all(r["status"] == "pending" for r in child["reviews"])
                    assert child["findings"][0]["recommendation"]["origin"] == "model_suggestion"
                    endpoint = f"http://127.0.0.1:8125/api/runs/{child_id}/findings/finding-C007"
                    assert page.request.get(endpoint + "/export").status == 403
                    page.get_by_role(
                        "button", name=re.compile("Review Items Needing My Attention")
                    ).click()
                    page.get_by_role("button", name="Examine this item →", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    dialog.get_by_label("Decision rationale", exact=True).fill(
                        "SIMULATED TEST: reviewed revised original evidence and authorize this evidence export only."
                    )
                    dialog.get_by_role("button", name="Approve evidence export", exact=True).click()
                    dialog.get_by_role(
                        "button", name="Download approved evidence package", exact=True
                    ).wait_for()
                    with page.expect_download() as download:
                        dialog.get_by_role(
                            "button", name="Download approved evidence package", exact=True
                        ).click()
                    assert download.value.suggested_filename == "review-package.json"
                    capture("07-separate-export-authorization.png")
                    page.keyboard.press("Escape")
                    page.reload(wait_until="networkidle")
                    page.get_by_role("heading", name="Needs Your Attention", exact=True).wait_for()
                    page.get_by_role("button", name="Past reviews", exact=False).click()
                    page.locator(".history-row").last.click()
                    page.get_by_role(
                        "heading", name="What your contribution enabled", exact=True
                    ).wait_for()
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    capture("08-mobile-outcome.png")
                    page.get_by_role(
                        "button", name=re.compile("Review Items Needing My Attention")
                    ).click()
                    page.locator("article").filter(
                        has=page.get_by_role(
                            "heading", name="Signed amendments disagree", exact=True
                        )
                    ).get_by_role("button", name="Examine this item →", exact=True).click()
                    saved_case = page.get_by_role("dialog")
                    saved_case.get_by_role(
                        "button", name="Open continued investigation", exact=True
                    ).wait_for()
                    assert (
                        saved_case.get_by_role(
                            "button", name="Continue investigation", exact=True
                        ).count()
                        == 0
                    )
                    assert len(page.request.get("http://127.0.0.1:8125/api/runs").json()) == 2
                    assert not errors, errors
                    print(
                        "Phase 3.2 browser workflow passed: escalation → documented evidence → paid confirmation → scoped tools → revised finding → separate export → history/mobile. Simulated SDK and authority only."
                    )
                finally:
                    browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
