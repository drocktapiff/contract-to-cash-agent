"""Enterprise integration with simulated SDK, real snapshot tools/SQLite/Decimal math."""

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_api
import test_local_session
import test_workflow
from test_agent import FakeClient, FakeResponse, call
from contract_to_cash.agent.events import Journal
from contract_to_cash.agent.runtime import Investigator, Limits
from contract_to_cash.agent.tools import ToolError
from contract_to_cash.billing_engine import expected_amount, ConflictError
from contract_to_cash.web.analysis_tools import AnalysisTools, INSTRUCTIONS
from contract_to_cash.web.enterprise_metrics import Scenario, roi
from contract_to_cash.web.enterprise import Enterprise
from contract_to_cash.web.store import Store, StoreError


def group_candidates(data):
    groups = {}
    for cid, c in data.customers.items():
        rows = data.rows[cid]
        if len(rows) != 1:
            continue
        try:
            diff = expected_amount(
                c, data.changes[cid], data.period, rows[0]["usage_quantity"]
            ) - Decimal(rows[0]["billed_amount"])
        except ConflictError:
            continue
        if diff:
            groups.setdefault((c["pricing_template"], str(diff)), []).append(cid)
    return next(ids for ids in groups.values() if len(ids) >= 3)


def enterprise_root_runner(store, run_id, data, request):
    with Journal(store.settings.root / run_id, io_lock=store.lock) as journal:
        journal.run_id = run_id
        tools = Store.investigation_tools(data, journal)
        group = group_candidates(data)
        selected = lambda name, args: dict(call(name, args), call_id=uuid4().hex)
        ids = list(dict.fromkeys(group + ["C005", "C006", "C007"]))
        required = lambda cids: sorted(set().union(*(tools._required(cid) for cid in cids)))
        script = [
            FakeResponse([selected("screen_customers", {})]),
            FakeResponse([selected("get_customer_evidence", dict(customer_ids=ids))]),
            FakeResponse(
                [
                    selected(
                        "submit_finding",
                        dict(
                            customer_ids=group,
                            evidence_ids=required(group),
                            state="verified",
                            rationale="SIMULATED SDK: shared deterministic template discrepancies; root cause unproven.",
                        ),
                    ),
                    selected(
                        "submit_finding",
                        dict(
                            customer_ids=["C005"],
                            evidence_ids=required(["C005"]),
                            state="verified",
                            rationale="SIMULATED SDK: credit needs human review.",
                        ),
                    ),
                    selected(
                        "submit_finding",
                        dict(
                            customer_ids=["C006"],
                            evidence_ids=required(["C006"]),
                            state="proposed",
                            rationale="SIMULATED SDK: reconcile invoice records before asserting duplicate exposure.",
                        ),
                    ),
                ]
            ),
            FakeResponse(
                [
                    selected(
                        "request_human_review",
                        dict(finding_id="finding-" + "-".join(sorted(group)), action="review"),
                    ),
                    selected(
                        "request_human_review", dict(finding_id="finding-C005", action="export")
                    ),
                    selected(
                        "request_human_review", dict(finding_id="finding-C006", action="review")
                    ),
                ]
            ),
            FakeResponse([]),
        ]
        return Investigator(
            FakeClient(script),
            "simulated-enterprise-source",
            tools,
            journal,
            Limits(
                max_tool_calls=request.max_tool_calls,
                max_responses=request.max_responses,
                max_seconds=request.max_seconds,
                max_cost_usd=request.max_cost_usd,
                input_usd_per_million=request.input_price,
                output_usd_per_million=request.output_price,
                cached_input_usd_per_million=request.cached_input_price,
            ),
        ).run("SIMULATED SDK operational source, real Python tools; no paid calls")


def simulated_analysis(service, a, scenario="success", clients=None):
    with Journal(
        service.store.settings.root / "analyses" / a["id"], io_lock=service.store.lock
    ) as journal:
        journal.run_id = a["id"]
        inputs = a["inputs"]
        tools = AnalysisTools(inputs, a["kind"], journal)
        selected = lambda name, args: dict(call(name, args), call_id=uuid4().hex)
        cases = [r for r, v in inputs["references"].items() if v["kind"] == "case"]
        case = next(
            (r for r in cases if len(inputs["references"][r]["body"]["customer_ids"]) >= 3),
            cases[0],
        )
        refs = [case]
        if a["kind"] == "executive":
            refs += [inputs["scenario_reference"], inputs["management_reference"]]
        claim = lambda text, cites: dict(text="SIMULATED SDK: " + text, citations=cites)
        output = dict(
            observations=[
                claim(
                    "Saved comparisons and human workflow records are available; department-wide productivity is not measured.",
                    [inputs["overview_reference"]],
                )
            ],
            hypotheses=[
                claim(
                    "Shared pricing characteristics may merit a configuration check; causation is unproven.",
                    [case],
                )
            ],
            recommendations=[
                claim(
                    (
                        "Review the shared discrepancy evidence with the responsible billing owner before expanding."
                        if a["kind"] == "management"
                        else "Consider a bounded pilot only after validating workload, costs and authority controls."
                    ),
                    refs,
                )
            ],
            limitations=[
                "SIMULATED SDK: source review is incomplete; staffing/ROI are assumptions and no collections or external assignments occurred."
            ],
            stance="not_applicable" if a["kind"] == "management" else "more_validation_needed",
        )
        script = [
            FakeResponse([selected("get_analysis_overview", {})]),
            FakeResponse([selected("get_analysis_reference", dict(reference_id=r)) for r in refs]),
            FakeResponse([selected("save_analysis", output)]),
            FakeResponse([]),
        ]
        if scenario == "api_failure":
            script = [RuntimeError("sensitive provider detail must not escape")]
        if scenario == "no_result":
            script = [FakeResponse([])]
        if scenario == "incomplete":
            script = [FakeResponse([], status="incomplete")]
        if scenario == "invalid_citation":
            script = [FakeResponse([selected("save_analysis", output)]), FakeResponse([])]
        client = FakeClient(script)
        if clients is not None:
            clients.append(client)
        rates = a["pricing_verification"]["rates"]
        limits = Limits(
            max_tool_calls=35,
            max_responses=40,
            max_seconds=180,
            max_cost_usd=Decimal("1"),
            input_usd_per_million=Decimal(rates["input_price"]),
            output_usd_per_million=Decimal(rates["output_price"]),
            cached_input_usd_per_million=Decimal(rates["cached_input_price"]),
            service_tier="default",
        )
        return Investigator(
            client,
            "simulated-enterprise-analysis",
            tools,
            journal,
            limits,
            instructions=INSTRUCTIONS,
        ).run("SIMULATED SDK " + a["kind"] + " analysis")


class EnterpriseTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = test_local_session.LocalSessionTests.asyncTearDown
    payload = test_local_session.LocalSessionTests.payload
    settled = test_local_session.LocalSessionTests.settled
    decision = test_local_session.LocalSessionTests.decision
    register = test_workflow.WorkflowTests.register
    action = test_workflow.WorkflowTests.action
    submit = test_workflow.WorkflowTests.submit
    resolved = test_workflow.WorkflowTests.resolved
    continue_run = test_workflow.WorkflowTests.continue_run

    async def asyncSetUp(self):
        await test_local_session.LocalSessionTests.asyncSetUp(self)
        self.enterprise = self.app.state.store.enterprise
        self.clients = []
        self.enterprise.runner = lambda a: simulated_analysis(
            self.enterprise, a, getattr(self, "analysis_scenario", "success"), self.clients
        )

    def simulated_runner(self, run_id, data, request):
        if hasattr(data, "authority"):
            return test_workflow.run_simulated_continuation(
                self.app.state.store, run_id, data, request
            )
        return enterprise_root_runner(self.app.state.store, run_id, data, request)

    def age(self):
        store = self.app.state.store
        for m in store.metadata():
            if (
                datetime.now(timezone.utc) - datetime.fromisoformat(m["created_at"])
            ).total_seconds() < 3600:
                m["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
                store.write_meta(m)
        with self.enterprise.database() as cur:
            for a in self.enterprise.analyses():
                a["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
                cur.execute("UPDATE analyses SET body=? WHERE id=?", (json.dumps(a), a["id"]))

    async def launch_analysis(self, run, kind="management", key=None, age=True):
        if age:
            self.age()
        overview = (
            await self.client.get("/api/enterprise", params={"root_run_id": run["id"]})
        ).json()
        body = dict(
            idempotency_key=key or str(uuid4()),
            acknowledge_paid=True,
            kind=kind,
            root_run_id=run["id"],
            expected_revision=overview["analysis_revisions"][kind],
        )
        response = await self.client.post(
            "/api/enterprise/analyses", headers=self.headers, json=body
        )
        self.assertEqual(response.status_code, 202, response.text)
        for _ in range(150):
            detail = await self.client.get("/api/enterprise/analyses/" + response.json()["id"])
            self.assertEqual(detail.status_code, 200, detail.text)
            if detail.json()["status"] not in ("queued", "running"):
                return detail.json(), body
            await asyncio.sleep(0.01)
        self.fail("Simulated enterprise analysis did not finish")

    async def management_decision(self, a, action="follow_up"):
        body = dict(
            idempotency_key=str(uuid4()),
            recommendation_index=0,
            expected_revision=a["input_revision"],
            action=action,
            rationale="SIMULATED human: prioritize source-backed verification before treating correlation as a proven cause.",
            owner="Billing Configuration Team" if a["kind"] == "management" else None,
            supporting_references=a["result"]["recommendations"][0]["citations"],
        )
        result = await self.client.post(
            "/api/enterprise/analyses/" + a["id"] + "/decisions", headers=self.headers, json=body
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json(), body

    async def test_management_grounded_shared_metrics_and_decision_persistence(self):
        run = await self.settled()
        overview = (await self.client.get("/api/enterprise")).json()
        op = overview["operational"]
        self.assertEqual(op["metrics"]["customers_screened"], 40)
        self.assertEqual(op["metrics"]["findings_verified"], 2)
        self.assertGreater(op["metrics"]["screened_candidates_without_findings"], 0)
        self.assertTrue(any(len(g["customer_ids"]) >= 3 for g in op["patterns"]))
        self.assertGreater(op["financial"]["unquantified_cases"], 0)
        self.assertIn("Single-operator", op["limitations"][0])
        a, body = await self.launch_analysis(run)
        self.assertEqual(a["status"], "completed", a)
        self.assertTrue(a["current"])
        for group in ("observations", "hypotheses", "recommendations"):
            self.assertTrue(
                all(set(c["citations"]) <= set(a["references"]) for c in a["result"][group])
            )
        self.assertEqual(self.clients[0].requests[0]["model"], "simulated-enterprise-analysis")
        self.assertEqual(
            {t["name"] for t in self.clients[0].requests[0]["tools"]},
            {"get_analysis_overview", "get_analysis_reference", "save_analysis"},
        )
        d, request = await self.management_decision(a)
        self.assertEqual(d["persona"]["name"], "Sarah Chen")
        self.assertEqual(d["reviewer"], "Local Test Operator")
        replay = await self.client.post(
            "/api/enterprise/analyses/" + a["id"] + "/decisions", headers=self.headers, json=request
        )
        self.assertEqual(replay.json()["id"], d["id"])
        self.assertEqual(len(self.enterprise.decisions()), 1)
        self.assertIn("no external", d["scope"])
        child_inputs = self.enterprise.inputs(run["id"], "executive")
        self.assertEqual(child_inputs["management"]["decisions"][0]["id"], d["id"])
        await self.lifespan.__aexit__(None, None, None)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.assertEqual(self.enterprise.decisions()[0]["id"], d["id"])

    async def test_executive_scenario_and_connected_management_recommendation(self):
        run = await self.settled()
        a, _ = await self.launch_analysis(run)
        d, _ = await self.management_decision(a)
        default = self.enterprise.scenario()
        out = default["outputs"]
        self.assertEqual(out["recurring_annual_net_benefit_cad"], "85000.00")
        self.assertEqual(out["redesigned_recurring_annual_cad"], "95000.00")
        self.assertEqual(out["operating_cost_reduction_percent"], "47.22")
        body = dict(
            expected_epoch=self.enterprise.epoch(),
            expected_version=0,
            scenario=dict(implementation_total_cad="50000", teams=2),
        )
        scenario = await self.client.put(
            "/api/enterprise/scenario", headers=self.headers, json=body
        )
        self.assertEqual(scenario.status_code, 200, scenario.text)
        self.assertEqual(
            scenario.json()["outputs"]["recurring_annual_net_benefit_cad"], "170000.00"
        )
        self.assertEqual(scenario.json()["outputs"]["first_year_net_benefit_cad"], "120000.00")
        executive, _ = await self.launch_analysis(run, "executive")
        self.assertEqual(executive["status"], "completed", executive)
        self.assertTrue(
            any(
                r["kind"] == "persisted_management_context"
                and r["body"]["decisions"][0]["id"] == d["id"]
                for r in executive["references"].values()
            )
        )
        decision, _ = await self.management_decision(executive, "request_validation")
        self.assertEqual(decision["persona"]["name"], "Robert Mitchell")
        self.assertIn("no external", decision["scope"])

    async def test_financial_scenarios_negative_zero_payback_and_strict_input(self):
        self.assertIsNone(
            roi(Scenario(traditional_employment_cad="0"))["operating_cost_reduction_percent"]
        )
        self.assertIsNone(roi(Scenario(redesigned_employment_cad="200000"))["payback_months"])
        self.assertEqual(roi(Scenario(implementation_total_cad="50000"))["payback_months"], "7.06")
        self.assertEqual(
            roi(Scenario(assumed_workload_reduction_percent="70"))[
                "recurring_annual_net_benefit_cad"
            ],
            "85000.00",
        )
        for scenario in (
            {"teams": 1.5},
            {"traditional_employment_cad": "NaN"},
            {"annual_software_cad": "-1"},
            {"basis": "measured"},
            {"assumed_workload_reduction_percent": "101"},
        ):
            response = await self.client.put(
                "/api/enterprise/scenario",
                headers=self.headers,
                json=dict(
                    expected_epoch=self.enterprise.epoch(), expected_version=0, scenario=scenario
                ),
            )
            self.assertEqual(response.status_code, 422, response.text)

    async def test_paid_authorization_csrf_stale_scope_and_shared_rate_limits(self):
        run = await self.settled()
        overview = (await self.client.get("/api/enterprise")).json()
        body = dict(
            idempotency_key=str(uuid4()),
            acknowledge_paid=True,
            kind="management",
            root_run_id=run["id"],
            expected_revision=overview["analysis_revisions"]["management"],
        )
        self.assertEqual(
            (await self.client.post("/api/enterprise/analyses", json=body)).status_code, 403
        )
        self.assertEqual(
            (
                await self.client.post(
                    "/api/enterprise/analyses",
                    headers=self.headers,
                    json=body | dict(acknowledge_paid=False),
                )
            ).status_code,
            422,
        )
        self.assertEqual(
            (
                await self.client.post("/api/enterprise/analyses", headers=self.headers, json=body)
            ).status_code,
            429,
        )
        self.age()
        body["expected_revision"] = "0" * 64
        self.assertEqual(
            (
                await self.client.post("/api/enterprise/analyses", headers=self.headers, json=body)
            ).status_code,
            409,
        )
        a, request = await self.launch_analysis(run)
        replay = await self.client.post(
            "/api/enterprise/analyses", headers=self.headers, json=request
        )
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json()["id"], a["id"])
        self.assertEqual(len(self.clients), 1)
        bad = await self.client.post(
            "/api/enterprise/analyses", headers=self.headers, json=request | dict(kind="executive")
        )
        self.assertEqual(bad.status_code, 409)
        launch = await self.client.post("/api/runs", headers=self.headers, json=self.payload())
        self.assertEqual(launch.status_code, 429)

    async def test_source_and_scenario_changes_invalidate_decisions(self):
        run = await self.settled()
        a, _ = await self.launch_analysis(run, "executive")
        response = await self.client.put(
            "/api/enterprise/scenario",
            headers=self.headers,
            json=dict(
                expected_epoch=self.enterprise.epoch(),
                expected_version=0,
                scenario=dict(implementation_total_cad="1"),
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.enterprise.detail(a["id"])["current"])
        body = dict(
            idempotency_key=str(uuid4()),
            recommendation_index=0,
            expected_revision=a["input_revision"],
            action="approve_pilot",
            rationale="SIMULATED validation rationale",
            supporting_references=a["result"]["recommendations"][0]["citations"],
        )
        self.assertEqual(
            (
                await self.client.post(
                    "/api/enterprise/analyses/" + a["id"] + "/decisions",
                    headers=self.headers,
                    json=body,
                )
            ).status_code,
            409,
        )
        path = self.settings.data / "invoices.json"
        path.write_text(path.read_text() + "\n")
        op = (await self.client.get("/api/enterprise")).json()["operational"]
        self.assertEqual(Decimal(op["financial"]["potential_receivables_cad"]), 0)
        self.assertTrue(any("stale" in s for s in op["limitations"]))

    async def test_scope_tools_reject_unknown_unread_citations_and_no_saved_result(self):
        run = await self.settled()
        self.age()
        inputs = self.enterprise.inputs(run["id"], "management")
        with Journal(self.root / "analysis-tools") as journal:
            tools = AnalysisTools(inputs, "management", journal)
            for name, args in [
                ("get_document", {"document_id": "sealed_answer_key.json"}),
                ("get_analysis_reference", {"reference_id": "../sealed_answer_key.json"}),
                ("approve", {}),
            ]:
                with self.assertRaises(ToolError):
                    tools.execute(name, args)
        for scenario in ("invalid_citation", "no_result", "incomplete", "api_failure"):
            self.analysis_scenario = scenario
            a, _ = await self.launch_analysis(run)
            self.assertNotEqual(a["status"], "completed", a)
            self.assertNotIn("sensitive provider", json.dumps(a))

    async def test_active_work_blocks_other_personas_reset_and_scenario(self):
        run = await self.settled()
        self.app.state.store.active = "analysis:test"
        preview = (await self.client.get("/api/admin/reset")).json()
        self.assertTrue(preview["active"])
        reset = await self.client.post(
            "/api/admin/reset",
            headers=self.headers,
            json=dict(
                acknowledge_archive=True,
                confirmation="ARCHIVE DEMO HISTORY",
                expected_epoch=preview["epoch"],
            ),
        )
        self.assertEqual(reset.status_code, 409)
        scenario = await self.client.put(
            "/api/enterprise/scenario",
            headers=self.headers,
            json=dict(expected_epoch=preview["epoch"], expected_version=0, scenario={}),
        )
        self.assertEqual(scenario.status_code, 409)
        self.app.state.store.active = None

    async def test_archive_reset_preserves_dataset_admin_and_all_journals(self):
        run = await self.settled()
        a, _ = await self.launch_analysis(run)
        await self.management_decision(a)
        data_before = (self.settings.data / "invoices.json").read_bytes()
        pricing = (self.settings.root / "admin/pricing.json").read_bytes()
        preview = (await self.client.get("/api/admin/reset")).json()
        bad = await self.client.post(
            "/api/admin/reset",
            headers=self.headers,
            json=dict(
                acknowledge_archive=False,
                confirmation="ARCHIVE DEMO HISTORY",
                expected_epoch=preview["epoch"],
            ),
        )
        self.assertEqual(bad.status_code, 422)
        result = await self.client.post(
            "/api/admin/reset",
            headers=self.headers,
            json=dict(
                acknowledge_archive=True,
                confirmation="ARCHIVE DEMO HISTORY",
                expected_epoch=preview["epoch"],
            ),
        )
        self.assertEqual(result.status_code, 200, result.text)
        archive = self.settings.root / "archives" / result.json()["archive_id"]
        self.assertTrue((archive / run["id"] / "events.sqlite3").exists())
        self.assertTrue((archive / "enterprise.sqlite3").exists())
        self.assertTrue((archive / "analyses" / a["id"] / "events.sqlite3").exists())
        self.assertEqual((self.settings.data / "invoices.json").read_bytes(), data_before)
        self.assertEqual((self.settings.root / "admin/pricing.json").read_bytes(), pricing)
        self.assertEqual(self.app.state.store.metadata(), [])
        self.assertEqual(self.enterprise.analyses(), [])
        self.assertEqual(self.enterprise.decisions(), [])
        self.assertNotEqual(self.enterprise.epoch(), preview["epoch"])
        self.assertEqual(self.enterprise.scenario()["version"], 0)
        self.assertTrue((self.settings.root / ".server.lock").exists())
        self.assertEqual(len(self.clients), 1)
        with closing(sqlite3.connect(archive / "enterprise.sqlite3")) as db:
            with closing(db.cursor()) as c:
                self.assertEqual(
                    c.execute("SELECT COUNT(*) FROM enterprise_decisions").fetchone()[0], 1
                )
        # A recent archived analysis still enforces the global paid throttle after reset.
        self.assertEqual(
            (
                await self.client.post("/api/runs", headers=self.headers, json=self.payload())
            ).status_code,
            429,
        )

    async def test_continuation_replaces_ambiguous_case_without_double_counting(self):
        run, record = await self.resolved()
        before = self.enterprise.overview(run["id"])["operational"]
        child = await self.continue_run(run, record)
        self.assertEqual(child["status"], "completed", child)
        op = self.enterprise.overview(run["id"])["operational"]
        self.assertEqual(op["metrics"]["customers_screened"], 40)
        self.assertEqual(len([c for c in op["cases"] if "C007" in c["customer_ids"]]), 1)
        self.assertEqual(
            next(c for c in op["cases"] if "C007" in c["customer_ids"])["run_id"], child["id"]
        )
        difference = Decimal(child["findings"][0]["comparisons"][0]["difference_cad"])
        self.assertEqual(
            Decimal(op["financial"]["potential_receivables_cad"]),
            Decimal(before["financial"]["potential_receivables_cad"]) + max(difference, 0),
        )

    async def test_reset_rollback_and_recovery_blocking(self):
        from pathlib import Path

        run = await self.settled()
        a, _ = await self.launch_analysis(run)
        original_replace = Path.replace

        def failed_move(source, target):
            if source.name == "enterprise.sqlite3":
                raise OSError("simulated Windows rename failure")
            return original_replace(source, target)

        preview = (await self.client.get("/api/admin/reset")).json()
        body = dict(
            acknowledge_archive=True,
            confirmation="ARCHIVE DEMO HISTORY",
            expected_epoch=preview["epoch"],
        )
        with patch.object(Path, "replace", failed_move):
            response = await self.client.post("/api/admin/reset", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertTrue((self.settings.root / run["id"] / "events.sqlite3").exists())
        self.assertEqual(len(self.enterprise.analyses()), 1)
        self.assertFalse((self.settings.root / ".reset-recovery.json").exists())

        def failed_restore(source, target):
            if source.name == "enterprise.sqlite3" or (
                source.name == "index" and source.parent != self.settings.root
            ):
                raise OSError("simulated recovery failure")
            return original_replace(source, target)

        with patch.object(Path, "replace", failed_restore):
            response = await self.client.post("/api/admin/reset", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 503, response.text)
        marker = self.settings.root / ".reset-recovery.json"
        self.assertTrue(marker.exists())
        self.assertFalse(self.app.state.store.accepting_launches)
        write = await self.client.put(
            "/api/admin/pricing",
            headers=self.headers,
            json=dict(
                input_price="2",
                cached_input_price=".1",
                output_price="10",
                checked_current_official_rates=True,
            ),
        )
        self.assertEqual(write.status_code, 503)
        self.assertEqual(len(self.clients), 1)

    async def test_interrupted_analysis_never_resumes_and_roles_are_not_rbac(self):
        run = await self.settled()
        a, _ = await self.launch_analysis(run)
        with self.enterprise.database() as cur:
            row = next(r for r in self.enterprise.analyses() if r["id"] == a["id"])
            row["status"] = "running"
            cur.execute("UPDATE analyses SET body=? WHERE id=?", (json.dumps(row), row["id"]))
        await self.lifespan.__aexit__(None, None, None)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        restored = self.enterprise.analyses()[0]
        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["reason"], "server_restart_no_resume")
        self.assertEqual(len(self.clients), 1)
        session = (await self.client.get("/api/session")).json()
        self.headers = {"x-csrf-token": session["csrf_token"]}
        overview = (await self.client.get("/api/enterprise")).json()
        self.assertEqual(
            {p["name"] for p in overview["personas"].values()},
            {"Maya Tremblay", "Sarah Chen", "Robert Mitchell"},
        )
        self.assertFalse(session["identity_verified"])

    async def test_recorded_mode_never_exposes_live_analysis_or_allows_mutations(self):
        run = await self.settled()
        a, _ = await self.launch_analysis(run)
        self.settings.mode = "recorded"
        # No genuine recording is imported by the simulated test fixture.
        overview = await self.client.get("/api/enterprise")
        self.assertEqual(overview.status_code, 200, overview.text)
        self.assertEqual(overview.json()["analyses"], [])
        self.assertEqual(overview.json()["decisions"], [])
        self.assertIsNone(overview.json()["operational"]["root_run_id"])
        self.assertEqual(
            (await self.client.get("/api/enterprise/analyses/" + a["id"])).status_code, 403
        )
        self.assertEqual((await self.client.get("/api/admin/reset")).status_code, 403)
        for path in (
            "/api/enterprise/analyses",
            "/api/admin/reset",
            "/api/enterprise/analyses/" + a["id"] + "/decisions",
        ):
            self.assertEqual(
                (await self.client.post(path, headers=self.headers, json={})).status_code, 403
            )
        self.settings.mode = "operator"

    async def test_analysis_runtime_cost_request_and_tool_limits(self):
        run = await self.settled()
        self.age()
        inputs = self.enterprise.inputs(run["id"], "management")
        for limit in ("cost", "responses", "tools", "time"):
            with Journal(self.root / ("limit-" + limit)) as journal:
                tools = AnalysisTools(inputs, "management", journal)
                script = [
                    FakeResponse([call("get_analysis_overview", {})]),
                    FakeResponse([call("get_analysis_overview", {})]),
                    FakeResponse([]),
                ]
                client = FakeClient(script)
                values = dict(
                    max_tool_calls=35,
                    max_responses=40,
                    max_seconds=180,
                    max_cost_usd=Decimal("1"),
                    input_usd_per_million=Decimal("2"),
                    output_usd_per_million=Decimal("10"),
                )
                if limit == "cost":
                    values["max_cost_usd"] = Decimal(".00000001")
                if limit == "responses":
                    values["max_responses"] = 1
                if limit == "tools":
                    values["max_tool_calls"] = 1
                if limit == "time":
                    values["max_seconds"] = 0.1
                clock = (
                    (lambda counter=iter([0, 1, 2, 3, 4, 5]): next(counter))
                    if limit == "time"
                    else __import__("time").monotonic
                )
                report = Investigator(
                    client,
                    "simulated-limit-test",
                    tools,
                    journal,
                    Limits(**values),
                    clock=clock,
                    instructions=INSTRUCTIONS,
                ).run("SIMULATED limits")
                self.assertEqual(report["status"], "incomplete")
                self.assertIn(
                    report["reason"],
                    ("estimated_cost_limit", "response_limit", "tool_call_limit", "time_limit"),
                )
                if limit in ("cost", "time"):
                    self.assertEqual(client.requests, [])
        self.assertEqual(self.enterprise.analyses(), [])

    async def test_decisions_require_current_cited_recommendations_and_correct_action(self):
        run = await self.settled()
        a, _ = await self.launch_analysis(run)
        base = dict(
            idempotency_key=str(uuid4()),
            recommendation_index=0,
            expected_revision=a["input_revision"],
            action="prioritize",
            rationale="SIMULATED decision with real cited input binding.",
            supporting_references=a["result"]["recommendations"][0]["citations"],
        )
        endpoint = "/api/enterprise/analyses/" + a["id"] + "/decisions"
        for changes, code in [
            (dict(rationale=""), 422),
            (dict(supporting_references=["invented-ref"]), 422),
            (dict(action="approve_pilot"), 422),
            (dict(expected_revision="0" * 64), 409),
            (dict(action="assign_owner", owner=""), 422),
        ]:
            self.assertEqual(
                (
                    await self.client.post(endpoint, headers=self.headers, json=base | changes)
                ).status_code,
                code,
            )
        self.assertEqual((await self.client.post(endpoint, json=base)).status_code, 403)
        result = await self.client.post(endpoint, headers=self.headers, json=base)
        self.assertEqual(result.status_code, 200, result.text)
        changed = await self.client.post(
            endpoint,
            headers=self.headers,
            json=base | dict(rationale="Different meaning with reused idempotency"),
        )
        self.assertEqual(changed.status_code, 409)
        duplicate = await self.client.post(
            endpoint, headers=self.headers, json=base | dict(idempotency_key=str(uuid4()))
        )
        self.assertEqual(duplicate.status_code, 409)

    async def test_overlapping_verified_findings_do_not_double_financial_totals(self):
        run = await self.settled()
        before = self.enterprise.overview(run["id"])["operational"]
        path = self.settings.root / run["id"] / "report.json"
        report = json.loads(path.read_text())
        group = next(f for f in report["findings"] if len(f["customer_ids"]) >= 3)
        duplicate = dict(
            group,
            finding_id="test-overlap",
            customer_ids=[group["customer_ids"][0]],
            comparisons=[group["comparisons"][0]],
            pattern=None,
        )
        report["findings"].append(duplicate)
        path.write_text(json.dumps(report))
        after = self.enterprise.overview(run["id"])["operational"]
        self.assertEqual(
            after["financial"]["potential_receivables_cad"],
            before["financial"]["potential_receivables_cad"],
        )
        self.assertEqual(len(after["patterns"]), 1)

    async def test_human_history_reaches_analysis_but_never_authorizes_export(self):
        run = await self.settled()
        body = self.action(run, action="escalate")
        response = await self.submit(run, body)
        self.assertEqual(response.status_code, 200)
        self.age()
        inputs = self.enterprise.inputs(run["id"], "management")
        history = next(
            r["body"]
            for r in inputs["references"].values()
            if r["kind"] == "persisted_human_workflow"
        )
        self.assertEqual(
            history["contributions"][0]["clarification_owner"], "Contract Administration"
        )
        self.assertEqual(
            (
                await self.client.get(f"/api/runs/{run['id']}/findings/finding-C005/export")
            ).status_code,
            403,
        )
        a, _ = await self.launch_analysis(run)
        await self.management_decision(a)
        self.assertEqual(
            (
                await self.client.get(f"/api/runs/{run['id']}/findings/finding-C005/export")
            ).status_code,
            403,
        )

    async def test_archived_and_cross_workflow_paid_keys_never_start_another_request(self):
        run = await self.settled()
        self.age()
        op = (await self.client.get("/api/enterprise")).json()
        key = self.app.state.store.meta(run["id"])["idempotency_key"]
        body = dict(
            idempotency_key=key,
            acknowledge_paid=True,
            kind="management",
            root_run_id=run["id"],
            expected_revision=op["analysis_revisions"]["management"],
        )
        self.assertEqual(
            (
                await self.client.post("/api/enterprise/analyses", headers=self.headers, json=body)
            ).status_code,
            409,
        )
        a, request = await self.launch_analysis(run)
        preview = (await self.client.get("/api/admin/reset")).json()
        reset = await self.client.post(
            "/api/admin/reset",
            headers=self.headers,
            json=dict(
                acknowledge_archive=True,
                confirmation="ARCHIVE DEMO HISTORY",
                expected_epoch=preview["epoch"],
            ),
        )
        self.assertEqual(reset.status_code, 200)
        old_root = self.payload()
        old_root["idempotency_key"] = key
        self.assertEqual(
            (await self.client.post("/api/runs", headers=self.headers, json=old_root)).status_code,
            409,
        )
        self.assertEqual(
            (
                await self.client.post(
                    "/api/enterprise/analyses", headers=self.headers, json=request
                )
            ).status_code,
            409,
        )
        self.assertEqual(len(self.clients), 1)

    async def test_dismissal_retains_deterministically_verified_financial_difference(self):
        run = await self.settled()
        before = self.enterprise.overview()["operational"]["financial"]
        finding = next(f for f in run["findings"] if f["finding_id"] == "finding-C005")
        body = dict(
            idempotency_key=uuid4().hex,
            expected_revision=run["data_revision"],
            expected_version=finding["version"],
            action="dismiss",
            rationale="SIMULATED: reject the interpretation while preserving the deterministic comparison for audit.",
        )
        response = await self.client.post(
            f"/api/runs/{run['id']}/findings/finding-C005/interventions",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(response.status_code, 200, response.text)
        after = self.enterprise.overview()["operational"]
        self.assertEqual(
            after["financial"]["potential_credits_cad"], before["potential_credits_cad"]
        )
        self.assertEqual(
            next(c["state"] for c in after["cases"] if c["finding_id"] == "finding-C005"),
            "dismissed",
        )

    async def test_failed_enterprise_startup_closes_store_lock_handle(self):
        with self.enterprise.database():
            pass
        before = self.enterprise.path.read_bytes()
        await self.lifespan.__aexit__(None, None, None)
        self.enterprise.path.write_bytes(b"not a sqlite database")
        self.lifespan = self.app.router.lifespan_context(self.app)
        with self.assertRaises(sqlite3.DatabaseError):
            await self.lifespan.__aenter__()
        self.assertIsNone(self.app.state.store.owner_fd)
        self.assertFalse((self.settings.root / ".server.lock").exists())
        self.enterprise.path.write_bytes(before)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
