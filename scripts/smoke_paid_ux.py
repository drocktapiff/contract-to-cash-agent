"""Evidence drawer/accessibility and real server admission UX; zero provider calls."""

import argparse
import json
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
            [sys.executable, "-m", "tests_web.smoke_server", "--port", "8129", "--paid-ux-limit"],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(100):
                if ready(8129):
                    break
                if process.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                time.sleep(0.1)
            else:
                raise RuntimeError("Paid UX fixture server did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1000},
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

                    def capture(name):
                        if args.screenshots:
                            args.screenshots.mkdir(parents=True, exist_ok=True)
                            page.screenshot(path=str(args.screenshots / name), full_page=not bool(page.locator("dialog[open]").count()))

                    page.goto("http://127.0.0.1:8129", wait_until="networkidle")
                    session = page.request.get("http://127.0.0.1:8129/api/session").json()
                    headers = {"x-csrf-token": session["csrf_token"]}
                    assert page.request.put(
                        "http://127.0.0.1:8129/api/admin/pricing",
                        headers=headers,
                        data=dict(
                            input_price="2",
                            output_price="10",
                            cached_input_price=".1",
                            checked_current_official_rates=True,
                        ),
                    ).ok
                    page.reload(wait_until="networkidle")
                    page.get_by_role(
                        "region", name="Paid launch availability", exact=True
                    ).get_by_role("button", name="Refresh availability", exact=True).click()
                    expect(page.get_by_role("button", name="Start Billing Review")).to_be_disabled()
                    maya = page.get_by_role("region", name="Maya Demo Controls")
                    expect(
                        maya.get_by_role("button", name="Complete Maya Demo", exact=True)
                    ).to_be_enabled()
                    capture("01-maya-paid-blocked-free-preparation.png")
                    maya.get_by_role("button", name="Complete Maya Demo", exact=True).click()
                    page.get_by_role(
                        "dialog", name="Confirm Maya simulated completion"
                    ).get_by_role(
                        "button",
                        name="Confirm Maya simulated completion — no API usage",
                        exact=True,
                    ).click()
                    expect(maya).to_contain_text("Maya stage prepared")
                    maya.get_by_role("button", name="Continue to Sarah", exact=True).click()
                    button = page.locator(".shared-insight").get_by_role(
                        "button", name="View Supporting Evidence", exact=True
                    )
                    # Deliberately retain retrieval until the visible loading dialog has opened.
                    held = []
                    page.route("**/findings/*/evidence", lambda route: held.append(route))
                    button.click()
                    drawer = page.get_by_role(
                        "dialog",
                        name="Supporting Evidence — Shared Pricing Discrepancy",
                        exact=True,
                    )
                    expect(drawer).to_be_visible()
                    expect(drawer.get_by_role("status")).to_have_text(
                        "Loading saved supporting evidence…"
                    )
                    expect(
                        drawer.get_by_role("button", name="Close evidence", exact=True)
                    ).to_be_focused()
                    assert page.evaluate(
                        "document.querySelector('dialog.evidence-drawer').matches(':modal')"
                    )
                    while not held:
                        page.wait_for_timeout(10)
                    for route in held:
                        route.continue_()
                    page.unroute("**/findings/*/evidence")
                    expect(drawer.locator(".source-text").first).to_be_visible()
                    select = drawer.get_by_label("Selected customer account", exact=True)
                    expect(select.locator("option")).to_have_text(["C008", "C009", "C010"])
                    for customer in ("C008", "C009", "C010"):
                        select.select_option(customer)
                        expect(drawer).to_contain_text("CTR-" + customer)
                        expect(drawer).to_contain_text("INV-" + customer + "-2026-04")
                        expect(drawer.locator(".impact-grid")).to_contain_text("$10,000.00")
                        expect(drawer.locator(".impact-grid")).to_contain_text("$9,000.00")
                        expect(drawer.locator(".impact-grid")).to_contain_text("$1,000.00")
                        expect(drawer.locator(".source-text").first).to_contain_text(customer)
                    capture("02-sarah-desktop-evidence-drawer.png")
                    page.get_by_label("Demo persona", exact=True).evaluate("(el)=>el.focus()")
                    assert page.evaluate(
                        "!!document.activeElement.closest('dialog.evidence-drawer')"
                    ), "Background focus escaped modal"
                    for _ in range(14):
                        page.keyboard.press("Tab")
                        assert page.evaluate(
                            "!!document.activeElement.closest('dialog.evidence-drawer')"
                        ), "Tab escaped modal"
                    page.keyboard.press("Escape")
                    expect(drawer).not_to_be_visible()
                    expect(button).to_be_focused()
                    # Retrieval errors remain in the visible dialog, with an explicit retry.
                    page.route(
                        "**/findings/*/evidence",
                        lambda route: route.fulfill(
                            status=503,
                            content_type="application/json",
                            body=json.dumps(
                                {"detail": "Test fixture: evidence retrieval unavailable"}
                            ),
                        ),
                    )
                    button.click()
                    expect(drawer.get_by_role("alert")).to_contain_text(
                        "evidence retrieval unavailable"
                    )
                    page.unroute("**/findings/*/evidence")
                    drawer.get_by_role(
                        "button", name="Retry evidence retrieval", exact=True
                    ).click()
                    expect(drawer.locator(".source-text").first).to_be_visible()
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(drawer).to_be_visible()
                    capture("03-sarah-mobile-evidence.png")
                    assert drawer.evaluate(
                        "(el)=>el.scrollWidth<=el.clientWidth"
                    ), "Drawer horizontal overflow"
                    drawer.get_by_role("button", name="Close evidence", exact=True).click()
                    expect(button).to_be_focused()
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    sarah = page.get_by_role("region", name="Sarah Demo Controls")
                    expect(
                        sarah.get_by_role("button", name="Complete Sarah Demo", exact=True)
                    ).to_be_enabled()
                    page.locator(".analysis-secondary > summary").click()
                    status = page.get_by_role("region", name="Analysis availability", exact=True)
                    expect(status).to_contain_text("Hourly launch limit reached")
                    expect(
                        page.get_by_role(
                            "button", name="Analyze Department Performance", exact=True
                        )
                    ).to_be_disabled()
                    sarah.get_by_role("button", name="Complete Sarah Demo", exact=True).click()
                    page.get_by_role(
                        "dialog", name="Confirm Sarah simulated completion"
                    ).get_by_role(
                        "button",
                        name="Confirm Sarah simulated completion — no API usage",
                        exact=True,
                    ).click()
                    expect(sarah).to_contain_text("Sarah stage prepared")
                    sarah.get_by_role("button", name="Continue to Robert", exact=True).click()
                    status = page.get_by_role("region", name="Analysis availability", exact=True)
                    expect(status).to_contain_text("Hourly launch limit reached")
                    generate = page.get_by_role(
                        "button", name="Generate Executive Decision Brief", exact=True
                    )
                    expect(generate).to_be_disabled()
                    actual = page.request.get(
                        "http://127.0.0.1:8129/api/paid-launch-availability"
                    ).json()
                    expect(status.locator("time")).to_have_attribute(
                        "datetime", actual["next_eligible_at"]
                    )
                    expect(
                        page.get_by_role("dialog", name="Authorize enterprise analysis")
                    ).not_to_be_visible()
                    capture("04-robert-server-authoritative-rate-limit.png")
                    assert not paid, paid
                    # Simulate stale informational availability; POST still meets the real server limit.
                    stale = dict(actual, available=True, reasons=[], next_eligible_at=None)
                    page.route(
                        "**/api/paid-launch-availability", lambda route: route.fulfill(json=stale)
                    )
                    status.get_by_role("button", name="Refresh availability", exact=True).click()
                    expect(generate).to_be_enabled()
                    generate.click()
                    consent = page.get_by_role("dialog", name="Authorize enterprise analysis")
                    expect(
                        consent.get_by_role("button", name="Begin authorized analysis", exact=True)
                    ).to_be_disabled()
                    consent.get_by_label("I authorize this paid analysis.", exact=True).check()

                    def submit(route):
                        page.unroute("**/api/paid-launch-availability")
                        route.continue_()

                    page.route("**/api/enterprise/analyses", submit)
                    with page.expect_response(
                        lambda response: response.url.endswith("/enterprise/analyses")
                        and response.request.method == "POST"
                    ) as rejection:
                        consent.get_by_role(
                            "button", name="Begin authorized analysis", exact=True
                        ).click()
                    response = rejection.value
                    assert response.status == 429, response.text()
                    assert response.json()["paid_run_created"] is False
                    assert response.json()["availability"]["available"] is False
                    expect(consent).not_to_be_visible()
                    expect(generate).to_be_disabled()
                    expect(page.get_by_role("alert").first).to_contain_text(
                        "Local launch limit reached"
                    )
                    assert (
                        len(
                            page.request.get("http://127.0.0.1:8129/api/enterprise").json()[
                                "analyses"
                            ]
                        )
                        == 3
                    )
                    capture("05-race-rejection-preserves-history.png")
                    assert not errors, errors
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)
    print(
        "PASS: immediate accessible evidence drawer/loading/errors/focus/mobile; shared server quota, free stage controls and stale-admission race rejection, zero provider calls."
    )


if __name__ == "__main__":
    main()
