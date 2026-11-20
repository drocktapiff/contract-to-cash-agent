from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from reportlab.pdfgen import canvas
from pypdf import PdfWriter
from contract_to_cash.document_ops.generator import generate
from contract_to_cash.document_ops.pdf_templates import render_pdf
from contract_to_cash.document_ops.parser import parse_pdf, MAX_BYTES
from contract_to_cash.document_ops.intake import ingest, close_routine
from contract_to_cash.document_ops.evaluate import evaluate


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prepare(self, seed=202604):
        root = generate(self.root / "batch", seed)
        result = ingest(root / "documents", self.root / "journal.sqlite3")
        return root, result

    def test_full_batch_independent_evaluation_zero_provider(self):
        # An accidental OpenAI dependency fails before it can make a paid call.
        with patch("socket.create_connection", side_effect=AssertionError("No network permitted")):
            root, result = self.prepare()
        report = evaluate(result, root / "evaluation" / "expected.json")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["unsafe_automatic_closures"], 0)
        self.assertEqual(result["paid_model_calls"], 0)
        self.assertEqual(len({d["customer_id"] for d in result["documents"]}), 40)
        self.assertTrue(120 <= len(result["documents"]) <= 160)
        self.assertEqual(len({d["document_type"] for d in result["documents"]}), 10)
        self.assertTrue(any(w["automation_eligible"] for w in result["work_items"]))
        self.assertTrue(any(w["intentionally_unresolved"] for w in result["work_items"]))
        # A genuine invalid calendar date remains review work, not silently repaired.
        self.assertEqual(report["parse_failures"], 1)

    def test_alternate_batch_and_no_oracle_access(self):
        root = generate(self.root / "alternate", 892371)
        expected = json.loads((root / "evaluation" / "expected.json").read_text())
        shutil.rmtree(root / "evaluation")
        original = Path.open

        def checked(path, *args, **kwargs):
            if path.suffix == ".json":
                raise AssertionError("Intake may not read any JSON")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", checked):
            result = ingest(root / "documents", self.root / "isolated.sqlite3")
        manifest = self.root / "separate-oracle.json"
        manifest.write_text(json.dumps(expected))
        self.assertTrue(evaluate(result, manifest)["passed"])

    def test_repeat_ingestion_retains_ids_timestamps_events_and_closure(self):
        root, first = self.prepare()
        database = self.root / "journal.sqlite3"
        candidate = next(w for w in first["work_items"] if w["automation_eligible"])
        closed = close_routine(
            database, candidate["work_item_id"], "test operator", "Read-only check reviewed"
        )
        second = ingest(root / "documents", database)
        found = next(
            w for w in second["work_items"] if w["work_item_id"] == candidate["work_item_id"]
        )
        self.assertEqual(found, closed)
        self.assertFalse(closed["event_history"][-1]["financial_action_executed"])
        with closing(sqlite3.connect(database)) as conn:
            with closing(conn.execute("SELECT count(*) FROM work_items")) as cursor:
                self.assertEqual(cursor.fetchone()[0], len(first["work_items"]))
        # Windows must be able to remove the whole journal directory immediately.
        database.unlink()

    def test_duplicate_file_copy_is_not_duplicate_work(self):
        root, first = self.prepare()
        one = next((root / "documents").glob("*.pdf"))
        shutil.copyfile(one, root / "documents" / "renamed-copy.pdf")
        second = ingest(root / "documents", self.root / "journal.sqlite3")
        self.assertEqual(second["duplicate_files_skipped"], 1)
        self.assertEqual(first["work_items"], second["work_items"])

    def test_human_financial_authority_cannot_be_auto_closed(self):
        _, result = self.prepare()
        for w in result["work_items"]:
            if not w["automation_eligible"]:
                with self.assertRaises(ValueError):
                    close_routine(
                        self.root / "journal.sqlite3", w["work_item_id"], "operator", "shortcut"
                    )
        self.assertTrue(any(w["category"] == "credit_review" for w in result["work_items"]))

    def test_evidence_spans_point_into_actual_pdf_text(self):
        _, result = self.prepare()
        docs = {d["file_hash"]: d for d in result["documents"]}
        for w in result["work_items"]:
            self.assertTrue(w["evidence"])
            for span in w["evidence"]:
                source = docs[span["file_hash"]]
                self.assertEqual(
                    source["pages"][span["page"] - 1][span["start"] : span["end"]], span["text"]
                )
                self.assertIn(span["document_id"], w["source_documents"])
                self.assertEqual(w["provenance"]["source"], "actual_pdf_processing")
                self.assertTrue(w["provenance"]["synthetic"])

    def custom_pair(self, total="8375.00", amendments=False):
        docs = self.root / "unseen"
        docs.mkdir()
        common = {
            "Customer account": "NEW-HERON-81",
            "Contract reference": "MSA-XQ-938",
            "Customer name": "Heron Robotics Demo Ltd",
            "Currency": "CAD",
        }
        contract = {
            "Document ID": "SIGNED-X81",
            **common,
            "Contract status": "Executed",
            "Effective date": "2026-01-01",
            "Term end": "2026-12-31",
            "Billing cadence": "monthly",
            "Subscription amount": "8375.00",
            "Included quantity": "0",
            "Unit rate": "0",
            "Discount percent": "0",
            "Discount valid through": "2026-12-31",
            "Implementation fee": "0",
            "Tax rate": "0",
        }
        invoice = {
            "Document ID": "INV-NEW-Z99",
            **common,
            "Invoice reference": "INV-NEW-Z99",
            "Invoice date": "2026-06-30",
            "Due date": "2026-07-30",
            "Period start": "2026-06-01",
            "Period end": "2026-06-30",
            "Quantity": "1",
            "Service subtotal": total,
            "Implementation charge": "0",
            "Tax rate": "0",
            "Tax amount": "0",
            "Invoice total": total,
        }
        render_pdf(docs / "a.pdf", "contract", contract, 1)
        render_pdf(docs / "b.pdf", "invoice", invoice, 0)
        if amendments:
            for n, price in enumerate(["9000", "9500"]):
                render_pdf(
                    docs / f"amend{n}.pdf",
                    "amendment",
                    {
                        "Document ID": f"AMD-OTHER-{n}",
                        **common,
                        "Contract status": "Executed",
                        "Effective date": "2026-06-01",
                        "Subscription amount": price,
                        "Supersedes": "Not established",
                    },
                    n,
                )
        return docs, contract, invoice

    def test_unseen_correct_pair(self):
        docs, _, _ = self.custom_pair()
        result = ingest(docs, self.root / "db.sqlite3")
        w = result["work_items"][0]
        self.assertEqual(w["customer_id"], "NEW-HERON-81")
        self.assertEqual(
            w["financial_impact"],
            {
                "currency": "CAD",
                "expected_total": "8375.00",
                "invoiced_total": "8375.00",
                "difference": "0.00",
            },
        )
        self.assertTrue(w["automation_eligible"])
        self.assertEqual(len(w["source_documents"]), 2)

    def test_unseen_discrepancy(self):
        docs, _, _ = self.custom_pair("8100.00")
        w = ingest(docs, self.root / "db.sqlite3")["work_items"][0]
        self.assertEqual(w["financial_impact"]["difference"], "275.00")
        self.assertFalse(w["automation_eligible"])
        self.assertTrue(w["human_review_required"])

    def test_unseen_contradictory_authority(self):
        docs, _, _ = self.custom_pair(amendments=True)
        w = next(
            w
            for w in ingest(docs, self.root / "db.sqlite3")["work_items"]
            if w["category"] == "contract_conflict"
        )
        self.assertIsNone(w["financial_impact"])
        self.assertTrue(w["intentionally_unresolved"])
        self.assertFalse(w["automatic_closure_allowed"])

    def test_unsupported_layout_and_malformed_pdf_require_review(self):
        docs = self.root / "docs"
        docs.mkdir()
        c = canvas.Canvas(str(docs / "unstructured.pdf"))
        c.drawString(60, 700, "Unrecognized legal agreement: pay an uncertain amount")
        c.save()
        (docs / "broken.pdf").write_bytes(b"%PDF-broken")
        result = ingest(docs, self.root / "db.sqlite3")
        self.assertEqual(len(result["documents"]), 2)
        self.assertTrue(
            all(
                w["category"] == "document_review" and w["human_review_required"]
                for w in result["work_items"]
            )
        )

    def test_image_only_and_encrypted_pdf_are_not_claimed_as_supported(self):
        path = self.root / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with path.open("wb") as stream:
            writer.write(stream)
        self.assertTrue(parse_pdf(path).errors)
        writer.encrypt("not-an-operator-password")
        with path.open("wb") as stream:
            writer.write(stream)
        self.assertTrue(parse_pdf(path).errors)

    def test_size_and_symlink_limits(self):
        path = self.root / "large.pdf"
        with path.open("wb") as stream:
            stream.write(b"%PDF-")
            stream.truncate(MAX_BYTES + 1)
        self.assertIn("PDF exceeds 5 MiB intake limit", parse_pdf(path).errors)
        link = self.root / "link.pdf"
        try:
            link.symlink_to(path)
        except OSError:
            self.skipTest("Native Windows symlink privilege unavailable")
        with self.assertRaises(ValueError):
            parse_pdf(link)

    def test_proposals_cannot_override_financial_authority(self):
        docs, _, _ = self.custom_pair("8100.00")

        class Advisor:
            def propose(self, document):
                return {
                    "Invoice total": "8375",
                    "automation_eligible": True,
                    "approve_credit": True,
                }

        w = ingest(docs, self.root / "db.sqlite3", Advisor())["work_items"][0]
        self.assertEqual(w["financial_impact"]["difference"], "275.00")
        self.assertFalse(w["automation_eligible"])

    def test_evaluator_includes_missing_parses_and_unsafe_closure(self):
        root, result = self.prepare()
        damaged = deepcopy(result)
        damaged["documents"].pop()
        target = next(w for w in damaged["work_items"] if not w["automatic_closure_allowed"])
        target["status"] = "Closed"
        report = evaluate(damaged, root / "evaluation" / "expected.json")
        self.assertFalse(report["passed"])
        self.assertEqual(report["unsafe_automatic_closures"], 1)
        self.assertLess(report["metrics"]["document_classification"]["accuracy"], 1)

    def test_generator_never_replaces_history(self):
        root, _ = self.prepare()
        before = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / "documents").iterdir()
        }
        with self.assertRaises(ValueError):
            generate(root)
        self.assertEqual(
            before,
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root / "documents").iterdir()
            },
        )

    def test_invalid_period_currency_and_arithmetic_never_produce_amounts(self):
        docs, contract, invoice = self.custom_pair()
        for changes in (
            {"Currency": "USD"},
            {"Period end": "2026-06-20"},
            {"Tax amount": "10"},
            {"Quantity": "NaN"},
        ):
            with self.subTest(changes=changes):
                render_pdf(docs / "b.pdf", "invoice", {**invoice, **changes})
                result = ingest(docs, self.root / "db.sqlite3")
                w = next(
                    w
                    for w in result["work_items"]
                    if w["business_object_id"] == "billing:NEW-HERON-81"
                )
                self.assertIsNone(w["financial_impact"])
                self.assertTrue(w["human_review_required"])

    def test_changed_evidence_preserves_prior_work_and_documents(self):
        docs, _, invoice = self.custom_pair()
        database = self.root / "history.sqlite3"
        first = ingest(docs, database)
        render_pdf(
            docs / "b.pdf",
            "invoice",
            {**invoice, "Invoice total": "8000", "Service subtotal": "8000"},
        )
        second = ingest(docs, database)
        self.assertNotEqual(
            first["work_items"][0]["work_item_id"], second["work_items"][0]["work_item_id"]
        )
        with closing(sqlite3.connect(database)) as conn:
            with closing(conn.execute("SELECT count(*) FROM work_items")) as cur:
                self.assertEqual(cur.fetchone()[0], 2)
            with closing(conn.execute("SELECT count(*) FROM documents")) as cur:
                self.assertEqual(cur.fetchone()[0], 3)

    def test_failed_transaction_closes_handles_and_rolls_back(self):
        docs, _, _ = self.custom_pair()
        database = self.root / "failure.sqlite3"

        class BrokenAdvisor:
            def propose(self, doc):
                raise RuntimeError("Expected adapter failure")

        with self.assertRaises(RuntimeError):
            ingest(docs, database, BrokenAdvisor())
        with closing(sqlite3.connect(database)) as conn:
            with closing(conn.execute("SELECT count(*) FROM documents")) as cur:
                self.assertEqual(cur.fetchone()[0], 0)
        database.unlink()

    def test_generation_is_byte_reproducible(self):
        first = generate(self.root / "one", seed=333, count=2)
        second = generate(self.root / "two", seed=333, count=2)
        self.assertEqual(
            {p.name: p.read_bytes() for p in (first / "documents").iterdir()},
            {p.name: p.read_bytes() for p in (second / "documents").iterdir()},
        )

    def test_conflicting_document_ids_and_cross_account_matching_require_review(self):
        docs, contract, invoice = self.custom_pair()
        render_pdf(docs / "other.pdf", "contract", {**contract, "Subscription amount": "9999"})
        result = ingest(docs, self.root / "duplicate-id.sqlite3")
        main = next(
            w for w in result["work_items"] if w["business_object_id"] == "billing:NEW-HERON-81"
        )
        self.assertIsNone(main["financial_impact"])
        self.assertFalse(main["automation_eligible"])
        self.assertEqual(len(main["supporting_facts"]), 3)
        (docs / "other.pdf").unlink()
        render_pdf(docs / "b.pdf", "invoice", {**invoice, "Customer account": "ANOTHER-ACCOUNT"})
        result = ingest(docs, self.root / "cross-account.sqlite3")
        self.assertTrue(all(w["human_review_required"] for w in result["work_items"]))

    def test_usage_quantity_mismatch_cannot_close_even_if_total_matches(self):
        docs, contract, invoice = self.custom_pair()
        render_pdf(docs / "a.pdf", "contract", {**contract, "Billing cadence": "usage"})
        render_pdf(docs / "b.pdf", "invoice", {**invoice, "Quantity": "2"})
        render_pdf(
            docs / "u.pdf",
            "usage",
            {
                "Document ID": "UNSEEN-USAGE",
                "Customer account": contract["Customer account"],
                "Contract reference": contract["Contract reference"],
                "Currency": "CAD",
                "Period start": "2026-06-01",
                "Period end": "2026-06-30",
                "Quantity": "1",
            },
        )
        work = ingest(docs, self.root / "usage.sqlite3")["work_items"]
        main = next(w for w in work if w["category"] == "contract_price_validation")
        self.assertEqual(main["financial_impact"]["difference"], "0.00")
        self.assertFalse(main["automation_eligible"])
        self.assertTrue(all(w["human_review_required"] for w in work))

    def test_missing_incorporated_schedule_and_conflicting_purchase_order(self):
        docs, contract, invoice = self.custom_pair()
        for updated in (
            {**contract, "Pricing authority": "Pricing schedule incorporated"},
            {**contract, "Purchase order": "PO-CONTRACT"},
        ):
            render_pdf(docs / "a.pdf", "contract", updated)
            render_pdf(docs / "b.pdf", "invoice", {**invoice, "Purchase order": "PO-DIFFERENT"})
            main = ingest(docs, self.root / "scope.sqlite3")["work_items"][0]
            self.assertIsNone(main["financial_impact"])
            self.assertFalse(main["automation_eligible"])


if __name__ == "__main__":
    unittest.main()
