"""Phase-one acceptance tests: use independent expected results, not agent prose."""
import unittest
from decimal import Decimal

from contract_to_cash.generate_data import build_fixture
from contract_to_cash.billing_engine import ConflictError, expected_amount, investigate


class FoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts, cls.amendments, cls.invoices, cls.key = build_fixture()
        cls.audit = investigate(cls.contracts, cls.amendments, cls.invoices)

    def test_fixture_size(self):
        self.assertEqual((len(self.contracts), len(self.amendments), len(self.invoices)), (40, 20, 121))

    def test_eight_issues_and_no_false_positive(self):
        self.assertEqual(self.audit["finding_count"], 8)
        self.assertIn("C011", self.audit["clean_customers"])
        self.assertNotIn("C011", [c for f in self.audit["findings"] for c in f["customers"]])

    def test_exact_answer_key_matches_discovered_findings(self):
        by_customers = {tuple(f["customers"]): f for f in self.audit["findings"]}
        for issue in self.key["issues"]:
            expected = tuple(issue["customers"])
            with self.subTest(issue=issue["id"]):
                self.assertIn(expected, by_customers)
                self.assertEqual(by_customers[expected]["type"], issue["type"])

    def test_expired_discount_and_live_uplift(self):
        c3 = self.contracts[2]
        a3 = [a for a in self.amendments if a["customer_id"] == "C003"]
        self.assertEqual(expected_amount(c3, a3, "2026-02"), Decimal("7200.00"))
        self.assertEqual(expected_amount(c3, a3, "2026-04"), Decimal("8000.00"))
        c4 = self.contracts[3]
        a4 = [a for a in self.amendments if a["customer_id"] == "C004"]
        self.assertEqual(expected_amount(c4, a4, "2026-04"), Decimal("11000.00"))

    def test_usage_tier(self):
        self.assertEqual(expected_amount(self.contracts[4], [], "2026-04", 110), Decimal("990.00"))

    def test_conflict_blocks_automatic_calculation(self):
        c7 = self.contracts[6]
        a7 = [a for a in self.amendments if a["customer_id"] == "C007"]
        with self.assertRaises(ConflictError):
            expected_amount(c7, a7, "2026-04")
        self.assertEqual(next(f for f in self.audit["findings"] if "C007" in f["customers"])["status"], "human_review")

    def test_systemic_discovery_has_three_customers(self):
        grouped = [f for f in self.audit["findings"] if f["type"] == "shared_pricing_template_error"]
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["total_difference_cad"], "3000.00")

    def test_repeatability(self):
        self.assertEqual(build_fixture(), build_fixture())


if __name__ == "__main__":
    unittest.main()
