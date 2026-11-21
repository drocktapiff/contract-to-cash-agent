"""Zero-provider full demo browser acceptance; real fixtures, Python and SQLite."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from playwright.sync_api import sync_playwright, expect
from scripts.smoke_web import ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryFile(mode="w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "tests_web.smoke_server", "--port", "8127"],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if ready(8127):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Demo browser server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1000}, locale="en-CA"
                    )
                    errors = []
                    requests = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("request", lambda request: requests.append(request.url))

                    def capture(name):
                        if args.screenshots:
                            args.screenshots.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(args.screenshots / name), full_page=True)

                    page.goto("http://127.0.0.1:8127/legacy", wait_until="networkidle")
                    page.get_by_role("button", name="Advanced Settings", exact=True).click()
                    page.get_by_role("button", name="Prepare Full Demo", exact=True).click()
                    dialog = page.get_by_role("dialog", name="Confirm simulated demo preparation")
                    expect(dialog).to_contain_text(
                        "Existing investigations, journals and decisions are retained"
                    )
                    dialog.get_by_role(
                        "button", name="Confirm preparation — no API usage", exact=True
                    ).click()
                    page.get_by_role("button", name="Start Full Demo", exact=True).click()
                    expect(page.locator(".demo-banner")).to_contain_text("Simulated Demo Data")
                    expect(page.locator(".summary-scene")).to_be_visible()
                    capture("01-maya-prepared-demo.png")
                    page.get_by_label("Demo persona", exact=True).select_option("sarah")
                    expect(
                        page.get_by_role(
                            "heading", name="Revenue Operations — Department Overview", exact=True
                        )
                    ).to_be_visible()
                    expect(page.locator(".enterprise-overview")).to_contain_text("$5,300.00")
                    expect(page.locator(".enterprise-overview")).to_contain_text("$610.00")
                    expect(page.locator(".enterprise-overview")).to_contain_text("$5,910.00")
                    shared = page.locator(".shared-insight")
                    expect(shared).to_contain_text("C008")
                    expect(shared).to_contain_text("C009")
                    expect(shared).to_contain_text("C010")
                    expect(shared).to_contain_text("$3,000.00")
                    expect(page.locator(".analysis-secondary")).not_to_have_attribute("open", "")
                    shared.get_by_role("button", name="View Supporting Evidence").click()
                    drawer = page.get_by_role(
                        "dialog",
                        name="Supporting Evidence — Shared Pricing Discrepancy",
                        exact=True,
                    )
                    expect(drawer).to_be_visible()
                    expect(drawer.locator(".source-text").first).to_be_visible()
                    drawer.get_by_role("button", name="Close evidence", exact=True).click()
                    shared_issue = page.locator(".priority-card").filter(
                        has=page.get_by_role(
                            "heading", name="Investigate shared pricing configuration", exact=True
                        )
                    )
                    shared_issue.get_by_role("button", name="Record management action").click()
                    editor = page.get_by_role("region", name="Management action editor")
                    editor.get_by_label("Internal owner or team", exact=True).fill(
                        "Billing Configuration Team"
                    )
                    editor.get_by_label("Target review date", exact=True).fill("2026-12-01")
                    editor.get_by_label("Status", exact=True).select_option("Assigned")
                    editor.get_by_label("Decision rationale", exact=True).fill(
                        "Presenter: inspect common template mapping before proposing any invoice changes."
                    )
                    editor.get_by_label(
                        "Expected verification or closure criteria", exact=True
                    ).fill("Document the mapping evidence and obtain independent financial review.")
                    editor.get_by_role(
                        "button", name="Save human management decision", exact=True
                    ).click()
                    expect(shared_issue).to_contain_text("Assigned · Billing Configuration Team")
                    capture("02-sarah-management-command-center.png")
                    page.get_by_label("Demo persona", exact=True).select_option("robert")
                    expect(
                        page.get_by_role("heading", name="Should this pilot grow?", exact=True)
                    ).to_be_visible()
                    expect(
                        page.get_by_role("heading", name="Sarah’s corrective actions", exact=True)
                    ).to_be_visible()
                    expect(page.locator(".enterprise-workspace")).to_contain_text(
                        "Billing Configuration Team · Assigned"
                    )
                    expect(page.locator(".enterprise-overview")).to_contain_text("$5,910.00")
                    expect(page.locator(".scenario-panel")).to_be_visible()
                    capture("03-robert-shared-context.png")
                    page.reload(wait_until="networkidle")
                    expect(page.locator(".enterprise-workspace")).to_contain_text(
                        "Billing Configuration Team · Assigned"
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.get_by_label("Demo persona", exact=True).select_option("sarah")
                    expect(page.locator(".shared-insight")).to_be_visible()
                    capture("04-sarah-mobile.png")
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    ), "Mobile page overflows"
                    assert not any(
                        "/enterprise/analyses" in u or "/api/investigations" in u for u in requests
                    ), requests
                    assert not errors, errors
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)
    print(
        "PASS: deterministic simulated Maya -> Sarah action -> Robert context, evidence, reload and mobile; zero provider requests."
    )


if __name__ == "__main__":
    main()
