"""Synchronize browser tests with bounded, successful free-demo commands."""


def confirm_simulated_stage(page, stage):
    """Wait for persistence, then let callers assert the rendered completion state.

    A click dispatches a request; it does not await SQLite/fixture preparation.
    In particular Windows preparation can exceed the default 5s DOM assertion
    timeout. Keep the DOM assertions unchanged and check the actual POST result.
    """
    name = {"maya": "Maya", "sarah": "Sarah"}[stage]
    with page.expect_response(
        lambda response: response.url.endswith(f"/api/demo/complete-{stage}")
        and response.request.method == "POST",
        timeout=30_000,
    ) as completion:
        page.get_by_role("dialog", name=f"Confirm {name} simulated completion").get_by_role(
            "button", name=f"Confirm {name} simulated completion — no API usage", exact=True
        ).click()
    response = completion.value
    assert response.ok, f"Free {name} preparation failed with HTTP {response.status}"
    body = response.json()
    assert body.get("id") or body.get("root_run_id"), "Preparation did not identify its saved scenario"
