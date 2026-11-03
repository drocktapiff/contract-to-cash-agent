"""Passwordless loopback sessions retain CSRF and explicit paid/review authorization."""

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
import test_api
from contract_to_cash.web.app import create_app
from contract_to_cash.web.store import Settings
from scripts.build_agent_runtime import build


class LocalSessionTests(unittest.IsolatedAsyncioTestCase):
    payload = test_api.ApiTests.payload
    settled = test_api.ApiTests.settled
    decision = test_api.ApiTests.decision
    simulated_runner = test_api.ApiTests.simulated_runner

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        runtime = build(self.root / "runtime")
        self.settings = Settings(
            data=runtime / "contract_to_cash/data",
            root=self.root / "runs",
            recordings=self.root / "recordings",
            frontend=self.root / "dist",
            reviewer="Local Test Operator",
        )
        self.env = patch.dict(os.environ, {"OPENAI_API_KEY": "local-test-placeholder"})
        self.env.start()
        self.app = create_app(self.settings, self.simulated_runner)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url="http://127.0.0.1:8000"
        )
        response = await self.client.get("/api/session")
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()["csrf_token"]
        self.headers = {"x-csrf-token": self.csrf}

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.env.stop()
        self.tmp.cleanup()

    async def test_dashboard_bootstrap_needs_no_password_and_starts_no_run(self):
        self.assertEqual(self.settings.operator_token, "")
        response = await self.client.get("/api/session")
        self.assertTrue(response.json()["authenticated"])
        self.assertTrue(response.json()["local_passwordless"])
        self.assertFalse(response.json()["identity_verified"])
        self.assertNotIn("local-test-placeholder", response.text)
        self.assertEqual(response.json()["csrf_token"], self.csrf)
        self.assertEqual((await self.client.get("/api/dataset")).json()["customer_count"], 40)
        self.assertEqual((await self.client.get("/api/runs")).json(), [])
        self.assertIsNone(self.app.state.store.active)
        self.assertEqual(
            (await self.client.post("/api/session", json={"token": "unused"})).status_code, 409
        )

    async def test_cookie_security_and_csrf_are_required_for_mutations(self):
        self.client.cookies.clear()
        response = await self.client.get("/api/session")
        cookie = response.headers["set-cookie"]
        for flag in ("HttpOnly", "SameSite=strict", "Max-Age=28800", "Path=/api"):
            self.assertIn(flag, cookie)
        self.assertGreaterEqual(len(self.client.cookies.get("ctc_session")), 40)
        self.assertNotEqual(response.json()["csrf_token"], self.csrf)
        self.assertEqual(
            (await self.client.post("/api/runs", json=self.payload())).status_code, 403
        )
        self.assertEqual(
            (
                await self.client.post("/api/runs", headers=self.headers, json=self.payload())
            ).status_code,
            403,
        )
        self.assertEqual((await self.client.get("/api/runs")).json(), [])

    async def test_cross_origin_and_cross_site_cannot_create_a_local_session(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url="http://127.0.0.1:8000"
        ) as outsider:
            response = await outsider.get(
                "/api/session", headers={"origin": "https://attacker.example"}
            )
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("set-cookie", response.headers)
            response = await outsider.get("/api/session", headers={"sec-fetch-site": "cross-site"})
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("set-cookie", response.headers)
        response = await self.client.post(
            "/api/runs",
            headers=self.headers | {"origin": "https://attacker.example"},
            json=self.payload(),
        )
        self.assertEqual(response.status_code, 403)

    async def test_network_peer_or_non_loopback_binding_is_rejected(self):
        for peer, url in [
            (("192.0.2.10", 1234), "http://127.0.0.1:8000"),
            (("127.0.0.1", 1234), "http://192.0.2.20:8000"),
        ]:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(self.app, client=peer), base_url=url
            ) as outsider:
                response = await outsider.get("/api/session")
                self.assertEqual(response.status_code, 403, response.text)
                self.assertNotIn("set-cookie", response.headers)

    async def test_paid_confirmation_and_limits_remain_mandatory(self):
        for overrides in (
            {"acknowledge_paid": False},
            {"max_cost_usd": "2"},
            {"max_tool_calls": 36},
            {"max_seconds": 181},
        ):
            body = self.payload()
            body.update(overrides)
            response = await self.client.post("/api/runs", headers=self.headers, json=body)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual((await self.client.get("/api/runs")).json(), [])
        run = await self.settled()
        self.assertEqual(run["status"], "incomplete")
        self.assertEqual(
            (
                await self.client.post("/api/runs", headers=self.headers, json=self.payload())
            ).status_code,
            429,
        )

    async def test_explicit_review_rationale_revision_and_export_permission_are_preserved(self):
        run = await self.settled()
        self.assertTrue(all(r["status"] == "pending" for r in run["reviews"]))
        endpoint = f"/api/runs/{run['id']}/findings/finding-C005"
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 403)
        body = self.decision(run)
        body.pop("rationale")
        self.assertEqual(
            (
                await self.client.post(endpoint + "/review", headers=self.headers, json=body)
            ).status_code,
            422,
        )
        body = self.decision(run, expected_version=99)
        self.assertEqual(
            (
                await self.client.post(endpoint + "/review", headers=self.headers, json=body)
            ).status_code,
            409,
        )
        response = await self.client.post(
            endpoint + "/review", headers=self.headers, json=self.decision(run)
        )
        self.assertEqual(response.status_code, 200, response.text)
        decision = response.json()["decision"]
        self.assertEqual(decision["reviewer"], "Local Test Operator")
        self.assertTrue(decision["rationale"])
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 200)

    async def test_session_renewal_after_restart_never_relaunches_investigation(self):
        run = await self.settled()
        await self.lifespan.__aexit__(None, None, None)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.assertEqual((await self.client.get("/api/runs")).status_code, 401)
        response = await self.client.get("/api/session")
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["csrf_token"], self.csrf)
        history = (await self.client.get("/api/runs")).json()
        self.assertEqual([r["id"] for r in history], [run["id"]])
        self.assertIsNone(self.app.state.store.active)

    async def test_session_creation_is_bounded_without_rate_limiting_cookie_reuse(self):
        for _ in range(10):
            self.assertEqual((await self.client.get("/api/session")).status_code, 200)
        for index in range(5):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(self.app), base_url="http://127.0.0.1:8000"
            ) as browser:
                response = await browser.get("/api/session")
                self.assertEqual(response.status_code, 200 if index < 4 else 429)

    def test_cli_still_binds_only_to_127_and_does_not_require_operator_secret(self):
        from contract_to_cash.web import __main__ as command

        with patch("sys.argv", ["web"]), patch.object(command.uvicorn, "run") as serve:
            command.main()
        self.assertEqual(serve.call_args.kwargs["host"], "127.0.0.1")
        self.assertTrue(serve.call_args.args[0].state.store.settings.local_passwordless)
        self.assertEqual(serve.call_args.args[0].state.store.settings.operator_token, "")
