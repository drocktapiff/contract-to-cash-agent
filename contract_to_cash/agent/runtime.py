"""Bounded Responses API loop. Model output selects tools, never authoritative money."""
from dataclasses import dataclass
from decimal import Decimal
import json
import math
from pathlib import Path
import time

from .tools import TOOLS, ToolError


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ToolError('Duplicate JSON argument keys are not permitted')
        result[key] = value
    return result


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = 500
    max_seconds: float = 900
    max_cost_usd: Decimal = Decimal('5')
    input_usd_per_million: Decimal = Decimal('1')
    output_usd_per_million: Decimal = Decimal('4')
    max_output_tokens: int = 4096
    max_responses: int = 600
    cached_input_usd_per_million: Decimal | None = None
    service_tier: str | None = None

    def __post_init__(self):
        if (type(self.max_tool_calls) is not int or self.max_tool_calls < 1
                or type(self.max_responses) is not int or self.max_responses < 1
                or type(self.max_output_tokens) is not int or self.max_output_tokens < 1
                or not math.isfinite(self.max_seconds) or self.max_seconds <= 0):
            raise ValueError('Run limits must be positive and finite')
        for rate in (self.max_cost_usd, self.input_usd_per_million, self.output_usd_per_million):
            if not isinstance(rate, Decimal) or not rate.is_finite() or rate <= 0:
                raise ValueError('Budget and token prices must be positive finite Decimals')

        if self.service_tier not in (None, "default"):
            raise ValueError("Only the explicitly priced default service tier is supported")
        cached = self.cached_input_usd_per_million
        if cached is not None and (not isinstance(cached, Decimal) or not cached.is_finite()
                                   or cached < 0 or cached > self.input_usd_per_million):
            raise ValueError('Cached token price must be finite, nonnegative, and no greater than input price')


def model_result(name, result):
    """Avoid re-sending full persisted findings/comparisons; never trim source documents."""
    if name == 'submit_finding' and 'error' not in result:
        keys = ('finding_id', 'customer_ids', 'version', 'state', 'evidence_verified', 'evidence_ids',
                'data_revision', 'model_hypothesis')
        return {key: result[key] for key in keys}
    if name == 'summarize_pattern' and 'error' not in result:
        return {key: value for key, value in result.items() if key != 'comparisons'}
    return result


class Investigator:
    def __init__(self, client, model, tools, journal, limits, watch_data=False, clock=time.monotonic):
        self.client, self.model, self.tools, self.journal = client, model, tools, journal
        self.limits, self.watch_data, self.clock = limits, watch_data, clock

    def run(self, objective):
        start = self.clock()
        calls = responses = failures = input_tokens = output_tokens = 0
        cached_input_tokens = reasoning_output_tokens = 0
        cost = Decimal(0)
        cost_complete = True
        cache_details_complete = True
        reason = 'response_limit'
        instructions = Path(__file__).with_name('INSTRUCTIONS.md').read_text(encoding='utf-8')
        history = [dict(role='user', content=f'Audit period: {self.tools.data.period}\nObjective: {objective}')]
        self.journal.emit('investigation.started', objective=objective, model=self.model,
                          period=self.tools.data.period, data_revision=self.tools.data.revision,
                          limits={k: str(v) if isinstance(v, Decimal) else v for k, v in vars(self.limits).items()})

        def persist(reason):
            compared = set(self.tools.comparisons)
            verified = [f for f in self.tools.findings.values() if f['state'] == 'verified'
                        and f['data_revision'] == self.tools.data.revision]
            covered = {cid for f in verified for cid in f['customer_ids']}
            anomalies = {cid for cid, r in self.tools.comparisons.items() if r['status'] != 'clean'}
            review_required = {f['finding_id'] for f in verified}
            reviews_pending = {fid for fid, r in self.tools.reviews.items() if r['status'] == 'pending'
                               and r['finding_version'] == self.tools.findings[fid]['version']}
            complete = (reason == 'model_finished' and not failures
                        and compared == set(self.tools.data.customers) and anomalies <= covered
                        and review_required <= reviews_pending)
            if reason == 'model_finished' and not complete:
                reason = 'coverage_evidence_or_review_incomplete' if not failures else 'tool_failures'
            validated = {cid: self.tools.comparisons[cid] for cid in covered}
            amounts = [Decimal(r['difference_cad']) for r in validated.values() if r['status'] == 'discrepancy']
            totals = dict(additional_receivables_cad=str(sum((v for v in amounts if v > 0), Decimal('0.00'))),
                          potential_credits_cad=str(-sum((v for v in amounts if v < 0), Decimal('0.00'))),
                          disclaimer='Potential differences only; no cash recovered and no billing records changed')
            report = dict(run_id=self.journal.run_id, journal_sequence=self.journal.sequence, status='completed' if complete else 'incomplete', reason=reason,
                          period=self.tools.data.period, data_revision=self.tools.data.revision,
                          customers_compared=sorted(compared),
                          screening_complete=compared == set(self.tools.data.customers),
                          customers_with_retrieved_documents=sorted({self.tools.data.documents[did]['customer_id']
                              for did in self.tools.documents_seen}),
                          clean_customers=sorted(cid for cid, row in self.tools.comparisons.items() if row['status'] == 'clean'),
                          findings=list(self.tools.findings.values()), reviews=list(self.tools.reviews.values()),
                          validated_financial_discrepancies=validated, financial_totals=totals,
                          metrics=dict(duration_seconds=round(self.clock() - start, 3), agent_tool_calls=calls,
                                       tool_failures=failures, api_requests=responses, human_interventions=0,
                                       human_review_requests=sum(e['type'] == 'human_review.requested' for e in self.journal.events),
                                       input_tokens=input_tokens, output_tokens=output_tokens,
                                       cached_input_tokens=cached_input_tokens, reasoning_output_tokens=reasoning_output_tokens,
                                       actual_billed_cost_usd=None,
                                       usage_priced_cost_usd=str(((Decimal(input_tokens - cached_input_tokens)
                                           * self.limits.input_usd_per_million)
                                           + Decimal(cached_input_tokens) * self.limits.cached_input_usd_per_million
                                           + Decimal(output_tokens) * self.limits.output_usd_per_million) / 1_000_000)
                                           if self.limits.cached_input_usd_per_million is not None
                                           and cache_details_complete and cost_complete else None,
                                       estimated_api_cost_usd=str(cost), cost_accounting_complete=cost_complete))
            self.journal.save_report(report)
            return report

        try:
            while responses < self.limits.max_responses:
                remaining = self.limits.max_seconds - (self.clock() - start)
                if remaining <= 0:
                    reason = 'time_limit'; break
                if calls >= self.limits.max_tool_calls:
                    reason = 'tool_call_limit'; break
                if self.watch_data:
                    update = self.tools.refresh()
                    if update:
                        history.append(dict(role='user', content=json.dumps(update)))
                # Conservative local estimate, not a tokenizer or a provider billing guarantee.
                # A byte per input token plus framing overhead also includes tool definitions.
                estimated_input = len(json.dumps([instructions, history, TOOLS], ensure_ascii=True).encode()) + 4096
                reserve = (Decimal(estimated_input) * self.limits.input_usd_per_million
                           + Decimal(self.limits.max_output_tokens) * self.limits.output_usd_per_million) / 1_000_000
                if cost + reserve > self.limits.max_cost_usd:
                    reason = 'estimated_cost_limit'; break
                responses += 1
                self.journal.emit('api.requested', model=self.model, request_number=responses)
                try:
                    response = self.client.with_options(timeout=min(remaining, 60), max_retries=0).responses.create(
                        model=self.model, instructions=instructions, input=history, tools=TOOLS,
                        parallel_tool_calls=True, max_output_tokens=self.limits.max_output_tokens,
                        store=False, include=['reasoning.encrypted_content'],
                        **({'service_tier': self.limits.service_tier} if self.limits.service_tier else {}))
                    data = response.model_dump(exclude_none=True)
                except Exception as exc:
                    # Never copy provider exception text: it can contain credentials/request content.
                    cost_complete = False
                    self.journal.emit('api.failed', error_type=type(exc).__name__,
                                      http_status=getattr(exc, 'status_code', None),
                                      message='API request failed; no model findings inferred')
                    reason = 'api_failure'; break
                usage = data.get('usage')
                if not usage or not all(type(usage.get(key)) is int and usage[key] >= 0
                                        for key in ('input_tokens', 'output_tokens')):
                    cost_complete = False
                    reason = 'missing_usage'; break
                input_tokens += usage['input_tokens']; output_tokens += usage['output_tokens']
                input_details = usage.get('input_tokens_details') or {}
                output_details = usage.get('output_tokens_details') or {}
                cached = input_details.get('cached_tokens', 0)
                reasoning = output_details.get('reasoning_tokens', 0)
                if (type(cached) is not int or not 0 <= cached <= usage['input_tokens']
                        or type(reasoning) is not int or not 0 <= reasoning <= usage['output_tokens']):
                    cost_complete = False
                    reason = 'invalid_usage_details'; break
                cache_details_complete = cache_details_complete and 'cached_tokens' in input_details
                cached_input_tokens += cached
                reasoning_output_tokens += reasoning
                request_cost = (Decimal(usage['input_tokens']) * self.limits.input_usd_per_million
                                + Decimal(usage['output_tokens']) * self.limits.output_usd_per_million) / 1_000_000
                cost += request_cost
                self.journal.emit('api.completed', response_id=data.get('id'),
                                  model=data.get('model', self.model), service_tier=data.get('service_tier'),
                                  cached_input_tokens=cached, reasoning_output_tokens=reasoning,
                                  usage_details_available='cached_tokens' in input_details,
                                  input_tokens=usage['input_tokens'], output_tokens=usage['output_tokens'],
                                  estimated_cost_usd=str(request_cost))
                if cost > self.limits.max_cost_usd:
                    reason = 'estimated_cost_limit'; break
                if self.clock() - start >= self.limits.max_seconds:
                    reason = 'time_limit'; break
                if data.get('status') != 'completed':
                    reason = 'api_response_incomplete'; break
                output = data.get('output', [])
                # Retain response items for stateless continuation, including encrypted reasoning.
                # Never log or display reasoning content or model final prose as validated findings.
                history.extend(output)
                function_calls = [item for item in output if item.get('type') == 'function_call']
                if not function_calls:
                    reason = 'model_finished'
                    break
                for item in function_calls:
                    if calls >= self.limits.max_tool_calls:
                        reason = 'tool_call_limit'; break
                    if self.clock() - start >= self.limits.max_seconds:
                        reason = 'time_limit'; break
                    calls += 1
                    name, call_id = item.get('name'), item.get('call_id')
                    self.journal.emit('tool.requested', actor='model', correlation_id=call_id, tool=name,
                                      arguments=item.get('arguments'))
                    try:
                        arguments = json.loads(item.get('arguments', ''),
                                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
                                               object_pairs_hook=_json_object)
                        result = self.tools.execute(name, arguments)
                    except Exception as exc:
                        failures += 1
                        result = dict(error='tool_failed', error_type=type(exc).__name__,
                                      message=str(exc) if isinstance(exc, ToolError) else 'Tool failed; affected conclusions are unverified')
                        self.journal.emit('tool.failed', actor='tool', correlation_id=call_id, tool=name, result=result)
                    else:
                        self.journal.emit('tool.completed', actor='tool', correlation_id=call_id, tool=name, result=result)
                    history.append(dict(type='function_call_output', call_id=call_id,
                                        output=json.dumps(model_result(name, result), allow_nan=False, separators=(',', ':'))))
                    persist('in_progress')
                if reason in ('tool_call_limit', 'time_limit'):
                    break
        except Exception as exc:
            reason = 'runtime_failure'
            self.journal.emit('investigation.error', error_type=type(exc).__name__,
                              message='Investigation interrupted; retained findings require review')
        # Detect last-minute operator edits before accepting a final result.
        if self.watch_data:
            try:
                if self.tools.refresh():
                    reason = 'evidence_changed_at_completion'
            except Exception:
                reason = 'invalid_evidence_update'
        report = persist(reason)
        self.journal.emit('investigation.completed', status=report['status'], reason=report['reason'], metrics=report['metrics'])
        return report
