"""Interactive lifecycle, exact current partition and PDF drill-down; no provider calls."""

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
                "8135",
                "--document-workspace",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if ready(8135):
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
                        base_url="http://127.0.0.1:8135",
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
                    graph = page.get_by_role(
                        "region", name="Work Lifecycle & Accountability", exact=True
                    )
                    expect(graph).to_be_visible()
                    expect(
                        page.get_by_role("region", name="Operational Activity", exact=True)
                    ).not_to_be_visible()
                    model = page.request.get(
                        f"/api/document-workspace/sessions/{sid}/lifecycle"
                    ).json()
                    before = page.request.get(
                        f"/api/document-workspace/sessions/{sid}/events"
                    ).json()
                    post_count = len(posts)
                    capture("04-lifecycle-overview.png")

                    def inspect(node, count):
                        button = graph.locator(f'[data-node="{node}"]')
                        expect(button).to_contain_text(str(count))
                        button.focus()
                        button.press("Enter")
                        d = page.get_by_role(
                            "dialog", name="Lifecycle evidence drill-down", exact=True
                        )
                        expect(d).to_be_visible()
                        expect(d).to_contain_text(f"{count} distinct work items")
                        return d

                    d = inspect("created", 102)
                    expect(
                        d.get_by_role("navigation", name="Lifecycle drill-down pagination")
                    ).to_contain_text("Page 1 of 7")
                    d.get_by_role("button", name="Next cases", exact=True).click()
                    expect(d.get_by_role("navigation")).to_contain_text("Page 2 of 7")
                    d.get_by_role("searchbox").fill(model["items"][0]["id"])
                    expect(d.locator("article")).to_have_count(1)
                    d.get_by_role("button", name="Close lifecycle details", exact=True).click()
                    d = inspect("prepared", 73)
                    capture("05-prepared-drilldown.png")
                    d.get_by_text("Supporting source documents", exact=False).first.click()
                    link = d.get_by_role("link", name="Open original PDF", exact=False).first
                    expect(link).to_be_visible()
                    pdf = page.request.get(link.get_attribute("href"))
                    assert pdf.ok and pdf.body().startswith(b"%PDF-")
                    d.get_by_role(
                        "button", name="Open original work item", exact=True
                    ).first.click()
                    expect(
                        page.get_by_role("heading", name="Maya’s recorded review", exact=True)
                    ).to_be_visible()
                    page.get_by_role("button", name="Close work item", exact=True).click()
                    d = inspect("individual", 1)
                    d.get_by_text("Automated result & Maya review provenance", exact=True).click()
                    expect(d).to_contain_text('"attestation": "individual"')
                    capture("06-individual-accountability.png")
                    d.press("Escape")
                    d = inspect("bulk", 72)
                    d.get_by_text(
                        "Automated result & Maya review provenance", exact=True
                    ).first.click()
                    expect(d).to_contain_text("bulk_attested")
                    d.press("Escape")
                    d = inspect("handoff", 29)
                    d.get_by_text(
                        "Actual case activity & Sarah escalation history", exact=True
                    ).first.click()
                    expect(d).to_contain_text("management handoff received")
                    capture("07-management-handoff.png")
                    d.press("Escape")
                    graph.locator('[data-node="documents"]').click()
                    expect(d).to_contain_text("149 source documents")
                    expect(d.locator("article")).to_have_count(15)
                    d.get_by_role("searchbox").fill(model["documents"][0]["id"])
                    expect(d.locator("article")).to_have_count(1)
                    d.get_by_text("Linked work items", exact=False).first.click()
                    expect(
                        d.get_by_role("button", name="Open work item", exact=False).first
                    ).to_be_visible()
                    d.press("Escape")
                    graph.get_by_text("Inspect recorded transitions", exact=False).click()
                    graph.get_by_role(
                        "button",
                        name="Maya review queue entered → Individually approved · 1 distinct work items",
                        exact=True,
                    ).click()
                    expect(d).to_contain_text("1 distinct work items")
                    d.get_by_text(
                        "Selected stage or transition audit references", exact=True
                    ).click()
                    expected_edge = next(
                        e for e in model["edges"] if e["id"] == "queue--individual"
                    )
                    expect(d).to_contain_text(expected_edge["item_ids"][0])
                    d.press("Escape")
                    graph.get_by_role("button", name="Current State", exact=True).click()
                    expect(graph).to_contain_text("102 of 102 work items accounted for")
                    state_ids = [i for n in model["current_state"] for i in n["item_ids"]]
                    assert len(state_ids) == 102 and len(set(state_ids)) == 102
                    expect(graph.locator('[data-node="state-closed"]')).to_contain_text("73")
                    capture("08-current-state.png")
                    graph.get_by_role("button", name="Lifecycle Flow", exact=True).click()
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(graph.locator('[data-node="prepared"]')).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Mobile lifecycle overflow"
                    capture("09-mobile-lifecycle.png")
                    page.emulate_media(color_scheme="dark")
                    expect(graph).to_have_css("background-color", "rgb(22, 39, 44)")
                    capture("10-dark-lifecycle.png")
                    page.set_viewport_size({"width": 1440, "height": 1050})
                    page.get_by_text("Activity Over Time", exact=True).click()
                    timeline = page.get_by_role("region", name="Operational Activity", exact=True)
                    expect(timeline.locator("svg [role=button]")).to_have_count(4)
                    timeline.get_by_label("Activity outcome", exact=True).select_option(
                        "approved_individual"
                    )
                    expect(timeline.locator("svg [role=button]")).to_have_count(1)
                    timeline.locator("svg [role=button]").focus()
                    timeline.locator("svg [role=button]").press("Enter")
                    expect(
                        timeline.get_by_role("region", name="Activity point details", exact=True)
                    ).to_contain_text("Review type: individual")
                    assert (
                        page.request.get(f"/api/document-workspace/sessions/{sid}/events").json()
                        == before
                    )
                    assert len(posts) == post_count, "Graph navigation mutated workflow"
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
        "PASS: 149 PDFs / 102 work / 73 prepared / 1 individual + 72 bulk / 29 handoffs; lifecycle nodes, edges, PDF, exact partition, keyboard, mobile/dark, read-only and retained timeline. No provider calls."
    )


if __name__ == "__main__":
    main()
