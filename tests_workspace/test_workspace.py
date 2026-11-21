"""Real Stage 1 PDFs, real journals and zero provider calls."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4
from contract_to_cash.web.store import Store, Settings, StoreError
from contract_to_cash.web.document_workspace import DocumentWorkspace, WorkspaceCommand, SAMPLE


def command(**changes):
    return WorkspaceCommand(
        **dict(
            operation_id=uuid4().hex,
            actor="Actual local test reviewer",
            rationale="Inspect source evidence and record a permitted administrative workflow only.",
            confirmation="ADMINISTRATIVE WORKFLOW ONLY",
            **changes
        )
    )


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(Settings(root=self.root / "legacy"))
        self.ws = DocumentWorkspace(self.store)
        self.snap = self.ws.load(command=command())
        self.sid = self.snap["session_id"]

    def work(self, category=None, eligible=None):
        return next(
            w
            for w in self.ws.snapshot()["items"]
            if (category is None or w["category"] == category)
            and (eligible is None or w["automation_eligible"] == eligible)
        )

    def events(self):
        with self.ws.database(self.ws.directory(self.sid) / "journal.sqlite3") as conn:
            return [
                json.loads(r[0])
                for r in self.ws.rows(conn, "SELECT body FROM workflow_events ORDER BY sequence")
            ]

    def item_command(self, work, **changes):
        return command(
            expected_version=work["version"],
            evidence_hashes=list(work["supporting_facts"])[:1],
            **changes
        )

    def test_real_sample_counts_categories_and_zero_completed(self):
        self.assertEqual(self.snap["document_count"], 149)
        self.assertEqual(self.snap["customer_count"], 40)
        self.assertEqual(
            self.snap["metrics"],
            dict(
                total=102,
                automatically_completed=0,
                awaiting_maya=102,
                escalated=0,
                routine_eligible=73,
                exceptions=29,
            ),
        )
        self.assertEqual(
            {w["category"] for w in self.snap["items"]},
            {
                "contract_price_validation",
                "contract_conflict",
                "missing_documentation",
                "amendment_review",
                "invoice_reconciliation",
                "payment_matching",
                "renewal_review",
                "credit_review",
                "usage_validation",
                "document_review",
            },
        )
        expected = json.loads(
            (SAMPLE.parent / "evaluation" / "expected.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            Counter(w["category"] for w in self.snap["items"]),
            Counter(w["category"] for w in expected["work_items"]),
        )
        self.assertTrue(
            all(
                e["actor_kind"] != "simulated_fixture" and not e["simulated_activity"]
                for e in self.events()
            )
        )

    def test_repeat_import_preserves_records_and_events_idempotently(self):
        body = command()
        before = self.ws.snapshot()["telemetry"]["event_count"]
        second = self.ws.load(command=body)
        third = self.ws.load(command=body)
        self.assertEqual(second["session_id"], self.sid)
        self.assertEqual(third["metrics"], second["metrics"])
        self.assertEqual(third["telemetry"]["event_count"], before + 1)
        self.assertEqual(
            {w["work_item_id"] for w in second["items"]},
            {w["work_item_id"] for w in self.snap["items"]},
        )

    def test_routine_revalidates_original_pdf_evidence_and_retries(self):
        body = command()
        with patch("socket.create_connection", side_effect=AssertionError("No provider requests")):
            result = self.ws.perform(self.sid, "routine", body)
        self.assertEqual(result["checks_completed"], 73)
        self.assertEqual(result["skipped"], 29)
        count = len(self.events())
        self.assertEqual(self.ws.perform(self.sid, "routine", body), result)
        self.assertEqual(len(self.events()), count)
        snap = self.ws.snapshot()
        self.assertEqual(snap["metrics"]["automatically_completed"], 73)
        self.assertEqual(snap["metrics"]["awaiting_maya"], 29)
        self.assertEqual(snap["telemetry"]["routine_completion_rate"], 1)
        self.assertEqual(len(snap["telemetry"]["status_transitions"]), 73)
        self.assertIsNone(snap["telemetry"]["human_labor_seconds"])
        self.assertEqual(snap["telemetry"]["api_cost_usd"], "0.00")
        self.assertTrue(all(not e["financial_action_executed"] for e in self.events()))

    def test_changed_evidence_never_closes_routine_item(self):
        work = self.work(eligible=True)
        digest = next(iter(work["supporting_facts"]))
        source = self.ws.pdf(self.sid, digest)
        original = source.read_bytes()
        source.write_bytes(b"%PDF-invalid modified source")
        result = self.ws.perform(self.sid, "routine", command())
        changed = self.ws.detail(self.sid, work["work_item_id"])["item"]
        self.assertNotEqual(changed["status"], "Closed")
        self.assertFalse(changed["automation_eligible"])
        self.assertIsNone(changed["financial_impact"])
        self.assertLess(result["checks_completed"], 73)
        with self.assertRaises(StoreError):
            self.ws.pdf(self.sid, digest)
        source.write_bytes(original)
        self.ws.perform(self.sid, "routine", command())
        self.assertEqual(self.ws.detail(self.sid, work["work_item_id"])["item"]["status"], "Closed")

    def test_individual_auto_is_disposition_not_unconditional_closure(self):
        work = self.work("contract_conflict")
        body = self.item_command(work)
        result = self.ws.perform(self.sid, "auto", body, work["work_item_id"])
        self.assertEqual(result["automatically_closed"], 0)
        self.assertEqual(result["escalated_to_sarah"], 1)
        inbox = self.ws.inbox(self.sid)
        self.assertEqual(len(inbox["items"]), 1)
        entry = inbox["items"][0]
        self.assertEqual(entry["item"]["work_item_id"], work["work_item_id"])
        self.assertTrue(entry["documents"])
        self.assertTrue(
            any(
                e.get("type") == "human_decision_recorded" and e["actor_kind"] == "human"
                for e in entry["item"]["event_history"]
            )
        )

    def test_bulk_auto_routes_uncertainty_and_is_repeatable(self):
        result = self.ws.perform(self.sid, "auto_all", command())
        snap = self.ws.snapshot()
        self.assertEqual(result["automatically_closed"], 73)
        self.assertGreater(result["escalated_to_sarah"], 0)
        self.assertEqual(snap["metrics"]["total"], 102)
        self.assertEqual(snap["metrics"]["automatically_completed"], 73)
        for work in snap["items"]:
            if work["category"] in (
                "contract_conflict",
                "amendment_review",
                "credit_review",
                "missing_documentation",
                "document_review",
                "invoice_reconciliation",
            ):
                self.assertNotEqual(work["status"], "Closed")
        again = self.ws.perform(self.sid, "auto_all", command())
        self.assertEqual(again["automatically_closed"], 0)
        self.assertEqual(self.ws.snapshot()["metrics"], snap["metrics"])

    def test_authority_and_financial_approvals_are_not_actions(self):
        work = self.work("credit_review")
        for action in ("approve_credit", "approve_contract", "export", "issue_credit"):
            with self.assertRaises(StoreError):
                self.ws.perform(self.sid, action, self.item_command(work), work["work_item_id"])
        with self.assertRaises(StoreError):
            self.ws.perform(self.sid, "routine", self.item_command(work), work["work_item_id"])
        self.ws.perform(self.sid, "accept", self.item_command(work), work["work_item_id"])
        fresh = self.ws.detail(self.sid, work["work_item_id"])["item"]
        self.assertEqual(fresh["status"], "Awaiting Financial Review")
        self.assertNotEqual(fresh["status"], "Closed")

    def test_stale_versions_and_foreign_evidence_rejected(self):
        work = self.work("contract_conflict")
        body = self.item_command(work)
        self.ws.perform(self.sid, "escalate", body, work["work_item_id"])
        with self.assertRaises(StoreError):
            self.ws.perform(
                self.sid, "request_evidence", self.item_command(work), work["work_item_id"]
            )
        fresh = self.ws.detail(self.sid, work["work_item_id"])["item"]
        invalid = command(expected_version=fresh["version"], evidence_hashes=["f" * 64])
        with self.assertRaises(StoreError):
            self.ws.perform(self.sid, "accept", invalid, work["work_item_id"])

    def test_rejection_blocks_automatic_disposition_until_human_accepts(self):
        work = self.work(eligible=True)
        self.ws.perform(self.sid, "reject", self.item_command(work), work["work_item_id"])
        self.ws.perform(self.sid, "auto_all", command())
        fresh = self.ws.detail(self.sid, work["work_item_id"])["item"]
        self.assertNotEqual(fresh["status"], "Closed")
        self.assertTrue(fresh["human_review_required"])
        self.ws.perform(self.sid, "accept", self.item_command(fresh), fresh["work_item_id"])
        self.assertEqual(self.ws.detail(self.sid, work["work_item_id"])["item"]["status"], "Closed")

    def test_restart_fresh_active_session_retains_history_and_idempotency(self):
        self.ws.perform(self.sid, "routine", command())
        old = self.ws.snapshot(self.sid)
        body = command(expected_session=self.sid)
        fresh = self.ws.load(True, self.sid, body)
        again = self.ws.load(True, self.sid, body)
        self.assertNotEqual(fresh["session_id"], self.sid)
        self.assertEqual(again["session_id"], fresh["session_id"])
        self.assertEqual(fresh["metrics"]["automatically_completed"], 0)
        self.assertEqual(fresh["metrics"]["total"], 102)
        self.assertEqual(self.ws.snapshot()["session_id"], fresh["session_id"])
        self.assertEqual(self.ws.snapshot(self.sid)["metrics"], old["metrics"])
        self.assertTrue(self.ws.snapshot(self.sid)["read_only"])
        with self.assertRaises(StoreError):
            self.ws.perform(self.sid, "routine", command())
        # Full source PDFs and original journal remain removable after handles close on Windows.
        self.assertTrue((self.ws.directory(self.sid) / "documents").is_dir())

    def test_immutable_audit_and_correct_human_vs_automation(self):
        work = self.work("contract_conflict")
        self.ws.perform(self.sid, "escalate", self.item_command(work), work["work_item_id"])
        events = self.events()
        self.assertTrue(any(e["actor_kind"] == "human" for e in events))
        self.assertTrue(any(e["actor_kind"] == "deterministic_automation" for e in events))
        with self.ws.database(self.ws.directory(self.sid) / "journal.sqlite3") as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                self.ws.execute(conn, "DELETE FROM workflow_events")
            with self.assertRaises(sqlite3.IntegrityError):
                self.ws.execute(conn, "UPDATE workflow_events SET body='{}'")

    def test_interrupted_operation_rolls_back_and_retry_recovers(self):
        body = command()
        original = self.ws.execute
        writes = 0

        def interrupted(conn, query, params=()):
            nonlocal writes
            if query.startswith("UPDATE work_items"):
                writes += 1
                if writes == 3:
                    raise RuntimeError("Simulated interruption")
            return original(conn, query, params)

        with patch.object(self.ws, "execute", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.ws.perform(self.sid, "routine", body)
        self.assertEqual(self.ws.snapshot()["metrics"]["automatically_completed"], 0)
        self.ws.initialize()
        result = self.ws.perform(self.sid, "routine", body)
        self.assertEqual(result["checks_completed"], 73)
        self.assertEqual(self.ws.snapshot()["telemetry"]["retry_count"], 1)

    def test_recovery_of_persisted_running_operation(self):
        body = command()
        self.ws.perform(self.sid, "routine", body)
        database = self.ws.directory(self.sid) / "journal.sqlite3"
        with self.ws.database(database) as conn, conn:
            self.ws.execute(
                conn,
                "UPDATE workflow_operations SET status='running',result=NULL WHERE id=?",
                (body.operation_id,),
            )
        self.ws.initialize()
        self.assertFalse(self.ws.snapshot()["processing_active"])
        self.assertTrue(any(e["type"] == "processing_failed" for e in self.events()))
        # Existing closed work is not duplicated or reopened by recovery.
        self.assertEqual(self.ws.snapshot()["metrics"]["automatically_completed"], 73)

    def test_concurrent_worker_and_workspace_operations_are_blocked(self):
        with self.ws.guard():
            with self.assertRaises(StoreError):
                self.ws.perform(self.sid, "routine", command())
            with self.assertRaises(StoreError):
                self.ws.load(True, self.sid, command(expected_session=self.sid))
        stop = Event()
        worker = Thread(target=stop.wait)
        worker.start()
        self.store.worker = worker
        try:
            with self.assertRaises(StoreError):
                self.ws.load(True, self.sid, command(expected_session=self.sid))
        finally:
            stop.set()
            worker.join()
            self.store.worker = None

    def test_existing_legacy_history_and_source_pdfs_never_mutated(self):
        legacy = self.store.settings.root
        legacy.mkdir(parents=True)
        file = legacy / "genuine-history.txt"
        file.write_text("Keep real decisions")
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in SAMPLE.glob("*.pdf")}
        self.ws.perform(self.sid, "auto_all", command())
        self.ws.load(True, self.sid, command(expected_session=self.sid))
        self.assertEqual(file.read_text(), "Keep real decisions")
        self.assertEqual(
            before,
            {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in SAMPLE.glob("*.pdf")},
        )

    def test_advisory_proposals_are_non_authoritative_and_evidence_bound(self):
        from contract_to_cash.web.document_recommendations import validate_proposal

        work = self.work("contract_conflict")
        payload = dict(
            suggested_disposition="escalate",
            why="Conflicting executed pricing terms require authority.",
            evidence_hashes=list(work["supporting_facts"])[:1],
            human_judgment_required="Resolve contractual authority separately.",
        )
        proposal = validate_proposal(payload, work)
        self.assertFalse(proposal["authority"])
        for changes in (
            {"suggested_disposition": "approve_contract"},
            {"financial_impact": {"amount": "9999"}},
            {"evidence_hashes": ["f" * 64]},
            {"evidence_hashes": payload["evidence_hashes"] * 2},
        ):
            with self.assertRaises(ValueError):
                validate_proposal({**payload, **changes}, work)

    def test_repeat_import_retains_processed_state_and_referral_scope(self):
        work = self.work("contract_price_validation", eligible=True)
        self.assertNotIn("financial_review", self.ws.allowed(work))
        with self.assertRaises(StoreError):
            self.ws.perform(
                self.sid, "financial_review", self.item_command(work), work["work_item_id"]
            )
        self.ws.perform(self.sid, "routine", command())
        current = self.ws.snapshot()
        imported = self.ws.load(command=command())
        self.assertEqual(imported["session_id"], self.sid)
        self.assertEqual(imported["metrics"], current["metrics"])
        self.assertEqual(imported["metrics"]["automatically_completed"], 73)


if __name__ == "__main__":
    unittest.main()
