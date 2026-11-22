import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from contract_to_cash.web.app import create_app
from contract_to_cash.web.store import Settings
from scripts.build_agent_runtime import build
from tests_workspace.test_workspace import command


class WorkspaceApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        runtime = build(root / "runtime")
        self.env = patch.dict(os.environ, {"OPENAI_API_KEY": ""})
        self.env.start()
        self.settings = Settings(
            root=root / "runs",
            data=runtime / "contract_to_cash/data",
            frontend=Path("frontend/dist"),
        )
        self.app = create_app(self.settings)
        self.life = self.app.router.lifespan_context(self.app)
        await self.life.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app), base_url="http://127.0.0.1:8000"
        )
        session = (await self.client.get("/api/session")).json()
        self.headers = {"x-csrf-token": session["csrf_token"]}

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.life.__aexit__(None, None, None)
        self.env.stop()
        self.tmp.cleanup()

    async def load(self):
        response = await self.client.post(
            "/api/document-workspace/load", headers=self.headers, json=command().model_dump()
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_real_import_routine_telemetry_pdf_and_inbox(self):
        initial = (await self.client.get("/api/document-workspace")).json()
        self.assertIsNone(initial["session_id"])
        data = await self.load()
        sid = data["session_id"]
        self.assertEqual(data["metrics"]["total"], 102)
        self.assertEqual(data["metrics"]["automatically_completed"], 0)
        work = next(w for w in data["items"] if w["category"] == "contract_conflict")
        detail = (
            await self.client.get(
                f'/api/document-workspace/sessions/{sid}/items/{work["work_item_id"]}'
            )
        ).json()
        pdf = await self.client.get(
            f'/api/document-workspace/sessions/{sid}/evidence/{detail["documents"][0]["file_hash"]}'
        )
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assertIn("inline", pdf.headers["content-disposition"])
        body = command(
            expected_version=work["version"], evidence_hashes=[detail["documents"][0]["file_hash"]]
        ).model_dump()
        response = await self.client.post(
            f'/api/document-workspace/sessions/{sid}/items/{work["work_item_id"]}/escalate',
            headers=self.headers,
            json=body,
        )
        self.assertEqual(response.status_code, 200, response.text)
        inbox = (
            await self.client.get(f"/api/document-workspace/sessions/{sid}/management-inbox")
        ).json()
        self.assertEqual(inbox["items"][0]["item"]["work_item_id"], work["work_item_id"])
        result = await self.client.post(
            f"/api/document-workspace/sessions/{sid}/process/routine",
            headers=self.headers,
            json=command().model_dump(),
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["prepared_for_review"], 73)
        snapshot = (await self.client.get("/api/document-workspace")).json()
        self.assertEqual(snapshot["metrics"]["escalated"], 1)
        self.assertEqual(snapshot["telemetry"]["api_requests"], 0)
        events = (await self.client.get(f"/api/document-workspace/sessions/{sid}/events")).json()
        self.assertTrue(any(e["type"] == "escalated" for e in events))
        self.assertEqual([e["sequence"] for e in events], sorted(e["sequence"] for e in events))

    async def test_csrf_origin_loopback_and_no_financial_authority(self):
        for path in ("/api/document-workspace/load", "/api/document-workspace/restart"):
            self.assertEqual(
                (await self.client.post(path, json=command().model_dump())).status_code, 403
            )
            self.assertEqual(
                (
                    await self.client.post(
                        path,
                        json=command().model_dump(),
                        headers={**self.headers, "origin": "https://attacker.example"},
                    )
                ).status_code,
                403,
            )
        external = httpx.AsyncClient(
            transport=httpx.ASGITransport(self.app, client=("192.0.2.1", 5000)),
            base_url="http://127.0.0.1:8000",
        )
        try:
            self.assertEqual((await external.get("/api/document-workspace")).status_code, 403)
        finally:
            await external.aclose()
        data = await self.load()
        sid = data["session_id"]
        work = next(w for w in data["items"] if w["category"] == "credit_review")
        payload = command(
            expected_version=1, evidence_hashes=list(work["supporting_facts"])[:1]
        ).model_dump()
        for action in ("approve_credit", "export", "approve_contract"):
            self.assertEqual(
                (
                    await self.client.post(
                        f'/api/document-workspace/sessions/{sid}/items/{work["work_item_id"]}/{action}',
                        headers=self.headers,
                        json=payload,
                    )
                ).status_code,
                422,
            )
        self.assertEqual((await self.client.get("/api/runs")).json(), [])

    async def test_restart_refresh_and_retained_human_escalation(self):
        data = await self.load()
        old = data["session_id"]
        work = next(w for w in data["items"] if w["category"] == "contract_conflict")
        payload = command(
            expected_version=1, evidence_hashes=list(work["supporting_facts"])[:1]
        ).model_dump()
        self.assertEqual(
            (
                await self.client.post(
                    f'/api/document-workspace/sessions/{old}/items/{work["work_item_id"]}/escalate',
                    headers=self.headers,
                    json=payload,
                )
            ).status_code,
            200,
        )
        body = command(expected_session=old).model_dump()
        response = await self.client.post(
            "/api/document-workspace/restart", headers=self.headers, json=body
        )
        self.assertEqual(response.status_code, 200, response.text)
        fresh = response.json()
        self.assertNotEqual(fresh["session_id"], old)
        self.assertEqual(fresh["metrics"]["automatically_completed"], 0)
        self.assertEqual(
            (await self.client.get("/api/document-workspace")).json()["session_id"],
            fresh["session_id"],
        )
        self.assertEqual(
            (
                await self.client.get(f"/api/document-workspace/sessions/{old}/management-inbox")
            ).json()["items"][0]["item"]["status"],
            "Escalated",
        )
        self.assertEqual(
            (
                await self.client.post(
                    f"/api/document-workspace/sessions/{old}/process/routine",
                    headers=self.headers,
                    json=command().model_dump(),
                )
            ).status_code,
            409,
        )
        again = await self.client.post(
            "/api/document-workspace/restart", headers=self.headers, json=body
        )
        self.assertEqual(again.json()["session_id"], fresh["session_id"])

    async def test_recorded_mode_cannot_mutate_document_workspace(self):
        self.app.state.store.settings.mode = "recorded"
        self.assertEqual(
            (
                await self.client.post(
                    "/api/document-workspace/load",
                    headers=self.headers,
                    json=command().model_dump(),
                )
            ).status_code,
            403,
        )
        self.app.state.store.settings.mode = "operator"

    async def test_invalid_attribution_confirmation_and_version_are_rejected(self):
        data = await self.load()
        sid = data["session_id"]
        work = data["items"][0]
        bad = command().model_dump()
        bad["confirmation"] = "APPROVE EVERYTHING"
        self.assertEqual(
            (
                await self.client.post(
                    f"/api/document-workspace/sessions/{sid}/process/auto_all",
                    headers=self.headers,
                    json=bad,
                )
            ).status_code,
            422,
        )
        bad = command().model_dump()
        bad["actor"] = " "
        self.assertEqual(
            (
                await self.client.post(
                    f"/api/document-workspace/sessions/{sid}/process/auto_all",
                    headers=self.headers,
                    json=bad,
                )
            ).status_code,
            422,
        )
        self.assertEqual(
            (
                await self.client.post(
                    f'/api/document-workspace/sessions/{sid}/items/{work["work_item_id"]}/auto',
                    headers=self.headers,
                    json=command().model_dump(),
                )
            ).status_code,
            409,
        )

    async def test_walkthrough_api_is_source_bound_read_only_and_session_protected(self):
        loaded = await self.load()
        sid = loaded["session_id"]
        wid = loaded["scenarios"][0]["work_item_id"]
        before = (await self.client.get("/api/document-workspace")).json()["telemetry"][
            "event_count"
        ]
        for _ in range(2):
            response = await self.client.get(
                f"/api/document-workspace/sessions/{sid}/walkthrough/{wid}"
            )
            self.assertEqual(response.status_code, 200, response.text)
            story = response.json()
            self.assertFalse(story["recorded"])
            self.assertTrue(story["can_process"])
            self.assertTrue(story["manual_steps"])
            self.assertTrue(story["documents"])
        self.assertEqual(
            (await self.client.get("/api/document-workspace")).json()["telemetry"]["event_count"],
            before,
        )
        self.client.cookies.clear()
        self.assertEqual(
            (
                await self.client.get(f"/api/document-workspace/sessions/{sid}/walkthrough/{wid}")
            ).status_code,
            401,
        )

    async def test_selected_endpoints_partial_results_refresh_and_oversight(self):
        loaded = await self.load()
        sid = loaded["session_id"]
        body = command(expected_session=sid).model_dump()
        body["selected"] = [
            dict(id=w["work_item_id"], version=w["version"]) for w in loaded["items"]
        ]
        self.assertEqual(
            (
                await self.client.post(
                    f"/api/document-workspace/sessions/{sid}/selected/close", json=body
                )
            ).status_code,
            403,
        )
        closed = await self.client.post(
            f"/api/document-workspace/sessions/{sid}/selected/close",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(closed.json()["checks_completed"], 73)
        replay = await self.client.post(
            f"/api/document-workspace/sessions/{sid}/selected/close",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(replay.json(), closed.json())
        snapshot = (await self.client.get("/api/document-workspace")).json()
        self.assertEqual(snapshot["last_bulk_operation"]["result"], closed.json())
        from tests_workspace.test_human_review_activity import approve_pending

        approve_pending(self.app.state.document_workspace, sid)
        snapshot = self.app.state.document_workspace.snapshot(sid)
        remaining = [w for w in snapshot["items"] if w["status"] != "Closed"]
        body = command(expected_session=sid).model_dump()
        body["selected"] = [dict(id=w["work_item_id"], version=w["version"]) for w in remaining] + [
            dict(id="WI-" + "f" * 24, version=1)
        ]
        result = await self.client.post(
            f"/api/document-workspace/sessions/{sid}/selected/escalate",
            headers=self.headers,
            json=body,
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["handoffs_created"], 29)
        self.assertEqual(result.json()["blocked"], 1)
        self.assertTrue(result.json()["partial"])
        inbox = (
            await self.client.get(f"/api/document-workspace/sessions/{sid}/management-inbox")
        ).json()
        self.assertEqual(len(inbox["items"]), 29)
        self.assertTrue(
            any(d["item"]["current_decision_owner"] == "Finance" for d in inbox["items"])
        )
        bad = {**body, "selected": [body["selected"][0], body["selected"][0]]}
        self.assertEqual(
            (
                await self.client.post(
                    f"/api/document-workspace/sessions/{sid}/selected/escalate",
                    headers=self.headers,
                    json=bad,
                )
            ).status_code,
            422,
        )

    async def test_management_api_enforces_session_origin_versions_and_safe_coordination(self):
        from contract_to_cash.web.selected_workflow import selected_operation, SelectedCommand
        from contract_to_cash.web.management_center import ManagementCommand

        data = await self.load()
        sid = data["session_id"]
        ws = self.app.state.document_workspace

        def selected(items):
            return SelectedCommand(
                **command(expected_session=sid).model_dump(),
                selected=[dict(id=w["work_item_id"], version=w["version"]) for w in items],
            )

        selected_operation(ws, sid, "close", selected(data["items"]))
        from tests_workspace.test_human_review_activity import approve_pending

        approve_pending(ws, sid)
        selected_operation(
            ws,
            sid,
            "escalate",
            selected([w for w in ws.snapshot()["items"] if w["status"] != "Closed"]),
        )
        path = f"/api/document-workspace/sessions/{sid}/management"
        overview = (await self.client.get(path)).json()
        self.assertEqual(overview["metrics"]["handoffs"], 29)
        w = next(w for w in overview["cases"] if w["status"] == "Awaiting Financial Review")
        body = ManagementCommand(
            **command(expected_session=sid).model_dump(),
            selected=[dict(id=w["work_item_id"], version=w["version"])],
            action="complete",
            required_next_action="Management coordination complete; Finance review is still required.",
        ).model_dump()
        self.assertEqual((await self.client.post(path + "/commands", json=body)).status_code, 403)
        self.assertEqual(
            (
                await self.client.post(
                    path + "/commands",
                    headers={**self.headers, "origin": "https://attacker.invalid"},
                    json=body,
                )
            ).status_code,
            403,
        )
        r = await self.client.post(path + "/commands", headers=self.headers, json=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["financial_actions_executed"], 0)
        updated = (await self.client.get(path)).json()
        case = next(x for x in updated["cases"] if x["work_item_id"] == w["work_item_id"])
        self.assertEqual(case["status"], "Awaiting Financial Review")
        self.assertEqual(case["current_decision_owner"], "Finance")
        self.assertEqual(
            (
                await self.client.post(
                    path + "/analysis-preview", headers=self.headers, json={"scope": []}
                )
            ).status_code,
            422,
        )
        preview = await self.client.post(
            path + "/analysis-preview", headers=self.headers, json={"scope": "all"}
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertFalse(preview.json()["availability"]["available"])
        self.assertEqual((await self.client.get(path + "/analyses")).json(), [])
        self.assertEqual(
            (await self.client.post(path + "/analyses", headers=self.headers, json={})).status_code,
            422,
        )

    async def test_human_review_api_csrf_source_versions_and_read_only_activity(self):
        data = await self.load()
        sid = data["session_id"]
        prefix = f"/api/document-workspace/sessions/{sid}"
        request = command(expected_session=sid).model_dump()
        request["selected"] = [
            dict(id=w["work_item_id"], version=w["version"]) for w in data["items"]
        ]
        prepared = await self.client.post(
            prefix + "/selected/close", headers=self.headers, json=request
        )
        self.assertEqual(prepared.json()["prepared_for_review"], 73)
        self.assertEqual(prepared.json()["automatically_closed"], 0)
        snapshot = (await self.client.get("/api/document-workspace")).json()
        self.assertEqual(snapshot["metrics"]["reviewed_closed"], 0)
        w = next(w for w in snapshot["items"] if w["status"] == "Awaiting Maya Review")
        body = command(expected_session=sid).model_dump()
        body.update(
            selected=[
                dict(
                    id=w["work_item_id"],
                    version=w["version"],
                    evidence_hashes=list(w["supporting_facts"]),
                )
            ],
            decision="approve",
            attestation="individual",
            acknowledge_review=True,
        )
        self.assertEqual(
            (await self.client.post(prefix + "/human-reviews", json=body)).status_code, 403
        )
        self.assertEqual(
            (
                await self.client.post(
                    prefix + "/human-reviews",
                    headers={**self.headers, "origin": "https://attacker.invalid"},
                    json=body,
                )
            ).status_code,
            403,
        )
        self.assertEqual(
            (
                await self.client.post(
                    prefix + "/human-reviews",
                    headers=self.headers,
                    json={**body, "acknowledge_review": False},
                )
            ).status_code,
            422,
        )
        approved = await self.client.post(
            prefix + "/human-reviews", headers=self.headers, json=body
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["approved"], 1)
        before = (await self.client.get(prefix + "/events")).json()
        for query in (
            "",
            "?series=maya&outcome=approved_individual",
            "?group=second&mode=interval",
        ):
            response = await self.client.get(prefix + "/activity" + query)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.client.get(prefix + "/events")).json(), before)
        self.assertEqual(
            (await self.client.get(prefix + "/activity?group=invented")).status_code, 422
        )


if __name__ == "__main__":
    unittest.main()
