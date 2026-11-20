"""Guided stage/provenance and grounded executive regressions; no paid provider calls."""

import copy
import json
import unittest
from unittest.mock import patch
import test_enterprise
from contract_to_cash.agent.events import Journal
from contract_to_cash.agent.tools import ToolError
from contract_to_cash.web.analysis_tools import AnalysisTools


class GuidedDemoTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_enterprise.EnterpriseTests.asyncSetUp
    asyncTearDown = test_enterprise.EnterpriseTests.asyncTearDown
    simulated_runner = test_enterprise.EnterpriseTests.simulated_runner
    payload = test_enterprise.EnterpriseTests.payload
    settled = test_enterprise.EnterpriseTests.settled
    age = test_enterprise.EnterpriseTests.age
    launch_analysis = test_enterprise.EnterpriseTests.launch_analysis

    async def maya(self):
        with patch(
            "openai.resources.responses.Responses.create",
            side_effect=AssertionError("Provider forbidden during preparation"),
        ):
            response = await self.client.post(
                "/api/demo/complete-maya",
                headers=self.headers,
                json={"confirmation": "PREPARE SIMULATED DEMO"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def sarah(self, root):
        with patch(
            "openai.resources.responses.Responses.create",
            side_effect=AssertionError("Provider forbidden during preparation"),
        ):
            response = await self.client.post(
                "/api/demo/complete-sarah",
                headers=self.headers,
                json={"confirmation": "COMPLETE SIMULATED SARAH DEMO", "root_run_id": root},
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def price(self):
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

    async def test_stage_buttons_share_idempotent_scenario_and_explicit_simulation(self):
        with patch.dict("os.environ", {}, clear=True):
            run = await self.maya()
            first = await self.sarah(run["id"])
            second = await self.sarah(run["id"])
            again = await self.maya()
        self.assertEqual(run, again)
        self.assertEqual(first, second)
        op = (await self.client.get("/api/enterprise", params={"root_run_id": run["id"]})).json()
        self.assertTrue(op["management_handoff"]["current"])
        self.assertEqual(len(op["command_center"]["actions"]), 3)
        self.assertTrue(
            all(
                a["provenance"]["kind"] == "simulated_demo_action" and a["status"] == "Proposed"
                for a in op["command_center"]["actions"]
            )
        )
        self.assertTrue(
            all(
                a["reviewer"].startswith("Simulated management")
                for a in op["command_center"]["actions"]
            )
        )
        self.assertEqual(
            op["operational"]["financial"]["unresolved_quantifiable_exposure_cad"], "5910.00"
        )
        self.assertEqual(op["operational"]["financial"]["unquantified_cases"], 2)
        inputs = self.enterprise.inputs(run["id"], "executive")
        self.assertEqual(inputs["management"]["actions"], op["command_center"]["actions"])
        self.assertEqual(inputs["management"]["handoff"]["root_run_id"], run["id"])
        self.assertTrue(
            any(r["kind"] == "original_evidence" for r in inputs["references"].values())
        )
        self.assertEqual(self.clients, [])

    async def test_actual_human_action_preserved_and_invalidates_generated_brief(self):
        run = await self.maya()
        await self.sarah(run["id"])
        await self.price()
        analysis, _ = await self.launch_analysis(run, "executive")
        self.assertEqual(analysis["status"], "completed", analysis)
        self.assertEqual(analysis["result"]["stance"], "more_validation_needed")
        self.assertEqual(
            set(analysis["result"]["brief"]),
            {
                "executive_assessment",
                "maya_demonstrated",
                "sarah_changed",
                "financial_opportunity",
                "risks_missing_evidence",
            },
        )
        op = (await self.client.get("/api/enterprise")).json()
        a = op["command_center"]["actions"][0]
        body = {
            k: a[k]
            for k in [
                "root_run_id",
                "issue_id",
                "owner",
                "priority",
                "target_date",
                "rationale",
                "closure_criteria",
                "status",
            ]
        }
        body.update(
            expected_revision=op["command_center"]["revision"],
            expected_version=a["version"],
            owner="Actual local billing lead",
            status="Investigating",
            rationale="Human: inspect mapping before any correction.",
        )
        changed = await self.client.post("/api/enterprise/actions", headers=self.headers, json=body)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["provenance"]["kind"], "human_internal_decision")
        self.assertEqual(
            changed.json()["history"][0]["provenance"]["kind"], "simulated_demo_action"
        )
        stale = (await self.client.get("/api/enterprise/analyses/" + analysis["id"])).json()
        self.assertFalse(stale["current"])
        self.assertFalse(
            (await self.client.get("/api/enterprise")).json()["management_handoff"]["current"]
        )
        await self.sarah(run["id"])
        actions = self.enterprise.inputs(run["id"], "executive")["management"]["actions"]
        self.assertIn(changed.json(), actions)
        self.assertEqual(len(actions), 3)
        current = (await self.client.get("/api/enterprise")).json()
        self.assertTrue(current["management_handoff"]["current"])
        self.assertEqual(current["operational"]["financial"], op["operational"]["financial"])
        self.assertEqual(current["decisions"], [])
        # An explicitly cautious executive recommendation can also be deferral.
        self.analysis_scenario = "defer"
        deferred, _ = await self.launch_analysis(run, "executive")
        self.assertEqual(deferred["status"], "completed", deferred)
        self.assertEqual(deferred["result"]["stance"], "defer")
        # A failed replacement must retain the earlier successful brief.
        self.analysis_scenario = "api_failure"
        failed, _ = await self.launch_analysis(run, "executive")
        self.assertEqual(failed["status"], "incomplete")
        retained = (await self.client.get("/api/enterprise/analyses/" + deferred["id"])).json()
        self.assertEqual(retained["result"], deferred["result"])

    async def test_genuine_history_security_and_atomic_interruption(self):
        genuine = await self.settled()
        refused = await self.client.post(
            "/api/demo/complete-sarah",
            headers=self.headers,
            json={"confirmation": "COMPLETE SIMULATED SARAH DEMO", "root_run_id": genuine["id"]},
        )
        self.assertEqual(refused.status_code, 409)
        before = (await self.client.get("/api/runs/" + genuine["id"])).json()
        run = await self.maya()
        self.assertEqual(before, (await self.client.get("/api/runs/" + genuine["id"])).json())
        self.assertEqual(
            (
                await self.client.post(
                    "/api/demo/complete-maya", json={"confirmation": "PREPARE SIMULATED DEMO"}
                )
            ).status_code,
            403,
        )
        self.app.state.store.active = "test-active"
        response = await self.client.post(
            "/api/demo/complete-sarah",
            headers=self.headers,
            json={"confirmation": "COMPLETE SIMULATED SARAH DEMO", "root_run_id": run["id"]},
        )
        self.assertEqual(response.status_code, 409)
        self.app.state.store.active = None
        original = self.enterprise.event

        def interrupted(cur, kind, **payload):
            if kind == "demo.management.handoff":
                raise OSError("simulated transaction interruption")
            return original(cur, kind, **payload)

        from contract_to_cash.web.guided_demo import complete_sarah, SarahDemo, handoff

        with patch.object(self.enterprise, "event", side_effect=interrupted):
            with self.assertRaises(OSError):
                complete_sarah(
                    self.enterprise,
                    SarahDemo(root_run_id=run["id"], confirmation="COMPLETE SIMULATED SARAH DEMO"),
                )
        self.assertEqual(
            (await self.client.get("/api/enterprise", params={"root_run_id": run["id"]})).json()[
                "command_center"
            ]["actions"],
            [],
        )
        self.assertIsNone(handoff(self.enterprise, run["id"]))
        await self.sarah(run["id"])
        path = self.settings.data / "invoices.json"
        path.write_text(path.read_text() + "\n")
        refused = await self.client.post(
            "/api/demo/complete-sarah",
            headers=self.headers,
            json={"confirmation": "COMPLETE SIMULATED SARAH DEMO", "root_run_id": run["id"]},
        )
        self.assertEqual(refused.status_code, 409)

    async def test_brief_requires_read_sources_and_never_changes_python_values(self):
        run = await self.maya()
        await self.sarah(run["id"])
        await self.price()
        analysis, _ = await self.launch_analysis(run, "executive")
        before = (await self.client.get("/api/enterprise")).json()["operational"]["financial"]
        inputs = self.enterprise.inputs(run["id"], "executive")
        args = {
            k: v
            for k, v in analysis["result"].items()
            if k
            in AnalysisTools(inputs, "executive", None).definitions["save_analysis"]["parameters"][
                "properties"
            ]
        }
        # Wrong/unread citations anywhere in the structured brief cannot be saved.
        with Journal(self.root / "brief-integrity") as journal:
            tools = AnalysisTools(inputs, "executive", journal)
            tools.seen.update(inputs["references"])
            bad = copy.deepcopy(args)
            bad["brief"]["executive_assessment"][0]["citations"] = ["not-in-snapshot"]
            with self.assertRaises(ToolError):
                tools.execute("save_analysis", bad)
            tools.seen = {
                ref
                for ref, value in inputs["references"].items()
                if value["kind"] not in ("case", "original_evidence")
            }
            with self.assertRaises(ToolError):
                tools.execute("save_analysis", args)
            tools.seen.update(inputs["references"])
            # Narrative is interpretation, never an authoritative calculation channel.
            args["brief"]["financial_opportunity"][0][
                "text"
            ] = "MOCKED UNTRUSTED PROSE: collected revenue is CAD 999999."
            tools.execute("save_analysis", args)
        self.assertEqual(
            before, (await self.client.get("/api/enterprise")).json()["operational"]["financial"]
        )

    async def test_real_action_before_first_sarah_completion_is_not_seeded_over(self):
        run = await self.maya()
        overview = (await self.client.get("/api/enterprise")).json()
        issue = overview["command_center"]["issues"][0]
        body = dict(
            root_run_id=run["id"],
            issue_id=issue["id"],
            expected_revision=overview["command_center"]["revision"],
            expected_version=0,
            owner="Actual human-selected owner",
            priority=1,
            target_date="2026-12-01",
            rationale="Human decision before any management fixture preparation.",
            closure_criteria="Validate source mapping with independent review.",
            status="Investigating",
        )
        saved = await self.client.post("/api/enterprise/actions", headers=self.headers, json=body)
        self.assertEqual(saved.status_code, 200, saved.text)
        await self.sarah(run["id"])
        actions = self.enterprise.inputs(run["id"], "executive")["management"]["actions"]
        self.assertIn(saved.json(), actions)
        self.assertEqual(len(actions), 3)
        self.assertEqual(
            sum(a["provenance"]["kind"] == "simulated_demo_action" for a in actions), 2
        )
