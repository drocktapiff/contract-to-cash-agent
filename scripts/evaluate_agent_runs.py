"""Offline evaluation only: reads the sealed key AFTER agent execution; never calls OpenAI."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from contract_to_cash.billing_engine import expected_amount, ConflictError, load_records, money


def reference(data, period):
    contracts, amendments, invoices = load_records(data)
    result = {}
    for contract in contracts:
        cid = contract['customer_id']
        changes = [a for a in amendments if a['customer_id'] == cid]
        rows = [i for i in invoices if i['customer_id'] == cid and i['period'] == period]
        quantities = sorted({i['usage_quantity'] for i in rows}) or [0]
        try:
            amounts = [dict(usage_quantity=q, expected_cad=str(expected_amount(contract, changes, period, q)))
                       for q in quantities]
        except ConflictError:
            result[cid] = dict(status='conflict', difference_cad=None)
            continue
        if not rows:
            result[cid] = dict(status='missing_invoice', difference_cad=None)
        elif len(rows) > 1:
            result[cid] = dict(status='duplicate_invoice', difference_cad=None,
                               invoice_amounts_cad=[str(money(i['billed_amount'])) for i in rows])
        else:
            expected = Decimal(amounts[0]['expected_cad'])
            billed = money(rows[0]['billed_amount'])
            delta = expected - billed
            result[cid] = dict(status='clean' if delta == 0 else 'discrepancy',
                               expected_cad=str(expected), billed_cad=str(billed), difference_cad=str(delta))
        result[cid]['amounts'] = amounts
    return result


def financial_errors(actual, expected):
    return {key: dict(expected=value, actual=actual.get(key)) for key, value in expected.items()
            if key != 'amounts' and actual.get(key) != value}


def evaluate(run, data, cached_price=None):
    report = json.loads((run / 'report.json').read_text(encoding='utf-8'))
    events = [json.loads(line) for line in (run / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
    key = json.loads((data / 'sealed_answer_key.json').read_text(encoding='utf-8'))
    if report['period'] != key['period']:
        raise ValueError('Run period does not match evaluation fixture')
    baseline = reference(data, report['period'])
    expected_groups = {tuple(sorted(issue['customers'])): issue for issue in key['issues']}
    active = [f for f in report['findings'] if f['state'] == 'verified'
              and f.get('evidence_verified') and f['data_revision'] == report['data_revision']]
    groups = {tuple(sorted(f['customer_ids'])): f for f in active}
    tp, unmatched = [], []
    for customers, finding in groups.items():
        if customers in expected_groups:
            tp.append(expected_groups[customers]['id'])
        else:
            unmatched.append(dict(customer_ids=list(customers), finding_id=finding['finding_id']))
    missed = [issue['id'] for customers, issue in expected_groups.items() if customers not in groups]
    affected = set().union(*(set(group) for group in expected_groups))
    found_customers = set().union(*(set(group) for group in groups)) if groups else set()
    financial_checks, mismatches = 0, []
    requests, outcomes = {}, {}
    all_requests = []
    for event in events:
        event_type = event['type']; payload = event['payload']; correlation = event.get('correlation_id')
        if event_type == 'tool.requested':
            if correlation in requests:
                mismatches.append(dict(event=event['sequence'], error='Duplicate tool call ID'))
            requests[correlation] = payload
            all_requests.append(event)
        if event_type in ('tool.completed', 'tool.failed'):
            outcomes[correlation] = event
        batch = []
        if event_type == 'screening.completed':
            batch = payload.get('comparisons', [])
        elif event_type == 'tool.completed' and payload.get('tool') == 'get_customer_evidence':
            batch = [case['comparison'] for case in payload['result']['cases']]
        for comparison in batch:
            financial_checks += 1
            cid = comparison.get('customer_id')
            errors = financial_errors(comparison, baseline[cid]) if cid in baseline else {'customer': 'Unknown'}
            if errors:
                mismatches.append(dict(event=event['sequence'], customer_id=cid, errors=errors))
        if event_type != 'tool.completed':
            continue
        tool, result = payload['tool'], payload['result']
        if tool in ('compare_invoices', 'calculate_expected'):
            cid = result.get('customer_id')
            if cid not in baseline:
                mismatches.append(dict(event=event['sequence'], error='Unknown result customer')); continue
            expected = baseline[cid]
            financial_checks += 1
            if tool == 'compare_invoices':
                errors = financial_errors(result, expected)
            elif expected['status'] == 'conflict':
                errors = {} if result.get('status') == 'conflict' and result.get('expected_cad') is None else {'conflict': 'Expected no charge'}
            else:
                errors = {} if result.get('amounts') == expected['amounts'] else {'amounts': 'Mismatch with authoritative calculation'}
            if errors:
                mismatches.append(dict(event=event['sequence'], customer_id=cid, errors=errors))
        if tool == 'summarize_pattern' and result.get('shared_pattern_verified'):
            financial_checks += 1
            selected = [baseline[cid] for cid in result['customer_ids']]
            total = sum((Decimal(row['difference_cad']) for row in selected), Decimal(0))
            if Decimal(result['total_difference_cad']) != total:
                mismatches.append(dict(event=event['sequence'], error='Pattern financial total mismatch'))
    # Validate final stored monetary evidence too, not just the tool stream.
    for finding in active:
        for comparison in finding.get('comparisons', []):
            financial_checks += 1
            cid = comparison['customer_id']
            errors = financial_errors(comparison, baseline[cid]) if cid in baseline else {'customer': 'Unknown'}
            if errors:
                mismatches.append(dict(finding_id=finding['finding_id'], customer_id=cid, errors=errors))
    missing_outcomes = sorted(str(cid) for cid in requests if cid not in outcomes)
    api_events = [e['payload'] for e in events if e['type'] == 'api.completed']
    pricing = events[0]['payload'].get('limits', {}) if events else {}
    usage_cost = None
    if api_events and all(event.get('usage_details_available', False) for event in api_events):
        if cached_price is not None or all(event['cached_input_tokens'] == 0 for event in api_events):
            regular, output = Decimal(pricing['input_usd_per_million']), Decimal(pricing['output_usd_per_million'])
            cached_rate = cached_price if cached_price is not None else regular
            usage_cost = str(sum(((Decimal(e['input_tokens'] - e['cached_input_tokens']) * regular
                                  + Decimal(e['cached_input_tokens']) * cached_rate
                                  + Decimal(e['output_tokens']) * output) / 1_000_000 for e in api_events), Decimal(0)))
    contracts, amendments, invoices = load_records(data)
    document_ids = {c['contract_id'] for c in contracts} | {a['amendment_id'] for a in amendments}
    retrieved_documents, retrieved_invoices = set(), set()
    for event in events:
        if event['type'] == 'evidence.updated':
            retrieved_documents.clear()
            retrieved_invoices.clear()
        payload = event['payload']
        if event['type'] != 'tool.completed':
            continue
        if payload['tool'] == 'get_customer_evidence':
            for case in payload['result']['cases']:
                # Reference-only repeats do not establish new source retrieval.
                retrieved_documents.update(doc['document_id'] for doc in case['documents'] if 'text' in doc)
                retrieved_invoices.update(row['invoice_id'] for row in case['invoices'])
        if payload['tool'] == 'get_document':
            retrieved_documents.add(payload['result']['document_id'])
        if payload['tool'] == 'get_invoices':
            retrieved_invoices.update(row['invoice_id'] for row in payload['result'])
    evidence_errors = []
    for finding in active:
        customers = set(finding['customer_ids'])
        required = ({c['contract_id'] for c in contracts if c['customer_id'] in customers}
                    | {a['amendment_id'] for a in amendments if a['customer_id'] in customers}
                    | {i['invoice_id'] for i in invoices if i['customer_id'] in customers and i['period'] == report['period']})
        cited = set(finding.get('evidence_ids', []))
        compared_ids = {c['customer_id'] for c in finding.get('comparisons', [])}
        if (cited != required or not (required & document_ids) <= retrieved_documents
                or not (required - document_ids) <= retrieved_invoices or compared_ids != customers):
            evidence_errors.append(dict(finding_id=finding['finding_id'], error='Missing/unretrieved/unrelated citations or comparisons'))
    reviews = report.get('reviews', [])
    return dict(run_id=report['run_id'], status=report['status'], completion_reason=report['reason'],
                scoring='Exact customer-set anomaly detection; causal labels are not machine-verifiable in the current finding schema',
                true_positives=len(tp), matched_anomalies=sorted(tp),
                false_positive_groups=len(unmatched), unmatched_groups=unmatched,
                false_positive_customers=sorted(found_customers - affected),
                missed_anomalies=missed, affected_customer_coverage=len(found_customers & affected),
                negative_control_flagged=key['negative_control']['customer'] in found_customers,
                financial_checks=financial_checks, financial_mismatches=mismatches,
                financial_accuracy_passed=financial_checks > 0 and not mismatches,
                evidence_errors=evidence_errors, evidence_verification_passed=bool(active) and not evidence_errors,
                human_escalations=reviews,
                metrics=report['metrics'], completed_model_calls=len(api_events),
                tool_call_counts=dict(Counter(e['payload']['tool'] for e in all_requests)),
                operational_failures=[e for e in events if e['type'] in ('api.failed', 'tool.failed', 'investigation.error')],
                missing_tool_outcomes=missing_outcomes,
                usage_priced_cost_usd=usage_cost, actual_billed_cost_usd=None,
                cost_note='Usage-priced amount uses supplied rates and actual token counters; reconcile against OpenAI billing. Not an invoice.',
                event_log_inspected=True, evaluation_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[1] / 'contract_to_cash/data')
    parser.add_argument('--runs', type=Path, nargs='+', required=True)
    parser.add_argument('--cached-input-price-per-million', type=Decimal)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    price = args.cached_input_price_per_million
    if price is not None and (not price.is_finite() or price < 0):
        parser.error('Cached input price must be finite and nonnegative')
    if args.output.exists():
        parser.error('Choose a new evaluation output path')
    result = dict(runs=[evaluate(run, args.data, price) for run in args.runs])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
