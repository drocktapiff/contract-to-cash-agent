"""Actual three-case walkthrough, safe execution/replay and bulk outcome; no provider calls."""

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
                "8131",
                "--document-workspace",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(150):
                if ready(8131):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Walkthrough test server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        base_url="http://127.0.0.1:8131",
                        viewport={"width": 1440, "height": 1050},
                        locale="en-CA", timezone_id="America/Toronto",
                    )
                    errors = []
                    writes = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "request", lambda r: writes.append(r.url) if r.method == "POST" else None
                    )

                    def capture(name):
                        if args.screenshots:
                            args.screenshots.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(args.screenshots / name))

                    def confirm(label, suffix):
                        dialog = page.get_by_role("dialog", name=label, exact=True)
                        dialog.get_by_label("Rationale", exact=True).fill(
                            "Browser acceptance: inspect source evidence and apply only permitted administrative workflow."
                        )
                        group = dialog.get_by_role(
                            "group", name="Evidence reviewed — select at least one source"
                        )
                        if group.count():
                            group.get_by_role("checkbox").first.check()
                        dialog.get_by_role(
                            "checkbox",
                            name="I confirm this is administrative processing only;",
                            exact=False,
                        ).check()
                        with page.expect_response(
                            lambda r: r.request.method == "POST" and r.url.endswith(suffix),
                            timeout=60000,
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
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("0")
                    capture("01-business-home.png")
                    page.get_by_role("button", name="Show Me the Work", exact=True).click()
                    walk = page.get_by_role("dialog", name="Show Me the Work", exact=True)
                    expect(
                        walk.get_by_role("heading", name="Before Ledgerline", exact=True)
                    ).to_be_visible()
                    capture("02-traditional-work.png")
                    firstlink = walk.get_by_role("link").first
                    original = page.request.get(firstlink.get_attribute("href"))
                    assert original.ok and original.body().startswith(b"%PDF-")
                    walk.get_by_role("button", name="Next manual task", exact=True).click()
                    expect(walk.locator(".mw-step-count")).to_contain_text("Task 2")
                    walk.get_by_role("button", name="Understand the documents", exact=False).click()
                    expect(walk.locator(".mw-document-cards")).to_contain_text(
                        "Subscription amount"
                    )
                    expect(walk.locator(".mw-document-cards")).to_contain_text("Page ")
                    capture("03-extracted-business-evidence.png")
                    walk.get_by_role("button", name="Process the work", exact=False).click()
                    walk.get_by_role("button", name="Process This Work Item", exact=True).click()
                    one = confirm("Process This Work Item", "/auto")
                    assert one["checks_completed"] == 1
                    expect(walk).to_contain_text("Actual recorded workflow")
                    capture("04-genuine-processing-evidence.png")
                    walk.get_by_role("button", name="Business outcome", exact=False).click()
                    expect(walk).to_contain_text("Verified administrative check completed")
                    capture("05-verified-administrative-outcome.png")
                    # Reopen the recorded case: no mutation may be triggered by replay or manual clicks.
                    walk.get_by_role("button", name="Close walkthrough", exact=True).click()
                    before = len(writes)
                    event_count = page.request.get("/api/document-workspace").json()["telemetry"][
                        "event_count"
                    ]
                    # Select the same specific item through the detail replay entry.
                    page.get_by_role("button", name="Completed", exact=True).click()
                    page.locator(".mw-item-link").first.click()
                    detail = page.get_by_role("dialog").filter(
                        has=page.get_by_role("heading", name="Supporting evidence", exact=True)
                    )
                    detail.get_by_role("button", name="Show Me the Work", exact=True).click()
                    expect(walk).to_contain_text("Recorded replay — historical processing")
                    walk.get_by_role("button", name="Process the work", exact=False).click()
                    expect(
                        walk.get_by_role("button", name="Process This Work Item", exact=True)
                    ).to_have_count(0)
                    assert len(writes) == before
                    assert (
                        page.request.get("/api/document-workspace").json()["telemetry"][
                            "event_count"
                        ]
                        == event_count
                    )
                    for scenario, target in [
                        ("discrepancy", "Awaiting Financial Review"),
                        ("ambiguity", "Escalated"),
                    ]:
                        walk.get_by_label("Choose a real case", exact=True).select_option(scenario)
                        walk.get_by_role("button", name="Process the work", exact=False).click()
                        button = walk.get_by_role(
                            "button", name="Process This Work Item", exact=True
                        )
                        expect(button).to_be_enabled()
                        button.click()
                        routed = confirm("Process This Work Item", "/auto")
                        assert routed["checks_completed"] == 0
                        expect(walk).to_contain_text("Actual recorded workflow")
                        walk.get_by_role("button", name="Business outcome", exact=False).click()
                        expect(walk).to_contain_text(target)
                        capture("06-" + scenario + "-human-boundary.png")
                    walk.get_by_role(
                        "button", name="Process All Remaining Work", exact=True
                    ).click()
                    remaining = confirm("Process All Remaining Work", "/process/auto_all")
                    assert (
                        remaining["total_examined"] == 102 and remaining["checks_completed"] == 72
                    )
                    expect(
                        page.get_by_role(
                            "heading", name="Here's What Ledgerline Accomplished", exact=True
                        )
                    ).to_be_visible()
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("73")
                    capture("07-real-queue-outcomes.png")
                    summary = page.get_by_role("region", name="Revenue operations work queue")
                    page.get_by_role("button", name="Awaiting Finance", exact=False).click()
                    expect(page.locator(".mw-table-scroll")).to_contain_text(
                        "Awaiting Financial Review"
                    )
                    # Session restart and browser refresh preserve fresh active state and retained evidence.
                    page.get_by_role("button", name="Restart Demo", exact=True).click()
                    fresh = confirm("Restart Demo", "/restart")
                    assert fresh["session_id"] != sid
                    page.reload(wait_until="networkidle")
                    expect(page.get_by_test_id("automatically_completed")).to_have_text("0")
                    assert (
                        page.request.get(f"/api/document-workspace/sessions/{sid}").json()[
                            "metrics"
                        ]["automatically_completed"]
                        == 73
                    )
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.get_by_role("button", name="Show Me the Work", exact=True).click()
                    expect(walk).to_be_visible()
                    assert walk.evaluate(
                        "(el)=>el.scrollWidth<=el.clientWidth"
                    ), "Walkthrough overflow"
                    capture("08-mobile-walkthrough.png")
                    page.keyboard.press("Escape")
                    expect(walk).not_to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth<=innerWidth"
                    ), "Page overflow"
                    assert not errors, errors
                    assert not any(
                        "/billing-reviews" in u
                        or "/enterprise/analyses" in u
                        or u.endswith("/api/runs")
                        for u in writes
                    ), writes
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=20)
    print(
        "PASS: real manual/source walkthrough, three safe scenarios, actual processing proof, mutation-free replay, remaining queue/results, restart, desktop/mobile and zero paid calls."
    )


if __name__ == "__main__":
    main()
