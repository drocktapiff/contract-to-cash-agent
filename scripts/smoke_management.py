"""Real PDF handoff, management workflow and explicitly simulated SDK integration; no paid calls."""

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
    expect.set_options(timeout=30000)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests_web.smoke_server",
                "--port",
                "8133",
                "--document-workspace",
                "--management-ai",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if ready(8133):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Management fixture server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        base_url="http://127.0.0.1:8133",
                        viewport={"width": 1440, "height": 1050},
                        locale="en-CA",
                        timezone_id="America/Toronto",
                    )
                    errors = []
                    posts = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "request", lambda r: posts.append(r.url) if r.method == "POST" else None
                    )

                    def capture(name):
                        if args.screenshots:
                            args.screenshots.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(args.screenshots / name), full_page=True)

                    def confirm(label, suffix):
                        dialog = page.get_by_role("dialog", name=label, exact=True)
                        dialog.get_by_label("Rationale", exact=True).fill(
                            "Simulated browser reviewer confirms internal administrative processing only."
                        )
                        dialog.get_by_role("checkbox").check()
                        with page.expect_response(
                            lambda r: r.request.method == "POST" and r.url.endswith(suffix),
                            timeout=90000,
                        ) as response:
                            dialog.get_by_role(
                                "button", name="Confirm " + label, exact=True
                            ).click()
                        assert response.value.ok, response.value.text()
                        return response.value.json()

                    page.goto("/", wait_until="networkidle")
                    page.get_by_role("button", name="Load Sample Documents", exact=True).click()
                    loaded = confirm("Load Sample Documents", "/load")
                    sid = loaded["session_id"]
                    page.get_by_role("button", name="Select All Matching", exact=True).click()
                    page.get_by_role("button", name="AI Powered Close", exact=True).click()
                    closed = confirm("AI Powered Close", "/selected/close")
                    assert closed["checks_completed"] == 73
                    page.get_by_role("button", name="Select All Remaining Work", exact=True).click()
                    page.get_by_role("button", name="Escalate to Sarah", exact=True).click()
                    handoff = confirm("Escalate Selected to Sarah", "/selected/escalate")
                    assert handoff["handoffs_created"] == 29
                    capture("01-maya-completed-handoff.png")
                    page.get_by_role(
                        "button", name="Sarah — Management Command Center", exact=True
                    ).click()
                    center = page.get_by_role("region", name="Sarah’s management inbox", exact=True)
                    expect(page.get_by_test_id("management-total")).to_have_text("102")
                    expect(page.get_by_test_id("management-completed")).to_have_text("73")
                    expect(page.get_by_test_id("management-handoffs")).to_have_text("29")
                    expect(center).to_contain_text("Rule-based operational overview")
                    capture("02-management-overview.png")
                    center.get_by_role(
                        "button",
                        name="Workload distribution: Automatic administrative completion, 73. View supporting work",
                        exact=True,
                    ).click()
                    expect(center).to_contain_text("73 matching cases")
                    expect(center.locator("tbody tr")).to_have_count(15)
                    center.get_by_role("combobox", name="Management queue view").select_option(
                        "Awaiting Finance"
                    )
                    expect(center).to_contain_text("8 matching cases")
                    center.get_by_role(
                        "checkbox", name="Select All Management Cases", exact=True
                    ).check()
                    center.get_by_role(
                        "button", name="Complete management review", exact=True
                    ).click()
                    dialog = page.get_by_role(
                        "dialog", name="Complete management review", exact=True
                    )
                    expect(
                        dialog.get_by_role("button", name="Confirm management action")
                    ).to_be_disabled()
                    dialog.get_by_label("Rationale", exact=True).fill(
                        "Coordination reviewed; Finance approval remains required."
                    )
                    dialog.get_by_label(
                        "Required next action / management closure criteria", exact=True
                    ).fill(
                        "Await separately authorized Finance review with current financial evidence."
                    )
                    dialog.get_by_role("checkbox").check()
                    with page.expect_response(
                        lambda r: r.request.method == "POST"
                        and r.url.endswith("/management/commands"),
                        timeout=90000,
                    ) as recorded:
                        dialog.get_by_role("button", name="Confirm management action").click()
                    assert recorded.value.ok, recorded.value.text()
                    assert recorded.value.json()["financial_actions_executed"] == 0
                    expect(center).to_contain_text("Management: Completed")
                    expect(center).to_contain_text("Awaiting Financial Review")
                    capture("03-finance-authority-preserved.png")
                    center.get_by_role("button", name="Overview", exact=True).click()
                    center.get_by_role(
                        "button", name="Create corrective action", exact=True
                    ).first.click()
                    dialog = page.get_by_role("dialog", name="Create corrective action", exact=True)
                    dialog.get_by_label("Rationale", exact=True).fill(
                        "Coordinate an internal investigation with source-backed closure criteria."
                    )
                    dialog.get_by_role("checkbox").check()
                    with page.expect_response(
                        lambda r: r.request.method == "POST"
                        and r.url.endswith("/management/corrective"),
                        timeout=90000,
                    ) as created:
                        dialog.get_by_role(
                            "button", name="Save corrective action", exact=True
                        ).click()
                    assert created.value.ok, created.value.text()
                    expect(center).to_contain_text("Investigate")
                    capture("04-corrective-action.png")
                    center.get_by_role("button", name="Management Intelligence", exact=True).click()
                    active_tab = center.get_by_role(
                        "button", name="Management Intelligence", exact=True
                    )
                    active_tab.hover()
                    expect(active_tab).to_have_css("background-color", "rgb(32, 89, 76)")
                    expect(active_tab).to_have_css("color", "rgb(255, 255, 255)")

                    center.get_by_role(
                        "button", name="Analyze Team Performance", exact=True
                    ).click()
                    paid = page.get_by_role(
                        "dialog", name="Authorize Team Performance Analysis", exact=True
                    )
                    expect(
                        paid.get_by_role("button", name="Begin authorized management analysis")
                    ).to_be_disabled()
                    expect(paid).to_contain_text("pricing")
                    paid.get_by_role("button", name="Cancel", exact=True).click()
                    session = page.request.get("/api/session").json()
                    headers = {"X-CSRF-Token": session["csrf_token"]}
                    pricing = page.request.put(
                        "/api/admin/pricing",
                        headers=headers,
                        data={
                            "input_price": "1",
                            "output_price": "1",
                            "cached_input_price": "0",
                            "checked_current_official_rates": True,
                        },
                    )
                    assert pricing.ok, pricing.text()
                    center.get_by_role(
                        "button", name="Analyze Team Performance", exact=True
                    ).click()
                    expect(paid).to_be_visible()
                    expect(
                        paid.get_by_role("button", name="Begin authorized management analysis")
                    ).to_be_disabled()
                    paid.get_by_label("Analysis rationale", exact=True).fill(
                        "Explicit simulated browser provider fixture integration, not a live acceptance test."
                    )
                    paid.get_by_role("checkbox").check()
                    with page.expect_response(
                        lambda r: r.request.method == "POST"
                        and r.url.endswith("/management/analyses"),
                        timeout=90000,
                    ) as launched:
                        paid.get_by_role(
                            "button", name="Begin authorized management analysis"
                        ).click()
                    assert launched.value.ok, launched.value.text()
                    expect(center).to_contain_text(
                        "Simulated provider fixture — not live reasoning", timeout=30000
                    )
                    expect(
                        center.get_by_role("heading", name="Coordinate evidence-backed follow-up")
                    ).to_be_visible(timeout=45000)
                    center.get_by_text("Source references and limitations", exact=True).click()
                    expect(center.locator('a[href*="/evidence/"]')).to_have_count(1)
                    assert (
                        page.request.get(
                            center.locator('a[href*="/evidence/"]').get_attribute("href")
                        )
                        .body()
                        .startswith(b"%PDF-")
                    )
                    center.get_by_text("Actual model and tool traces", exact=True).click()
                    center.get_by_role("button", name="Retrieve retained trace", exact=True).click()
                    expect(center.locator("pre")).to_contain_text("tool.requested")
                    capture("05-simulated-sdk-insights.png")
                    center.get_by_role(
                        "button", name="Accept & Create corrective action", exact=True
                    ).click()
                    dialog = page.get_by_role("dialog", name="Create corrective action", exact=True)
                    dialog.get_by_label("Rationale", exact=True).fill(
                        "Human accepts the qualified simulated test recommendation for internal investigation."
                    )
                    dialog.get_by_role("checkbox").check()
                    dialog.get_by_role("button", name="Save corrective action", exact=True).click()
                    expect(dialog).not_to_be_visible(timeout=30000)
                    page.reload(wait_until="networkidle")
                    page.get_by_role(
                        "button", name="Sarah — Management Command Center", exact=True
                    ).click()
                    center.get_by_role("button", name="Corrective Actions", exact=True).click()
                    expect(center).to_contain_text("Assign internal evidence review")
                    page.set_viewport_size({"width": 390, "height": 844})
                    center.get_by_role("button", name="Overview", exact=True).click()
                    expect(page.get_by_test_id("management-total")).to_have_text("102")
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Mobile overview overflow"
                    capture("06-mobile-overview.png")
                    center.get_by_role("button", name="Escalations", exact=True).click()
                    expect(center.locator("tbody tr")).to_have_count(15)
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Mobile queue overflow"
                    capture("07-mobile-management-queue.png")
                    center.get_by_role("button", name="Management Intelligence", exact=True).click()
                    expect(
                        center.get_by_role("heading", name="Coordinate evidence-backed follow-up")
                    ).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Mobile insight overflow"
                    capture("08-mobile-recorded-insight.png")
                    assert (
                        len([url for url in posts if url.endswith("/management/analyses")]) == 1
                    ), "Navigation or replay started another analysis"
                    assert not errors, errors
                finally:
                    browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    print(
        "PASS: actual Maya → Sarah shared PDF handoff; chart drill-downs, Finance boundaries, corrective action persistence, consent, simulated SDK insights/replay, actual citations/traces and responsive layouts. No paid provider calls."
    )


if __name__ == "__main__":
    main()
