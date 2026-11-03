"""Offline validation infrastructure tests. These never execute the OpenAI API."""
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from scripts.evaluate_agent_runs import evaluate
from test_agent import FakeResponse, FakeClient
from contract_to_cash.agent.runtime import Investigator, Limits


class UsageTelemetryTests(unittest.TestCase):
    def test_cached_and_reasoning_tokens_are_preserved_not_called_billed_cost(self):
        from contract_to_cash.agent.tools import PublicData, Tools
        from contract_to_cash.agent.events import Journal
        data = Path(__file__).resolve().parents[1] / 'data'
        response = FakeResponse([])
        response.data['model'] = 'model-snapshot'
        response.data['usage'].update(input_tokens_details={'cached_tokens': 40},
                                      output_tokens_details={'reasoning_tokens': 12})
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(Path(tmp) / 'run')
            try:
                report = Investigator(FakeClient([response]), 'model', Tools(PublicData(data, '2026-04'), journal),
                                      journal, Limits()).run('Audit')
                self.assertEqual(report['metrics']['cached_input_tokens'], 40)
                self.assertEqual(report['metrics']['reasoning_output_tokens'], 12)
                self.assertIsNone(report['metrics']['actual_billed_cost_usd'])
                event = next(e for e in journal.events if e['type'] == 'api.completed')
                self.assertEqual(event['payload']['model'], 'model-snapshot')
            finally:
                journal.close()


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        self.data = Path(__file__).resolve().parents[1] / 'data'
        self.report = dict(run_id='SIMULATED', status='incomplete', reason='tool_call_limit', period='2026-04',
                           data_revision='test-revision', findings=[], reviews=[], metrics={})
        self.events = [dict(sequence=1, type='investigation.started', payload=dict(limits=dict(
            input_usd_per_million='1', output_usd_per_million='4')))]

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        (self.run / 'report.json').write_text(json.dumps(self.report))
        (self.run / 'events.jsonl').write_text('\n'.join(json.dumps(e) for e in self.events) + '\n')

    def test_no_findings_are_missed_not_a_successful_zero_anomaly_audit(self):
        self.write()
        result = evaluate(self.run, self.data)
        self.assertEqual(result['true_positives'], 0)
        self.assertEqual(len(result['missed_anomalies']), 8)
        self.assertFalse(result['financial_accuracy_passed'])
        self.assertIsNone(result['actual_billed_cost_usd'])

    def test_correct_group_and_clean_negative_control_scoring(self):
        for customers in (['C001'], ['C011']):
            self.report['findings'].append(dict(customer_ids=customers, finding_id='-'.join(customers),
                state='verified', evidence_verified=True, data_revision='test-revision', comparisons=[]))
        self.write()
        result = evaluate(self.run, self.data)
        self.assertEqual(result['true_positives'], 1)
        self.assertEqual(result['false_positive_groups'], 1)
        self.assertEqual(result['false_positive_customers'], ['C011'])
        self.assertTrue(result['negative_control_flagged'])

    def test_altered_calculation_and_missing_tool_outcome_are_detected(self):
        self.events.extend([
            dict(sequence=2, type='tool.requested', correlation_id='one', payload=dict(tool='compare_invoices')),
            dict(sequence=3, type='tool.completed', correlation_id='one', payload=dict(tool='compare_invoices',
                result=dict(customer_id='C001', status='discrepancy', expected_cad='1.00',
                            billed_cad='12500.00', difference_cad='-500.00'))),
            dict(sequence=4, type='tool.requested', correlation_id='missing', payload=dict(tool='get_document'))])
        self.write()
        result = evaluate(self.run, self.data)
        self.assertEqual(result['financial_checks'], 1)
        self.assertFalse(result['financial_accuracy_passed'])
        self.assertEqual(result['missing_tool_outcomes'], ['missing'])

    def test_cached_usage_cost_is_calculated_separately_from_invoice(self):
        self.events.append(dict(sequence=2, type='api.completed', payload=dict(input_tokens=100,
            cached_input_tokens=40, output_tokens=20, usage_details_available=True)))
        self.write()
        self.assertIsNone(evaluate(self.run, self.data)['usage_priced_cost_usd'])
        result = evaluate(self.run, self.data, cached_price=Decimal('0.25'))
        self.assertEqual(result['usage_priced_cost_usd'], '0.00015')
        self.assertIsNone(result['actual_billed_cost_usd'])
