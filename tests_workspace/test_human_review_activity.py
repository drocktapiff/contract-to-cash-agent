"""Actual PDF preparation -> attributed review -> event-backed activity. No providers."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from contract_to_cash.web.store import Store, Settings, StoreError
from contract_to_cash.web.document_workspace import DocumentWorkspace
from contract_to_cash.web.selected_workflow import SelectedCommand, selected_operation
from contract_to_cash.web.human_review import ReviewCommand, review, preview, PENDING, REJECTED
from contract_to_cash.web.operational_activity import activity
from tests_workspace.test_workspace import command


def approve_pending(ws, sid, *, attestation="bulk", limit=None):
    pending = [w for w in ws.snapshot(sid)["items"] if w["status"] == PENDING]
    if limit:
        pending = pending[:limit]
    return review(
        ws,
        sid,
        ReviewCommand(
            **command(expected_session=sid).model_dump(),
            selected=[
                dict(
                    id=w["work_item_id"],
                    version=w["version"],
                    evidence_hashes=list(w["supporting_facts"]),
                )
                for w in pending
            ],
            decision="approve",
            attestation=attestation,
            acknowledge_review=True
        ),
    )


class HumanReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Settings(root=Path(self.tmp.name) / "runs"))
        self.addCleanup(self.store.close)
        self.ws = DocumentWorkspace(self.store)
        self.snap = self.ws.load()
        self.sid = self.snap["session_id"]

    def selected(self, works=None):
        return SelectedCommand(
            **command(expected_session=self.sid).model_dump(),
            selected=[
                dict(id=w["work_item_id"], version=w["version"])
                for w in (works or self.ws.snapshot()["items"])
            ]
        )

    def prepare(self):
        return selected_operation(self.ws, self.sid, "close", self.selected())

    def pending(self):
        return [w for w in self.ws.snapshot()["items"] if w["status"] == PENDING]

    def body(self, works=None, **changes):
        values = dict(
            **command(expected_session=self.sid).model_dump(),
            selected=[
                dict(
                    id=w["work_item_id"],
                    version=w["version"],
                    evidence_hashes=list(w["supporting_facts"]),
                )
                for w in (works or self.pending())
            ],
            decision="approve",
            attestation="bulk",
            acknowledge_review=True
        )
        values.update(changes)
        return ReviewCommand(**values)

    def events(self):
        with self.ws.database(self.ws.directory(self.sid) / "journal.sqlite3") as conn:
            return [
                json.loads(r[0]) for r in self.ws.rows(conn, "SELECT body FROM workflow_events")
            ]

    def test_prepare_is_not_closure_and_retry_cannot_close_pending(self):
        with patch("socket.create_connection", side_effect=AssertionError("No provider calls")):
            result = self.prepare()
        self.assertEqual(result["prepared_for_review"], 73)
        self.assertEqual(result["automatically_closed"], 0)
        self.assertEqual(len(self.pending()), 73)
        self.assertFalse(any(w["status"] == "Closed" for w in self.ws.snapshot()["items"]))
        self.prepare()
        self.ws.perform(self.sid, "auto_all", command())
        self.assertEqual(len(self.pending()), 73)
        self.assertEqual(sum(e["type"] == "automated_check_prepared" for e in self.events()), 73)
        self.assertFalse(any(e["type"] == "administratively_closed" for e in self.events()))

    def test_repeated_preparation_keeps_pending_versions_reviewable(self):
        self.prepare()
        before = {w["work_item_id"]: w["version"] for w in self.pending()}
        self.prepare()
        self.assertEqual({w["work_item_id"]: w["version"] for w in self.pending()}, before)
        self.assertEqual(approve_pending(self.ws, self.sid)["approved"], 73)

    def test_processing_reports_reviewed_closures_without_second_approval(self):
        self.prepare()
        approve_pending(self.ws, self.sid, attestation="individual", limit=1)
        result = selected_operation(self.ws, self.sid, "close", self.selected())
        self.assertEqual(result["already_reviewed_closed"], 1)
        self.assertEqual(result["prepared_for_review"], 0)
        self.assertEqual(result["legacy_closures_excluded"], 0)
        self.assertEqual(activity(self.ws, self.sid)["metrics"]["approved_individual"]["value"], 1)

    def test_every_processing_entry_point_requires_review(self):
        self.ws.perform(self.sid, "auto_all", command())
        self.assertEqual(len(self.pending()), 73)
        self.assertEqual(self.ws.snapshot()["metrics"]["reviewed_closed"], 0)

    def test_individual_review_links_source_versions_and_immutable_preparation(self):
        self.prepare()
        w = self.pending()[0]
        body = self.body([w], attestation="individual")
        result = review(self.ws, self.sid, body)
        self.assertEqual(result["approved"], 1)
        after = self.ws.detail(self.sid, w["work_item_id"])["item"]
        self.assertEqual(after["lifecycle_label"], "Reviewed & Closed")
        self.assertEqual(after["review"]["attestation"], "individual")
        self.assertEqual(after["review"]["reviewed_version"], w["version"])
        self.assertEqual(after["review"]["preparation_event_id"], w["automated_result"]["event_id"])
        self.assertEqual(after["automated_result"], w["automated_result"])
        self.assertEqual(review(self.ws, self.sid, body), result)
        self.assertEqual(review(self.ws, self.sid, self.body([after]))["excluded"], 1)

    def test_advisor_context_never_labels_prepared_work_as_closed(self):
        from contract_to_cash.web.management_center import ManagementCenter
        from contract_to_cash.web.document_advisor import DocumentAdvisor, INSTRUCTIONS

        self.prepare()
        exceptions = [w for w in self.ws.snapshot()["items"] if w["status"] != PENDING]
        selected_operation(self.ws, self.sid, "escalate", self.selected(exceptions))
        center = ManagementCenter(self.ws)
        advisor = DocumentAdvisor(center)
        self.store.document_advisor = advisor
        advisor.initialize()
        inputs = advisor.inputs(self.sid)
        self.assertEqual(inputs["metrics"]["completed"], 0)
        self.assertEqual(inputs["metrics"]["awaiting_maya_review"], 73)
        self.assertEqual(inputs["metrics"]["automated_checks_prepared"], 73)
        self.assertIn("NOT closed", INSTRUCTIONS)
        self.assertIn("NOT individual inspections", INSTRUCTIONS)
        self.assertEqual(advisor.records(), [])

    def test_bulk_review_separate_attribution_and_distinct_counts(self):
        self.prepare()
        approve_pending(self.ws, self.sid, attestation="individual", limit=1)
        approve_pending(self.ws, self.sid)
        o = activity(self.ws, self.sid)
        m = o["metrics"]
        self.assertEqual(
            [
                m[k]["value"]
                for k in (
                    "prepared",
                    "approved_individual",
                    "approved_bulk",
                    "closed",
                    "awaiting_review",
                )
            ],
            [73, 1, 72, 73, 0],
        )
        self.assertEqual(o["distinct_closed"], 73)
        events = [e for e in self.events() if e["type"] == "human_review_approved"]
        self.assertEqual(len(events), 73)
        self.assertEqual(sum(e["details"]["attestation"] == "bulk_attested" for e in events), 72)
        self.assertTrue(
            all(
                e["actor_kind"] == "human" and e["actor"] == "Actual local test reviewer"
                for e in events
            )
        )
        self.assertEqual(m["acceptance_rate"]["value"], 1)
        self.assertGreaterEqual(m["turnaround"]["value"], 0)

    def test_rejection_retained_and_cannot_be_approved_by_retry(self):
        self.prepare()
        w = self.pending()[0]
        review(self.ws, self.sid, self.body([w], attestation="individual", decision="reject"))
        self.prepare()
        self.ws.perform(self.sid, "auto_all", command())
        after = self.ws.detail(self.sid, w["work_item_id"])["item"]
        self.assertEqual(after["status"], REJECTED)
        self.assertEqual(after["review"]["decision"], "reject")
        self.assertEqual(review(self.ws, self.sid, self.body([after]))["excluded"], 1)
        m = activity(self.ws, self.sid)["metrics"]
        self.assertEqual(m["acceptance_rate"]["value"], 0)
        self.assertEqual(m["rejected"]["value"], 1)

    def test_rejection_preview_remains_accurate_after_evidence_request(self):
        self.prepare()
        w = self.pending()[0]
        review(self.ws, self.sid, self.body([w], decision="reject", attestation="individual"))
        w = self.ws.detail(self.sid, w["work_item_id"])["item"]
        self.ws.perform(
            self.sid,
            "request_evidence",
            command(expected_version=w["version"], evidence_hashes=list(w["supporting_facts"])),
            w["work_item_id"],
        )
        w = self.ws.detail(self.sid, w["work_item_id"])["item"]
        result = preview(self.ws, self.sid, self.selected([w]))
        self.assertEqual(result["previously_rejected"], 1)
        self.assertEqual(result["eligible"], 0)
        self.assertEqual(result["changed_evidence"], 0)

    def test_bulk_excludes_financial_conflicts_and_uncertain_cases(self):
        self.prepare()
        body = self.selected()
        p = preview(self.ws, self.sid, body)
        self.assertEqual([p[k] for k in ("selected", "eligible", "excluded")], [102, 73, 29])
        result = review(self.ws, self.sid, self.body(self.ws.snapshot()["items"]))
        self.assertEqual(result["approved"], 73)
        self.assertEqual(result["excluded"], 29)
        for w in self.ws.snapshot()["items"]:
            if not w.get("automated_result"):
                self.assertNotEqual(w["status"], "Closed")
        self.assertEqual(result["financial_actions_executed"], 0)

    def test_changed_evidence_and_stale_version_excluded_per_item(self):
        self.prepare()
        works = self.pending()[:2]
        body = self.body(works)
        self.ws.pdf(self.sid, next(iter(works[0]["supporting_facts"]))).write_bytes(b"%PDF-changed")
        result = review(self.ws, self.sid, body)
        self.assertEqual(result["approved"], 1)
        self.assertEqual(result["excluded"], 1)
        self.assertEqual(
            self.ws.detail(self.sid, works[0]["work_item_id"])["item"]["status"], PENDING
        )
        retry = selected_operation(self.ws, self.sid, "close", self.selected([works[0]]))
        self.assertEqual(retry["blocked"], 1)
        self.assertEqual(
            self.ws.detail(self.sid, works[0]["work_item_id"])["item"]["status"],
            "Awaiting Evidence",
        )

    def test_bad_hashes_acknowledgement_session_and_concurrency(self):
        self.prepare()
        w = self.pending()[0]
        with self.assertRaises(ValidationError):
            self.body([w], acknowledge_review=False)
        body = self.body(
            [w],
            selected=[
                dict(id=w["work_item_id"], version=w["version"], evidence_hashes=["foreign"])
            ],
        )
        self.assertEqual(review(self.ws, self.sid, body)["excluded"], 1)
        body = self.body(
            [w],
            selected=[
                dict(id=w["work_item_id"], version=999, evidence_hashes=list(w["supporting_facts"]))
            ],
        )
        self.assertEqual(review(self.ws, self.sid, body)["excluded"], 1)
        self.store.active = "busy"
        try:
            with self.assertRaises(StoreError):
                review(self.ws, self.sid, self.body([w]))
        finally:
            self.store.active = None
        with self.assertRaises(StoreError):
            review(self.ws, self.sid, self.body([w], expected_session="f" * 32))

    def test_forged_preparation_cannot_create_a_human_approval(self):
        self.prepare()
        w = self.pending()[0]
        with self.ws.database(self.ws.directory(self.sid) / "journal.sqlite3") as conn, conn:
            w["automated_result"]["event_id"] = "forged"
            self.ws.execute(
                conn, "UPDATE work_items SET body=? WHERE id=?", (json.dumps(w), w["work_item_id"])
            )
        self.assertEqual(preview(self.ws, self.sid, self.selected([w]))["eligible"], 0)
        self.assertEqual(review(self.ws, self.sid, self.body([w]))["excluded"], 1)
        self.assertEqual(self.ws.snapshot()["metrics"]["reviewed_closed"], 0)

    def test_review_table_and_events_are_immutable(self):
        self.prepare()
        approve_pending(self.ws, self.sid, attestation="individual", limit=1)
        import sqlite3

        with self.ws.database(self.ws.directory(self.sid) / "journal.sqlite3") as conn:
            for query in (
                "DELETE FROM human_review_decisions",
                "UPDATE human_review_decisions SET body=body",
            ):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.ws.execute(conn, query)

    def test_review_interruption_rolls_back_and_retries_same_operation(self):
        self.prepare()
        body = self.body()
        original = self.ws.execute
        updates = 0

        class Interrupted(BaseException):
            pass

        def stop(conn, sql, params=()):
            nonlocal updates
            if sql.startswith("UPDATE work_items"):
                updates += 1
                if updates == 2:
                    raise Interrupted()
            return original(conn, sql, params)

        with patch.object(self.ws, "execute", side_effect=stop):
            with self.assertRaises(Interrupted):
                review(self.ws, self.sid, body)
        self.assertEqual(len(self.pending()), 73)
        self.assertEqual(review(self.ws, self.sid, body)["approved"], 73)

    def test_restart_retains_review_history_read_only_no_inherited_approvals(self):
        self.prepare()
        approve_pending(self.ws, self.sid)
        body = self.body([self.ws.snapshot()["items"][0]])
        fresh = self.ws.load(True, self.sid, command(expected_session=self.sid))
        self.assertEqual(fresh["metrics"]["automated_checks_prepared"], 0)
        self.assertEqual(fresh["metrics"]["reviewed_closed"], 0)
        self.assertEqual(activity(self.ws, self.sid)["metrics"]["closed"]["value"], 73)
        with self.assertRaises(StoreError):
            review(self.ws, self.sid, body)

    def test_legacy_closure_projection_does_not_invent_review(self):
        w = self.snap["items"][0]
        with self.ws.database(self.ws.directory(self.sid) / "journal.sqlite3") as conn, conn:
            w["status"] = "Closed"
            self.ws.execute(
                conn, "UPDATE work_items SET body=? WHERE id=?", (json.dumps(w), w["work_item_id"])
            )
        self.ws.initialize()
        after = self.ws.detail(self.sid, w["work_item_id"])["item"]
        self.assertIn("Legacy automated closure", after["lifecycle_label"])
        self.assertNotIn("review", after)
        self.assertEqual(activity(self.ws, self.sid)["metrics"]["closed"]["value"], 0)
        self.assertEqual(activity(self.ws, self.sid)["legacy_closed"], 1)

    def test_graph_filter_ordering_contributors_and_no_double_counting(self):
        self.prepare()
        approve_pending(self.ws, self.sid)
        exceptions = [w for w in self.ws.snapshot()["items"] if w["status"] != "Closed"]
        selected_operation(self.ws, self.sid, "escalate", self.selected(exceptions))
        graph = activity(self.ws, self.sid)
        self.assertEqual({p["series"] for p in graph["points"]}, {"automation", "maya", "sarah"})
        stamps = [datetime.fromisoformat(p["at"]) for p in graph["points"]]
        self.assertEqual(stamps, sorted(stamps))
        ids = {e["id"] for e in self.events()}
        for p in graph["points"]:
            self.assertTrue({e["id"] for e in p["events"]} <= ids)
            self.assertEqual(p["count"], len({w["id"] for w in p["items"]}))
            self.assertTrue(all(e["at"] <= p["at"] for e in p["events"]))
        self.assertEqual(graph["distinct_closed"], 73)
        self.assertEqual(graph["metrics"]["escalated"]["value"], 29)
        for outcome, series, expected in [
            ("prepared", "automation", 73),
            ("approved_bulk", "maya", 73),
            ("escalated", "sarah", 29),
        ]:
            part = activity(self.ws, self.sid, outcome=outcome, series=series)
            self.assertEqual(part["points"][-1]["value"], expected)
            self.assertTrue(all(p["series"] == series for p in part["points"]))
        self.assertEqual(activity(self.ws, self.sid, series="")["points"], [])

    def test_identical_recorded_coordinates_keep_every_actor_and_source(self):
        self.ws.interaction_kind = "simulated_fixture"
        fixed = "2026-04-15T12:00:00+00:00"
        with patch("contract_to_cash.web.document_workspace.now", return_value=fixed), patch(
            "contract_to_cash.web.human_review.now", return_value=fixed
        ):
            w = next(w for w in self.snap["items"] if w["automation_eligible"])
            selected_operation(self.ws, self.sid, "close", self.selected([w]))
            w = self.pending()[0]
            review(self.ws, self.sid, self.body([w], decision="reject", attestation="individual"))
            w = self.ws.detail(self.sid, w["work_item_id"])["item"]
            selected_operation(self.ws, self.sid, "escalate", self.selected([w]))
        graph = activity(self.ws, self.sid)
        self.assertEqual({(p["at"], p["value"]) for p in graph["points"]}, {(fixed, 1)})
        self.assertEqual({p["series"] for p in graph["points"]}, {"automation", "maya", "sarah"})
        self.assertTrue(all(p["items"][0]["id"] == w["work_item_id"] for p in graph["points"]))

    def test_management_coordination_is_real_activity_not_a_resolution(self):
        from contract_to_cash.web.management_center import ManagementCenter, ManagementCommand

        self.prepare()
        approve_pending(self.ws, self.sid)
        exceptions = [w for w in self.ws.snapshot()["items"] if w["status"] != "Closed"]
        selected_operation(self.ws, self.sid, "escalate", self.selected(exceptions))
        center = ManagementCenter(self.ws)
        w = center.overview(self.sid)["cases"][0]
        body = ManagementCommand(
            **command(expected_session=self.sid).model_dump(),
            selected=[dict(id=w["work_item_id"], version=w["version"])],
            action="prioritize",
            priority="High",
            required_next_action="Coordinate an evidence-backed departmental review."
        )
        center.command(self.sid, body)
        graph = activity(self.ws, self.sid, outcome="management_coordination", series="sarah")
        self.assertEqual(graph["points"][0]["count"], 1)
        self.assertEqual(graph["points"][0]["events"][0]["type"], "priority_changed")
        self.assertEqual(graph["distinct_closed"], 73)
        self.assertEqual(graph["metrics"]["escalated"]["value"], 29)

    def test_graph_real_time_grouping_zoom_and_replay_are_read_only(self):
        self.prepare()
        approve_pending(self.ws, self.sid)
        before = self.events()
        for group in ("operation", "second", "minute", "hour"):
            o = activity(self.ws, self.sid, mode="interval", group=group)
            self.assertTrue(all(p["value"] == p["count"] for p in o["points"]))
            if o["points"]:
                part = activity(self.ws, self.sid, operation=o["points"][0]["operation_ids"][0])
                self.assertTrue(all(len(p["operation_ids"]) == 1 for p in part["points"]))
        self.assertEqual(self.events(), before)
        with self.assertRaises(StoreError):
            activity(self.ws, self.sid, group="fake-sequence")
        with self.assertRaises(StoreError):
            activity(self.ws, self.sid, start="not-a-time")

    def test_evidence_request_and_escalation_preserve_preparation(self):
        self.prepare()
        works = self.pending()[:2]
        for w, decision in zip(works, ("evidence", "escalate")):
            self.assertEqual(
                review(
                    self.ws, self.sid, self.body([w], attestation="individual", decision=decision)
                )["excluded"],
                0,
            )
            after = self.ws.detail(self.sid, w["work_item_id"])["item"]
            self.assertEqual(after["automated_result"], w["automated_result"])
            self.assertNotEqual(after["status"], "Closed")
        self.assertEqual(activity(self.ws, self.sid)["metrics"]["escalated"]["value"], 1)
        metrics = activity(self.ws, self.sid)["metrics"]
        self.assertEqual(set(metrics["turnaround"]["ids"]), {w["work_item_id"] for w in works})
        self.assertIsNotNone(metrics["turnaround"]["value"])
        self.assertIsNone(metrics["acceptance_rate"]["value"])


if __name__ == "__main__":
    unittest.main()
