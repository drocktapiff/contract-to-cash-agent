"""Selected real PDF processing and independent management oversight, never providers."""

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from pydantic import ValidationError
from contract_to_cash.web.store import Store, Settings, StoreError
from contract_to_cash.web.document_workspace import DocumentWorkspace
from contract_to_cash.web.selected_workflow import SelectedCommand, selected_operation
from tests_workspace.test_workspace import command


class SelectedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = DocumentWorkspace(Store(Settings(root=Path(self.tmp.name) / "runs")))
        self.snap = self.ws.load()
        self.sid = self.snap["session_id"]

    def body(self, items=None, **changes):
        values = dict(
            operation_id=uuid4().hex,
            actor="Actual local reviewer",
            rationale="Inspect sources; administrative checks or management oversight only.",
            confirmation="ADMINISTRATIVE WORKFLOW ONLY",
            expected_session=self.sid,
            selected=[
                dict(id=w["work_item_id"], version=w["version"])
                for w in (self.snap["items"] if items is None else items)
            ],
        )
        values.update(changes)
        return SelectedCommand(**values)

    def perform(self, action, body=None):
        return selected_operation(self.ws, self.sid, action, body or self.body())

    def remaining(self):
        return [w for w in self.ws.snapshot()["items"] if w["status"] != "Closed"]

    def event_count(self, kind):
        with self.ws.database(self.ws.directory(self.sid) / "journal.sqlite3") as conn:
            return sum(
                json.loads(r[0])["type"] == kind
                for r in self.ws.rows(conn, "SELECT body FROM workflow_events")
            )

    def test_close_selected_actual_evidence_only_and_idempotent(self):
        body = self.body()
        with patch("socket.create_connection", side_effect=AssertionError("No paid requests")):
            result = self.perform("close", body)
        self.assertEqual(result["checks_completed"], 73)
        self.assertEqual(result["requires_review"], 29)
        self.assertEqual(result["financial_actions_executed"], 0)
        self.assertEqual(len(result["per_item"]), 102)
        count = self.event_count("automated_check_prepared")
        self.assertEqual(self.perform("close", body), result)
        self.assertEqual(self.event_count("automated_check_prepared"), count)
        self.assertEqual(self.ws.snapshot()["last_bulk_operation"]["result"], result)

    def test_subset_does_not_process_other_rows(self):
        selected = [w for w in self.snap["items"] if w["automation_eligible"]][:2]
        result = self.perform("close", self.body(selected))
        self.assertEqual(result["checks_completed"], 2)
        self.assertEqual(self.ws.snapshot()["metrics"]["automated_checks_prepared"], 2)

    def test_all_remaining_handoffs_preserve_finance_and_evidence(self):
        self.perform("close")
        from tests_workspace.test_human_review_activity import approve_pending

        approve_pending(self.ws, self.sid)
        remaining = self.remaining()
        result = self.perform("escalate", self.body(remaining))
        self.assertEqual(len(remaining), 29)
        self.assertEqual(result["handoffs_created"], 29)
        self.assertGreater(result["awaiting_finance"], 0)
        self.assertGreater(result["awaiting_evidence"], 0)
        inbox = self.ws.inbox(self.sid)
        self.assertEqual(len(inbox["items"]), 29)
        for detail in inbox["items"]:
            work = detail["item"]
            self.assertEqual(work["case_owner"], "Maya Tremblay")
            self.assertEqual(work["management_oversight_owner"], "Sarah Chen")
            self.assertFalse(work["oversight"]["financial_authority_transferred"])
            self.assertTrue(detail["documents"])
            self.assertNotEqual(work["status"], "Closed")
            if work["status"] == "Awaiting Financial Review":
                self.assertEqual(work["current_decision_owner"], "Finance")
            if work["status"] == "Awaiting Evidence":
                self.assertIn("Evidence provider", work["current_decision_owner"])
        self.assertEqual(self.ws.snapshot()["business_counts"]["needs_maya"], 0)

    def test_existing_finance_referral_keeps_status_and_authority(self):
        self.ws.perform(self.sid, "auto_all", command())
        finance = next(
            w for w in self.ws.snapshot()["items"] if w["status"] == "Awaiting Financial Review"
        )
        result = self.perform("escalate", self.body([finance]))
        self.assertEqual(result["handoffs_created"], 1)
        work = self.ws.detail(self.sid, finance["work_item_id"])["item"]
        self.assertEqual(work["status"], "Awaiting Financial Review")
        self.assertEqual(work["current_decision_owner"], "Finance")
        self.assertEqual(
            self.ws.inbox(self.sid)["items"][0]["item"]["work_item_id"], finance["work_item_id"]
        )
        # Existing Process All Work cannot take back an oversight handoff or close it.
        self.ws.perform(self.sid, "auto_all", command())
        self.assertEqual(
            self.ws.detail(self.sid, finance["work_item_id"])["item"]["status"],
            "Awaiting Financial Review",
        )

    def test_duplicate_handoff_reuses_real_record(self):
        items = [w for w in self.snap["items"] if not w["automation_eligible"]][:3]
        self.perform("escalate", self.body(items))
        before = self.event_count("escalated")
        current = [self.ws.detail(self.sid, w["work_item_id"])["item"] for w in items]
        second = self.perform("escalate", self.body(current))
        self.assertEqual(second["handoffs_created"], 0)
        self.assertEqual(second["handoffs_reused"], 3)
        self.assertEqual(self.event_count("escalated"), before)
        self.assertEqual(len(self.ws.inbox(self.sid)["items"]), 3)

    def test_partial_success_stale_foreign_and_closed_items(self):
        valid = [w for w in self.snap["items"] if w["automation_eligible"]][:3]
        self.perform("close", self.body([valid[0]]))
        body = self.body(
            valid,
            selected=[
                dict(id=valid[0]["work_item_id"], version=1),
                dict(id=valid[1]["work_item_id"], version=999),
                dict(id=valid[2]["work_item_id"], version=1),
                dict(id="WI-" + "f" * 24, version=1),
            ],
        )
        result = self.perform("close", body)
        self.assertTrue(result["partial"])
        self.assertEqual(result["checks_completed"], 1)
        self.assertEqual(result["blocked"], 3)
        self.assertEqual(self.ws.snapshot()["metrics"]["automated_checks_prepared"], 2)
        self.assertEqual(self.perform("close", body), result)

    def test_item_failure_does_not_block_other_valid_handoffs(self):
        items = self.snap["items"][:3]
        broken = items[1]["work_item_id"]
        original = self.ws.execute

        def fail(conn, query, params=()):
            if query.startswith("UPDATE work_items") and params[1] == broken:
                raise RuntimeError("Injected item failure")
            return original(conn, query, params)

        with patch.object(self.ws, "execute", side_effect=fail):
            result = self.perform("escalate", self.body(items))
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["handoffs_created"], 2)
        self.assertTrue(result["partial"])
        self.assertEqual(len(self.ws.inbox(self.sid)["items"]), 2)
        self.assertNotIn("oversight", self.ws.detail(self.sid, broken)["item"])

    def test_interruption_rolls_back_all_uncommitted_success(self):
        class Interrupted(BaseException):
            pass

        original = self.ws.execute
        updates = 0
        body = self.body()

        def stop(conn, query, params=()):
            nonlocal updates
            if query.startswith("UPDATE work_items"):
                updates += 1
                if updates == 3:
                    raise Interrupted()
            return original(conn, query, params)

        with patch.object(self.ws, "execute", side_effect=stop):
            with self.assertRaises(Interrupted):
                self.perform("close", body)
        snap = self.ws.snapshot()
        self.assertEqual(snap["metrics"]["automatically_completed"], 0)
        self.assertEqual(snap["last_bulk_operation"]["status"], "interrupted")
        self.ws.initialize()
        result = self.perform("close", body)
        self.assertEqual(result["checks_completed"], 73)
        self.assertEqual(self.event_count("automated_check_prepared"), 73)

    def test_changed_source_blocks_only_affected_selected_items(self):
        items = [w for w in self.snap["items"] if w["automation_eligible"]]
        chosen = items[0]
        self.ws.pdf(self.sid, next(iter(chosen["supporting_facts"]))).write_bytes(b"%PDF-changed")
        result = self.perform("close", self.body(items))
        self.assertGreater(result["blocked"], 0)
        self.assertGreater(result["checks_completed"], 0)
        self.assertNotEqual(
            self.ws.detail(self.sid, chosen["work_item_id"])["item"]["status"], "Closed"
        )

    def test_individual_escalation_uses_same_finance_oversight_behavior(self):
        self.ws.perform(self.sid, "auto_all", command())
        finance = next(
            w for w in self.ws.snapshot()["items"] if w["status"] == "Awaiting Financial Review"
        )
        result = self.ws.perform(
            self.sid,
            "escalate",
            command(
                expected_version=finance["version"],
                evidence_hashes=list(finance["supporting_facts"])[:1],
            ),
            finance["work_item_id"],
        )
        self.assertEqual(result["handoffs_created"], 1)
        self.assertEqual(
            self.ws.detail(self.sid, finance["work_item_id"])["item"]["status"],
            "Awaiting Financial Review",
        )

    def test_archived_selection_and_conflicting_operations_rejected(self):
        body = self.body()
        self.ws.load(True, self.sid, command(expected_session=self.sid))
        with self.assertRaises(StoreError):
            self.perform("close", body)
        self.assertEqual(self.ws.snapshot()["metrics"]["automatically_completed"], 0)
        with self.ws.guard():
            with self.assertRaises(StoreError):
                selected_operation(self.ws, self.ws.active(), "close", body)

    def test_selection_schema_uniqueness_and_no_financial_actions(self):
        row = self.body().selected[0]
        with self.assertRaises(ValidationError):
            self.body(selected=[row.model_dump(), row.model_dump()])
        with self.assertRaises(StoreError):
            self.perform("approve_credit")
        work = next(w for w in self.snap["items"] if w["category"] == "contract_conflict")
        body = self.body([work])
        self.perform("escalate", body)
        before = self.event_count("escalated")
        story = self.ws.walkthrough(self.sid, work["work_item_id"])
        self.assertTrue(story["recorded"])
        self.assertFalse(story["can_process"])
        self.ws.walkthrough(self.sid, work["work_item_id"])
        self.assertEqual(self.event_count("escalated"), before)


if __name__ == "__main__":
    unittest.main()
