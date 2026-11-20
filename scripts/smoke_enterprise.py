"""Connected enterprise browser test: simulated SDK, real tools/journals, no paid API."""

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
                "8126",
                "--phase4",
                "--slow-test-runner",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if ready(8126):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Enterprise simulated test server did not start")
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
                    page.goto("http://127.0.0.1:8126", wait_until="networkidle")

                    def capture(name):
                        if not args.screenshots:
                            return
                        args.screenshots.mkdir(parents=True, exist_ok=True)
                        page.evaluate(
                            """() => {if(document.getElementById('ux-capture-label'))return;const n=document.createElement('div');n.id='ux-capture-label';n.className='ux-capture-note';n.textContent='AUTOMATED TEST · SIMULATED SDK · REAL LOCAL PYTHON / SQLITE · TEST COOLDOWN OVERRIDE · NO PAID API CALLS';document.body.appendChild(n);} """
                        )
                        page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
                        page.screenshot(path=str(args.screenshots / name), full_page=True)

                    persona = page.get_by_label("Demo persona", exact=True)
                    expect(persona).to_have_value("maya")
                    page.get_by_role("button", name="Advanced Settings", exact=True).click()
                    page.get_by_label("Input USD per million tokens", exact=True).fill("2")
                    page.get_by_label("Cached input USD per million tokens", exact=True).fill(".1")
                    page.get_by_label("Output USD per million tokens", exact=True).fill("10")
                    page.get_by_role("checkbox").check()
                    page.get_by_role("button", name="Save pricing confirmation", exact=True).click()
                    page.get_by_text(
                        "Administrator confirmation saved for 24 hours.", exact=False
                    ).wait_for()
                    page.get_by_role("button", name="Billing review", exact=False).first.click()
                    capture("01-maya-operational-workspace.png")
                    page.get_by_role("button", name=re.compile("^Start Billing Review")).click()
                    page.get_by_label("I authorize this investigation.", exact=True).check()
                    page.get_by_role("button", name=re.compile("^Begin authorized review")).click()
                    page.locator(".summary-scene .badge.incomplete").wait_for()
                    root = parse_qs(urlparse(page.url).query)["run"][0]
                    page.get_by_role(
                        "button", name=re.compile("Review Items Needing My Attention")
                    ).click()
                    page.locator("article").filter(
                        has=page.get_by_role(
                            "heading", name="Signed amendments disagree", exact=True
                        )
                    ).get_by_role("button", name="Examine this item →", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    dialog.get_by_role(
                        "button", name="Escalate for clarification", exact=True
                    ).click()
                    dialog.get_by_label("Who should provide clarification?", exact=True).fill(
                        "Contract Administration"
                    )
                    dialog.get_by_label("What information is missing?", exact=True).fill(
                        "Written authority for the governing April amendment"
                    )
                    dialog.get_by_label("Explain your decision", exact=True).fill(
                        "SIMULATED DEMO: request governing-term evidence before calculating the unresolved charge."
                    )
                    dialog.get_by_role(
                        "button", name="Save clarification request", exact=True
                    ).click()
                    dialog.locator(".decision-record").get_by_text(
                        "Awaiting clarification", exact=True
                    ).wait_for()
                    capture("02-maya-human-judgment.png")
                    page.keyboard.press("Escape")
                    persona.select_option("sarah")
                    page.get_by_role(
                        "heading", name="Revenue Operations — Department Overview", exact=True
                    ).wait_for()
                    expect(
                        page.get_by_role("heading", name="What Needs Your Attention", exact=True)
                    ).to_be_visible()
                    capture("03-sarah-management-workspace.png")
                    page.locator(".analysis-secondary > summary").click()
                    page.get_by_role(
                        "button", name="Analyze Department Performance", exact=True
                    ).click()
                    paid = page.get_by_role(
                        "dialog", name="Authorize enterprise analysis", exact=True
                    )
                    assert paid.get_by_role(
                        "button", name="Begin authorized analysis", exact=True
                    ).is_disabled()
                    paid.get_by_label("I authorize this paid analysis.", exact=True).check()
                    paid.get_by_role("button", name="Begin authorized analysis", exact=True).click()
                    page.get_by_role(
                        "heading", name="AI is examining the saved inputs.", exact=True
                    ).wait_for()
                    expect(page.locator(".analysis-working ol li").first).to_be_visible()
                    capture("04-sarah-real-test-activity.png")
                    page.get_by_role(
                        "heading", name="Set a management priority", exact=True
                    ).wait_for()
                    expect(
                        page.locator(".enterprise-human-decision button.primary")
                    ).to_be_disabled()
                    page.get_by_label("Decision action", exact=True).select_option("follow_up")
                    page.get_by_label("Internal investigation owner", exact=True).fill(
                        "Billing Configuration Team"
                    )
                    page.get_by_label("Decision rationale", exact=True).fill(
                        "SIMULATED DEMO: investigate the shared template discrepancy before declaring a root cause; follow up with the recorded internal owner."
                    )
                    page.get_by_label(
                        "I considered this recommendation's cited supporting inputs.", exact=True
                    ).check()
                    page.get_by_role("button", name="Save management decision", exact=True).click()
                    page.locator(".enterprise-human-decision .decision-record").wait_for()
                    capture("05-sarah-persisted-decision.png")
                    persona.select_option("robert")
                    page.get_by_role(
                        "heading", name="Should this pilot grow?", exact=True
                    ).wait_for()
                    page.locator(".management-bridge .decision-record").wait_for()
                    expect(page.locator(".scenario-results h3")).to_have_text("$85,000.00")
                    page.get_by_label("One-time implementation / all teams", exact=True).fill(
                        "10000"
                    )
                    page.get_by_label("Comparable teams", exact=True).fill("2")
                    page.get_by_role(
                        "button", name="Calculate and save scenario", exact=True
                    ).click()
                    expect(page.locator(".scenario-results h3")).to_have_text("$170,000.00")
                    capture("06-robert-saved-financial-scenario.png")
                    page.get_by_role(
                        "button", name="Evaluate AI Expansion Opportunity", exact=True
                    ).click()
                    paid = page.get_by_role(
                        "dialog", name="Authorize enterprise analysis", exact=True
                    )
                    paid.get_by_label("I authorize this paid analysis.", exact=True).check()
                    paid.get_by_role("button", name="Begin authorized analysis", exact=True).click()
                    page.get_by_role(
                        "heading", name="Record the strategic decision", exact=True
                    ).wait_for()
                    page.get_by_label("Decision action", exact=True).select_option("approve_pilot")
                    page.get_by_label("Decision rationale", exact=True).fill(
                        "SIMULATED DEMO: approve a bounded validation pilot as an internal record only; validate workload and cost assumptions before any real investment."
                    )
                    page.get_by_label(
                        "I considered this recommendation's cited supporting inputs.", exact=True
                    ).check()
                    page.get_by_role("button", name="Save strategic decision", exact=True).click()
                    page.locator(".enterprise-human-decision .decision-record").wait_for()
                    capture("07-robert-persisted-strategic-decision.png")
                    overview = page.request.get("http://127.0.0.1:8126/api/enterprise").json()
                    assert len(overview["analyses"]) == 2 and len(overview["decisions"]) == 2
                    assert {d["root_run_id"] for d in overview["decisions"]} == {root}
                    assert (
                        overview["scenario"]["outputs"]["first_year_net_benefit_cad"] == "160000.00"
                    )
                    assert (
                        page.request.get(
                            f"http://127.0.0.1:8126/api/runs/{root}/findings/finding-C005/export"
                        ).status
                        == 403
                    )
                    page.reload(wait_until="networkidle")
                    expect(page.get_by_label("Demo persona", exact=True)).to_have_value("robert")
                    page.locator(".enterprise-human-decision .decision-record").wait_for()
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    capture("08-robert-mobile.png")
                    persona = page.get_by_label("Demo persona", exact=True)
                    persona.select_option("sarah")
                    page.get_by_role(
                        "heading", name="Revenue Operations — Department Overview", exact=True
                    ).wait_for()
                    page.locator(".analysis-secondary > summary").click()
                    page.locator(".enterprise-human-decision .decision-record").wait_for()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    capture("09-sarah-mobile.png")
                    persona.select_option("maya")
                    page.get_by_role(
                        "heading", name="Your April 2026 billing review is ready.", exact=True
                    ).wait_for()
                    page.set_viewport_size({"width": 1440, "height": 1080})
                    page.get_by_role("button", name="Advanced Settings", exact=True).click()
                    page.get_by_role("button", name="Review reset scope", exact=True).click()
                    archive = page.get_by_role(
                        "button", name="Archive history and reset all personas", exact=True
                    )
                    assert archive.is_disabled()
                    page.get_by_label("Type ARCHIVE DEMO HISTORY", exact=True).fill(
                        "ARCHIVE DEMO HISTORY"
                    )
                    capture("10-confirmed-archive-reset.png")
                    archive.click()
                    page.get_by_role(
                        "heading", name="Your April 2026 billing review is ready.", exact=True
                    ).wait_for()
                    expect(page.get_by_label("Demo persona", exact=True)).to_have_value("maya")
                    reset = page.request.get("http://127.0.0.1:8126/api/enterprise").json()
                    assert (
                        reset["operational"]["root_run_id"] is None
                        and not reset["analyses"]
                        and not reset["decisions"]
                    )
                    assert page.request.get("http://127.0.0.1:8126/api/admin/pricing").json()[
                        "ready"
                    ]
                    capture("11-maya-after-archive.png")
                    assert not errors, errors
                    print(
                        "PASS: three personas share persisted operational -> management -> executive records; Python ROI, paid confirmations, source-bound decisions, no export approval, reload/mobile and archive-only reset. SDK simulated; no paid calls."
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
