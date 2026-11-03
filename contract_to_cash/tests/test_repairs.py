"""Independent examples, invalid-input boundaries, and checked-in evidence integrity."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal, localcontext

from contract_to_cash.billing_engine import (
    BillingInputError, ConflictError, expected_amount, investigate, load_records, money,
)
from contract_to_cash.generate_data import generate

DATA = Path(__file__).resolve().parents[1] / 'data'


def contract(**overrides):
    return dict(customer_id='X', contract_id='CTR-X', pricing_template='example',
                status='signed', billing_cycle='monthly', start_date='2026-01-01',
                base_monthly_cad='100.00', **overrides)


def amendment(aid='A', **overrides):
    row = dict(amendment_id=aid, customer_id='X', status='signed', kind='set_price',
               effective_date='2026-04-01', end_date=None, value='80.00')
    row.update(overrides)
    return row


class IndependentCalculationTests(unittest.TestCase):
    def test_half_up_rounding(self):
        self.assertEqual(money('1.005'), Decimal('1.01'))
        self.assertEqual(expected_amount(contract(), [amendment(kind='discount_percent', value='0.005')],
                                         '2026-04'), Decimal('100.00'))

    def test_decimal_precision_is_local_and_overflow_is_rejected(self):
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(expected_amount(contract(), [amendment(value='1234.56')], '2026-04'),
                             Decimal('1234.56'))
            self.assertEqual(context.prec, 3)
        c = contract(); c['base_monthly_cad'] = '1000000000000'
        with self.assertRaises(BillingInputError):
            expected_amount(c, [amendment(kind='uplift_percent', value='100')], '2026-04')

    def test_effective_and_expiry_boundaries(self):
        a = amendment(kind='discount_percent', value='10', end_date='2026-04-30')
        for period, result in [('2026-03', '100.00'), ('2026-04', '90.00'), ('2026-05', '100.00')]:
            with self.subTest(period=period):
                self.assertEqual(expected_amount(contract(), [a], period), Decimal(result))
        a['end_date'] = '2026-04-01'
        self.assertEqual(expected_amount(contract(), [a], '2026-04'), Decimal('90.00'))
        a['effective_date'] = '2026-04-02'; a['end_date'] = None
        self.assertEqual(expected_amount(contract(), [a], '2026-04'), Decimal('100.00'))

    def test_latest_price_unsigned_and_percentage_composition(self):
        rows = [amendment('old', effective_date='2026-02-01', value='90'),
                amendment('new', value='80'), amendment('unsigned', status='unsigned', value='1'),
                amendment('discount', kind='discount_percent', value='10'),
                amendment('uplift', kind='uplift_percent', value='5')]
        self.assertEqual(expected_amount(contract(), rows, '2026-04'), Decimal('75.60'))
        self.assertEqual(expected_amount(contract(), list(reversed(rows)), '2026-04'), Decimal('75.60'))

    def test_usage_threshold_and_zero(self):
        c = contract(usage_tier=dict(threshold=100, unit_rate_above='9', unit_rate_at_or_below='10'))
        for quantity, result in [(0, '0.00'), (100, '1000.00'), (101, '909.00')]:
            self.assertEqual(expected_amount(c, [], '2026-04', quantity), Decimal(result))

    def test_conflict_and_identical_signed_prices(self):
        self.assertEqual(expected_amount(contract(), [amendment('a'), amendment('b')], '2026-04'), Decimal('80.00'))
        with self.assertRaises(ConflictError):
            expected_amount(contract(), [amendment('a'), amendment('b', value='81')], '2026-04')


class ValidationTests(unittest.TestCase):
    def test_invalid_money(self):
        for value in ['NaN', 'sNaN', 'Infinity', '-1', 'nonsense', None, True, 1.2, '1e100']:
            with self.subTest(value=value), self.assertRaises(BillingInputError):
                money(value)

    def test_invalid_period_and_quantity(self):
        for period in ['2026-4', '2026-13', '0000-01', None, '2026-04-01']:
            with self.subTest(period=period), self.assertRaises(BillingInputError):
                expected_amount(contract(), [], period)
        for quantity in [-1, 1.5, '110', True, None]:
            with self.subTest(quantity=quantity), self.assertRaises(BillingInputError):
                expected_amount(contract(), [], '2026-04', quantity)

    def test_unsupported_contracts(self):
        for patch in [dict(status='unsigned'), dict(billing_cycle='annual'), dict(currency='USD'),
                      dict(start_date='2026-04-02'), dict(start_date='2026-02-30'),
                      dict(end_date='2026-12-31'), dict(base_monthly_cad='-1'),
                      dict(usage_tier={}), dict(contract_id='')]:
            c = contract(); c.update(patch)
            with self.subTest(patch=patch), self.assertRaises(BillingInputError):
                expected_amount(c, [], '2026-04')

    def test_invalid_amendments(self):
        for patch in [dict(kind='unknown'), dict(customer_id='OTHER'), dict(status='mystery'),
                      dict(value='NaN'), dict(kind='discount_percent', value='101'),
                      dict(effective_date='bad'), dict(end_date='2026-03-31')]:
            with self.subTest(patch=patch), self.assertRaises(BillingInputError):
                expected_amount(contract(), [amendment(**patch)], '2026-04')
        with self.assertRaises(BillingInputError):
            expected_amount(contract(), [amendment(), amendment()], '2026-04')
        c = contract(usage_tier=dict(threshold=100, unit_rate_above='9', unit_rate_at_or_below='10'))
        with self.assertRaises(BillingInputError):
            expected_amount(c, [amendment()], '2026-04')

    def test_invalid_invoice_and_record_links(self):
        invoice = dict(invoice_id='I', customer_id='X', period='2026-04', currency='CAD',
                       usage_quantity=0, billed_amount='100')
        for patch in [dict(currency='USD'), dict(usage_quantity=1.5), dict(billed_amount='NaN'),
                      dict(customer_id='missing'), dict(period='bad'), dict(invoice_id='')]:
            row = dict(invoice); row.update(patch)
            with self.subTest(patch=patch), self.assertRaises(BillingInputError):
                investigate([contract()], [], [row])
        with self.assertRaises(BillingInputError):
            investigate([contract()], [], [invoice, invoice])
        with self.assertRaises(BillingInputError):
            investigate([contract(), contract()], [], [])
        with self.assertRaises(BillingInputError):
            investigate([contract()], [amendment(customer_id='missing')], [])

    def test_validation_does_not_mutate_records(self):
        c, a = contract(), [amendment()]
        before = copy.deepcopy((c, a))
        expected_amount(c, a, '2026-04')
        self.assertEqual((c, a), before)


class CheckedInFixtureTests(unittest.TestCase):
    def test_document_hashes_and_lf(self):
        manifest = json.loads((DATA / 'document_hashes.json').read_text())
        files = {p.name: p for p in (DATA / 'documents').glob('*.txt')}
        self.assertEqual(len(files), 60)
        self.assertEqual(set(files), set(manifest))
        for name, path in files.items():
            with self.subTest(document=name):
                self.assertNotIn(b'\r', path.read_bytes())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), manifest[name])

    def test_generated_bytes_match_checked_in_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generate(root)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            generate(root)
            after = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            for name, content in before.items():
                with self.subTest(file=str(name)):
                    self.assertEqual(content, (DATA / name).read_bytes())

    def test_independent_checked_in_financial_expectations(self):
        records = load_records(DATA)
        self.assertEqual(tuple(map(len, records)), (40, 20, 121))
        audit = investigate(*records)
        findings = {tuple(f['customers']): f for f in audit['findings']}
        expected = {('C001',): ('overbilling', '-500.00'),
                    ('C002',): ('underbilling', '500.00'),
                    ('C003',): ('expired_discount', '800.00'),
                    ('C004',): ('missed_uplift', '1000.00'),
                    ('C005',): ('usage_tier_error', '-110.00')}
        self.assertEqual(len(findings), 8)
        for customers, (kind, difference) in expected.items():
            self.assertEqual(findings[customers]['type'], kind)
            self.assertEqual(findings[customers]['difference_cad'], difference)
        self.assertEqual(findings[('C006',)]['type'], 'duplicate_invoice')
        self.assertEqual(findings[('C006',)]['amount_at_risk_cad'], '10500.00')
        self.assertEqual(findings[('C007',)]['type'], 'conflicting_signed_amendments')
        self.assertIsNone(findings[('C007',)]['amount_at_risk_cad'])
        self.assertEqual(findings[('C008', 'C009', 'C010')]['total_difference_cad'], '3000.00')
        self.assertIn('C011', audit['clean_customers'])
