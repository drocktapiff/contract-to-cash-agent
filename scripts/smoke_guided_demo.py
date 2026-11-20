"""Guided Maya/Sarah shortcuts and mocked executive brief; no paid requests."""

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
            [
                sys.executable,
                "-m",
                "tests_web.smoke_server",
                "--port",
                "8128",
                "--phase4",
                "--slow-test-runner",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if ready(8128):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Guided demo server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1050},
                        locale="en-CA",
                        timezone_id="America/Toronto",
                    )
                    errors = []
                    paid = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "request",
                        lambda request: (
                            paid.append(request.url)
                            if request.method == "POST"
                            and request.url.endswith("/enterprise/analyses")
                            else None
                        ),
                    )
                    page.goto("http://127.0.0.1:8128", wait_until="networkidle")

                    def capture(name):
                        if args.screenshots:
                            args.screenshots.mkdir(parents=True, exist_ok=True)
                            page.evaluate("window.scrollTo(0,0)")
                            page.screenshot(path=str(args.screenshots / name), full_page=True)

                    maya = page.get_by_role("region", name="Maya Demo Controls")
                    expect(
                        maya.get_by_role("button", name="Complete Maya Demo", exact=True)
                    ).to_be_visible()
                    capture("01-maya-demo-controls.png")
                    maya.get_by_role("button", name="Complete Maya Demo", exact=True).click()
                    page.get_by_role(
                        "dialog", name="Confirm Maya simulated completion"
                    ).get_by_role(
                        "button",
                        name="Confirm Maya simulated completion — no API usage",
                        exact=True,
                    ).click()
                    expect(maya).to_contain_text("Maya stage prepared")
                    expect(page.locator(".summary-scene")).to_be_visible()
                    capture("02-maya-completed-simulation.png")
                    maya.get_by_role("button", name="Continue to Sarah", exact=True).click()
                    sarah = page.get_by_role("region", name="Sarah Demo Controls")
                    expect(
                        sarah.get_by_role("button", name="Complete Sarah Demo", exact=True)
                    ).to_be_enabled()
                    capture("03-sarah-demo-controls.png")
                    sarah.get_by_role("button", name="Complete Sarah Demo", exact=True).click()
                    page.get_by_role(
                        "dialog", name="Confirm Sarah simulated completion"
                    ).get_by_role(
                        "button",
                        name="Confirm Sarah simulated completion — no API usage",
                        exact=True,
                    ).click()
                    expect(sarah).to_contain_text("Sarah stage prepared")
                    expect(page.locator(".management-command")).to_contain_text(
                        "Simulated Demo Data · proposed fixture action"
                    )
                    expect(page.locator(".priority-card")).to_have_count(3)
                    capture("04-sarah-prepared-management-actions.png")
                    assert not paid, paid
                    sarah.get_by_role("button", name="Continue to Robert", exact=True).click()
                    expect(
                        page.get_by_role(
                            "button", name="Generate Executive Decision Brief", exact=True
                        )
                    ).to_be_visible()
                    expect(page.locator(".enterprise-workspace")).to_contain_text(
                        "Billing Configuration Team · Proposed"
                    )
                    expect(page.locator(".enterprise-overview")).to_contain_text("$5,910.00")
                    capture("05-robert-executive-workspace.png")
                    session = page.request.get("http://127.0.0.1:8128/api/session").json()
                    pricing = page.request.put(
                        "http://127.0.0.1:8128/api/admin/pricing",
                        headers={"x-csrf-token": session["csrf_token"]},
                        data={
                            "input_price": "2",
                            "output_price": "10",
                            "cached_input_price": ".1",
                            "checked_current_official_rates": True,
                        },
                    )
                    assert pricing.ok, pricing.text()
                    page.reload(wait_until="networkidle")
                    page.get_by_role(
                        "button", name="Generate Executive Decision Brief", exact=True
                    ).click()
                    dialog = page.get_by_role("dialog", name="Authorize enterprise analysis")
                    expect(
                        dialog.get_by_role("button", name="Begin authorized analysis", exact=True)
                    ).to_be_disabled()
                    dialog.get_by_label("I authorize this paid analysis.", exact=True).check()
                    dialog.get_by_role(
                        "button", name="Begin authorized analysis", exact=True
                    ).click()
                    expect(
                        page.get_by_role(
                            "heading", name="AI is examining the saved inputs.", exact=True
                        )
                    ).to_be_visible()
                    brief = page.get_by_role("region", name="Executive Decision Brief")
                    expect(brief).to_be_visible(timeout=30000)
                    expect(brief).to_contain_text("Mocked provider response — not live AI")
                    for heading in [
                        "Executive Assessment",
                        "What Maya Demonstrated",
                        "What Sarah Changed",
                        "Financial Opportunity",
                        "Risks & Missing Evidence",
                        "AI Recommendation",
                    ]:
                        expect(
                            brief.get_by_role("heading", name=heading, exact=True)
                        ).to_be_visible()
                    expect(brief).to_contain_text("more validation needed")
                    expect(
                        page.locator(".enterprise-human-decision button.primary")
                    ).to_be_disabled()
                    assert len(paid) == 1, paid
                    capture("06-robert-mocked-executive-brief.png")
                    brief.locator(".citation-buttons button").first.click()
                    expect(page.get_by_role("dialog",name="Supporting input",exact=True)).to_be_visible()
                    page.get_by_role("button", name="Close evidence", exact=True).click()
                    page.get_by_label("Decision action", exact=True).select_option(
                        "request_validation"
                    )
                    page.get_by_label("Decision rationale", exact=True).fill(
                        "Mocked-provider presentation: capture baseline review effort and source-backed correction outcomes before any investment."
                    )
                    page.get_by_label(
                        "I considered this recommendation's cited supporting inputs.", exact=True
                    ).check()
                    page.get_by_role("button", name="Save strategic decision", exact=True).click()
                    expect(
                        page.locator(".enterprise-human-decision .decision-record")
                    ).to_be_visible()
                    page.reload(wait_until="networkidle")
                    expect(
                        page.get_by_role("region", name="Executive Decision Brief")
                    ).to_be_visible()
                    expect(
                        page.locator(".enterprise-human-decision .decision-record")
                    ).to_be_visible()
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(brief).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    ), "Mobile overflow"
                    assert not errors, errors
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)
    print(
        "PASS: visible guided Maya -> Sarah controls, preserved simulated actions, grounded mocked executive brief, explicit paid consent and separate human decision; reload/mobile."
    )


if __name__ == "__main__":
    main()
