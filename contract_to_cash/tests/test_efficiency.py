"""Offline protocol simulations and real deterministic tools; no live-model accuracy claims."""
import copy
from decimal import Decimal
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from contract_to_cash.agent import tools as tool_module
from contract_to_cash.agent.events import Journal
from contract_to_cash.agent.runtime import Investigator, Limits
from contract_to_cash.agent.tools import PublicData, Tools, ToolError
from scripts.evaluate_agent_runs import evaluate
from test_agent import FakeClient, FakeResponse, call

DATA = Path(__file__).resolve().parents[1] / 'data'


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.journal = Journal(self.root / 'run')
        self.addCleanup(self.journal.close)
        self.data = PublicData(DATA, '2026-04')
        self.tools = Tools(self.data, self.journal)
        self.serial = itertools.count()

    def selected(self, name, **arguments):
        item = call(name, arguments)
        item['call_id'] = str(next(self.serial))
        return item

    def finding_args(self, ids, state='verified'):
        return dict(customer_ids=ids, evidence_ids=sorted(set().union(*(self.tools._required(cid) for cid in ids))),
                    state=state, rationale='SIMULATED model claim: evaluate signed terms and recorded billing.')

    def run_fake(self, script, **limits):
        client = FakeClient(script)
        report = Investigator(client, 'simulated-model', self.tools, self.journal, Limits(**limits)).run('Audit')
        return client, report

    def test_screen_all_customers_matches_granular_calculations_without_verifying(self):
        original = Tools(self.data, self.journal)
        expected = {cid: original.compare_invoices(cid) for cid in self.data.customers}
        result = self.tools.execute('screen_customers', {})
        self.assertEqual(result['screened_count'], 40)
        self.assertEqual(self.tools.comparisons, expected)
        candidates = {row['customer_id']: row for row in result['candidates']}
        self.assertEqual(candidates['C005']['difference_cad'], '-110.00')
        self.assertIn('C011', result['clean_customer_ids'])
        self.assertNotIn('C011', candidates)
        self.assertFalse(self.tools.seen)
        self.assertFalse(self.tools.documents_seen)
        self.assertFalse(any(f['state'] == 'verified' for f in self.tools.findings.values()))
        self.assertEqual(self.tools.findings['finding-C007']['origin'], 'deterministic_conflict_guard')
        self.assertEqual(self.tools.reviews['finding-C007']['status'], 'pending')
        self.assertIsNone(candidates['C007']['difference_cad'])
        with self.assertRaises(ToolError):
            self.tools.execute('submit_finding', self.finding_args(['C005']))
        _, report = self.run_fake([FakeResponse([])])
        self.assertTrue(report['screening_complete'])
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['financial_totals']['potential_credits_cad'], '0.00')

    def test_screen_and_bundles_never_read_key_or_modify_public_data(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.rglob('*') if p.is_file()}
        reads = []
        read = Path.read_bytes
        def monitored(path):
            reads.append(path)
            self.assertNotIn('sealed_answer_key', str(path))
            return read(path)
        with patch.object(Path, 'read_bytes', monitored):
            tools = Tools(PublicData(DATA, '2026-04'), self.journal)
            tools.execute('screen_customers', {})
            tools.execute('get_customer_evidence', {'customer_ids': ['C005', 'C011']})
        self.assertTrue(reads)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_evidence_bundle_includes_all_terms_reuses_sources_and_rejects_bad_selection(self):
        result = self.tools.execute('get_customer_evidence', {'customer_ids': ['C003', 'C011']})
        for case in result['cases']:
            self.assertEqual(set(case['evidence_ids']), self.tools._required(case['customer_id']))
            self.assertEqual({d['document_id'] for d in case['documents']},
                             {case['contract']['contract_id']} | {a['amendment_id'] for a in case['amendments']})
            self.assertTrue(all('text' in d for d in case['documents']))
        repeat = self.tools.execute('get_customer_evidence', {'customer_ids': ['C003']})
        self.assertTrue(all(d.get('already_retrieved') for d in repeat['cases'][0]['documents']))
        self.tools.execute('submit_finding', self.finding_args(['C003']))
        with self.assertRaises(ToolError):
            self.tools.execute('submit_finding', self.finding_args(['C011']))
        seen = set(self.tools.seen)
        for ids in (['C001', 'UNKNOWN'], ['C001', 'C001'], list(self.data.customers)[:11]):
            with self.subTest(ids=ids), self.assertRaises(ToolError):
                self.tools.execute('get_customer_evidence', {'customer_ids': ids})
            self.assertEqual(self.tools.seen, seen)

    def test_model_can_choose_different_orders_and_independent_calls_in_one_response(self):
        for ids in (['C005', 'C020'], ['C020', 'C005']):
            script = [FakeResponse([self.selected('get_customer_evidence', customer_ids=[cid]) for cid in ids]),
                      FakeResponse([])]
            client, report = self.run_fake(script)
            self.assertTrue(client.requests[0]['parallel_tool_calls'])
            outputs = [item for item in client.requests[1]['input'] if item.get('type') == 'function_call_output']
            self.assertEqual([json.loads(item['output'])['cases'][0]['customer_id'] for item in outputs], ids)
            self.assertEqual(report['metrics']['api_requests'], 2)
            self.assertEqual(report['metrics']['agent_tool_calls'], 2)

    def test_full_offline_protocol_for_eight_groups_uses_six_responses(self):
        # The discoveries below are scripted TEST input, never production orchestration.
        groups = [[f'C{i:03}'] for i in range(1, 8)] + [['C008', 'C009', 'C010']]
        script = [FakeResponse([self.selected('screen_customers')]),
                  FakeResponse([self.selected('get_customer_evidence', customer_ids=[f'C{i:03}' for i in range(1, 11)])]),
                  FakeResponse([self.selected('summarize_pattern', customer_ids=groups[-1])]),
                  FakeResponse([self.selected('submit_finding', **self.finding_args(ids)) for ids in groups]),
                  FakeResponse([self.selected('request_human_review', finding_id='finding-' + '-'.join(ids), action='review')
                                for ids in groups]), FakeResponse([])]
        _, report = self.run_fake(script, max_tool_calls=35)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['metrics']['api_requests'], 6)
        self.assertEqual(report['metrics']['agent_tool_calls'], 19)
        self.assertEqual(len(report['findings']), 8)
        self.assertTrue(all(r['status'] == 'pending' for r in report['reviews']))
        self.assertIn('C011', report['clean_customers'])
        # Only this separate evaluator accesses the sealed key, after the simulated run.
        result = evaluate(self.journal.directory, DATA)
        self.assertEqual(result['true_positives'], 8)
        self.assertEqual(result['false_positive_customers'], [])
        self.assertEqual(result['missed_anomalies'], [])
        self.assertTrue(result['financial_accuracy_passed'], result['financial_mismatches'])
        self.assertTrue(result['evidence_verification_passed'], result['evidence_errors'])
        self.assertEqual(result['missing_tool_outcomes'], [])
        # Corrupt a logged screening calculation: offline checking must catch it.
        events = copy.deepcopy(self.journal.events)
        next(e for e in events if e['type'] == 'screening.completed')['payload']['comparisons'][0]['difference_cad'] = '999'
        (self.journal.directory / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events) + '\n')
        self.assertFalse(evaluate(self.journal.directory, DATA)['financial_accuracy_passed'])

    def test_budget_stop_preserves_verified_finding_and_review(self):
        script = [FakeResponse([self.selected('get_customer_evidence', customer_ids=['C005'])]),
                  FakeResponse([self.selected('submit_finding', **self.finding_args(['C005']))]),
                  FakeResponse([self.selected('request_human_review', finding_id='finding-C005', action='review')])]
        _, report = self.run_fake(script, max_tool_calls=3)
        self.assertEqual(report['reason'], 'tool_call_limit')
        self.assertEqual(report['findings'][0]['state'], 'verified')
        self.assertEqual(report['reviews'][0]['status'], 'pending')
        self.assertEqual(report['financial_totals']['potential_credits_cad'], '110.00')
        saved = json.loads((self.journal.directory / 'report.json').read_text())
        self.assertEqual(saved['financial_totals'], report['financial_totals'])

    def test_checkpoint_exists_before_the_next_api_request_and_error_keeps_finding(self):
        client = FakeClient([FakeResponse([self.selected('get_customer_evidence', customer_ids=['C005'])]),
                             FakeResponse([self.selected('submit_finding', **self.finding_args(['C005']))]),
                             RuntimeError('simulated API failure')])
        create = client.create
        def inspecting(**kwargs):
            if len(client.requests) == 2:
                checkpoint = json.loads((self.journal.directory / 'report.json').read_text())
                self.assertEqual(checkpoint['reason'], 'in_progress')
                self.assertEqual(checkpoint['findings'][0]['state'], 'verified')
                self.assertEqual(checkpoint['financial_totals']['potential_credits_cad'], '110.00')
                outputs = [i for i in kwargs['input'] if i.get('type') == 'function_call_output']
                self.assertNotIn('comparisons', json.loads(outputs[-1]['output']))
                persisted = next(e for e in self.journal.events if e['type'] == 'finding.verified')
                self.assertIn('comparisons', persisted['payload']['finding'])
            return create(**kwargs)
        client.create = inspecting
        report = Investigator(client, 'simulated', self.tools, self.journal, Limits()).run('Audit')
        self.assertEqual(report['reason'], 'api_failure')
        self.assertEqual(report['findings'][0]['state'], 'verified')
        self.assertFalse(report['metrics']['cost_accounting_complete'])
        self.assertIsNone(report['metrics']['usage_priced_cost_usd'])

    def test_evidence_change_invalidates_bundle_cache_pattern_and_review_then_allows_retraction(self):
        public = self.root / 'public'
        shutil.copytree(DATA, public, ignore=shutil.ignore_patterns('sealed_answer_key.json'))
        self.tools = Tools(PublicData(public, '2026-04'), self.journal)
        self.tools.execute('get_customer_evidence', {'customer_ids': ['C005']})
        self.tools.execute('submit_finding', self.finding_args(['C005']))
        self.tools.request_human_review('finding-C005', 'review')
        invoices = json.loads((public / 'invoices.json').read_text())
        for row in invoices:
            if row['customer_id'] == 'C005' and row['period'] == '2026-04':
                row['billed_amount'] = self.tools.comparisons['C005']['expected_cad']
        (public / 'invoices.json').write_text(json.dumps(invoices))
        self.assertIsNotNone(self.tools.refresh())
        self.assertFalse(self.tools.documents_seen)
        self.assertFalse(self.tools.comparisons)
        self.assertEqual(self.tools.reviews['finding-C005']['status'], 'invalidated')
        refreshed = self.tools.execute('get_customer_evidence', {'customer_ids': ['C005']})
        self.assertTrue(all('text' in d for d in refreshed['cases'][0]['documents']))
        self.assertEqual(refreshed['cases'][0]['comparison']['status'], 'clean')
        self.tools.execute('submit_finding', self.finding_args(['C005'], state='retracted'))
        _, report = self.run_fake([FakeResponse([])])
        self.assertEqual(report['financial_totals']['potential_credits_cad'], '0.00')
        self.assertEqual(report['findings'][0]['state'], 'retracted')

    def test_multiple_calls_obey_individual_tool_limit_and_log_only_executed_calls(self):
        _, report = self.run_fake([FakeResponse([self.selected('get_customer_evidence', customer_ids=[cid])
                                  for cid in ('C020', 'C021', 'C022')])], max_tool_calls=2)
        self.assertEqual(report['reason'], 'tool_call_limit')
        self.assertEqual(report['metrics']['agent_tool_calls'], 2)
        self.assertEqual(report['metrics']['api_requests'], 1)
        self.assertEqual(report['customers_compared'], ['C020', 'C021'])
        requested = [e for e in self.journal.events if e['type'] == 'tool.requested']
        completed = [e for e in self.journal.events if e['type'] == 'tool.completed']
        self.assertEqual([e['correlation_id'] for e in requested], [e['correlation_id'] for e in completed])

    def test_repeated_screen_and_evidence_reuse_comparisons_without_recalculating(self):
        with patch('contract_to_cash.agent.tools.expected_amount', wraps=tool_module.expected_amount) as calculate:
            self.tools.execute('screen_customers', {})
            calls = calculate.call_count
            self.tools.execute('screen_customers', {})
            self.tools.execute('get_customer_evidence', {'customer_ids': ['C005', 'C008']})
            self.assertEqual(calculate.call_count, calls)
            self.assertGreater(calls, 0)

    def test_screen_marks_missing_usage_unassessed_instead_of_inventing_amounts(self):
        public = self.root / 'missing'
        shutil.copytree(DATA, public, ignore=shutil.ignore_patterns('sealed_answer_key.json'))
        rows = json.loads((public / 'invoices.json').read_text())
        (public / 'invoices.json').write_text(json.dumps([
            row for row in rows if not (row['customer_id'] == 'C005' and row['period'] == '2026-04')]))
        self.tools = Tools(PublicData(public, '2026-04'), self.journal)
        result = self.tools.execute('screen_customers', {})
        self.assertEqual(result['screened_count'], 39)
        self.assertEqual(result['unassessed'][0]['customer_id'], 'C005')
        self.assertNotIn('C005', self.tools.comparisons)
        _, report = self.run_fake([FakeResponse([])])
        self.assertFalse(report['screening_complete'])
        self.assertEqual(report['status'], 'incomplete')

    def test_cached_usage_is_separate_from_conservative_budget_and_reasoning_is_not_double_charged(self):
        response = FakeResponse([])
        response.data['usage'].update(input_tokens_details={'cached_tokens': 40},
                                     output_tokens_details={'reasoning_tokens': 12})
        _, report = self.run_fake([response], input_usd_per_million=Decimal('2'),
                                 output_usd_per_million=Decimal('10'), cached_input_usd_per_million=Decimal('0.1'))
        self.assertEqual(report['metrics']['estimated_api_cost_usd'], '0.0004')
        self.assertEqual(report['metrics']['usage_priced_cost_usd'], '0.000324')
        self.assertEqual(report['metrics']['reasoning_output_tokens'], 12)
        self.assertIsNone(report['metrics']['actual_billed_cost_usd'])
        _, missing = self.run_fake([FakeResponse([])], cached_input_usd_per_million=Decimal('0.1'))
        self.assertIsNone(missing['metrics']['usage_priced_cost_usd'])
        for value in (Decimal('-1'), Decimal('NaN'), Decimal('2')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Limits(cached_input_usd_per_million=value)

    def test_default_tier_is_explicit_only_when_configured(self):
        client, _ = self.run_fake([FakeResponse([])], service_tier='default')
        self.assertEqual(client.requests[0]['service_tier'], 'default')
        client, _ = self.run_fake([FakeResponse([])])
        self.assertNotIn('service_tier', client.requests[0])
        with self.assertRaises(ValueError):
            Limits(service_tier='priority')
