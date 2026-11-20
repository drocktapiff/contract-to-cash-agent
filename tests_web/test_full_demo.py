"""Real deterministic tools, isolated files and SQLite. Provider requests forbidden."""

import json
import hashlib
import unittest
from unittest.mock import patch
import test_local_session


class FullDemoTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_local_session.LocalSessionTests.asyncSetUp
    asyncTearDown = test_local_session.LocalSessionTests.asyncTearDown
    simulated_runner = test_local_session.LocalSessionTests.simulated_runner
    payload = test_local_session.LocalSessionTests.payload
    settled = test_local_session.LocalSessionTests.settled

    async def prepare(self):
        with patch(
            "openai.resources.responses.Responses.create",
            side_effect=AssertionError("Paid request forbidden"),
        ):
            response = await self.client.post(
                "/api/admin/prepare-demo",
                headers=self.headers,
                json={"confirmation": "PREPARE SIMULATED DEMO"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_deterministic_shared_scenario_and_evidence_no_provider_calls(self):
        before = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.settings.data.rglob("*")
            if p.is_file()
        }
        run = await self.prepare()
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["provenance"]["label"], "Simulated Demo Data")
        self.assertEqual(len(run["customers_compared"]), 40)
        self.assertEqual(run["metrics"]["api_requests"], 0)
        self.assertEqual(run["metrics"]["agent_tool_calls"], 0)
        self.assertTrue(all(f["origin"] == "simulated_demo" for f in run["findings"]))
        self.assertTrue(all(r["status"] == "pending" for r in run["reviews"]))
        overview = (
            await self.client.get("/api/enterprise", params={"root_run_id": run["id"]})
        ).json()
        op = overview["operational"]
        self.assertEqual(op["financial"]["potential_receivables_cad"], "5300.00")
        self.assertEqual(op["financial"]["potential_credits_cad"], "610.00")
        self.assertEqual(op["financial"]["unresolved_quantifiable_exposure_cad"], "5910.00")
        self.assertEqual(op["financial"]["unquantified_cases"], 2)
        shared = next(
            i
            for i in overview["command_center"]["issues"]
            if i["customer_ids"] == ["C008", "C009", "C010"]
        )
        self.assertEqual(shared["potential_exposure_cad"], "3000.00")
        self.assertTrue(
            all(
                r["expected_cad"] == "10000.00" and r["billed_cad"] == "9000.00"
                for r in shared["comparisons"]
            )
        )
        for cid, status in [("C007", "conflict"), ("C006", "duplicate_invoice")]:
            case = next(c for c in op["cases"] if cid in c["customer_ids"])
            row = next(r for r in case["comparisons"] if r["customer_id"] == cid)
            self.assertEqual(row["status"], status)
            self.assertIsNone(row["difference_cad"])
        sources = (
            await self.client.get(f"/api/runs/{run['id']}/findings/finding-C008-C009-C010/evidence")
        ).json()
        self.assertGreaterEqual(len(sources), 6)
        self.assertTrue(any("text" in s for s in sources))
        self.assertTrue(any("record" in s for s in sources))
        events = self.app.state.store.events(run["id"])
        self.assertFalse(any(e["type"].startswith("api.") for e in events))
        self.assertTrue(
            all(
                e["actor"] == "demo_fixture"
                and e["payload"]["provenance"]["kind"] == "simulated_demo"
                for e in events
            )
        )
        self.assertNotIn('"origin": "model_submission"', json.dumps(events))
        again = await self.prepare()
        self.assertEqual(run, again)
        self.assertEqual(len((await self.client.get("/api/runs")).json()), 1)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})
        self.assertEqual(overview["analyses"], [])

    async def test_human_actions_version_history_and_robert_context(self):
        run = await self.prepare()
        overview = (await self.client.get("/api/enterprise")).json()
        center = overview["command_center"]
        issue = center["issues"][0]
        body = dict(
            root_run_id=run["id"],
            issue_id=issue["id"],
            expected_revision=center["revision"],
            expected_version=0,
            owner="Billing Operations",
            priority=1,
            target_date="2026-12-01",
            rationale="Validate template mapping before any corrections.",
            closure_criteria="Review mapping evidence and obtain independent financial review.",
            status="Assigned",
        )
        first = await self.client.post("/api/enterprise/actions", headers=self.headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        body.update(expected_version=1, status="Investigating")
        second = await self.client.post("/api/enterprise/actions", headers=self.headers, json=body)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(len(second.json()["history"]), 2)
        stale = await self.client.post("/api/enterprise/actions", headers=self.headers, json=body)
        self.assertEqual(stale.status_code, 409)
        body.update(expected_version=2, status="Closed — Verified")
        self.assertEqual(
            (
                await self.client.post("/api/enterprise/actions", headers=self.headers, json=body)
            ).status_code,
            422,
        )
        management = self.app.state.store.enterprise.inputs(run["id"], "executive")["management"]
        self.assertEqual(management["actions"][0]["status"], "Investigating")
        self.assertEqual(management["actions"][0]["reviewer"], "Local Test Operator")
        self.assertEqual(management["actions"][0]["provenance"]["kind"], "human_internal_decision")
        await self.prepare()
        self.assertEqual(
            len(
                self.app.state.store.enterprise.inputs(run["id"], "executive")["management"][
                    "actions"
                ]
            ),
            1,
        )
        body.update(closure_references=issue["references"])
        closed = await self.client.post("/api/enterprise/actions", headers=self.headers, json=body)
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(len(closed.json()["history"]), 3)
        forbidden = dict(body, expected_version=3, action="approve_pilot")
        self.assertEqual(
            (
                await self.client.post(
                    "/api/enterprise/actions", headers=self.headers, json=forbidden
                )
            ).status_code,
            422,
        )
        current = (await self.client.get("/api/enterprise")).json()
        self.assertEqual(
            current["operational"]["financial"]["unresolved_quantifiable_exposure_cad"], "5910.00"
        )
        self.assertEqual(len(current["decisions"]), 0)
        self.assertEqual(
            (
                await self.client.get(
                    f"/api/runs/{run['id']}/findings/finding-C008-C009-C010/export"
                )
            ).status_code,
            403,
        )

    async def test_security_active_worker_missing_key_and_history_preservation(self):
        historical = await self.settled()
        snapshot = (await self.client.get("/api/runs/" + historical["id"])).json()
        self.assertEqual(
            (
                await self.client.post(
                    "/api/admin/prepare-demo", json={"confirmation": "PREPARE SIMULATED DEMO"}
                )
            ).status_code,
            403,
        )
        self.app.state.store.active = "test-active"
        self.assertEqual(
            (
                await self.client.post(
                    "/api/admin/prepare-demo",
                    headers=self.headers,
                    json={"confirmation": "PREPARE SIMULATED DEMO"},
                )
            ).status_code,
            409,
        )
        self.app.state.store.active = None
        with patch.dict("os.environ", {}, clear=True):
            await self.prepare()
        self.assertEqual(snapshot, (await self.client.get("/api/runs/" + historical["id"])).json())

    async def test_recover_publication_interruption_and_stale_evidence(self):
        store = self.app.state.store
        with patch.object(
            store, "write_meta", side_effect=OSError("simulated publication interruption")
        ):
            with self.assertRaises(OSError):
                from contract_to_cash.web.demo_prepare import prepare

                prepare(store)
        self.assertEqual(store.metadata(), [])
        run = await self.prepare()
        old = (await self.client.get("/api/enterprise")).json()
        path = self.settings.data / "invoices.json"
        path.write_text(path.read_text() + "\n")
        changed = (await self.client.get("/api/enterprise")).json()
        self.assertEqual(changed["operational"]["financial"]["potential_receivables_cad"], "0.00")
        self.assertGreater(changed["operational"]["financial"]["unquantified_cases"], 0)
        self.assertNotEqual(
            old["command_center"]["revision"], changed["command_center"]["revision"]
        )
        self.assertEqual(
            (await self.client.get("/api/runs/" + run["id"])).json()["status"], "completed"
        )

    async def test_source_integrity_origin_stale_actions_and_prior_human_decisions(self):
        import test_api

        historical = await self.settled()
        review = await self.client.post(
            f"/api/runs/{historical['id']}/findings/finding-C005/review",
            headers=self.headers,
            json=test_api.ApiTests.decision(self, historical),
        )
        self.assertEqual(review.status_code, 200, review.text)
        before = (await self.client.get("/api/runs/" + historical["id"])).json()
        bad = await self.client.post(
            "/api/admin/prepare-demo",
            headers={**self.headers, "origin": "https://untrusted.example"},
            json={"confirmation": "PREPARE SIMULATED DEMO"},
        )
        self.assertEqual(bad.status_code, 403)
        run = await self.prepare()
        self.assertEqual(before, (await self.client.get("/api/runs/" + historical["id"])).json())
        overview = (
            await self.client.get("/api/enterprise", params={"root_run_id": run["id"]})
        ).json()
        center = overview["command_center"]
        issue = center["issues"][0]
        body = dict(
            root_run_id=run["id"],
            issue_id=issue["id"],
            expected_revision=center["revision"],
            expected_version=0,
            owner="Billing team",
            priority=1,
            target_date="2026-12-01",
            rationale="Inspect source evidence.",
            closure_criteria="Obtain source-backed independent review.",
            status="Assigned",
        )
        path = self.settings.data / "invoices.json"
        path.write_text(path.read_text() + "\n")
        self.assertEqual(
            (
                await self.client.post("/api/enterprise/actions", headers=self.headers, json=body)
            ).status_code,
            409,
        )
        doc = next((self.settings.data / "documents").glob("*.txt"))
        doc.write_text(doc.read_text() + "\nmodified source evidence")
        bad = await self.client.post(
            "/api/admin/prepare-demo",
            headers=self.headers,
            json={"confirmation": "PREPARE SIMULATED DEMO"},
        )
        self.assertEqual(bad.status_code, 503, bad.text)

    async def test_preparation_preserves_incomplete_analysis_and_does_not_satisfy_paid_gates(self):
        from contract_to_cash.web.enterprise import timestamp

        store = self.app.state.store
        with store.enterprise.database() as cur:
            record = dict(
                id="f" * 32,
                idempotency_key="retained-incomplete-analysis",
                kind="management",
                root_run_id="a" * 32,
                status="incomplete",
                reason="tool_failures",
                created_at=timestamp(),
                result=None,
            )
            cur.execute(
                "INSERT INTO analyses VALUES (?,?,?)",
                (record["id"], record["idempotency_key"], json.dumps(record)),
            )
        run = await self.prepare()
        self.assertEqual(store.enterprise.analyses()[0], record)
        overview = (
            await self.client.get("/api/enterprise", params={"root_run_id": run["id"]})
        ).json()
        from uuid import uuid4

        request = dict(
            idempotency_key=str(uuid4()),
            acknowledge_paid=True,
            kind="management",
            root_run_id=run["id"],
            expected_revision=overview["analysis_revisions"]["management"],
        )
        # No administrator pricing verification was established by preparation.
        denied = await self.client.post(
            "/api/enterprise/analyses", headers=self.headers, json=request
        )
        self.assertNotEqual(denied.status_code, 202)
        self.assertIsNone(store.active)

    async def test_administrative_dismissal_does_not_resolve_contract_authority(self):
        import test_workflow

        run = await self.prepare()
        response = await self.client.post(
            f"/api/runs/{run['id']}/findings/finding-C007/interventions",
            headers=self.headers,
            json=test_workflow.WorkflowTests.action(self, run, action="dismiss"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        overview = (await self.client.get("/api/enterprise")).json()
        self.assertEqual(overview["operational"]["financial"]["unquantified_cases"], 2)
        conflict = next(
            i for i in overview["command_center"]["issues"] if i["customer_ids"] == ["C007"]
        )
        self.assertIsNone(conflict["potential_exposure_cad"])
        self.assertIn("conflicting contractual authority", conflict["title"])
