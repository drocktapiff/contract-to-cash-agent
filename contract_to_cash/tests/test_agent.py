"""Simulated orchestration and real local tools; no OpenAI API calls in this suite."""
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from contract_to_cash.agent.events import Journal
from contract_to_cash.agent.runtime import Investigator, Limits
from contract_to_cash.agent.tools import PublicData, Tools, ToolError, TOOLS
from contract_to_cash.agent.review import decide
from scripts.build_agent_runtime import build

DATA = Path(__file__).resolve().parents[1] / 'data'


class FakeResponse:
    def __init__(self, output, status='completed'):
        self.data = dict(id='fake-response', output=output, status=status,
                         usage=dict(input_tokens=100, output_tokens=20))

    def model_dump(self, **kwargs):
        return copy.deepcopy(self.data)


def call(name, arguments):
    return dict(type='function_call', name=name, arguments=json.dumps(arguments), call_id=name + '-call')


class FakeClient:
    def __init__(self, responses):
        self.script = iter(responses)
        self.requests = []
        self.options = []
        self.responses = self

    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        result = next(self.script)
        if isinstance(result, Exception):
            raise result
        return result


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # unittest runs cleanups in reverse order, including when setUp fails.
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.journal = Journal(self.root / 'run')
        self.addCleanup(self.journal.close)
        self.data = PublicData(DATA, '2026-04')
        self.tools = Tools(self.data, self.journal)

    def evidence(self, cid):
        c = self.tools.execute('get_contract', dict(customer_id=cid))
        amendments = self.tools.execute('get_amendments', dict(customer_id=cid))
        invoices = self.tools.execute('get_invoices', dict(customer_id=cid))
        docs = [c['contract_id']] + [a['amendment_id'] for a in amendments]
        for did in docs:
            self.tools.execute('get_document', dict(document_id=did))
        return docs + [i['invoice_id'] for i in invoices]

    def verify(self, cid):
        self.tools.execute('compare_invoices', dict(customer_id=cid))
        evidence = self.evidence(cid)
        return self.tools.execute('submit_finding', dict(customer_ids=[cid], evidence_ids=evidence,
                                  state='verified', rationale='Signed terms and invoice differ; review required.'))

    def run_fake(self, responses, **limits):
        client = FakeClient(responses)
        report = Investigator(client, 'test-model', self.tools, self.journal, Limits(**limits)).run('Audit all customers')
        return client, report

    def test_exact_allowlist_and_no_batch_audit(self):
        self.assertEqual(set(self.tools.handlers), {'list_customers', 'get_contract', 'get_amendments',
                         'get_invoices', 'get_document', 'calculate_expected', 'compare_invoices',
                         'summarize_pattern', 'submit_finding', 'request_human_review'})
        for name in ('investigate', 'investigate_period', '__getattribute__', 'execute',
                     'approve', 'modify_invoice', 'request_human_review.__globals__'):
            with self.subTest(name=name), self.assertRaises(ToolError):
                self.tools.execute(name, {})

    def test_key_and_paths_are_inaccessible(self):
        for name in ('sealed_answer_key.json', '../sealed_answer_key', '/etc/passwd',
                     '../../data/sealed_answer_key.json', 'document_hashes.json'):
            with self.subTest(name=name), self.assertRaises(ToolError):
                self.tools.execute('get_document', dict(document_id=name))
        self.assertNotIn('sealed_answer_key', json.dumps(self.tools.execute('list_customers', {})))

    def test_loader_never_reads_key(self):
        original = Path.read_bytes
        read_paths = []
        def monitored(path):
            read_paths.append(path)
            self.assertNotIn('sealed_answer_key', str(path))
            return original(path)
        with patch.object(Path, 'read_bytes', monitored):
            PublicData(DATA, '2026-04')
        self.assertEqual({path.name for path in read_paths if path.suffix == '.json'},
                         {'contracts.json', 'amendments.json', 'invoices.json', 'document_hashes.json'})

    def test_all_tools_enforce_strict_object_schemas(self):
        for definition in TOOLS:
            schema = definition['parameters']
            self.assertTrue(definition['strict'])
            self.assertFalse(schema['additionalProperties'])
            self.assertEqual(set(schema['required']), set(schema['properties']))
            with self.subTest(tool=definition['name']), self.assertRaises(ToolError):
                self.tools.execute(definition['name'], dict(unauthorized_amount='999'))
        for args in ([], None, {'customer_id': 3}, {'customer_id': 'C001', 'usage_quantity': 1},
                     {'customer_id': 'C001', 'period': '2026-05'}):
            with self.subTest(args=args), self.assertRaises(ToolError):
                self.tools.execute('calculate_expected', args)

    def test_calculator_is_authoritative(self):
        with patch('contract_to_cash.agent.tools.expected_amount', return_value=Decimal('123.45')) as calc:
            result = self.tools.execute('compare_invoices', dict(customer_id='C002'))
        self.assertTrue(calc.called)
        self.assertEqual(result['expected_cad'], '123.45')
        self.assertEqual(result['difference_cad'], '-9376.55')
        self.assertEqual(calc.call_args.args[3], 0)

    def test_conflict_queues_real_review_without_amount(self):
        result = self.tools.execute('compare_invoices', dict(customer_id='C007'))
        self.assertEqual(result['status'], 'conflict')
        self.assertIsNone(result['difference_cad'])
        self.assertEqual(self.tools.reviews['finding-C007']['status'], 'pending')
        self.assertTrue(any(e['type'] == 'human_review.requested' for e in self.journal.events))

    def test_financial_mutations_and_model_approvals_blocked(self):
        finding = self.verify('C001')
        for action in ('send_invoice', 'refund', 'approved', 'collect'):
            with self.subTest(action=action), self.assertRaises(ToolError):
                self.tools.execute('request_human_review', dict(finding_id=finding['finding_id'], action=action))

    def test_verification_requires_retrieved_linked_evidence(self):
        self.tools.execute('compare_invoices', dict(customer_id='C001'))
        arguments = dict(customer_ids=['C001'], evidence_ids=['CTR-C001'], state='verified', rationale='Investigate difference')
        with self.assertRaises(ToolError):
            self.tools.execute('submit_finding', arguments)
        self.evidence('C002')
        arguments['evidence_ids'] = ['CTR-C002']
        with self.assertRaises(ToolError):
            self.tools.execute('submit_finding', arguments)
        finding = self.verify('C001')
        self.assertTrue(finding['evidence_verified'])
        self.assertEqual(finding['comparisons'][0]['difference_cad'], '-500.00')

    def test_clean_negative_control_cannot_be_verified(self):
        self.tools.execute('compare_invoices', dict(customer_id='C011'))
        evidence = self.evidence('C011')
        with self.assertRaises(ToolError):
            self.tools.execute('submit_finding', dict(customer_ids=['C011'], evidence_ids=evidence,
                               state='verified', rationale='An unsupported hypothesis'))

    def test_patterns_only_aggregate_selected_previously_compared_records(self):
        ids = ['C008', 'C009', 'C010']
        with self.assertRaises(ToolError):
            self.tools.execute('summarize_pattern', dict(customer_ids=ids))
        for cid in ids:
            self.tools.execute('compare_invoices', dict(customer_id=cid))
        pattern = self.tools.execute('summarize_pattern', dict(customer_ids=ids))
        self.assertTrue(pattern['shared_pattern_verified'])
        self.assertEqual(pattern['total_difference_cad'], '3000.00')
        self.assertIn('unproven', pattern['root_cause'])

    def test_model_directed_order_and_protocol(self):
        client, report = self.run_fake([
            FakeResponse([call('get_contract', dict(customer_id='C020'))]),
            FakeResponse([call('list_customers', {})]), FakeResponse([])])
        requested = [e['payload']['tool'] for e in self.journal.events if e['type'] == 'tool.requested']
        self.assertEqual(requested, ['get_contract', 'list_customers'])
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['metrics']['agent_tool_calls'], 2)
        continuation = client.requests[1]['input']
        self.assertTrue(any(item.get('type') == 'function_call_output' for item in continuation))
        self.assertFalse(client.requests[0]['store'])
        self.assertFalse(client.requests[0]['parallel_tool_calls'])
        self.assertEqual(client.options[0]['max_retries'], 0)

    def test_tool_failure_is_not_fabricated_success(self):
        _, report = self.run_fake([FakeResponse([call('get_document', {'document_id': 'MISSING'})]), FakeResponse([])])
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['metrics']['tool_failures'], 1)
        types = [e['type'] for e in self.journal.events]
        self.assertIn('tool.failed', types)
        self.assertNotIn('tool.completed', types)
        self.assertEqual(report['findings'], [])

    def test_invalid_json_and_allowlist_bypass_are_safe(self):
        malformed = call('list_customers', {}); malformed['arguments'] = '{bad'
        _, report = self.run_fake([FakeResponse([malformed, call('modify_invoice', {})]), FakeResponse([])])
        self.assertEqual(report['metrics']['tool_failures'], 2)
        self.assertEqual(report['status'], 'incomplete')

    def test_api_error_does_not_leak_exception_or_claim_success(self):
        _, report = self.run_fake([RuntimeError('secret-error-value')])
        self.assertEqual(report['reason'], 'api_failure')
        self.assertFalse(report['metrics']['cost_accounting_complete'])
        self.assertNotIn('secret-error-value', json.dumps(self.journal.events))

    def test_hidden_reasoning_and_final_prose_are_not_reported_as_findings(self):
        _, report = self.run_fake([FakeResponse([
            dict(type='reasoning', summary=[dict(text='HIDDEN-REASONING')]),
            dict(type='message', content=[dict(type='output_text', text='Recovered a million dollars')])])])
        self.assertNotIn('HIDDEN-REASONING', json.dumps(self.journal.events))
        self.assertNotIn('Recovered', json.dumps(report))
        self.assertEqual(report['findings'], [])

    def test_tool_budget_and_cost_budget(self):
        _, report = self.run_fake([FakeResponse([call('list_customers', {}), call('list_customers', {})])], max_tool_calls=1)
        self.assertEqual(report['reason'], 'tool_call_limit')
        self.assertEqual(report['metrics']['agent_tool_calls'], 1)

    def test_cost_preflight_prevents_request(self):
        client, report = self.run_fake([], max_cost_usd=Decimal('0.000001'))
        self.assertEqual(report['reason'], 'estimated_cost_limit')
        self.assertEqual(client.requests, [])

    def test_incomplete_api_response_does_not_execute_partial_calls(self):
        _, report = self.run_fake([FakeResponse([call('list_customers', {})], status='incomplete')])
        self.assertEqual(report['reason'], 'api_response_incomplete')
        self.assertEqual(report['metrics']['agent_tool_calls'], 0)

    def test_real_evidence_update_invalidates_findings_and_allows_retraction(self):
        public = self.root / 'public'
        shutil.copytree(DATA, public, ignore=shutil.ignore_patterns('sealed_answer_key.json'))
        self.tools = Tools(PublicData(public, '2026-04'), self.journal)
        finding = self.verify('C001')
        self.tools.request_human_review(finding['finding_id'], 'export')
        invoices = json.loads((public / 'invoices.json').read_text())
        for row in invoices:
            if row['customer_id'] == 'C001' and row['period'] == '2026-04':
                row['billed_amount'] = '12000.00'
        (public / 'invoices.json').write_text(json.dumps(invoices))
        self.assertIsNotNone(self.tools.refresh())
        self.assertFalse(self.tools.findings[finding['finding_id']]['evidence_verified'])
        self.assertEqual(self.tools.reviews[finding['finding_id']]['status'], 'invalidated')
        self.assertEqual(self.tools.compare_invoices('C001')['status'], 'clean')
        evidence = self.evidence('C001')
        retracted = self.tools.execute('submit_finding', dict(customer_ids=['C001'], evidence_ids=evidence,
                           state='retracted', rationale='Updated authoritative invoice removes the discrepancy.'))
        self.assertEqual(retracted['state'], 'retracted')
        self.assertTrue(any(e['type'] == 'finding.retracted' for e in self.journal.events))

    def test_review_is_local_and_version_bound(self):
        finding = self.verify('C001')
        self.tools.request_human_review(finding['finding_id'], 'export')
        _, report = self.run_fake([FakeResponse([])])
        decision = decide(self.journal.directory, finding['finding_id'], 'approved', 'Test Operator')
        self.assertEqual(decision['finding_version'], finding['version'])
        exports = list(self.journal.directory.glob('*-export.json'))
        self.assertEqual(len(exports), 1)
        updated = json.loads((self.journal.directory / 'report.json').read_text())
        self.assertEqual(updated['metrics']['human_interventions'], 1)
        self.assertEqual(updated['reviews'][0]['status'], 'approved')
        with self.assertRaises(Exception):
            decide(self.journal.directory, finding['finding_id'], 'approved', 'Test Operator')

    def test_runtime_bundle_excludes_key_generator_tests_and_prompts(self):
        target = build(self.root / 'bundle')
        names = [str(p.relative_to(target)) for p in target.rglob('*') if p.is_file()]
        for forbidden in ('sealed_answer_key', 'generate_data', 'test_foundation', 'USER_PROMPTS'):
            self.assertFalse(any(forbidden in name for name in names))
        self.assertEqual(len(PublicData(target / 'contract_to_cash/data', '2026-04').customers), 40)
        with self.assertRaises(ValueError):
            build(target)

    def test_billing_records_unchanged_by_tools(self):
        def digest():
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA.glob('*.json')}
        before = digest()
        self.verify('C001')
        self.tools.request_human_review('finding-C001', 'review')
        self.assertEqual(before, digest())

    def test_symlinked_evidence_and_tampering_rejected(self):
        public = self.root / 'public'
        shutil.copytree(DATA, public, ignore=shutil.ignore_patterns('sealed_answer_key.json'))
        doc = public / 'documents/CTR-C001.txt'
        doc.write_text('tampered')
        with self.assertRaises(ToolError):
            PublicData(public, '2026-04')
        doc.unlink(); doc.symlink_to(DATA / 'documents/CTR-C001.txt')
        with self.assertRaises(ToolError):
            PublicData(public, '2026-04')

    def test_fully_verified_run_can_complete_and_totals_are_deduplicated(self):
        # Narrow public scope for a fast protocol test, not a scripted runtime investigation.
        self.data.customers = {'C001': self.data.customers['C001']}
        self.data.contracts = [self.data.customers['C001']]
        messages = [FakeResponse([call('compare_invoices', {'customer_id': 'C001'})]),
                    FakeResponse([call('get_contract', {'customer_id': 'C001'})]),
                    FakeResponse([call('get_document', {'document_id': 'CTR-C001'})]),
                    FakeResponse([call('get_invoices', {'customer_id': 'C001'})]),
                    FakeResponse([call('submit_finding', dict(customer_ids=['C001'],
                        evidence_ids=['CTR-C001', 'INV-C001-2026-04'], state='verified', rationale='Review discrepancy'))]),
                    FakeResponse([call('request_human_review', dict(finding_id='finding-C001', action='review'))]),
                    FakeResponse([])]
        _, report = self.run_fake(messages)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['financial_totals']['potential_credits_cad'], '500.00')
        self.assertEqual(report['metrics']['input_tokens'], 700)
        self.assertEqual(report['metrics']['estimated_api_cost_usd'], '0.00126')

    def test_time_limit_prevents_next_request(self):
        client = FakeClient([])
        clock = iter([0, 10, 11])
        report = Investigator(client, 'test-model', self.tools, self.journal,
                              Limits(max_seconds=1), clock=lambda: next(clock)).run('Audit')
        self.assertEqual(report['reason'], 'time_limit')
        self.assertEqual(client.requests, [])

    def test_duplicate_ids_and_duplicate_json_keys_rejected(self):
        with self.assertRaises(ToolError):
            self.tools.execute('summarize_pattern', {'customer_ids': ['C001', 'C001']})
        item = call('get_contract', {})
        item['arguments'] = '{"customer_id":"C001","customer_id":"C002"}'
        _, report = self.run_fake([FakeResponse([item]), FakeResponse([])])
        self.assertEqual(report['metrics']['tool_failures'], 1)

    def test_calculate_conflict_alone_queues_review(self):
        result = self.tools.execute('calculate_expected', dict(customer_id='C007'))
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(self.tools.reviews['finding-C007']['status'], 'pending')

    def test_sdk_transport_protocol_without_network_or_credentials(self):
        from openai import OpenAI
        import httpx2
        requests = []
        responses = [FakeResponse([call('list_customers', {})]).data, FakeResponse([]).data]
        def serve(request):
            requests.append(json.loads(request.content))
            body = responses.pop(0)
            body.update(object='response', created_at=1, model='test-model')
            return httpx2.Response(200, json=body)
        with OpenAI(api_key='local-test-placeholder', base_url='https://example.invalid/v1',
                    http_client=httpx2.Client(transport=httpx2.MockTransport(serve))) as client:
            report = Investigator(client, 'test-model', self.tools, self.journal, Limits()).run('Audit')
        self.assertEqual(len(requests), 2)
        self.assertEqual(report['metrics']['agent_tool_calls'], 1)
        self.assertEqual(requests[1]['input'][-1]['type'], 'function_call_output')
        self.assertEqual(requests[1]['input'][-1]['call_id'], 'list_customers-call')


    def test_overlapping_verified_findings_do_not_double_count_money(self):
        ids = ['C008', 'C009', 'C010']
        evidence = []
        for cid in ids:
            self.tools.compare_invoices(cid)
            evidence.extend(self.evidence(cid))
        individual = self.verify('C008')
        group = self.tools.execute('submit_finding', dict(customer_ids=ids, evidence_ids=evidence,
                                  state='verified', rationale='A shared discrepancy warrants review.'))
        for finding in (individual, group):
            self.tools.request_human_review(finding['finding_id'], 'review')
        _, report = self.run_fake([FakeResponse([])])
        self.assertEqual(report['financial_totals']['additional_receivables_cad'], '3000.00')

    def test_watch_data_event_is_delivered_to_model_after_real_update(self):
        public = self.root / 'watch-public'
        shutil.copytree(DATA, public, ignore=shutil.ignore_patterns('sealed_answer_key.json'))
        self.tools = Tools(PublicData(public, '2026-04'), self.journal)
        client = FakeClient([FakeResponse([call('list_customers', {})]), FakeResponse([])])
        original_create = client.create
        def updating_create(**kwargs):
            result = original_create(**kwargs)
            if len(client.requests) == 1:
                invoices = json.loads((public / 'invoices.json').read_text())
                invoices[0]['billed_amount'] = '123.45'
                (public / 'invoices.json').write_text(json.dumps(invoices))
            return result
        client.create = updating_create
        Investigator(client, 'test-model', self.tools, self.journal, Limits(), watch_data=True).run('Audit')
        self.assertTrue(any(event['type'] == 'evidence.updated' for event in self.journal.events))
        self.assertTrue(any('evidence.updated' in item.get('content', '') for item in client.requests[1]['input']))

    def test_run_cli_rejects_data_containing_key(self):
        from contract_to_cash.agent.__main__ import main
        with self.assertRaises(SystemExit) as result:
            with patch('sys.stderr'):
                main(['run', '--model', 'test-model', '--data', str(DATA),
                      '--input-price-per-million', '1', '--output-price-per-million', '4'])
        self.assertEqual(result.exception.code, 2)
