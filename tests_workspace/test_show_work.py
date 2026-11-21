"""Real source-backed walkthrough and business projections; never a model call."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contract_to_cash.web.document_workspace import DocumentWorkspace
from contract_to_cash.web.store import Store, Settings
from contract_to_cash.web.work_presentation import scenarios, queue_counts
from tests_workspace.test_workspace import command


class ShowWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = DocumentWorkspace(Store(Settings(root=Path(self.tmp.name) / "legacy")))
        self.snap = self.ws.load(command=command())
        self.sid = self.snap["session_id"]

    def selected(self, key):
        return next(s["work_item_id"] for s in self.ws.snapshot()["scenarios"] if s["key"] == key)

    def apply(self, wid):
        work = self.ws.detail(self.sid, wid)["item"]
        return self.ws.perform(
            self.sid,
            "auto",
            command(
                expected_version=work["version"], evidence_hashes=list(work["supporting_facts"])
            ),
            wid,
        )

    def test_scenarios_use_available_records_and_honest_absence(self):
        self.assertEqual(
            {s["key"] for s in self.snap["scenarios"]}, {"routine", "discrepancy", "ambiguity"}
        )
        for s in self.snap["scenarios"]:
            self.assertIn(s["work_item_id"], {w["work_item_id"] for w in self.snap["items"]})
        self.assertTrue(all(s["work_item_id"] is None for s in scenarios([])))
        self.assertEqual(
            self.ws.detail(self.sid, self.selected("ambiguity"))["item"]["category"],
            "contract_conflict",
        )

    def test_manual_and_extracted_facts_point_to_real_pdfs_and_spans(self):
        story = self.ws.walkthrough(self.sid, self.selected("routine"))
        self.assertFalse(story["recorded"])
        self.assertTrue(story["can_process"])
        detail = self.ws.detail(self.sid, story["item"]["work_item_id"])
        docs = {d["file_hash"]: d for d in detail["documents"]}
        for step in story["manual_steps"]:
            if step.get("file_hash"):
                self.assertTrue(
                    self.ws.pdf(self.sid, step["file_hash"]).read_bytes().startswith(b"%PDF-")
                )
        for card in story["documents"]:
            for fact in card["facts"]:
                self.assertEqual(fact["value"], docs[card["file_hash"]]["fields"][fact["field"]])
                for span in fact["spans"]:
                    self.assertIn(span["text"], docs[card["file_hash"]]["pages"][span["page"] - 1])
        self.assertIn("not a measured", story["manual_label"])

    def test_actual_routine_processing_and_read_only_recorded_replay(self):
        wid = self.selected("routine")
        with patch("socket.create_connection", side_effect=AssertionError("No paid requests")):
            result = self.apply(wid)
        self.assertEqual(result["automatically_closed"], 1)
        first = self.ws.snapshot()["telemetry"]["event_count"]
        for _ in range(3):
            story = self.ws.walkthrough(self.sid, wid)
            self.assertTrue(story["recorded"])
            self.assertFalse(story["can_process"])
            self.assertTrue(story["validation"]["details"]["evidence_current"])
            self.assertTrue(story["outcome"]["administratively_completed"])
            self.assertTrue(
                any(e["type"] == "administratively_closed" for e in story["processing_events"])
            )
        self.assertEqual(self.ws.snapshot()["telemetry"]["event_count"], first)

    def test_discrepancy_and_contract_conflict_stop_at_human_decision(self):
        for key, status in [
            ("discrepancy", "Awaiting Financial Review"),
            ("ambiguity", "Escalated"),
        ]:
            wid = self.selected(key)
            before = self.ws.walkthrough(self.sid, wid)
            result = self.apply(wid)
            after = self.ws.walkthrough(self.sid, wid)
            self.assertEqual(result["automatically_closed"], 0)
            self.assertEqual(after["outcome"]["status"], status)
            self.assertFalse(after["outcome"]["financial_action_executed"])
            if key == "discrepancy":
                self.assertEqual(
                    after["validation"]["details"]["financial_comparison"],
                    before["financial_comparison"],
                )
            else:
                self.assertIsNone(after["financial_comparison"])

    def test_remaining_operation_does_not_repeat_completion_or_handoff(self):
        wid = self.selected("routine")
        self.apply(wid)
        other = self.selected("discrepancy")
        self.apply(other)
        result = self.ws.perform(self.sid, "auto_all", command())
        self.assertEqual(result["total_examined"], 102)
        self.assertEqual(result["checks_completed"], 72)
        counts = result["queue_outcome"]
        self.assertEqual(counts["completed"], 73)
        self.assertEqual(
            sum(
                counts[k]
                for k in (
                    "completed",
                    "needs_maya",
                    "awaiting_sarah",
                    "awaiting_finance",
                    "awaiting_evidence",
                )
            ),
            102,
        )
        story = self.ws.walkthrough(self.sid, other)
        self.assertEqual(
            sum(
                e["type"] == "human_review_requested"
                for e in story["item"]["event_history"]
                if e.get("after") == "Awaiting Financial Review"
            ),
            1,
        )
        second = self.ws.perform(self.sid, "auto_all", command())
        self.assertEqual(second["checks_completed"], 0)
        self.assertEqual(second["queue_outcome"], counts)

    def test_altered_source_blocks_walkthrough_closure(self):
        wid = self.selected("routine")
        work = self.ws.detail(self.sid, wid)["item"]
        self.ws.pdf(self.sid, next(iter(work["supporting_facts"]))).write_bytes(b"%PDF-modified")
        self.apply(wid)
        story = self.ws.walkthrough(self.sid, wid)
        self.assertFalse(story["validation"]["details"]["evidence_current"])
        self.assertFalse(story["outcome"]["administratively_completed"])
        self.assertIsNone(story["financial_comparison"])

    def test_legacy_history_without_proof_is_not_fabricated(self):
        wid = self.selected("routine")
        self.apply(wid)
        database = self.ws.directory(self.sid) / "journal.sqlite3"
        with self.ws.database(database) as conn, conn:
            work = json.loads(
                self.ws.rows(conn, "SELECT body FROM work_items WHERE id=?", (wid,))[0][0]
            )
            work["event_history"] = [
                e for e in work["event_history"] if e.get("type") != "evidence_validation_recorded"
            ]
            self.ws.execute(
                conn, "UPDATE work_items SET body=? WHERE id=?", (json.dumps(work), wid)
            )
        story = self.ws.walkthrough(self.sid, wid)
        self.assertTrue(story["recorded"])
        self.assertIsNone(story["validation"])


if __name__ == "__main__":
    unittest.main()
