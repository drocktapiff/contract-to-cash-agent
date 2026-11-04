"""Administrator pricing attestation and employee launch path, with simulated SDK only."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock
from uuid import uuid4
import test_local_session
from contract_to_cash.web.pricing import OFFICIAL_PRICING


class PricingWorkflowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_local_session.LocalSessionTests.asyncSetUp
    asyncTearDown = test_local_session.LocalSessionTests.asyncTearDown
    simulated_runner = test_local_session.LocalSessionTests.simulated_runner

    def rates(self, **changes):
        # Explicit simulated test inputs, not an assertion about actual/current prices.
        return (
            dict(
                input_price="2",
                cached_input_price="0.1",
                output_price="10",
                checked_current_official_rates=True,
            )
            | changes
        )

    def authorization(self, **changes):
        return dict(idempotency_key=str(uuid4()), acknowledge_paid=True) | changes

    async def confirm(self):
        response = await self.client.put(
            "/api/admin/pricing", headers=self.headers, json=self.rates()
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_missing_configuration_is_a_simple_safe_setup_state(self):
        state = (await self.client.get("/api/admin/pricing")).json()
        self.assertFalse(state["ready"])
        self.assertIsNone(state["profile"])
        self.assertEqual(state["limits"]["maximum_seconds"], 180)
        self.assertEqual(state["limits"]["spending_limit_usd"], "1")
        runner = Mock()
        self.app.state.store.runner = runner
        response = await self.client.post(
            "/api/billing-reviews", headers=self.headers, json=self.authorization()
        )
        self.assertEqual(response.status_code, 503)
        runner.assert_not_called()
        self.assertEqual((await self.client.get("/api/runs")).json(), [])

    async def test_confirmation_requires_csrf_valid_rates_model_source_and_attestation(self):
        self.assertEqual(
            (await self.client.put("/api/admin/pricing", json=self.rates())).status_code, 403
        )
        for changes in (
            {"checked_current_official_rates": False},
            {"model": "another-model"},
            {"service_tier": "flex"},
            {"source": "https://untrusted.example/pricing"},
            {"cached_input_price": "3"},
            {"input_price": "NaN"},
            {"api_key": "not-an-api-input"},
        ):
            with self.subTest(changes=changes):
                response = await self.client.put(
                    "/api/admin/pricing", headers=self.headers, json=self.rates(**changes)
                )
                self.assertEqual(response.status_code, 422, response.text)
        self.assertFalse((await self.client.get("/api/admin/pricing")).json()["ready"])

    async def test_saved_rates_are_explicitly_attributed_and_expire_after_one_day(self):
        state = await self.confirm()
        self.assertTrue(state["ready"])
        profile = state["profile"]
        self.assertEqual(profile["rates"]["source"], OFFICIAL_PRICING)
        self.assertEqual(profile["confirmed_by"], "Local Test Operator")
        self.assertEqual(profile["verification_method"], "local_administrator_attestation")
        confirmed = datetime.fromisoformat(profile["confirmed_at"])
        expires = datetime.fromisoformat(profile["expires_at"])
        self.assertEqual(expires - confirmed, timedelta(hours=24))
        self.assertEqual((await self.client.get("/api/admin/pricing")).json()["profile"], profile)

    async def test_employee_supplies_only_authorization_and_server_owns_rates_and_caps(self):
        state = await self.confirm()
        for changes in (
            {"input_price": "0.001"},
            {"max_cost_usd": "2"},
            {"acknowledge_paid": False},
        ):
            response = await self.client.post(
                "/api/billing-reviews", headers=self.headers, json=self.authorization(**changes)
            )
            self.assertEqual(response.status_code, 422)
        response = await self.client.post(
            "/api/billing-reviews", headers=self.headers, json=self.authorization()
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["id"]
        for _ in range(150):
            run = (await self.client.get("/api/runs/" + run_id)).json()
            if run["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(0.01)
        self.assertEqual(run["status"], "incomplete")
        self.assertEqual(run["pricing_verification"], state["profile"])
        started = self.app.state.store.events(run_id)[0]["payload"]["limits"]
        self.assertEqual(started["input_usd_per_million"], "2")
        self.assertEqual(started["output_usd_per_million"], "10")
        self.assertEqual(started["max_seconds"], 180)
        self.assertEqual(started["max_tool_calls"], 35)
        self.assertEqual(run["financial_totals"]["potential_credits_cad"], "110.00")

    async def test_expired_or_invalid_pricing_cannot_launch_a_review(self):
        await self.confirm()
        path = self.settings.root / "admin/pricing.json"
        profile = json.loads(path.read_text())
        profile["confirmed_at"] = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        profile["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        path.write_text(json.dumps(profile))
        self.assertFalse((await self.client.get("/api/admin/pricing")).json()["ready"])
        response = await self.client.post(
            "/api/billing-reviews", headers=self.headers, json=self.authorization()
        )
        self.assertEqual(response.status_code, 503)
        path.write_text(json.dumps({"private_secret": "not-safe-for-a-response"}))
        response = await self.client.get("/api/admin/pricing")
        self.assertFalse(response.json()["ready"])
        self.assertIsNone(response.json()["profile"])
        self.assertNotIn("not-safe-for-a-response", response.text)

    async def test_active_review_and_recorded_mode_cannot_change_pricing(self):
        self.app.state.store.active = "test-running"
        try:
            self.assertEqual(
                (
                    await self.client.put(
                        "/api/admin/pricing", headers=self.headers, json=self.rates()
                    )
                ).status_code,
                409,
            )
        finally:
            self.app.state.store.active = None
        self.settings.mode = "recorded"
        self.assertEqual(
            (
                await self.client.put("/api/admin/pricing", headers=self.headers, json=self.rates())
            ).status_code,
            403,
        )
        self.assertEqual(
            (
                await self.client.post(
                    "/api/billing-reviews", headers=self.headers, json=self.authorization()
                )
            ).status_code,
            403,
        )
        self.assertEqual(
            (await self.client.get("/api/admin/pricing")).json()["reason"], "recorded_only"
        )

    async def test_advanced_launch_cannot_bypass_current_confirmed_rates(self):
        body = test_local_session.LocalSessionTests.payload(self)
        response = await self.client.post("/api/runs", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 503)
        await self.confirm()
        body["input_price"] = "1"
        response = await self.client.post("/api/runs", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.client.get("/api/runs")).json(), [])

    async def test_confirmation_survives_restart_without_starting_paid_work(self):
        state = await self.confirm()
        await self.lifespan.__aexit__(None, None, None)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        await self.client.get("/api/session")
        self.assertEqual(
            (await self.client.get("/api/admin/pricing")).json()["profile"], state["profile"]
        )
        self.assertEqual((await self.client.get("/api/runs")).json(), [])
