"""Presentation-ready performance dashboard and exact shared evidence drawer; no provider calls."""

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
                "8136",
                "--document-workspace",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if ready(8136):
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
                        base_url="http://127.0.0.1:8136",
                        viewport={"width": 1920, "height": 1080},
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
                            if name == "07-mobile-dashboard.png":
                                page.get_by_role(
                                    "region", name="Management performance dashboard", exact=True
                                ).screenshot(path=str(args.screenshots / name))
                            else:
                                page.screenshot(path=str(args.screenshots / name), full_page=False)

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
                    dashboard = page.get_by_role(
                        "region", name="Management performance dashboard", exact=True
                    )
                    expect(dashboard).to_be_visible()
                    page.wait_for_load_state("networkidle")
                    model = page.request.get(
                        f"/api/document-workspace/sessions/{sid}/lifecycle"
                    ).json()
                    before = page.request.get(
                        f"/api/document-workspace/sessions/{sid}/events"
                    ).json()
                    post_count = len(posts)
                    expect(
                        page.get_by_role(
                            "region", name="Work Lifecycle & Accountability", exact=True
                        )
                    ).not_to_be_visible()
                    expect(
                        page.get_by_role("region", name="Operational Activity", exact=True)
                    ).not_to_be_visible()
                    for key, value in (
                        ("identified", "102"),
                        ("reviewed_closed", "73"),
                        ("open", "29"),
                        ("preparation_rate", "71.6%"),
                    ):
                        expect(dashboard.get_by_test_id("mp-kpi-" + key)).to_contain_text(value)
                    capture("01-desktop-light.png")
                    last = dashboard.get_by_test_id("mp-contribution-handoff").bounding_box()
                    assert last and last["y"] + last["height"] <= 1080, last
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Desktop overflow"
                    capture("01-desktop-light.png")
                    page.emulate_media(color_scheme="dark")
                    expect(dashboard.get_by_test_id("mp-kpi-identified")).to_have_css(
                        "background-color", "rgb(24, 42, 48)"
                    )
                    capture("02-desktop-dark.png")
                    page.emulate_media(color_scheme="light")
                    distribution = dashboard.get_by_role(
                        "region", name="Current Work Distribution", exact=True
                    )
                    expect(distribution).to_contain_text("102 of 102 accounted for")
                    state_ids = [
                        i for n in model["performance"]["distribution"] for i in n["item_ids"]
                    ]
                    assert len(state_ids) == 102 and len(set(state_ids)) == 102
                    finance = distribution.get_by_role(
                        "button", name="Inspect Awaiting Finance: 8 cases", exact=True
                    )
                    finance.hover()
                    expect(distribution.get_by_role("tooltip")).to_contain_text(
                        "Authorized Finance team"
                    )
                    expect(distribution.get_by_role("tooltip")).to_contain_text("8")
                    finance.click()
                    d = page.get_by_role("dialog", name="Lifecycle evidence drill-down", exact=True)
                    expect(d).to_contain_text("8 distinct work items")
                    expect(d).to_contain_text("Awaiting Financial Review")
                    capture("03-distribution-evidence.png")

                    def close():
                        d.get_by_role("button", name="Close lifecycle details", exact=True).click()
                        expect(d).not_to_be_visible()

                    close()
                    expect(finance).to_be_focused()
                    for key, total in (
                        ("identified", 102),
                        ("reviewed_closed", 73),
                        ("open", 29),
                        ("preparation_rate", 73),
                    ):
                        dashboard.get_by_test_id("mp-kpi-" + key).click()
                        expect(d).to_contain_text(f"{total} distinct work items")
                        if key == "identified":
                            expect(
                                d.get_by_role("navigation", name="Lifecycle drill-down pagination")
                            ).to_contain_text("Page 1 of 7")
                            d.get_by_role("searchbox").fill(model["items"][0]["id"])
                            expect(d.locator("article")).to_have_count(1)
                        close()
                    for key, total in (("prepared", 73), ("human_reviews", 73), ("handoff", 29)):
                        bar = dashboard.get_by_test_id("mp-contribution-" + key)
                        bar.focus()
                        bar.press("Enter")
                        expect(d).to_contain_text(f"{total} distinct work items")
                        d.evaluate("el => el.dispatchEvent(new Event('close'))")
                        expect(d).to_be_visible()
                        if key == "prepared":
                            d.get_by_text("Supporting source documents", exact=False).first.click()
                            link = d.get_by_role(
                                "link", name="Open original PDF", exact=False
                            ).first
                            pdf = page.request.get(link.get_attribute("href"))
                            assert pdf.ok and pdf.body().startswith(b"%PDF-")
                            d.get_by_role(
                                "button", name="Open original work item", exact=True
                            ).first.click()
                            expect(
                                page.get_by_role(
                                    "heading", name="Maya’s recorded review", exact=True
                                )
                            ).to_be_visible()
                            page.get_by_role("button", name="Close work item", exact=True).click()
                        else:
                            summary = (
                                "Automated result & Maya review provenance"
                                if key == "human_reviews"
                                else "Actual case activity & Sarah escalation history"
                            )
                            d.get_by_text(summary, exact=True).first.click()
                            expect(d).to_contain_text(
                                "human_review"
                                if key == "human_reviews"
                                else "management handoff received"
                            )
                            capture(
                                "04-maya-review-contribution.png"
                                if key == "human_reviews"
                                else "05-sarah-handoff-contribution.png"
                            )
                            close()
                            expect(bar).to_be_focused()
                    dashboard.get_by_role(
                        "button", name="Individually reviewed 1", exact=True
                    ).click()
                    expect(d).to_contain_text("1 distinct work items")
                    d.get_by_text("Automated result & Maya review provenance", exact=True).click()
                    expect(d).to_contain_text('"attestation": "individual"')
                    close()
                    dashboard.get_by_role("button", name="Bulk-attested 72", exact=True).click()
                    expect(d).to_contain_text("72 distinct work items")
                    d.get_by_text(
                        "Automated result & Maya review provenance", exact=True
                    ).first.click()
                    expect(d).to_contain_text("bulk_attested")
                    close()
                    page.set_viewport_size({"width": 1366, "height": 900})
                    expect(dashboard).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Laptop overflow"
                    capture("06-laptop.png")
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(dashboard).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Mobile overflow"
                    dashboard.scroll_into_view_if_needed()
                    capture("07-mobile-dashboard.png")
                    page.set_viewport_size({"width": 1920, "height": 1080})
                    page.get_by_text("Detailed Lifecycle & Accountability", exact=True).click()
                    graph = page.get_by_role(
                        "region", name="Work Lifecycle & Accountability", exact=True
                    )
                    expect(graph.locator('[data-node="prepared"]')).to_contain_text("73")
                    graph.get_by_role("button", name="Current State", exact=True).click()
                    expect(graph).to_contain_text("102 of 102 work items accounted for")
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
                    assert len(posts) == post_count, "Analytics navigation mutated workflow"
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
        "PASS: real PDF management dashboard, 4 KPIs, exact current partition, contribution/attestation sets, shared PDF drawer, focus/late-close, desktop/laptop/mobile/dark, retained analytics and zero mutations or paid calls."
    )


if __name__ == "__main__":
    main()
