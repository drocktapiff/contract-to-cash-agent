"""Local ASGI tests with real journals and simulated Responses. Never call OpenAI."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contract_to_cash/tests"))
from test_agent import FakeClient, FakeResponse, call
from contract_to_cash.agent.events import Journal
from contract_to_cash.agent.runtime import Investigator, Limits
from contract_to_cash.agent.tools import Tools
from contract_to_cash.web.app import create_app
from contract_to_cash.web.models import RunView
from contract_to_cash.web.presentation import event_view
from contract_to_cash.web.recording import import_recording, sanitize
from contract_to_cash.web.store import Settings, StoreError
from scripts.build_agent_runtime import build


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runtime = build(self.root / "runtime")
        self.settings = Settings(
            data=self.runtime / "contract_to_cash/data",
            root=self.root / "runs",
            recordings=self.root / "recordings",
            frontend=self.root / "dist",
            operator_token="operator-credential-" + "x" * 32,
            local_passwordless=False,
            reviewer="Test Operator",
        )
        self.env = patch.dict(os.environ, {"OPENAI_API_KEY": "local-test-placeholder"})
        self.env.start()
        self.app = create_app(self.settings, self.simulated_runner)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url="http://testserver"
        )
        response = await self.client.post(
            "/api/session", json={"token": self.settings.operator_token}
        )
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json()["csrf_token"]
        self.headers = {"x-csrf-token": self.csrf}

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.env.stop()
        self.tmp.cleanup()

    def payload(self, **changes):
        return dict(
            idempotency_key=str(uuid4()),
            acknowledge_paid=True,
            input_price="2",
            cached_input_price="0.1",
            output_price="10",
            **changes,
        )

    def simulated_runner(self, run_id, data, request):
        with Journal(self.settings.root / run_id) as journal:
            journal.run_id = run_id
            tools = Tools(data, journal)

            def selected(name, args):
                item = call(name, args)
                item["call_id"] = uuid4().hex
                return item

            required = lambda cid: sorted(tools._required(cid))
            script = [
                FakeResponse(
                    [selected("get_customer_evidence", {"customer_ids": ["C005", "C006", "C007"]})]
                ),
                FakeResponse(
                    [
                        selected(
                            "submit_finding",
                            dict(
                                customer_ids=["C005"],
                                evidence_ids=required("C005"),
                                state="verified",
                                rationale="SIMULATED SDK test: credit needs operator review.",
                            ),
                        )
                    ]
                ),
                FakeResponse(
                    [
                        selected(
                            "request_human_review", dict(finding_id="finding-C005", action="export")
                        )
                    ]
                ),
                FakeResponse(
                    [
                        selected(
                            "submit_finding",
                            dict(
                                customer_ids=["C006"],
                                evidence_ids=required("C006"),
                                state="proposed",
                                rationale="SIMULATED SDK test: invoice reconciliation is unresolved.",
                            ),
                        )
                    ]
                ),
                FakeResponse(
                    [
                        selected(
                            "request_human_review", dict(finding_id="finding-C006", action="review")
                        )
                    ]
                ),
                FakeResponse([]),
            ]
            return Investigator(FakeClient(script), "simulated-test", tools, journal, Limits()).run(
                "Simulated test only"
            )

    async def settled(self, payload=None):
        response = await self.client.post(
            "/api/runs", headers=self.headers, json=payload or self.payload()
        )
        self.assertEqual(response.status_code, 202, response.text)
        run_id = response.json()["id"]
        for _ in range(150):
            response = await self.client.get("/api/runs/" + run_id)
            if response.json()["status"] not in ("queued", "running"):
                return response.json()
            await asyncio.sleep(0.01)
        self.fail("Simulated worker did not finish")

    def decision(self, run, fid="finding-C005", **overrides):
        row = next(f for f in run["findings"] if f["finding_id"] == fid)
        return (
            dict(
                decision="approved",
                rationale="Reviewed original source documents and deterministic comparison.",
                expected_revision=row["data_revision"],
                expected_version=row["version"],
            )
            | overrides
        )

    async def test_five_character_local_password_and_four_character_rejection(self):
        self.settings.operator_token = "abcde"
        response = await self.client.post("/api/session", json={"token": "abcde"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue((await self.client.get("/api/health")).json()["operator_configured"])
        self.assertEqual(
            (await self.client.post("/api/session", json={"token": "abcd"})).status_code, 422
        )
        self.settings.operator_token = "abcd"
        self.assertFalse((await self.client.get("/api/health")).json()["operator_configured"])
        self.assertEqual(
            (await self.client.post("/api/session", json={"token": "abcde"})).status_code, 503
        )

    async def test_short_local_password_preserves_login_rate_limit(self):
        self.settings.operator_token = "abcde"
        # setUp already made one successful login from this address.
        for _ in range(4):
            self.assertEqual(
                (await self.client.post("/api/session", json={"token": "wrong"})).status_code, 401
            )
        self.assertEqual(
            (await self.client.post("/api/session", json={"token": "abcde"})).status_code, 429
        )

    async def test_starting_journal_can_be_polled_before_schema_initialization(self):
        import sqlite3
        from contextlib import closing
        from contract_to_cash.web.store import now, StoreError

        run_id = uuid4().hex
        store = self.app.state.store
        metadata = dict(
            id=run_id,
            idempotency_key=str(uuid4()),
            created_at=now(),
            status="running",
            reason="starting",
        )
        store.write_meta(metadata)
        directory = store.directory(run_id)
        directory.mkdir()
        with closing(sqlite3.connect(directory / "events.sqlite3")):
            pass
        self.assertEqual(store.events(run_id), [])
        self.assertEqual((await self.client.get("/api/runs/" + run_id)).status_code, 200)
        metadata["status"] = "failed"
        store.write_meta(metadata)
        with self.assertRaises(StoreError) as failure:
            store.events(run_id)
        self.assertEqual(failure.exception.status, 503)

    async def test_schema_inventory_and_validation(self):
        schema = (await self.client.get("/api/schema")).json()
        self.assertIn("Launch", schema["components"]["schemas"])
        data = (await self.client.get("/api/dataset")).json()
        self.assertEqual(data["customer_count"], 40)
        self.assertEqual(data["invoice_count"], 41)
        for extra in (
            {"max_tool_calls": 36},
            {"max_seconds": 181},
            {"max_cost_usd": "2"},
            {"model": "unauthorized-model"},
            {"max_responses": 41},
            {"input_price": "NaN"},
            {"cached_input_price": "3"},
            {"acknowledge_paid": False},
        ):
            payload = self.payload()
            payload.update(extra)
            response = await self.client.post("/api/runs", headers=self.headers, json=payload)
            self.assertEqual(response.status_code, 422, response.text)

    async def test_auth_csrf_origin_and_host_boundaries(self):
        self.assertEqual(
            (await self.client.post("/api/runs", json=self.payload())).status_code, 403
        )
        self.assertEqual(
            (
                await self.client.post(
                    "/api/runs",
                    json=self.payload(),
                    headers=self.headers | {"origin": "https://attacker.example"},
                )
            ).status_code,
            403,
        )
        self.assertEqual(
            (await self.client.get("/api/runs", headers={"host": "attacker.example"})).status_code,
            400,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url="http://testserver"
        ) as outsider:
            self.assertEqual((await outsider.get("/api/dataset")).status_code, 401)
            self.assertEqual((await outsider.get("/api/runs")).status_code, 401)
        cookie = self.client.cookies.get("ctc_session")
        self.assertTrue(cookie)
        response = await self.client.post(
            "/api/session", json={"token": self.settings.operator_token}
        )
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])

    async def test_shutdown_disables_new_paid_requests_without_creating_history(self):
        self.app.state.store.accepting_launches = False
        response = await self.client.post("/api/runs", headers=self.headers, json=self.payload())
        self.assertEqual(response.status_code, 503)
        self.assertEqual((await self.client.get("/api/runs")).json(), [])
        self.assertIsNone(self.app.state.store.active)

    async def test_missing_credentials_fail_before_creating_paid_run(self):
        with patch.dict(os.environ, {}, clear=True):
            response = await self.client.post(
                "/api/runs", headers=self.headers, json=self.payload()
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual((await self.client.get("/api/runs")).json(), [])

    async def test_idempotency_single_worker_and_rate_limit(self):
        import threading

        gate = threading.Event()
        original = self.app.state.store.runner
        self.app.state.store.runner = lambda *args: (gate.wait(timeout=2), original(*args))[1]
        payload = self.payload()
        first = await self.client.post("/api/runs", headers=self.headers, json=payload)
        try:
            second = await self.client.post("/api/runs", headers=self.headers, json=payload)
            self.assertEqual(first.json()["id"], second.json()["id"])
            self.assertEqual(
                (
                    await self.client.post("/api/runs", headers=self.headers, json=self.payload())
                ).status_code,
                409,
            )
        finally:
            gate.set()
        for _ in range(150):
            if self.app.state.store.active is None:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(
            (
                await self.client.post("/api/runs", headers=self.headers, json=self.payload())
            ).status_code,
            429,
        )

    async def test_genuine_journal_sse_reconnection_and_incomplete_snapshot(self):
        run = await self.settled()
        self.assertEqual(run["status"], "incomplete")
        self.assertEqual(run["financial_totals"]["potential_credits_cad"], "110.00")
        self.assertEqual(run["metrics"]["agent_tool_calls"], 5)
        self.assertLessEqual(run["report_event_sequence"], run["last_event_sequence"])
        events = self.app.state.store.events(run["id"])
        self.assertTrue(events)
        first = await self.client.get(f"/api/runs/{run['id']}/events")
        self.assertIn("text/event-stream", first.headers["content-type"])
        self.assertIn("event: settled", first.text)
        self.assertIn("Model selected get_customer_evidence", first.text)
        cursor = events[len(events) // 2]["sequence"]
        replay = await self.client.get(
            f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": str(cursor)}
        )
        ids = [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")]
        self.assertTrue(ids)
        self.assertTrue(all(i > cursor for i in ids))
        self.assertEqual(ids[-1], events[-1]["sequence"])
        self.assertEqual(
            (
                await self.client.get(
                    f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": "bad"}
                )
            ).status_code,
            422,
        )
        saved = json.loads((self.settings.root / run["id"] / "report.json").read_text())
        self.assertEqual(saved["run_id"], run["id"])
        self.assertEqual(saved["financial_totals"], run["financial_totals"])

    async def test_evidence_and_ambiguous_finding_states(self):
        run = await self.settled()
        rows = {f["finding_id"]: f for f in run["findings"]}
        self.assertEqual(rows["finding-C005"]["state"], "verified")
        self.assertEqual(rows["finding-C006"]["state"], "proposed")
        self.assertIsNone(rows["finding-C006"]["comparisons"][0]["difference_cad"])
        self.assertIsNone(rows["finding-C007"]["comparison"]["difference_cad"])
        self.assertEqual(rows["finding-C007"]["origin"], "deterministic_conflict_guard")
        response = await self.client.get(f"/api/runs/{run['id']}/findings/finding-C005/evidence")
        self.assertTrue(any("text" in doc for doc in response.json()))
        self.assertTrue(any(doc.get("kind") == "invoice" for doc in response.json()))

    async def test_review_rationale_attribution_export_gating_and_duplicate_decision(self):
        run = await self.settled()
        endpoint = f"/api/runs/{run['id']}/findings/finding-C005"
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 403)
        body = self.decision(run)
        response = await self.client.post(endpoint + "/review", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        decision = response.json()["decision"]
        self.assertEqual(decision["reviewer"], "Test Operator")
        self.assertEqual(decision["rationale"], body["rationale"])
        package = await self.client.get(endpoint + "/export")
        self.assertEqual(package.status_code, 200, package.text)
        self.assertIn("No billing changes", package.json()["disclaimer"])
        self.assertEqual(
            (
                await self.client.post(endpoint + "/review", headers=self.headers, json=body)
            ).status_code,
            409,
        )
        self.assertEqual(self.app.state.store.events(run["id"])[-1]["type"], "human_review.decided")

    async def test_reject_and_defer_unresolved_cases_never_approve_them(self):
        run = await self.settled()
        for fid, decision in [("finding-C006", "rejected"), ("finding-C007", "needs_information")]:
            endpoint = f"/api/runs/{run['id']}/findings/{fid}"
            self.assertEqual(
                (
                    await self.client.post(
                        endpoint + "/review", headers=self.headers, json=self.decision(run, fid)
                    )
                ).status_code,
                409,
            )
            response = await self.client.post(
                endpoint + "/review",
                headers=self.headers,
                json=self.decision(run, fid, decision=decision),
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["decision"]["decision"], decision)
            self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 403)

    async def test_stale_revision_version_and_active_run_reject_review(self):
        run = await self.settled()
        endpoint = f"/api/runs/{run['id']}/findings/finding-C005/review"
        self.assertEqual(
            (
                await self.client.post(
                    endpoint, headers=self.headers, json=self.decision(run, expected_version=99)
                )
            ).status_code,
            409,
        )
        self.app.state.store.active = "another-run"
        self.assertEqual(
            (
                await self.client.post(endpoint, headers=self.headers, json=self.decision(run))
            ).status_code,
            409,
        )
        self.app.state.store.active = None
        path = self.settings.data / "invoices.json"
        rows = json.loads(path.read_text())
        rows[0]["billed_amount"] = "1.00"
        path.write_text(json.dumps(rows))
        response = await self.client.post(endpoint, headers=self.headers, json=self.decision(run))
        self.assertEqual(response.status_code, 409)
        self.assertIn("revision changed", response.json()["detail"])
        sources = await self.client.get(endpoint.replace("/review", "/evidence"))
        self.assertEqual(
            sources.status_code, 200
        )  # Historical source still comes from the journal.

    async def test_no_secrets_keys_provider_bodies_or_source_mutations(self):
        before = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.settings.data.rglob("*")
            if p.is_file()
        }
        run = await self.settled()
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})
        secret = "sk-" + "sensitivecredential" * 4
        fake = dict(
            sequence=1,
            timestamp="2026-11-03T00:00:00Z",
            type="api.failed",
            actor="orchestrator",
            payload={"body": secret, "reasoning_content": secret},
        )
        self.assertNotIn(secret, event_view(fake).model_dump_json())
        response = await self.client.post(
            "/api/session", json={"token": secret, "unrecognized_secret": secret}
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)
        stream = await self.client.get(f"/api/runs/{run['id']}/events")
        for prohibited in (
            "local-test-placeholder",
            self.settings.operator_token,
            "encrypted_content",
            "sealed_answer_key",
            "SIMULATED SDK test",
        ):
            self.assertNotIn(prohibited, stream.text)
        self.assertEqual((await self.client.get("/api/runs/sealed_answer_key")).status_code, 404)
        schema = (await self.client.get("/api/schema")).text
        self.assertNotIn(self.settings.operator_token, schema)

    async def test_recorded_mode_is_empty_readonly_and_simulations_cannot_be_imported(self):
        run = await self.settled()
        with self.assertRaises(ValueError):
            import_recording(self.settings.root / run["id"], self.settings.recordings, True)
        self.settings.mode = "recorded"
        self.assertEqual((await self.client.get("/api/runs")).json(), [])
        self.assertEqual(
            (
                await self.client.post("/api/runs", headers=self.headers, json=self.payload())
            ).status_code,
            403,
        )
        self.assertEqual(
            (
                await self.client.post(
                    f"/api/runs/{run['id']}/findings/finding-C005/review",
                    headers=self.headers,
                    json=self.decision(run),
                )
            ).status_code,
            403,
        )
        self.assertEqual((await self.client.get("/api/dataset")).json()["customer_count"], None)
        self.assertNotIn(
            "sensitive@example.com",
            json.dumps(
                sanitize(
                    {
                        "reviewer": "sensitive@example.com",
                        "secret": "do not expose",
                        "text": "sk-" + "a" * 30,
                    }
                )
            ),
        )

    async def test_missing_frontend_and_unknown_api_fail_without_paths(self):
        response = await self.client.get("/")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual((await self.client.get("/api/not-a-resource")).status_code, 404)

    async def test_store_survives_reload_and_rejects_second_owner(self):
        run = await self.settled()
        other = create_app(self.settings, self.simulated_runner)
        with self.assertRaises(RuntimeError):
            other.state.store.open()
        await self.lifespan.__aexit__(None, None, None)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        login = await self.client.post("/api/session", json={"token": self.settings.operator_token})
        self.assertEqual(
            login.status_code, 200
        )  # Server restart invalidates sessions, not run history.
        self.assertEqual(
            (await self.client.get("/api/runs/" + run["id"])).json()["status"], "incomplete"
        )
        self.assertEqual(len((await self.client.get("/api/runs")).json()), 1)

    async def test_interrupted_worker_is_not_restarted_or_called_completed(self):
        run = await self.settled()
        meta = self.app.state.store.meta(run["id"])
        meta.update(status="running", reason="investigating")
        self.app.state.store.write_meta(meta)
        await self.lifespan.__aexit__(None, None, None)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        login = await self.client.post("/api/session", json={"token": self.settings.operator_token})
        self.assertEqual(login.status_code, 200)
        snapshot = (await self.client.get("/api/runs/" + run["id"])).json()
        self.assertEqual(snapshot["status"], "interrupted")
        self.assertEqual(snapshot["reason"], "server_restart_no_resume")
        self.assertFalse(snapshot["metrics"]["cost_accounting_complete"])
        self.assertIsNone(snapshot["metrics"]["usage_priced_cost_usd"])
        self.assertEqual(snapshot["findings"], run["findings"])
        self.assertIsNone(self.app.state.store.active)

    async def test_api_schema_snapshot_matches_canonical_models(self):
        from scripts.export_web_schema import public_schema

        path = Path(__file__).resolve().parents[1] / "frontend/src/api-schema.json"
        self.assertEqual(json.loads(path.read_text()), public_schema())

    async def test_read_only_approval_does_not_upgrade_to_export(self):
        run = await self.settled()
        path = self.settings.root / run["id"] / "report.json"
        report = json.loads(path.read_text())
        next(r for r in report["reviews"] if r["finding_id"] == "finding-C005")["action"] = "review"
        path.write_text(json.dumps(report))
        endpoint = f"/api/runs/{run['id']}/findings/finding-C005"
        response = await self.client.post(
            endpoint + "/review", headers=self.headers, json=self.decision(run)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 403)

        report = json.loads(path.read_text())
        next(r for r in report["reviews"] if r["finding_id"] == "finding-C005")["action"] = "export"
        path.write_text(json.dumps(report))
        self.assertEqual((await self.client.get(endpoint + "/export")).status_code, 403)
