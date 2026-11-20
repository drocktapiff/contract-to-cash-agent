"""Deterministic rolling-window admission tests. No provider requests."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_local_session
from contract_to_cash.web.paid_availability import availability


class PaidAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_local_session.LocalSessionTests.asyncSetUp
    asyncTearDown = test_local_session.LocalSessionTests.asyncTearDown
    simulated_runner = test_local_session.LocalSessionTests.simulated_runner
    payload = test_local_session.LocalSessionTests.payload

    async def setup_pricing(self):
        response = await self.client.put(
            "/api/admin/pricing",
            headers=self.headers,
            json=dict(
                input_price="2",
                output_price="10",
                cached_input_price=".1",
                checked_current_official_rates=True,
            ),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return datetime.now(timezone.utc) + timedelta(seconds=1)

    def run_record(self, at, simulation=False):
        record = dict(
            id=uuid4().hex,
            idempotency_key=uuid4().hex,
            created_at=at.isoformat(),
            status="incomplete",
        )
        if simulation:
            record["provenance"] = dict(kind="simulated_demo")
        self.app.state.store.write_meta(record)
        return record

    async def test_available_and_exact_rolling_minute_boundary(self):
        at = await self.setup_pricing()
        store = self.app.state.store
        self.assertTrue(availability(store, at)["available"])
        self.run_record(at - timedelta(seconds=20))
        status = availability(store, at)
        self.assertEqual([r["code"] for r in status["reasons"]], ["minute_cooldown"])
        self.assertEqual(status["next_eligible_at"], (at + timedelta(seconds=40)).isoformat())
        self.assertFalse(availability(store, at + timedelta(seconds=39))["available"])
        self.assertTrue(availability(store, at + timedelta(seconds=40))["available"])

    async def test_hourly_release_uses_third_most_recent_and_both_windows(self):
        at = await self.setup_pricing()
        store = self.app.state.store
        for seconds in (10, 20, 30, 40):
            self.run_record(at - timedelta(seconds=seconds))
        state = availability(store, at)
        self.assertEqual(
            set(r["code"] for r in state["reasons"]), {"minute_cooldown", "hourly_limit"}
        )
        deadline = at + timedelta(seconds=3570)
        self.assertEqual(state["next_eligible_at"], deadline.isoformat())
        self.assertFalse(availability(store, deadline - timedelta(microseconds=1))["available"])
        self.assertTrue(availability(store, deadline)["available"])

    async def test_shared_maya_sarah_robert_archives_and_simulated_exemption(self):
        at = await self.setup_pricing()
        store = self.app.state.store
        self.run_record(at - timedelta(minutes=10))
        management = dict(
            id=uuid4().hex,
            idempotency_key=uuid4().hex,
            kind="management",
            created_at=(at - timedelta(minutes=20)).isoformat(),
            status="failed",
        )
        with store.enterprise.database() as cur:
            cur.execute(
                "INSERT INTO analyses VALUES (?,?,?)",
                (management["id"], management["idempotency_key"], json.dumps(management)),
            )
        archive = store.settings.root / "archives" / "retained"
        archive.mkdir(parents=True)
        executive = dict(
            id=uuid4().hex, kind="executive", created_at=(at - timedelta(minutes=30)).isoformat()
        )
        with closing(sqlite3.connect(archive / "enterprise.sqlite3")) as db:
            with db, closing(db.cursor()) as cur:
                cur.execute("CREATE TABLE analyses (body TEXT)")
                cur.execute("INSERT INTO analyses VALUES (?)", (json.dumps(executive),))
        for _ in range(4):
            self.run_record(at, True)
        state = availability(store, at)
        self.assertEqual(state["usage"], dict(minute_launches=0, hour_launches=3))
        self.assertEqual(state["next_eligible_at"], (at + timedelta(minutes=30)).isoformat())
        self.assertEqual([r["code"] for r in state["reasons"]], ["hourly_limit"])

    async def test_distinct_blockers_and_uncertain_time(self):
        at = await self.setup_pricing()
        store = self.app.state.store
        self.run_record(at - timedelta(seconds=10))
        store.active = "another-worker"
        state = availability(store, at)
        self.assertIn("active_worker", [r["code"] for r in state["reasons"]])
        self.assertIsNone(state["next_eligible_at"])
        store.active = None
        with patch.dict("os.environ", {}, clear=True):
            state = availability(store, at)
        self.assertIn("credential_missing", [r["code"] for r in state["reasons"]])
        self.assertIsNone(state["next_eligible_at"])
        state = availability(store, at + timedelta(hours=25))
        self.assertEqual([r["code"] for r in state["reasons"]], ["pricing_expired"])
        store.settings.mode = "recorded"
        self.assertEqual(availability(store, at)["reasons"][0]["code"], "recorded_mode")
        store.settings.mode = "operator"

    async def test_race_rejected_structurally_without_new_paid_record_or_consent_bypass(self):
        await self.setup_pricing()
        store = self.app.state.store
        first = await self.client.get("/api/paid-launch-availability")
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["available"])
        self.run_record(datetime.now(timezone.utc))
        before = store.metadata()
        body = dict(idempotency_key=str(uuid4()), acknowledge_paid=True)
        with patch(
            "openai.resources.responses.Responses.create",
            side_effect=AssertionError("No provider request permitted"),
        ):
            rejected = await self.client.post(
                "/api/billing-reviews", headers=self.headers, json=body
            )
        self.assertEqual(rejected.status_code, 429, rejected.text)
        self.assertEqual(rejected.json()["code"], "paid_launch_rejected")
        self.assertFalse(rejected.json()["paid_run_created"])
        self.assertFalse(rejected.json()["availability"]["available"])
        self.assertEqual(store.metadata(), before)
        self.assertIsNone(store.worker)
        body["acknowledge_paid"] = False
        self.assertEqual(
            (
                await self.client.post("/api/billing-reviews", headers=self.headers, json=body)
            ).status_code,
            422,
        )
        self.assertEqual(
            (
                await self.client.get(
                    "/api/paid-launch-availability", headers={"origin": "https://untrusted.example"}
                )
            ).status_code,
            403,
        )

    async def test_free_preparation_does_not_consume_capacity_even_without_key(self):
        at = await self.setup_pricing()
        store = self.app.state.store
        with patch.dict("os.environ", {}, clear=True), patch(
            "openai.resources.responses.Responses.create",
            side_effect=AssertionError("Provider forbidden"),
        ):
            maya = await self.client.post(
                "/api/demo/complete-maya",
                headers=self.headers,
                json={"confirmation": "PREPARE SIMULATED DEMO"},
            )
            self.assertEqual(maya.status_code, 200, maya.text)
            sarah = await self.client.post(
                "/api/demo/complete-sarah",
                headers=self.headers,
                json={
                    "confirmation": "COMPLETE SIMULATED SARAH DEMO",
                    "root_run_id": maya.json()["id"],
                },
            )
            self.assertEqual(sarah.status_code, 200, sarah.text)
        self.assertTrue(availability(store, at)["available"])
        self.assertEqual(availability(store, at)["usage"], dict(minute_launches=0, hour_launches=0))

    async def test_retained_worker_start_failure_is_not_reported_as_no_record(self):
        await self.setup_pricing()
        with patch(
            "contract_to_cash.web.store.Thread.start",
            side_effect=RuntimeError("test worker start failure"),
        ):
            response = await self.client.post(
                "/api/billing-reviews",
                headers=self.headers,
                json=dict(idempotency_key=str(uuid4()), acknowledge_paid=True),
            )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["code"], "paid_launch_retained_failure")
        self.assertTrue(response.json()["paid_run_created"])
        self.assertEqual(len(self.app.state.store.metadata()), 1)
        self.assertEqual(self.app.state.store.metadata()[0]["reason"], "worker_start_failed")
        self.assertIsNone(self.app.state.store.active)
