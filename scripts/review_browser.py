"""Shared actual human-review interaction for browser acceptance, never a provider."""

from playwright.sync_api import expect


def review_prepared(page, expected=None):
    page.get_by_role("button", name="Review All", exact=True).click()
    dialog = page.get_by_role("dialog", name="Review All", exact=True)
    expect(dialog.get_by_role("button", name="Confirm Bulk Review", exact=True)).to_be_disabled()
    if expected is not None:
        expect(dialog).to_contain_text(f"{expected} eligible for approval", timeout=30000)
    dialog.get_by_label("Review rationale", exact=True).fill(
        "Explicit browser-fixture bulk attestation of validated low-risk administrative checks; no financial authorization."
    )
    dialog.get_by_role("checkbox").check()
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/human-reviews"), timeout=90000
    ) as response:
        dialog.get_by_role("button", name="Confirm Bulk Review", exact=True).click()
    assert response.value.ok, response.value.text()
    result = response.value.json()
    if expected is not None:
        assert result["approved"] == expected, result
    assert result["financial_actions_executed"] == 0
    dialog.get_by_role("button", name="Done", exact=True).click()
    return result
