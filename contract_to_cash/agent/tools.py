"""Read-only screening and model-selected evidence tools; no legal conclusions or billing writes."""
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from contract_to_cash.billing_engine import (
    BillingInputError, ConflictError, expected_amount, money, _period,
    _validate_contract, _validate_amendments, _quantity,
)


class ToolError(ValueError):
    pass


STRING = {'type': 'string', 'minLength': 1, 'maxLength': 200}
IDS = {'type': 'array', 'items': STRING, 'minItems': 1, 'maxItems': 100}
CASE_IDS = {**IDS, 'maxItems': 10}


def schema(name, description, **properties):
    return dict(type='function', name=name, description=description, strict=True,
                parameters=dict(type='object', properties=properties,
                                required=list(properties), additionalProperties=False))


CUSTOMER = {'customer_id': STRING}
TOOLS = [
    schema('screen_customers', 'Screen all structured records with deterministic billing comparisons. Returns candidates and clean IDs, not evidence verification, legal conclusions, or model findings. Conflicts queue mandatory guard review.'),
    schema('get_customer_evidence', 'Retrieve records, all original contract/amendment documents (including contrary/future terms), and comparison for up to ten model-selected customers. Previously retrieved documents are referenced in this revision; get_document can reread them.', customer_ids=CASE_IDS),
    schema('list_customers', 'List public customer IDs, names, and pricing templates. No audit results.'),
    schema('get_contract', 'Retrieve authoritative contract and document reference.', **CUSTOMER),
    schema('get_amendments', 'Retrieve all amendments, including contrary and future evidence.', **CUSTOMER),
    schema('get_invoices', 'Retrieve invoices for this run audit period.', **CUSTOMER),
    schema('get_document', 'Retrieve a public contract/amendment by exact document ID, never a path.', document_id=STRING),
    schema('calculate_expected', 'Calculate authoritative expected charges using recorded quantities. Conflicts require review.', **CUSTOMER),
    schema('compare_invoices', 'Compare recorded invoices with deterministic expected charges for one selected customer.', **CUSTOMER),
    schema('summarize_pattern', 'Aggregate already compared customers. Verify shared template and identical discrepancies; not proof of root cause.', customer_ids=IDS),
    schema('submit_finding', 'Propose, verify, or retract a finding. Amounts come only from server comparisons. Verification requires retrieved contract, all amendment documents, and invoices. Rationale is a model hypothesis, not authoritative financial data.',
           customer_ids=IDS, evidence_ids=IDS,
           state={'type': 'string', 'enum': ['proposed', 'verified', 'retracted']},
           rationale={'type': 'string', 'minLength': 1, 'maxLength': 1000}),
    schema('recommend_next_action', 'Persist a suggested action for an existing finding, grounded in exact retrieved evidence. Suggestions and rationale are model hypotheses, never contractual authority.', finding_id=STRING, evidence_ids=IDS, problem={'type': 'string', 'minLength': 1, 'maxLength': 1000}, suggested_action={'type': 'string', 'minLength': 1, 'maxLength': 1000}, reasoning={'type': 'string', 'minLength': 1, 'maxLength': 1000}, uncertainty={'type': 'string', 'minLength': 1, 'maxLength': 1000}),
    schema('request_human_review', 'Queue a finding for human review/export only. Never approves or executes billing changes.',
           finding_id=STRING, action={'type': 'string', 'enum': ['review', 'export']}),
]
for definition in TOOLS:
    Draft202012Validator.check_schema(definition['parameters'])


class PublicData:
    """Load exactly three record files and allowlisted documents; never read the key."""
    def __init__(self, directory: Path, period: str):
        self.directory = Path(directory).resolve()
        self.period = period
        first = _period(period)

        def read(relative):
            path = self.directory / relative
            if path.is_symlink() or not path.resolve().is_relative_to(self.directory):
                raise ToolError('Symlinked evidence is unsupported')
            return path.read_bytes()

        raw = {name: read(name + '.json') for name in ('contracts', 'amendments', 'invoices')}
        self.contracts, self.amendments, self.invoices = [json.loads(raw[n]) for n in raw]
        if not all(isinstance(rows, list) for rows in (self.contracts, self.amendments, self.invoices)):
            raise ToolError('Public record files must contain arrays')
        self.customers = {}
        identifiers = set()
        for contract in self.contracts:
            _validate_contract(contract, first)
            cid = contract['customer_id']
            if cid in self.customers or contract['contract_id'] in identifiers:
                raise ToolError('Duplicate contract/customer ID')
            identifiers.add(contract['contract_id'])
            self.customers[cid] = contract
        self.changes = {cid: [] for cid in self.customers}
        for amendment in self.amendments:
            if not isinstance(amendment, dict) or amendment.get('customer_id') not in self.customers:
                raise ToolError('Unknown amendment customer')
            cid = amendment['customer_id']
            self.changes[cid].append(amendment)
            if amendment.get('amendment_id') in identifiers:
                raise ToolError('Duplicate evidence ID')
            identifiers.add(amendment.get('amendment_id'))
        for cid, amendments in self.changes.items():
            _validate_amendments(self.customers[cid], amendments)
        self.rows = {cid: [] for cid in self.customers}
        for invoice in self.invoices:
            if not isinstance(invoice, dict) or invoice.get('customer_id') not in self.customers:
                raise ToolError('Unknown invoice customer')
            iid = invoice.get('invoice_id')
            if not isinstance(iid, str) or not iid or iid in identifiers:
                raise ToolError('Invalid or duplicate invoice ID')
            identifiers.add(iid)
            _period(invoice.get('period'))
            _quantity(invoice.get('usage_quantity'))
            money(invoice.get('billed_amount'))
            if invoice.get('currency') != 'CAD':
                raise ToolError('Only CAD invoices are supported')
            if invoice['period'] == period:
                self.rows[invoice['customer_id']].append(invoice)
        self.documents = {}
        manifest_bytes = read('document_hashes.json')
        manifest = json.loads(manifest_bytes)
        for record in self.contracts + self.amendments:
            did = record.get('contract_id', record.get('amendment_id'))
            if not isinstance(did, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', did):
                raise ToolError('Invalid public document ID')
            content = read(Path('documents') / (did + '.txt'))
            digest = hashlib.sha256(content).hexdigest()
            if manifest.get(did + '.txt') != digest:
                raise ToolError('Document integrity check failed')
            self.documents[did] = dict(document_id=did, customer_id=record['customer_id'],
                                       sha256=digest, text=content.decode('utf-8'))
        if set(manifest) != {did + '.txt' for did in self.documents}:
            raise ToolError('Manifest must contain exactly public documents')
        digest = hashlib.sha256()
        for content in [*raw.values(), manifest_bytes]:
            digest.update(content)
        # Reject an operator update that changed files while this snapshot was read.
        if any(read(name + '.json') != content for name, content in raw.items()) or read('document_hashes.json') != manifest_bytes:
            raise ToolError('Public snapshot changed during loading; retry with a stable snapshot')
        self.revision = digest.hexdigest()


class Tools:
    def __init__(self, data: PublicData, journal):
        self.data, self.journal = data, journal
        self.seen = set()
        self.documents_seen = set()
        self.comparisons = {}
        self.findings = {}
        self.reviews = {}
        self.definitions = {definition['name']: definition for definition in TOOLS}
        # Explicit mapping; never dispatch arbitrary attributes supplied by a model.
        self.handlers = {name: handler for name, handler in (
            ('screen_customers', self.screen_customers), ('get_customer_evidence', self.get_customer_evidence),
            ('list_customers', self.list_customers), ('get_contract', self.get_contract),
            ('get_amendments', self.get_amendments), ('get_invoices', self.get_invoices),
            ('get_document', self.get_document), ('calculate_expected', self.calculate_expected),
            ('compare_invoices', self.compare_invoices), ('summarize_pattern', self.summarize_pattern),
            ('submit_finding', self.submit_finding), ('recommend_next_action', self.recommend_next_action), ('request_human_review', self.request_human_review))}

    def execute(self, name, arguments):
        if name not in self.handlers:
            raise ToolError('Tool is not in the read-only allowlist')
        validator = Draft202012Validator(self.definitions[name]['parameters'])
        if list(validator.iter_errors(arguments)):
            raise ToolError('Invalid tool arguments; required fields/types and additional properties are enforced')
        for value in arguments.values():
            if isinstance(value, list) and len(value) != len(set(value)):
                raise ToolError('Duplicate IDs are not permitted')
        return copy.deepcopy(self.handlers[name](**arguments))

    def _customer(self, customer_id):
        if customer_id not in self.data.customers:
            raise ToolError('Unknown customer ID')
        return self.data.customers[customer_id]

    def list_customers(self):
        return [dict(customer_id=c['customer_id'], customer_name=c.get('customer_name', ''),
                     pricing_template=c['pricing_template']) for c in self.data.contracts]

    @staticmethod
    def compact_comparison(row):
        # The complete comparison remains in server state and screening events.
        keys = ('customer_id', 'status', 'pricing_template', 'expected_cad', 'billed_cad',
                'difference_cad', 'financial_category', 'invoice_amounts_cad', 'requires_human_review')
        return {key: row[key] for key in keys if key in row}

    def screen_customers(self):
        candidates, clean, unassessed = [], [], []
        for cid in sorted(self.data.customers):
            try:
                row = self.comparisons.get(cid) or self.compare_invoices(cid)
            except ToolError as exc:
                # For example, absent usage quantity cannot be guessed. Do not mark covered.
                unassessed.append(dict(customer_id=cid, reason=str(exc)))
                continue
            if row['status'] == 'clean':
                clean.append(cid)
            else:
                candidates.append(self.compact_comparison(row))
        # Full calculation evidence is logged without sending all clean rows back to the model.
        self.journal.emit('screening.completed', actor='tool', period=self.data.period,
                          data_revision=self.data.revision,
                          comparisons=list(self.comparisons.values()), unassessed=unassessed)
        return dict(period=self.data.period, data_revision=self.data.revision,
                    customer_count=len(self.data.customers), screened_count=len(self.comparisons),
                    candidates=candidates, clean_customer_ids=clean, unassessed=unassessed,
                    boundary='Structured candidates only. Investigate sources before verifying findings.')

    def get_customer_evidence(self, customer_ids):
        # Validate the complete selection before retrieving anything.
        for cid in customer_ids:
            self._customer(cid)
        cases = []
        for cid in customer_ids:
            contract = self.get_contract(cid)
            amendments = self.get_amendments(cid)
            invoices = self.get_invoices(cid)
            documents = []
            for did in [contract['contract_id']] + [a['amendment_id'] for a in amendments]:
                if did in self.documents_seen:
                    documents.append(dict(document_id=did, already_retrieved=True,
                                          data_revision=self.data.revision))
                else:
                    documents.append(self.get_document(did))
            comparison = self.comparisons.get(cid) or self.compare_invoices(cid)
            cases.append(dict(customer_id=cid, contract=contract, amendments=amendments,
                              invoices=invoices, documents=documents,
                              comparison=self.compact_comparison(comparison),
                              evidence_ids=sorted(self._required(cid))))
        return dict(data_revision=self.data.revision, cases=cases)

    def _evidence(self, ids):
        self.seen.update(ids)
        self.journal.emit('evidence.retrieved', actor='tool', evidence_ids=ids,
                          data_revision=self.data.revision)

    def get_contract(self, customer_id):
        c = self._customer(customer_id)
        self._evidence([c['contract_id']])
        return c

    def get_amendments(self, customer_id):
        self._customer(customer_id)
        rows = self.data.changes[customer_id]
        self._evidence([a['amendment_id'] for a in rows])
        return rows

    def get_invoices(self, customer_id):
        self._customer(customer_id)
        rows = self.data.rows[customer_id]
        self._evidence([i['invoice_id'] for i in rows])
        return rows

    def get_document(self, document_id):
        if document_id not in self.data.documents:
            raise ToolError('Unknown public document ID')
        self.documents_seen.add(document_id)
        self._evidence([document_id])
        return self.data.documents[document_id]

    def _required(self, customer_id):
        return {self._customer(customer_id)['contract_id'],
                *(a['amendment_id'] for a in self.data.changes[customer_id]),
                *(i['invoice_id'] for i in self.data.rows[customer_id])}

    def calculation_amendments(self, customer_id):
        return self.data.changes[customer_id]

    def calculate_expected(self, customer_id):
        c = self._customer(customer_id)
        rows = self.data.rows[customer_id]
        # A missing invoice provides no authoritative usage quantity.
        if not rows and 'usage_tier' in c:
            raise ToolError('Missing authoritative usage quantity')
        quantities = sorted({i['usage_quantity'] for i in rows}) or [0]
        try:
            amounts = [dict(usage_quantity=q, expected_cad=str(expected_amount(
                c, self.calculation_amendments(customer_id), self.data.period, q))) for q in quantities]
        except ConflictError:
            result = dict(status='conflict', expected_cad=None, difference_cad=None, customer_id=customer_id,
                          data_revision=self.data.revision,
                          evidence_ids=sorted(self._required(customer_id)), requires_human_review=True)
            self._queue_conflict(customer_id, result)
            return result
        return dict(customer_id=customer_id, status='calculated', amounts=amounts,
                    evidence_ids=sorted(self._required(customer_id)), currency='CAD')

    def compare_invoices(self, customer_id):
        c = self._customer(customer_id)
        rows = self.data.rows[customer_id]
        calculation = self.calculate_expected(customer_id)
        result = dict(customer_id=customer_id, period=self.data.period, currency='CAD',
                      pricing_template=c['pricing_template'], evidence_ids=sorted(self._required(customer_id)),
                      data_revision=self.data.revision)
        if calculation['status'] == 'conflict':
            result.update(status='conflict', difference_cad=None, requires_human_review=True)
        elif not rows:
            result.update(status='missing_invoice', difference_cad=None, requires_human_review=True)
        elif len(rows) > 1:
            # Do not invent an authoritative payable invoice or net duplicate exposure.
            result.update(status='duplicate_invoice', difference_cad=None,
                          invoice_amounts_cad=[str(money(i['billed_amount'])) for i in rows],
                          requires_human_review=True)
        else:
            expected = Decimal(calculation['amounts'][0]['expected_cad'])
            billed = money(rows[0]['billed_amount'])
            difference = expected - billed
            result.update(status='clean' if difference == 0 else 'discrepancy',
                          expected_cad=str(expected), billed_cad=str(billed), difference_cad=str(difference),
                          financial_category='additional_receivable' if difference > 0 else
                          'potential_credit' if difference < 0 else 'none')
        self.comparisons[customer_id] = result
        if result['status'] == 'conflict':
            self._queue_conflict(customer_id, result)
        return result

    def summarize_pattern(self, customer_ids):
        ids = sorted(customer_ids)
        if len(ids) < 2 or any(cid not in self.comparisons for cid in ids):
            raise ToolError('Select at least two customers already compared in this revision')
        rows = [self.comparisons[cid] for cid in ids]
        matched = (len(ids) >= 3 and all(r['status'] == 'discrepancy' for r in rows)
                   and len({(r['pricing_template'], r['difference_cad']) for r in rows}) == 1)
        return dict(customer_ids=ids, shared_pattern_verified=matched,
                    total_difference_cad=str(sum((Decimal(r['difference_cad']) for r in rows), Decimal(0)))
                    if matched else None,
                    comparisons=rows, root_cause='unproven; shared characteristics are a correlation')

    def _queue_conflict(self, cid, result):
        fid = 'finding-' + cid
        old = self.findings.get(fid)
        if not old or old['data_revision'] != self.data.revision or old['state'] == 'retracted':
            self.findings[fid] = dict(finding_id=fid, customer_ids=[cid], state='proposed',
                version=old['version'] + 1 if old else 1,
                comparison=result, evidence_ids=result['evidence_ids'], data_revision=self.data.revision,
                origin='deterministic_conflict_guard', evidence_verified=False)
            self._procedural_recommendation(self.findings[fid], old)
            self.journal.emit('finding.proposed', actor='tool', finding=self.findings[fid])
        review = self.reviews.get(fid)
        if not review or review['status'] == 'invalidated' or review['finding_version'] != self.findings[fid]['version']:
            self.request_human_review(fid, 'review')

    def submit_finding(self, customer_ids, evidence_ids, state, rationale):
        ids = sorted(customer_ids)
        fid = 'finding-' + '-'.join(ids)
        if any(cid not in self.comparisons for cid in ids):
            raise ToolError('Compare each selected customer first')
        required = set().union(*(self._required(cid) for cid in ids))
        provided = set(evidence_ids)
        if not provided <= required or not provided <= self.seen:
            raise ToolError('Citations must be retrieved evidence belonging to selected customers')
        old = self.findings.get(fid)
        if state == 'retracted' and (not old or old['state'] == 'retracted'):
            raise ToolError('Only an existing active finding can be retracted')
        rows = [self.comparisons[cid] for cid in ids]
        pattern = self.summarize_pattern(ids) if len(ids) > 1 else None
        if state == 'verified':
            docs = required & set(self.data.documents)
            if not required <= provided or not docs <= self.documents_seen:
                raise ToolError('Retrieve and cite contract, all amendment documents, and invoices before verification')
            if any(row['status'] == 'clean' for row in rows):
                raise ToolError('Clean accounts cannot be verified as discrepancies')
            if pattern and not pattern['shared_pattern_verified']:
                raise ToolError('Shared pattern is not supported by comparisons')
        finding = dict(finding_id=fid, customer_ids=ids, state=state,
                       version=old['version'] + 1 if old else 1, evidence_ids=sorted(provided),
                       evidence_verified=state == 'verified', comparisons=rows, pattern=pattern,
                       model_hypothesis=rationale, data_revision=self.data.revision, origin='model_submission')
        self._procedural_recommendation(finding, old)
        self.findings[fid] = finding
        # Every revision invalidates prior pending/approved review scope.
        if fid in self.reviews:
            self.reviews[fid]['status'] = 'invalidated'
        self.journal.emit('finding.' + state, actor='tool', finding=finding)
        return finding

    def _procedural_recommendation(self, finding, old=None):
        finding['recommendation_history'] = copy.deepcopy((old or {}).get('recommendation_history', []))
        rec = self.select_procedural_recommendation(finding)
        finding['recommendation'] = rec
        finding['recommendation_history'].append(rec)

    @staticmethod
    def select_procedural_recommendation(finding):
        rows = finding.get('comparisons', [finding.get('comparison', {})])
        kinds = {row.get('status') for row in rows}
        if 'conflict' in kinds:
            problem = 'The signed terms conflict; no governing price is established.'
            action = 'Obtain written confirmation from the responsible contract authority, register the supporting record, then resolve with evidence.'
            uncertainty = 'Which conflicting signed amendment governs this billing period remains unknown.'
        elif 'duplicate_invoice' in kinds:
            problem = 'Multiple invoice records require reconciliation.'
            action = 'Ask Billing Operations to identify authoritative invoice and payment records before asserting duplicate exposure.'
            uncertainty = 'The records do not establish that multiple charges were collected.'
        else:
            problem = 'The saved comparison needs human review.'
            action = 'Inspect the cited original terms and invoice records; approve only the requested review or export scope if supported.'
            uncertainty = 'Business context and authorization remain for the employee to establish.'
        rec = dict(origin='evidence_rule', problem=problem, suggested_action=action,
                   reasoning='Selected by the deterministic comparison state, not model-generated reasoning.',
                   uncertainty=uncertainty, evidence_ids=finding['evidence_ids'],
                   finding_version=finding['version'], data_revision=finding['data_revision'])
        return rec

    def recommend_next_action(self, finding_id, evidence_ids, problem, suggested_action, reasoning, uncertainty):
        finding = self.findings.get(finding_id)
        if not finding or finding['state'] == 'retracted':
            raise ToolError('Recommendation requires an active finding')
        required = set().union(*(self._required(cid) for cid in finding['customer_ids']))
        if not set(evidence_ids) <= required or not set(evidence_ids) <= self.seen or not evidence_ids:
            raise ToolError('Recommendation citations must be retrieved evidence for this finding')
        rec = dict(origin='model_suggestion', problem=problem, suggested_action=suggested_action,
                   reasoning=reasoning, uncertainty=uncertainty, evidence_ids=sorted(evidence_ids),
                   finding_version=finding['version'], data_revision=self.data.revision)
        finding['recommendation'] = rec
        finding.setdefault('recommendation_history', []).append(rec)
        self.journal.emit('recommendation.created', actor='model', finding_id=finding_id,
                          recommendation=rec)
        return rec

    def request_human_review(self, finding_id, action):
        if finding_id not in self.findings or self.findings[finding_id]['state'] == 'retracted':
            raise ToolError('Review requires an active finding')
        finding = self.findings[finding_id]
        review = dict(finding_id=finding_id, finding_version=finding['version'], action=action,
                      status='pending', data_revision=self.data.revision,
                      boundary='Human review/export only; no billing mutation is implemented')
        self.reviews[finding_id] = review
        self.journal.emit('human_review.requested', actor='tool', review=review)
        return review

    def refresh(self):
        """Trusted operator file updates only; never callable through the model allowlist."""
        fresh = PublicData(self.data.directory, self.data.period)
        if fresh.revision == self.data.revision:
            return None
        previous = self.data.revision
        self.data = fresh
        self.seen.clear()
        self.documents_seen.clear()
        self.comparisons.clear()
        for finding in self.findings.values():
            if finding['state'] != 'retracted':
                finding['state'] = 'proposed'
                finding['evidence_verified'] = False
                finding['version'] += 1
                finding['requires_revalidation'] = True
        for review in self.reviews.values():
            review['status'] = 'invalidated'
        return self.journal.emit('evidence.updated', previous_revision=previous,
                                 data_revision=fresh.revision, source='operator_public_snapshot',
                                 effect='Comparisons cleared; findings and reviews require revalidation')
