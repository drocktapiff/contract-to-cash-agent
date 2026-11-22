"""Mandatory attributed reviews and real-event graph, desktop/mobile/dark; no provider calls."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from playwright.sync_api import sync_playwright, expect
from scripts.smoke_web import ready
from scripts.review_browser import review_prepared


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
                "8134",
                "--document-workspace",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if ready(8134):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Human review browser server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        base_url="http://127.0.0.1:8134",
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
                        d = page.get_by_role("dialog", name=label, exact=True)
                        d.get_by_label("Rationale", exact=True).fill(
                            "Simulated browser reviewer confirms this administrative workflow only."
                        )
                        d.get_by_role("checkbox").check()
                        with page.expect_response(
                            lambda r: r.request.method == "POST" and r.url.endswith(suffix),
                            timeout=90000,
                        ) as response:
                            d.get_by_role("button", name="Confirm " + label, exact=True).click()
                        assert response.value.ok, response.value.text()
                        return response.value.json()

                    page.goto("/", wait_until="networkidle")
                    page.get_by_role("button", name="Load Sample Documents", exact=True).click()
                    sid = confirm("Load Sample Documents", "/load")["session_id"]
                    page.get_by_role("button", name="Select All Matching", exact=True).click()
                    page.get_by_role("button", name="AI Powered Close", exact=True).click()
                    prepared = confirm("AI Powered Close", "/selected/close")
                    assert (
                        prepared["prepared_for_review"] == 73
                        and prepared["automatically_closed"] == 0
                    )
                    expect(page.get_by_test_id("awaiting_review")).to_have_text("73")
                    expect(page.get_by_test_id("reviewed_closed")).to_have_text("0")
                    capture("01-prepared-awaiting-human-review.png")
                    page.get_by_role("button", name="Awaiting My Review", exact=True).click()
                    page.locator(".mw-item-link").first.click()
                    detail = page.get_by_role("dialog").filter(
                        has=page.get_by_role(
                            "heading",
                            name="Automated finding · awaiting human verification",
                            exact=True,
                        )
                    )
                    detail.get_by_role("button", name="Review Automated Result", exact=True).click()
                    d = page.get_by_role("dialog", name="Review Automated Result", exact=True)
                    expect(
                        d.get_by_role("button", name="Approve & Close", exact=True)
                    ).to_be_disabled()
                    link = d.get_by_role("link", name="Open review source PDF", exact=False).first
                    expect(link).to_be_visible()
                    pdf = page.request.get(link.get_attribute("href"))
                    assert pdf.ok and pdf.body().startswith(b"%PDF-")
                    capture("02-individual-evidence-review.png")
                    d.get_by_label("Review actor attribution", exact=True).fill(
                        "Maya browser fixture reviewer"
                    )
                    d.get_by_label("Review rationale", exact=True).fill(
                        "Individually inspected the displayed source findings, original PDF and deterministic comparison."
                    )
                    d.get_by_role("checkbox").check()
                    with page.expect_response(
                        lambda r: r.request.method == "POST" and r.url.endswith("/human-reviews"),
                        timeout=90000,
                    ) as decision:
                        d.get_by_role("button", name="Approve & Close", exact=True).click()
                    assert decision.value.ok and decision.value.json()["approved"] == 1
                    d.get_by_role("button", name="Done", exact=True).click()
                    page.get_by_role("button", name="Close work item", exact=True).click()
                    expect(page.get_by_test_id("awaiting_review")).to_have_text("72")
                    review_prepared(page, 72)
                    expect(page.get_by_test_id("reviewed_closed")).to_have_text("73")
                    capture("03-bulk-attested-review.png")
                    page.get_by_role("button", name="Select All Remaining Work", exact=True).click()
                    page.get_by_role("button", name="Escalate to Sarah", exact=True).click()
                    handoff = confirm("Escalate Selected to Sarah", "/selected/escalate")
                    assert handoff["handoffs_created"] == 29
                    page.get_by_role(
                        "button", name="Sarah — Management Command Center", exact=True
                    ).click()
                    page.get_by_text("Activity Over Time", exact=True).click()
                    graph = page.get_by_role("region", name="Operational Activity", exact=True)
                    expect(
                        graph.get_by_role(
                            "button",
                            name="Reviewed & Closed: 73. Inspect supporting work",
                            exact=True,
                        )
                    ).to_be_visible()
                    expect(
                        graph.get_by_role(
                            "button",
                            name="Individually approved reviews: 1. Inspect supporting work",
                            exact=True,
                        )
                    ).to_be_visible()
                    expect(
                        graph.get_by_role(
                            "button",
                            name="Bulk-attested approvals: 72. Inspect supporting work",
                            exact=True,
                        )
                    ).to_be_visible()
                    capture("04-sarah-operational-activity.png")
                    first = graph.locator("svg [role=button]").first
                    first.focus()
                    first.press("Enter")
                    drill = graph.get_by_role("region", name="Activity point details", exact=True)
                    expect(drill).to_contain_text("automated check prepared")
                    expect(drill).to_contain_text("73 distinct work items")
                    capture("05-automation-point-drilldown.png")
                    drill.locator(".oa-cases button").first.click()
                    expect(
                        page.get_by_role("heading", name="Maya’s recorded review", exact=True)
                    ).to_be_visible()
                    page.get_by_role("button", name="Close work item", exact=True).click()
                    graph.get_by_label("Activity outcome", exact=True).select_option(
                        "approved_individual"
                    )
                    expect(graph.locator("svg [role=button]")).to_have_count(1)
                    graph.locator("svg [role=button]").first.focus()
                    graph.locator("svg [role=button]").first.press("Enter")
                    expect(drill).to_contain_text("Review type: individual")
                    expect(drill).to_contain_text("human review approved")
                    capture("06-individual-approval-point.png")
                    graph.get_by_label("Activity outcome", exact=True).select_option(
                        "approved_bulk"
                    )
                    expect(graph.locator("svg [role=button]")).to_have_count(1)
                    graph.locator("svg [role=button]").first.click()
                    expect(drill).to_contain_text("bulk_attested")
                    expect(drill).to_contain_text("72 distinct work items")
                    graph.get_by_label("Activity outcome", exact=True).select_option("escalated")
                    expect(graph.locator("svg [role=button]")).to_have_count(1)
                    graph.locator("svg [role=button]").first.click()
                    expect(drill).to_contain_text("29 distinct work items")
                    expect(drill).to_contain_text("management handoff received")
                    capture("07-management-received-point.png")
                    graph.get_by_label("Activity view", exact=True).select_option("interval")
                    graph.get_by_label("Time grouping", exact=True).select_option("second")
                    graph.get_by_label("Activity outcome", exact=True).select_option("all")
                    graph.get_by_role(
                        "checkbox", name="Ledgerline Automation", exact=False
                    ).uncheck()
                    graph.get_by_role("checkbox", name="Maya", exact=False).uncheck()
                    expect(graph.locator("svg [role=button]")).to_have_count(1)
                    expect(graph.locator("svg [role=button]")).to_have_attribute(
                        "aria-label", __import__("re").compile(r"^Sarah:")
                    )
                    graph.get_by_role("checkbox", name="Ledgerline Automation", exact=False).check()
                    graph.get_by_role("checkbox", name="Maya", exact=False).check()
                    graph.get_by_label("Time grouping", exact=True).select_option("operation")
                    graph.get_by_label("Activity view", exact=True).select_option("cumulative")
                    expect(graph.locator("svg [role=button]")).to_have_count(4)
                    before = page.request.get(
                        f"/api/document-workspace/sessions/{sid}/events"
                    ).json()
                    page.reload(wait_until="networkidle")
                    page.get_by_role(
                        "button", name="Sarah — Management Command Center", exact=True
                    ).click()
                    page.get_by_text("Activity Over Time", exact=True).click()
                    expect(graph.locator("svg [role=button]")).to_have_count(4)
                    assert (
                        page.request.get(f"/api/document-workspace/sessions/{sid}/events").json()
                        == before
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(graph.locator("svg")).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Mobile graph overflow"
                    capture("08-mobile-activity.png")
                    page.emulate_media(color_scheme="dark")
                    expect(graph).to_have_css("background-color", "rgb(22, 39, 44)")
                    capture("09-dark-activity.png")
                    page.emulate_media(color_scheme="light")
                    page.get_by_role("button", name="Maya — Revenue Operations", exact=True).click()
                    page.get_by_role("button", name="Restart Demo", exact=True).click()
                    new = confirm("Restart Demo", "/restart")
                    assert new["session_id"] != sid
                    expect(page.get_by_test_id("awaiting_review")).to_have_text("0")
                    expect(page.get_by_test_id("reviewed_closed")).to_have_text("0")
                    old = page.request.get(
                        f"/api/document-workspace/sessions/{sid}/activity"
                    ).json()
                    assert (
                        old["metrics"]["closed"]["value"] == 73
                        and old["metrics"]["approved_bulk"]["value"] == 72
                    )
                    assert not any(
                        url.endswith("/management/analyses")
                        or "/billing-reviews" in url
                        or url.endswith("/api/runs")
                        for url in posts
                    ), posts
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
        "PASS: actual PDFs -> 73 prepared, not closed -> one individual review -> 72 bulk attestations -> 29 handoffs; real-time activity points, source/decision drill-down, keyboard, filters, replay, mobile/dark and retained restart. No provider calls."
    )


if __name__ == "__main__":
    main()
