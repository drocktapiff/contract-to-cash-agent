"""Human resolution + new scoped Responses orchestration. All SDK responses simulated."""

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_api
import test_local_session
from test_agent import FakeClient, FakeResponse, call
from contract_to_cash.agent.events import Journal
from contract_to_cash.agent.runtime import Investigator, Limits
from contract_to_cash.agent.tools import ToolError
from contract_to_cash.billing_engine import expected_amount
from contract_to_cash.web.resolution_evidence import (
    register_evidence,
    registered_evidence,
    scoped_data,
    select_evidence,
)
from contract_to_cash.web.workflow import interventions
from contract_to_cash.web.store import Store


def authority_assertion(data, cid="C007", choose=0):
    changes = [r for r in data.changes[cid] if r["kind"] == "set_price" and r["status"] == "signed"]
    governing = changes[choose]["amendment_id"]
    superseded = [r["amendment_id"] for r in changes if r["amendment_id"] != governing]
    contract = data.customers[cid]["contract_id"]
    text = f"SIMULATED TEST DOCUMENT, NOT REAL CONTRACT AUTHORITY. {cid}, {contract}, {data.period}: {governing} governs; {', '.join(superseded)} is superseded for this period. Written confirmation from the test contract administrator."
    return dict(
        customer_id=cid,
        contract_id=contract,
        period=data.period,
        base_revision=data.revision,
        governing_amendment_id=governing,
        superseded_amendment_ids=superseded,
        issuer="Simulated Contract Authority",
        issuer_authority="TEST ONLY: responsible contract administrator's documented authority verified out of band.",
        source_reference="TEST ONLY authority record / test-clarification-001",
        confirmation_text=text,
    )


def run_simulated_continuation(settings, run_id, data, request, scenario="success", clients=None):
    with Journal(settings.root / run_id) as journal:
        journal.run_id = run_id
        tools = Store.investigation_tools(data, journal)
        cid = next(iter(data.customers))
        selected = lambda name, args: dict(call(name, args), call_id=uuid4().hex)
        script = [
            FakeResponse([selected("get_customer_evidence", dict(customer_ids=[cid]))]),
            FakeResponse(
                [
                    selected(
                        "submit_finding",
                        dict(
                            customer_ids=[cid],
                            evidence_ids=sorted(tools._required(cid)),
                            state="verified",
                            rationale="SIMULATED SDK: revised authority and original documents support the Python comparison.",
                        ),
                    )
                ]
            ),
            FakeResponse(
                [
                    selected(
                        "recommend_next_action",
                        dict(
                            finding_id="finding-" + cid,
                            evidence_ids=sorted(tools._required(cid)),
                            problem="SIMULATED SDK: revised comparison needs review.",
                            suggested_action="Review the revised supporting evidence before any export.",
                            reasoning="Python compared the existing invoice with the authority-backed terms.",
                            uncertainty="No billing correction has been authorized.",
                        ),
                    ),
                    selected(
                        "request_human_review", dict(finding_id="finding-" + cid, action="export")
                    ),
                ]
            ),
            FakeResponse([]),
        ]
        if scenario == "api_failure":
            script = [RuntimeError("sensitive provider failure")]
        elif scenario == "incomplete":
            script = [FakeResponse([], status="incomplete")]
        elif scenario == "out_of_scope":
            script = [
                FakeResponse([selected("get_customer_evidence", dict(customer_ids=["C001"]))]),
                FakeResponse([]),
            ]
        elif scenario == "interrupted":
            script = [
                FakeResponse([selected("get_customer_evidence", dict(customer_ids=[cid]))]),
                RuntimeError("interrupted"),
            ]
        client = FakeClient(script)
        if clients is not None:
            clients.append(client)
        limits = Limits(
            max_tool_calls=request.max_tool_calls,
            max_responses=request.max_responses,
            max_seconds=request.max_seconds,
            max_cost_usd=request.max_cost_usd,
            input_usd_per_million=request.input_price,
            output_usd_per_million=request.output_price,
            cached_input_usd_per_million=request.cached_input_price,
            service_tier="default",
        )
        return Investigator(client, "simulated-phase32", tools, journal, limits).run(
            request.objective
        )


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_local_session.LocalSessionTests.asyncSetUp
    asyncTearDown = test_local_session.LocalSessionTests.asyncTearDown
    payload = test_local_session.LocalSessionTests.payload
    settled = test_local_session.LocalSessionTests.settled
    decision = test_local_session.LocalSessionTests.decision

    def simulated_runner(self, run_id, data, request):
        if hasattr(data, "authority"):
            return run_simulated_continuation(
                self.settings,
                run_id,
                data,
                request,
                getattr(self, "scenario", "success"),
                getattr(self, "clients", None),
            )
        return test_api.ApiTests.simulated_runner(self, run_id, data, request)

    def register(self, choose=0):
        data = self.app.state.store.public_data()
        assertion = authority_assertion(data, choose=choose)
        return register_evidence(
            self.settings.root,
            data,
            assertion,
            "Test source verifier",
            True,
            assertion["confirmation_text"],
        )

    def action(self, run, action="resolve", record=None, **changes):
        f = next(f for f in run["findings"] if f["finding_id"] == "finding-C007")
        body = dict(
            idempotency_key=uuid4().hex,
            expected_revision=run["data_revision"],
            expected_version=f["version"],
            expected_workflow_version=0,
            action=action,
            rationale="TEST: reviewed the source and issuer authority; retain this explicit business judgment.",
        )
        if action == "resolve" and record:
            body.update(
                evidence_id=record["evidence_id"],
                governing_amendment_id=record["payload"]["assertion"]["governing_amendment_id"],
            )
        if action == "escalate":
            body.update(
                clarification_owner="Contract Administration",
                missing_information="Written governing amendment confirmation for this billing period",
            )
        return body | changes

    async def submit(self, run, body):
        return await self.client.post(
            f"/api/runs/{run['id']}/findings/finding-C007/interventions",
            headers=self.headers,
            json=body,
        )

    async def resolved(self):
        run = await self.settled()
        record = self.register()
        response = await self.submit(run, self.action(run, record=record))
        self.assertEqual(response.status_code, 200, response.text)
        return run, response.json()["intervention"]

    async def continue_run(self, run, intervention, key=None, expected=202):
        # Only tests age the original metadata to exercise the real shared launch throttle.
        store = self.app.state.store
        for meta in store.metadata():
            if (
                datetime.now(timezone.utc) - datetime.fromisoformat(meta["created_at"])
            ).total_seconds() < 60:
                meta["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
                store.write_meta(meta)
        response = await self.client.post(
            f"/api/runs/{run['id']}/continue",
            headers=self.headers,
            json=dict(
                idempotency_key=key or uuid4().hex,
                intervention_id=intervention["id"],
                acknowledge_paid=True,
            ),
        )
        self.assertEqual(response.status_code, expected, response.text)
        if expected != 202:
            return response
        for _ in range(200):
            child = (await self.client.get("/api/runs/" + response.json()["id"])).json()
            if child["status"] not in ("queued", "running"):
                return child
            await asyncio.sleep(0.01)
        self.fail("Simulated continuation did not settle")

    async def test_documented_resolution_and_scoped_deterministic_continuation(self):
        self.clients = []
        run, record = await self.resolved()
        directory = self.app.state.store.directory(run["id"])
        original_report = (directory / "report.json").read_bytes()
        before = (await self.client.get(f"/api/runs/{run['id']}/outcome")).json()
        self.assertEqual(before["continued_investigations"], [])
        key = uuid4().hex
        child = await self.continue_run(run, record, key)
        self.assertEqual(child["status"], "completed", child)
        self.assertEqual(child["customers_compared"], ["C007"])
        self.assertTrue(child["screening_complete"])  # Only the explicit one-customer scope.
        self.assertEqual(child["continuation"]["parent_run_id"], run["id"])
        self.assertNotEqual(child["data_revision"], run["data_revision"])
        finding = child["findings"][0]
        self.assertTrue(finding["evidence_verified"])
        self.assertIn(record["evidence_id"], finding["evidence_ids"])
        self.assertEqual(finding["recommendation"]["origin"], "model_suggestion")
        data = self.app.state.store.public_data()
        a = record["authority"]["payload"]["assertion"]
        amount = expected_amount(
            data.customers["C007"],
            [
                r
                for r in data.changes["C007"]
                if r["amendment_id"] not in a["superseded_amendment_ids"]
            ],
            data.period,
            data.rows["C007"][0]["usage_quantity"],
        )
        self.assertEqual(Decimal(finding["comparisons"][0]["expected_cad"]), amount)
        self.assertEqual(
            Decimal(finding["comparisons"][0]["difference_cad"]),
            amount - Decimal(data.rows["C007"][0]["billed_amount"]),
        )
        self.assertEqual((directory / "report.json").read_bytes(), original_report)
        self.assertIn("original_finding", self.clients[0].requests[0]["input"][0]["content"])
        evidence = (
            await self.client.get(f"/api/runs/{child['id']}/findings/finding-C007/evidence")
        ).json()
        self.assertIn(record["evidence_id"], [e["document_id"] for e in evidence])
        self.assertTrue(all(r["status"] == "pending" for r in child["reviews"]))
        endpoint = f"/api/runs/{child['id']}/findings/finding-C007"
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 403)
        approved = await self.client.post(
            endpoint + "/review", headers=self.headers, json=self.decision(child, "finding-C007")
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 200)
        replay = await self.continue_run(run, record, key)
        self.assertEqual(replay["id"], child["id"])
        self.assertEqual(len(self.clients), 1)
        summary = (await self.client.get(f"/api/runs/{run['id']}/outcome")).json()
        self.assertEqual(len(summary["human_contributions"]), 1)
        self.assertEqual(summary["continued_investigations"][0]["billing_changes"], 0)
        events = self.app.state.store.events(run["id"])
        self.assertTrue(any(e["type"] == "human_resolution.resolve" for e in events))
        self.assertTrue(any(e["type"] == "continuation.authorized" for e in events))

    async def test_unsupported_and_contradictory_resolutions_rejected(self):
        run = await self.settled()
        no_support = await self.submit(run, self.action(run))
        self.assertEqual(no_support.status_code, 422)
        record = self.register()
        mismatch = self.action(
            run,
            record=record,
            governing_amendment_id=record["payload"]["assertion"]["superseded_amendment_ids"][0],
        )
        self.assertEqual((await self.submit(run, mismatch)).status_code, 422)
        self.assertEqual(
            (
                await self.submit(run, self.action(run, record=record, expected_version=99))
            ).status_code,
            409,
        )
        self.assertEqual(interventions(self.app.state.store.directory(run["id"])), [])
        with self.assertRaises(ValueError):
            self.register(choose=1)

    async def test_escalation_then_resolution_and_replayed_submissions(self):
        run = await self.settled()
        body = self.action(run, action="escalate")
        first = await self.submit(run, body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            (await self.submit(run, body)).json()["intervention"]["id"],
            first.json()["intervention"]["id"],
        )
        self.assertEqual(
            (await self.submit(run, body | dict(rationale="Different decision"))).status_code, 409
        )
        await self.continue_run(run, first.json()["intervention"], expected=409)
        self.assertEqual(len(self.app.state.store.metadata()), 1)
        record = self.register()
        self.assertEqual((await self.submit(run, self.action(run, record=record))).status_code, 409)
        second = await self.submit(
            run, self.action(run, record=record, expected_workflow_version=1)
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(len(second.json()["run"]["interventions"]), 2)
        self.assertEqual(second.json()["run"]["metrics"]["human_interventions"], 2)

    async def test_dismissal_retains_original_and_blocks_old_authorization(self):
        run = await self.settled()
        original = self.app.state.store.directory(run["id"]) / "report.json"
        original_bytes = original.read_bytes()
        response = await self.submit(run, self.action(run, action="dismiss"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(response.json()["run"]["findings"], run["findings"])
        self.assertEqual(
            (
                await self.client.post(
                    f"/api/runs/{run['id']}/findings/finding-C007/review",
                    headers=self.headers,
                    json=self.decision(run, "finding-C007"),
                )
            ).status_code,
            409,
        )
        await self.continue_run(run, response.json()["intervention"], expected=409)

    async def test_api_failure_incomplete_and_repeated_attempt_limits(self):
        run, record = await self.resolved()
        self.scenario = "api_failure"
        one = await self.continue_run(run, record)
        self.assertEqual(one["status"], "incomplete")
        self.assertEqual(one["reason"], "api_failure")
        self.assertFalse(one["metrics"]["cost_accounting_complete"])
        self.assertEqual(one["findings"], [])
        self.scenario = "incomplete"
        two = await self.continue_run(run, record)
        self.assertEqual(two["reason"], "api_response_incomplete")
        # Age beyond the hour to isolate the per-resolution cap from the global rate limit.
        for meta in self.app.state.store.metadata():
            meta["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            self.app.state.store.write_meta(meta)
        self.scenario = "interrupted"
        # Three/hour still permits this after the aging above.
        three = await self.continue_run(run, record)
        self.assertEqual(three["status"], "incomplete")
        await self.continue_run(run, record, expected=429)

    async def test_authority_revocation_or_source_edit_invalidates_export(self):
        run, record = await self.resolved()
        child = await self.continue_run(run, record)
        endpoint = f"/api/runs/{child['id']}/findings/finding-C007"
        approved = await self.client.post(
            endpoint + "/review", headers=self.headers, json=self.decision(child, "finding-C007")
        )
        self.assertEqual(approved.status_code, 200)
        authority = (
            self.settings.root / "admin/resolution-evidence" / (record["evidence_id"] + ".json")
        )
        authority.unlink()
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 409)
        await self.continue_run(run, record, expected=409)

    async def test_paid_confirmation_csrf_rate_limits_and_restart(self):
        run, record = await self.resolved()
        endpoint = f"/api/runs/{run['id']}/continue"
        body = dict(
            idempotency_key=uuid4().hex, intervention_id=record["id"], acknowledge_paid=True
        )
        self.assertEqual((await self.client.post(endpoint, json=body)).status_code, 403)
        self.assertEqual(
            (
                await self.client.post(
                    endpoint, headers=self.headers, json=body | dict(acknowledge_paid=False)
                )
            ).status_code,
            422,
        )
        self.assertEqual(
            (await self.client.post(endpoint, headers=self.headers, json=body)).status_code, 429
        )
        with patch.dict("os.environ", {}, clear=True):
            await self.continue_run(run, record, expected=503)
        store = self.app.state.store
        await self.lifespan.__aexit__(None, None, None)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        session = (await self.client.get("/api/session")).json()
        self.headers = {"x-csrf-token": session["csrf_token"]}
        reloaded = (await self.client.get(f"/api/runs/{run['id']}")).json()
        self.assertEqual(reloaded["interventions"][0]["id"], record["id"])
        self.assertEqual(len(store.metadata()), 1)
        self.assertIsNone(store.active)

    async def test_outside_scope_tools_fail_and_unretrieved_authority_cannot_verify(self):
        run, record = await self.resolved()
        data = scoped_data(self.app.state.store.public_data(), record, record["authority"])
        with Journal(self.root / "scoped-tools") as journal:
            tools = Store.investigation_tools(data, journal)
            for name, args in [
                ("get_contract", {"customer_id": "C001"}),
                ("get_customer_evidence", {"customer_ids": ["C001"]}),
                ("get_document", {"document_id": "CON-C001"}),
            ]:
                with self.assertRaises(ToolError):
                    tools.execute(name, args)
            tools.get_customer_evidence(["C007"])
            tools.documents_seen.remove(record["evidence_id"])
            with self.assertRaises(ToolError):
                tools.submit_finding(
                    ["C007"],
                    sorted(tools._required("C007")),
                    "verified",
                    "TEST cannot verify unread supporting authority",
                )
        self.scenario = "out_of_scope"
        child = await self.continue_run(run, record)
        self.assertEqual(child["customers_compared"], [])
        self.assertGreater(child["metrics"]["tool_failures"], 0)
        self.assertEqual(child["status"], "incomplete")

    async def test_additive_sqlite_schema_and_durable_history(self):
        run = await self.settled()
        path = self.app.state.store.directory(run["id"]) / "events.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            with closing(db.cursor()) as cursor:
                before = cursor.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                self.assertIsNone(
                    cursor.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='human_interventions'"
                    ).fetchone()
                )
        response = await self.submit(run, self.action(run, action="escalate"))
        self.assertEqual(response.status_code, 200)
        with closing(sqlite3.connect(path)) as db:
            with closing(db.cursor()) as cursor:
                self.assertEqual(
                    cursor.execute("SELECT COUNT(*) FROM events").fetchone()[0], before + 1
                )
                self.assertEqual(
                    cursor.execute("SELECT COUNT(*) FROM human_interventions").fetchone()[0], 1
                )
        self.assertEqual(len(self.app.state.store.snapshot(run["id"]).interventions), 1)

    async def test_recommendation_is_evidence_grounded_persisted_and_versioned(self):
        run = await self.settled()
        with Journal(self.root / "recommendations") as journal:
            data = self.app.state.store.public_data()
            tools = Store.investigation_tools(data, journal)
            tools.get_customer_evidence(["C007"])
            fid = "finding-C007"
            args = dict(
                finding_id=fid,
                evidence_ids=sorted(tools._required("C007")),
                problem="SIMULATED SDK: signed terms conflict.",
                suggested_action="Obtain written clarification from the contract authority.",
                reasoning="The two cited signed amendments cannot establish precedence.",
                uncertainty="The governing amendment remains unknown.",
            )
            rec = tools.execute("recommend_next_action", args)
            self.assertEqual(rec["origin"], "model_suggestion")
            original = list(tools.findings[fid]["recommendation_history"])
            with self.assertRaises(ToolError):
                tools.execute(
                    "recommend_next_action", args | dict(evidence_ids=["unretrieved-record"])
                )
            tools.submit_finding(
                ["C007"],
                sorted(tools._required("C007")),
                "proposed",
                "SIMULATED updated hypothesis, uncertainty remains",
            )
            self.assertEqual(
                tools.findings[fid]["recommendation_history"][: len(original)], original
            )
            self.assertEqual(tools.findings[fid]["version"], 2)
            journal.save_report(dict(findings=list(tools.findings.values())))
            saved = json.loads((journal.directory / "report.json").read_text())
            self.assertEqual(saved["findings"][0]["recommendation_history"][1], rec)
        displayed = (await self.client.get(f"/api/runs/{run['id']}")).json()
        conflict = next(f for f in displayed["findings"] if f["finding_id"] == "finding-C007")
        self.assertEqual(conflict["recommendation"]["origin"], "evidence_rule")
        self.assertIn("not model-generated", conflict["recommendation"]["reasoning"])

    async def test_document_integrity_relevance_and_unattested_registration(self):
        data = self.app.state.store.public_data()
        a = authority_assertion(data)
        for changed in (
            a | dict(customer_id="C001"),
            a | dict(base_revision="0" * 64),
            a
            | dict(
                confirmation_text="An unrelated paragraph with no source reference details at all."
            ),
            a | dict(superseded_amendment_ids=[]),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                register_evidence(
                    self.settings.root, data, changed, "Test verifier", True, a["confirmation_text"]
                )
        with self.assertRaises(ValueError):
            register_evidence(
                self.settings.root, data, a, "Test verifier", False, a["confirmation_text"]
            )
        with self.assertRaises(ValueError):
            register_evidence(
                self.settings.root,
                data,
                a,
                "Test verifier",
                True,
                "A different original document unrelated to this confirmation.",
            )
        record = self.register()
        file = self.settings.root / "admin/resolution-evidence" / (record["evidence_id"] + ".json")
        tampered = json.loads(file.read_text())
        tampered["payload"]["assertion"]["governing_amendment_id"] = "made-up"
        file.write_text(json.dumps(tampered))
        with self.assertRaises(ValueError):
            registered_evidence(self.settings.root, data)

    async def test_source_revision_and_expired_pricing_block_new_continuation(self):
        run, record = await self.resolved()
        pricing = self.settings.root / "admin/pricing.json"
        profile = json.loads(pricing.read_text())
        profile["confirmed_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        profile["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        pricing.write_text(json.dumps(profile))
        await self.continue_run(run, record, expected=503)
        await self.client.put(
            "/api/admin/pricing",
            headers=self.headers,
            json=dict(
                input_price="2",
                cached_input_price="0.1",
                output_price="10",
                checked_current_official_rates=True,
            ),
        )
        invoices = self.settings.data / "invoices.json"
        invoices.write_text(invoices.read_text() + "\n")
        await self.continue_run(run, record, expected=409)
        self.assertEqual(len(self.app.state.store.metadata()), 1)

    async def test_continuation_limits_not_employee_adjustable_and_shutdown_safe(self):
        run, record = await self.resolved()
        endpoint = f"/api/runs/{run['id']}/continue"
        body = dict(
            idempotency_key=uuid4().hex, intervention_id=record["id"], acknowledge_paid=True
        )
        for key, value in [
            ("max_cost_usd", "100"),
            ("max_tool_calls", 100),
            ("max_seconds", 900),
            ("objective", "Investigate all customers"),
        ]:
            self.assertEqual(
                (
                    await self.client.post(endpoint, headers=self.headers, json=body | {key: value})
                ).status_code,
                422,
            )
        self.app.state.store.accepting_launches = False
        await self.continue_run(run, record, expected=503)
        self.app.state.store.accepting_launches = True
        child = await self.continue_run(run, record)
        started = next(
            e
            for e in self.app.state.store.events(child["id"])
            if e["type"] == "investigation.started"
        )
        limits = started["payload"]["limits"]
        self.assertEqual(
            (
                limits["max_tool_calls"],
                limits["max_responses"],
                limits["max_seconds"],
                limits["max_cost_usd"],
            ),
            (35, 40, 180, "1"),
        )

    async def test_interrupted_child_is_not_automatically_resumed_on_restart(self):
        run, record = await self.resolved()
        self.scenario = "interrupted"
        child = await self.continue_run(run, record)
        store = self.app.state.store
        meta = store.meta(child["id"])
        meta.update(status="running", reason="test crash after saved partial evidence")
        store.write_meta(meta)
        await self.lifespan.__aexit__(None, None, None)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        restored = store.snapshot(child["id"])
        self.assertEqual(restored.status, "interrupted")
        self.assertEqual(restored.reason, "server_restart_no_resume")
        self.assertIsNone(store.active)
        self.assertEqual(len(store.metadata()), 2)

    async def test_historical_findings_get_persisted_procedural_guidance_without_rewriting_report(
        self,
    ):
        run = await self.settled()
        path = self.app.state.store.directory(run["id"]) / "report.json"
        report = json.loads(path.read_text())
        for f in report["findings"]:
            f.pop("recommendation", None)
            f.pop("recommendation_history", None)
        path.write_text(json.dumps(report))
        original = path.read_bytes()
        endpoint = f"/api/runs/{run['id']}/findings/finding-C007/recommendation"
        self.assertIsNone((await self.client.get(endpoint)).json())
        body = dict(expected_revision=run["data_revision"], expected_version=1)
        self.assertEqual((await self.client.post(endpoint, json=body)).status_code, 403)
        result = await self.client.post(endpoint, headers=self.headers, json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["origin"], "evidence_rule")
        self.assertEqual((await self.client.get(endpoint)).json(), result.json())
        again = await self.client.post(endpoint, headers=self.headers, json=body)
        self.assertEqual(again.json(), result.json())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(
            sum(e["type"] == "guidance.prepared" for e in self.app.state.store.events(run["id"])), 1
        )
        self.assertEqual(len(self.app.state.store.metadata()), 1)

    async def test_concurrent_submission_is_single_durable_intervention(self):
        run = await self.settled()
        body = self.action(run, action="escalate")
        results = await asyncio.gather(self.submit(run, body), self.submit(run, body))
        self.assertEqual([r.status_code for r in results], [200, 200])
        self.assertEqual(
            results[0].json()["intervention"]["id"], results[1].json()["intervention"]["id"]
        )
        self.assertEqual(len(interventions(self.app.state.store.directory(run["id"]))), 1)

    async def test_prior_export_approval_does_not_survive_dismissal(self):
        run = await self.settled()
        endpoint = f"/api/runs/{run['id']}/findings/finding-C005"
        self.assertEqual(
            (
                await self.client.post(
                    endpoint + "/review", headers=self.headers, json=self.decision(run)
                )
            ).status_code,
            200,
        )
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 200)
        f = next(f for f in run["findings"] if f["finding_id"] == "finding-C005")
        body = dict(
            idempotency_key=uuid4().hex,
            expected_revision=run["data_revision"],
            expected_version=f["version"],
            action="dismiss",
            rationale="TEST: reject this hypothesis after additional business review; retain the historical approved package.",
        )
        result = await self.client.post(
            endpoint + "/interventions", headers=self.headers, json=body
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 409)
        self.assertTrue(
            any(e["type"] == "human_review.decided" for e in self.app.state.store.events(run["id"]))
        )

    async def test_administrator_cli_preserves_original_windows_document_bytes(self):
        import hashlib
        import subprocess
        import sys

        data = self.app.state.store.public_data()
        assertion = authority_assertion(data)
        original = ("Original test letter\r\n" + assertion["confirmation_text"] + "\r\n").encode(
            "utf-8"
        )
        document = self.root / "original-confirmation.txt"
        document.write_bytes(original)
        assertion_file = self.root / "assertion.json"
        assertion_file.write_text(json.dumps(assertion), encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "scripts.register_resolution_evidence",
            "--data",
            str(self.settings.data),
            "--runs",
            str(self.settings.root),
            "--assertion",
            str(assertion_file),
            "--document",
            str(document),
            "--verified-by",
            "Test administrator",
        ]
        denied = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(denied.returncode, 0)
        accepted = subprocess.run(
            command + ["--verified-source-and-authority"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        records = registered_evidence(self.settings.root, data)
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["payload"]["original_document_sha256"], hashlib.sha256(original).hexdigest()
        )
        self.assertEqual(records[0]["payload"]["original_document_text"].encode("utf-8"), original)

    async def test_authorization_journal_failure_prevents_paid_worker(self):
        run, record = await self.resolved()
        with patch(
            "contract_to_cash.web.workflow.append_event",
            side_effect=sqlite3.OperationalError("simulated storage fault"),
        ):
            await self.continue_run(run, record, expected=503)
        store = self.app.state.store
        child = next(m for m in store.metadata() if m.get("continuation"))
        self.assertEqual(child["status"], "failed")
        self.assertEqual(child["reason"], "authorization_journal_failed_no_api_request")
        self.assertEqual(store.events(child["id"]), [])
        self.assertIsNone(store.active)
