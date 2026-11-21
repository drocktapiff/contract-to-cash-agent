"""Actual checkbox selection -> routine validation -> independent Sarah oversight."""

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
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests_web.smoke_server",
                "--port",
                "8132",
                "--document-workspace",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if ready(8132):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Bulk fixture server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        base_url="http://127.0.0.1:8132",
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
                            page.screenshot(path=str(args.screenshots / name))

                    def confirm(label, suffix):
                        dialog = page.get_by_role("dialog", name=label, exact=True)
                        expect(dialog).to_be_visible()
                        expect(
                            dialog.get_by_role("button", name="Confirm " + label, exact=True)
                        ).to_be_disabled()
                        dialog.get_by_label("Rationale", exact=True).fill(
                            "Browser acceptance: source-backed administrative processing or management oversight, no financial authorization."
                        )
                        dialog.get_by_role(
                            "checkbox",
                            name="I confirm this is administrative processing only;",
                            exact=False,
                        ).check()
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
                    header = page.get_by_role("checkbox", name="Select All", exact=True)
                    header.check()
                    toolbar = page.get_by_role("region", name="Selected work actions", exact=True)
                    expect(toolbar).to_contain_text("25 Work Items Selected")
                    page.get_by_role("button", name="Next Page", exact=True).click()
                    boxes = page.locator("tbody input[type=checkbox]")
                    boxes.first.check()
                    expect(toolbar).to_contain_text("26 Work Items Selected")
                    page.get_by_role("button", name="Previous Page", exact=True).click()
                    expect(header).to_be_checked()
                    page.locator("tbody input[type=checkbox]").first.uncheck()
                    expect(toolbar).to_contain_text("25 Work Items Selected")
                    assert header.evaluate("(e)=>e.indeterminate")
                    toolbar.get_by_role("button", name="Clear Selection", exact=True).click()
                    expect(toolbar).to_have_count(0)
                    page.get_by_role("button", name="Select All Matching", exact=True).click()
                    expect(toolbar).to_contain_text("102 Work Items Selected")
                    expect(toolbar).to_contain_text("No live AI model used")
                    page.evaluate("window.scrollTo(0,document.querySelector('.mw-table-scroll').getBoundingClientRect().top+scrollY+300)")
                    expect(toolbar).to_be_in_viewport()
                    assert abs(toolbar.bounding_box()['y'])<3,'Selected toolbar did not stick to viewport'
                    capture("01-select-all-real-work.png")
                    toolbar.get_by_role("button", name="AI Powered Close", exact=True).click()
                    closed = confirm("AI Powered Close", "/selected/close")
                    assert (
                        closed["checks_completed"] == 73
                        and closed["requires_review"] == 29
                        and closed["financial_actions_executed"] == 0
                    )
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("73")
                    capture("02-actual-close-outcome.png")
                    page.reload(wait_until="networkidle")
                    outcome = page.get_by_role("region", name="Selected work outcome", exact=True)
                    expect(outcome).to_contain_text("73")
                    page.get_by_role("button", name="Select All Remaining Work", exact=True).click()
                    expect(toolbar).to_contain_text("29 Work Items Selected")
                    capture("03-select-remaining-exceptions.png")
                    toolbar.get_by_role("button", name="Escalate to Sarah", exact=True).click()
                    escalated = confirm("Escalate Selected to Sarah", "/selected/escalate")
                    assert (
                        escalated["handoffs_created"] == 29
                        and escalated["failed"] == 0
                        and escalated["blocked"] == 0
                    )
                    assert escalated["awaiting_finance"] > 0 and escalated["awaiting_evidence"] > 0
                    capture("04-persisted-management-handoffs.png")
                    page.get_by_role("button", name="Sarah — Management Command Center", exact=True).click()
                    inbox = page.get_by_role("region", name="Sarah’s management inbox", exact=True)
                    expect(inbox).to_contain_text("29 oversight cases")
                    expect(inbox).to_contain_text("Finance")
                    expect(inbox).to_contain_text("Awaiting Evidence")
                    expect(inbox).to_contain_text(
                        "No budget, credit, invoice, export or contract authorization"
                    )
                    capture("05-sarah-independent-oversight.png")
                    actual = page.request.get(
                        f"/api/document-workspace/sessions/{sid}/management-inbox"
                    ).json()
                    assert len(actual["items"]) == 29
                    assert all(
                        not d["item"]["oversight"]["financial_authority_transferred"]
                        for d in actual["items"]
                    )
                    finance = next(
                        d
                        for d in actual["items"]
                        if d["item"]["status"] == "Awaiting Financial Review"
                    )
                    assert finance["item"]["current_decision_owner"] == "Finance"
                    pdf = page.request.get(
                        f'/api/document-workspace/sessions/{sid}/evidence/{finance["documents"][0]["file_hash"]}'
                    )
                    assert pdf.ok and pdf.body().startswith(b"%PDF-")
                    page.get_by_role("button", name="Maya — Revenue Operations", exact=True).click()
                    page.get_by_role("button", name="Escalated to Sarah", exact=True).click()
                    expect(page.locator(".mw-table-footer")).to_contain_text(
                        "of 29 matching work items"
                    )
                    page.get_by_role("button", name="Select All Matching", exact=True).click()
                    toolbar.get_by_role("button", name="Escalate to Sarah", exact=True).click()
                    reused = confirm("Escalate Selected to Sarah", "/selected/escalate")
                    assert reused["handoffs_created"] == 0 and reused["handoffs_reused"] == 29
                    page.reload(wait_until="networkidle")
                    assert (
                        page.request.get("/api/document-workspace").json()["last_bulk_operation"][
                            "result"
                        ]["handoffs_reused"]
                        == 29
                    )
                    # Session-bound selection is cleared and old results are not reused by restart.
                    page.get_by_role("button", name="Select All Remaining Work", exact=True).click()
                    expect(toolbar).to_contain_text("29 Work Items Selected")
                    page.get_by_role("button", name="Restart Demo", exact=True).click()
                    fresh = confirm("Restart Demo", "/restart")
                    assert fresh["session_id"] != sid
                    expect(toolbar).to_have_count(0)
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("0")
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.get_by_role("button", name="Select All Matching", exact=True).click()
                    expect(toolbar).to_contain_text("102 Work Items Selected")
                    assert toolbar.evaluate(
                        "(e)=>e.scrollWidth<=e.clientWidth"
                    ), "Bulk toolbar overflow"
                    toolbar.scroll_into_view_if_needed()
                    capture("06-mobile-selection-toolbar.png")
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Page overflow"
                    assert not errors, errors
                    assert not any(
                        "/billing-reviews" in u
                        or "/enterprise/analyses" in u
                        or u.endswith("/api/runs")
                        for u in posts
                    ), posts
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=20)
    print(
        "PASS: selection/page/matching scope, 73 genuine closures, 29 oversight handoffs with independent Finance/evidence authority, reused handoffs, refresh/restart, PDF access, desktop/mobile and zero paid requests."
    )


if __name__ == "__main__":
    main()
