"""Real PDF -> Maya queue -> audited routing/restart; never provider requests."""

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
                "8130",
                "--document-workspace",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if ready(8130):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Document workspace fixture server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        base_url="http://127.0.0.1:8130",
                        viewport={"width": 1440, "height": 1050},
                        locale="en-CA",
                    )
                    errors = []
                    paid = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "request",
                        lambda r: (
                            paid.append(r.url)
                            if r.method == "POST"
                            and any(
                                x in r.url
                                for x in ("/billing-reviews", "/enterprise/analyses", "/api/runs")
                            )
                            else None
                        ),
                    )

                    def capture(name):
                        if args.screenshots:
                            args.screenshots.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(args.screenshots / name), full_page=False)

                    def confirm(
                        label,
                        mode,
                        rationale="Browser validation: reviewed linked PDF evidence; administrative workflow only.",
                    ):
                        dialog = page.get_by_role("dialog", name=label, exact=True)
                        expect(dialog).to_be_visible()
                        expect(
                            dialog.get_by_role("button", name="Confirm " + label, exact=True)
                        ).to_be_disabled()
                        dialog.get_by_label("Rationale", exact=True).fill(rationale)
                        check = dialog.get_by_role(
                            "group", name="Evidence reviewed — select at least one source"
                        )
                        if check.count():
                            check.get_by_role("checkbox").first.check()
                        dialog.get_by_role(
                            "checkbox",
                            name="I confirm this is administrative processing only;",
                            exact=False,
                        ).check()
                        with page.expect_response(
                            lambda r: r.request.method == "POST" and r.url.endswith(mode),
                            timeout=60000,
                        ) as response:
                            dialog.get_by_role(
                                "button", name="Confirm " + label, exact=True
                            ).click()
                        assert response.value.ok, response.value.text()
                        return response.value.json()

                    page.goto("http://127.0.0.1:8130", wait_until="networkidle")
                    expect(
                        page.get_by_role("heading", name="Revenue Operations — My Work", exact=True)
                    ).to_be_visible()
                    capture("01-load-source-documents.png")
                    page.get_by_role("button", name="Load Sample Documents", exact=True).click()
                    imported = confirm("Load Sample Documents", "/load")
                    expect(page.get_by_test_id("total")).to_have_text("102")
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("0")
                    expect(page.locator(".mw-session")).to_contain_text("149 source PDFs")
                    first_session = imported["session_id"]
                    capture("02-unprocessed-real-queue.png")
                    # Representative original PDF: use a real table item and server-associated source.
                    page.locator(".mw-item-link").first.click()
                    detail = page.get_by_role("dialog").filter(
                        has=page.get_by_role("heading", name="Supporting evidence")
                    )
                    expect(detail).to_be_visible()
                    source = detail.locator(".mw-source").first
                    if source.get_attribute("open") is None:
                        source.locator("summary").first.click()
                    link = source.get_by_role("link", name="Open original PDF", exact=False)
                    pdf = page.request.get(link.get_attribute("href"))
                    assert pdf.ok and pdf.body().startswith(b"%PDF-")
                    expect(source.locator("dl")).to_be_visible()
                    capture("03-original-evidence-and-recommendation.png")
                    detail.get_by_role("button", name="Close work item", exact=True).click()
                    page.get_by_text("Granular processing controls", exact=True).click()
                    page.get_by_role("button", name="Process Routine Work", exact=True).click()
                    outcome = confirm("Process Routine Work", "/process/routine")
                    assert (
                        outcome["checks_completed"] == 73
                        and outcome["items_requiring_review"] == 29
                    )
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("73")
                    current = page.request.get("/api/document-workspace").json()
                    assert (
                        current["business_counts"]["needs_maya"]
                        + current["business_counts"]["awaiting_others"]
                        == 29
                    )
                    capture("04-routine-processing-outcome.png")
                    page.get_by_role("button", name="Completed", exact=True).click()
                    expect(page.locator(".mw-table-footer")).to_contain_text(
                        "of 73 matching work items"
                    )
                    page.get_by_role("button", name="Awaiting Others", exact=True).click()
                    expect(page.locator(".mw-item-link").first).to_be_visible()
                    page.get_by_role("button", name="All Work", exact=True).click()
                    page.get_by_role("textbox", name="Search work items", exact=True).fill(
                        "contract_conflict"
                    )
                    page.locator(".mw-item-link").first.click()
                    expect(detail).to_contain_text("Financial impact is not determinable")
                    detail.get_by_role("button", name="Escalate to Sarah", exact=True).click()
                    escalation = confirm("Escalate to Sarah", "/escalate")
                    assert (
                        escalation["automatically_closed"] == 0
                        and escalation["escalated_to_sarah"] == 1
                    )
                    expect(detail).to_contain_text("Waiting on: Sarah")
                    capture("05-human-escalation-recorded.png")
                    detail.get_by_role("button", name="Close work item", exact=True).click()
                    assert (
                        page.request.get("/api/document-workspace").json()["business_counts"][
                            "awaiting_sarah"
                        ]
                        == 1
                    )
                    inbox = page.request.get(
                        f"/api/document-workspace/sessions/{first_session}/management-inbox"
                    ).json()
                    assert (
                        len(inbox["items"]) == 1
                        and inbox["items"][0]["item"]["status"] == "Escalated"
                    )
                    page.get_by_role("textbox", name="Search work items", exact=True).fill("")
                    page.get_by_role("button", name="Auto Complete All", exact=True).click()
                    result = confirm("Auto Complete All", "/process/auto_all")
                    assert (
                        result["automatically_closed"] == 0
                        and result["human_queue_remaining"] == 29
                    )
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("73")
                    page.reload(wait_until="networkidle")
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("73")
                    page.get_by_role("button", name="Restart Demo", exact=True).click()
                    fresh = confirm("Restart Demo", "/restart")
                    assert fresh["session_id"] != first_session
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("0")
                    page.reload(wait_until="networkidle")
                    active = page.request.get("/api/document-workspace").json()
                    assert (
                        active["session_id"] == fresh["session_id"]
                        and active["metrics"]["automatically_completed"] == 0
                    )
                    retained = page.request.get(
                        f"/api/document-workspace/sessions/{first_session}"
                    ).json()
                    assert (
                        retained["metrics"]["automatically_completed"] == 73
                        and retained["read_only"]
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(
                        page.get_by_role("button", name="Process All Work", exact=True)
                    ).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Page overflow"
                    capture("06-mobile-fresh-session.png")
                    page.locator(".mw-item-link").first.click()
                    expect(detail).to_be_visible()
                    assert detail.evaluate(
                        "(el)=>el.scrollWidth<=el.clientWidth"
                    ), "Detail overflow"
                    page.keyboard.press("Escape")
                    expect(detail).not_to_be_visible()
                    page.get_by_role(
                        "link", name="Advanced / Legacy workspace", exact=False
                    ).click()
                    expect(page.get_by_label("Demo persona", exact=True)).to_be_visible()
                    assert "/legacy" in page.url
                    assert not errors, errors
                    assert not paid, paid
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=20)
    print(
        "PASS: actual 149 PDFs -> 102 persisted work items -> 73 revalidated checks; evidence, human escalation/inbox, bulk dispositions, retained restart, refresh/mobile and legacy. Zero provider requests."
    )


if __name__ == "__main__":
    main()
