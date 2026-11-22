"""Real-PDF lifecycle and pure adverse-history projections, without a provider."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from contract_to_cash.web.store import Store, Settings, StoreError
from contract_to_cash.web.document_workspace import DocumentWorkspace
from contract_to_cash.web.selected_workflow import selected_operation, SelectedCommand
from contract_to_cash.web.human_review import ReviewCommand, review, PENDING
from contract_to_cash.web.management_center import ManagementCenter, ManagementCommand
from contract_to_cash.web.work_lifecycle import lifecycle, project, current_bucket
from tests_workspace.test_workspace import command
from tests_workspace.test_human_review_activity import approve_pending


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(Settings(root=Path(cls.tmp.name) / "runs"))
        cls.ws = DocumentWorkspace(cls.store)
        cls.sid = cls.ws.load()["session_id"]
        cls.initial = lifecycle(cls.ws, cls.sid)
        cls.close_all()
        cls.prepared = lifecycle(cls.ws, cls.sid)
        approve_pending(cls.ws, cls.sid, attestation="individual", limit=1)
        approve_pending(cls.ws, cls.sid)
        cls.approved = lifecycle(cls.ws, cls.sid)
        remaining = [w for w in cls.ws.snapshot()["items"] if w["status"] != "Closed"]
        selected_operation(cls.ws, cls.sid, "escalate", cls.selection(remaining))
        cls.handoff = lifecycle(cls.ws, cls.sid)

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.tmp.cleanup()

    @classmethod
    def selection(cls, items):
        return SelectedCommand(
            **command(expected_session=cls.sid).model_dump(),
            selected=[dict(id=w["work_item_id"], version=w["version"]) for w in items]
        )

    @classmethod
    def close_all(cls):
        with patch("socket.create_connection", side_effect=AssertionError("No provider calls")):
            selected_operation(cls.ws, cls.sid, "close", cls.selection(cls.ws.snapshot()["items"]))

    def nodes(self, model):
        return {n["id"]: n for n in model["nodes"]}

    def test_actual_intake_and_document_relationships(self):
        n = self.nodes(self.initial)
        self.assertEqual(n["documents"]["count"], 149)
        self.assertEqual(n["created"]["count"], 102)
        self.assertEqual(n["investigation"]["count"], 29)
        self.assertEqual(
            next(n for n in self.initial["current_state"] if n["id"] == "state-ready")["count"], 73
        )
        self.assertNotIn("manual", n)
        documents = {d["id"]: d for d in self.initial["documents"]}
        items = {i["id"]: i for i in self.initial["items"]}
        self.assertEqual(len(documents), 149)
        for d in documents.values():
            for wid in d["item_ids"]:
                self.assertIn(d["id"], items[wid]["document_ids"])
            self.assertIn("/evidence/", d["pdf_url"])
            self.assertTrue(self.ws.pdf(self.sid, d["hash"]).read_bytes().startswith(b"%PDF-"))

    def test_preparation_is_not_closure(self):
        n = self.nodes(self.prepared)
        self.assertEqual(n["prepared"]["count"], 73)
        self.assertEqual(n["queue"]["count"], 73)
        self.assertEqual(n["closed"]["count"], 0)
        states = {n["id"]: n["count"] for n in self.prepared["current_state"]}
        self.assertEqual(states["state-pending"], 73)
        self.assertTrue(self.prepared["integrity"]["reconciled"])

    def test_review_provenance_and_overlap(self):
        n = self.nodes(self.approved)
        self.assertEqual(n["individual"]["count"], 1)
        self.assertEqual(n["bulk"]["count"], 72)
        self.assertEqual(n["closed"]["count"], 73)
        self.assertEqual(set(n["prepared"]["item_ids"]), set(n["closed"]["item_ids"]))
        self.assertFalse(set(n["individual"]["item_ids"]) & set(n["bulk"]["item_ids"]))
        events = {e["id"]: e for e in self.approved["events"]}
        for key, attestation in [("individual", "individual"), ("bulk", "bulk_attested")]:
            for eid in n[key]["event_ids"]:
                e = events[eid]
                self.assertEqual(e["details"]["attestation"], attestation)
                self.assertEqual(e["actor_kind"], "human")
                self.assertIn(e["details"]["preparation_event_id"], events)

    def test_edges_use_ordered_case_events_not_fabricated_funnels(self):
        model = self.handoff
        events = {e["id"]: e for e in model["events"]}
        nodes = self.nodes(model)
        for edge in model["edges"]:
            self.assertEqual(edge["count"], len(set(edge["item_ids"])))
            self.assertTrue(set(edge["item_ids"]) <= set(nodes[edge["source"]]["item_ids"]))
            self.assertTrue(set(edge["item_ids"]) <= set(nodes[edge["target"]]["item_ids"]))
            for wid in edge["item_ids"]:
                self.assertTrue(any(events[eid].get("item_id") == wid for eid in edge["event_ids"]))
        links = {e["id"]: e for e in model["edges"]}
        self.assertEqual(links["queue--individual"]["count"], 1)
        self.assertEqual(links["queue--bulk"]["count"], 72)
        self.assertEqual(links["investigation--handoff"]["count"], 29)
        self.assertNotIn("manual--handoff", links)
        self.assertEqual(nodes["handoff"]["count"], 29)  # sent and received are not doubled

    def test_current_partition_and_shared_metrics(self):
        model = self.handoff
        ids = [i for n in model["current_state"] for i in n["item_ids"]]
        self.assertEqual(len(ids), 102)
        self.assertEqual(len(set(ids)), 102)
        self.assertEqual(set(ids), {i["id"] for i in model["items"]})
        self.assertEqual(model["integrity"]["unclassified"], 0)
        for m in model["metrics"]:
            source = next(
                (n for n in model["nodes"] + model["current_state"] if n["id"] == m["id"]), None
            )
            if source:
                self.assertEqual(m, source)
            else:
                self.assertEqual(m["count"], 0)
                self.assertEqual(m["item_ids"], [])

    def test_finance_evidence_and_return_precedence(self):
        base = dict(
            status="Awaiting Financial Review",
            management={"review_status": "Completed"},
            oversight={"owner": "Sarah"},
        )
        self.assertEqual(current_bucket(base), "finance")
        base["status"] = "Awaiting Evidence"
        self.assertEqual(current_bucket(base), "evidence")
        base.update(status="Escalated", management={"review_status": "Returned to Maya"})
        self.assertEqual(current_bucket(base), "returned")
        base["management"]["review_status"] = "Completed"
        self.assertEqual(current_bucket(base), "managed")
        base["current_decision_owner"] = "Authorized financial review team"
        self.assertEqual(current_bucket(base), "finance")

    def raw(self):
        with self.ws.database(self.ws.directory(self.sid) / "journal.sqlite3") as conn:
            return (
                self.ws.works(conn),
                self.ws.documents(conn),
                [
                    json.loads(r[0])
                    for r in self.ws.rows(
                        conn, "SELECT body FROM workflow_events ORDER BY sequence"
                    )
                ],
            )

    def test_missing_ambiguous_and_foreign_events_are_exposed(self):
        works, docs, events = self.raw()
        wid = self.approved["nodes"][0]["item_ids"][0]
        approved = next(e for e in events if e["type"] == "human_review_approved")
        bad = deepcopy(approved)
        bad["details"]["preparation_event_id"] = "missing"
        events = [
            bad if e["id"] == approved["id"] else e
            for e in events
            if not (e.get("item_id") == wid and e["type"] == "item_created")
        ]
        events.append(dict(bad, id=uuid4().hex, item_id="foreign"))
        model = project(self.sid, works, docs, events, [])
        codes = {d["code"] for d in model["integrity"]["diagnostics"]}
        self.assertTrue(
            {
                "missing_creation_event",
                "unbound_review_event",
                "foreign_event_item",
                "closure_without_review_event",
            }
            <= codes
        )
        self.assertEqual(model["integrity"]["unclassified"], 1)
        self.assertEqual(model["integrity"]["accounted"], 102)

    def test_legacy_history_never_gains_human_approval(self):
        works, docs, events = self.raw()
        for w in works:
            w.pop("review", None)
        events = [e for e in events if not e["type"].startswith("human_review_")]
        model = project(self.sid, works, docs, events, [])
        legacy = next(n for n in model["current_state"] if n["id"] == "state-legacy")
        self.assertEqual(legacy["count"], 73)
        self.assertIn("no recorded human review", legacy["label"])
        self.assertEqual(self.nodes(model)["closed"]["count"], 0)

    def test_manual_triage_requires_explicit_attributed_action(self):
        works, docs, events = self.raw()
        wid = next(w["work_item_id"] for w in works if w["status"] != "Closed")
        original = next(e for e in events if e.get("item_id") == wid)
        e = dict(
            original,
            id=uuid4().hex,
            type="human_decision_recorded",
            actor_kind="human",
            details={"action": "review", "evidence_hashes": list(works[0]["supporting_facts"])},
        )
        model = project(self.sid, works, docs, events + [e], [])
        self.assertEqual(self.nodes(model)["manual"]["item_ids"], [wid])
        e["actor_kind"] = "deterministic_automation"
        self.assertNotIn("manual", self.nodes(project(self.sid, works, docs, events + [e], [])))

    def test_read_only_session_isolation_and_retained_restart(self):
        before = self.raw()
        for _ in range(3):
            self.assertEqual(lifecycle(self.ws, self.sid), lifecycle(self.ws, self.sid))
        self.assertEqual(self.raw(), before)
        with self.assertRaises(StoreError):
            lifecycle(self.ws, "0" * 32)
        # A new workspace instance reads the same immutable session, no migration approvals.
        reopened = DocumentWorkspace(self.store)
        self.assertEqual(lifecycle(reopened, self.sid)["nodes"], self.handoff["nodes"])
        new = self.ws.load(True, self.sid, command(expected_session=self.sid))
        retained = lifecycle(self.ws, self.sid)
        self.assertTrue(retained["read_only"])
        self.assertEqual(retained["nodes"], self.handoff["nodes"])
        self.assertEqual(self.raw(), before)
        fresh = lifecycle(self.ws, new["session_id"])
        self.assertEqual(self.nodes(fresh)["prepared"]["count"], 0)

    def test_rejected_review_stays_unresolved_and_is_not_manual_triage(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(Settings(root=Path(root) / "runs"))
            try:
                ws = DocumentWorkspace(store)
                sid = ws.load()["session_id"]
                ws.perform(sid, "routine", command())
                w = next(w for w in ws.snapshot()["items"] if w["status"] == PENDING)
                review(
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
                        ],
                        decision="reject",
                        attestation="individual",
                        acknowledge_review=True
                    ),
                )
                model = lifecycle(ws, sid)
                self.assertEqual(self.nodes(model)["rejected"]["item_ids"], [w["work_item_id"]])
                self.assertNotIn("manual", self.nodes(model))
                self.assertEqual(
                    next(n for n in model["current_state"] if n["id"] == "state-rejected")["count"],
                    1,
                )
                self.assertEqual(self.nodes(model)["closed"]["count"], 0)
            finally:
                store.close()

    def test_foreign_session_event_cannot_contribute(self):
        works, docs, events = self.raw()
        approval = next(e for e in events if e["type"] == "human_review_approved")
        events = [dict(e, session_id="foreign") if e["id"] == approval["id"] else e for e in events]
        model = project(self.sid, works, docs, events, [])
        self.assertEqual(self.nodes(model)["closed"]["count"], 72)
        self.assertFalse(any(e.get("session_id") != self.sid for e in model["events"]))
        self.assertTrue(
            any(d["code"] == "foreign_session_event" for d in model["integrity"]["diagnostics"])
        )

    def test_unknown_status_and_missing_documents_are_visible(self):
        works, docs, events = self.raw()
        works[0]["status"] = None
        works[0]["oversight"] = None
        works[0].pop("current_decision_owner", None)
        works[0].pop("management", None)
        model = project(self.sid, works, [], events, [])
        self.assertEqual(model["integrity"]["accounted"], 102)
        self.assertTrue(
            any(d["code"] == "missing_document" for d in model["integrity"]["diagnostics"])
        )
        self.assertIn("state-unclassified", {n["id"] for n in model["current_state"]})

    def test_management_completion_never_closes_financial_case(self):
        works, docs, events = self.raw()
        finance = next(w for w in works if w["status"] == "Awaiting Financial Review")
        before = finance["status"]
        finance["management"] = {"review_status": "Completed", "last_reviewer": "Sarah test"}
        e = next(e for e in events if e.get("item_id") == finance["work_item_id"])
        events.append(
            dict(
                e,
                id=uuid4().hex,
                type="management_review_completed",
                actor_kind="human",
                details={},
                before=before,
                after=before,
            )
        )
        model = project(self.sid, works, docs, events, [])
        self.assertIn(
            finance["work_item_id"],
            next(n for n in model["current_state"] if n["id"] == "state-finance")["item_ids"],
        )
        self.assertIn(finance["work_item_id"], self.nodes(model)["management_complete"]["item_ids"])
        self.assertEqual(finance["status"], before)
