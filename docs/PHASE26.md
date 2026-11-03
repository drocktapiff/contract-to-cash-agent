# Phase 2.6: investigation efficiency

Implemented changes are offline-tested only. No paid Responses requests or new live
investigation were run for this change. Model effectiveness, eight-group recall,
negative-control performance and the 2–3 minute target require an approved live run.
The financial engine, original records, source documents and sealed key are unchanged.

## Diagnosis

The user-supplied successful baseline reports 35 tools / 35 Responses requests,
69.128 seconds, 148,734 input tokens (142,243 cached), 775 output tokens, zero tool
failures, and no completed verified findings. That successful run's artifacts are
not present in this checkout, so these numbers are supplied observations, not
independently re-evaluated logs. Source inspection establishes the following:

- `parallel_tool_calls=False` restricted the model to one tool per round trip.
  At the supplied baseline this averaged about 1.98 seconds per request, including
  API and local work. Conflating tool count with round trips hid the main bottleneck.
- Each customer involved separate contract, amendments, invoices and source-document
  calls. A separate `calculate_expected` immediately before `compare_invoices`
  repeated the same authoritative calculation: comparison already calls calculation.
- Each full comparison carries period, currency, revision, template and evidence IDs.
  Pattern results and submitted findings repeat those full comparisons. Serial
  granular retrieval followed by repeated summaries grew the stateless input history.
- Prompt caching was effective: 95.64% of reported input was cached. It reduces
  usage-priced cost, not the number of tool/API exchanges. The existing budget
  estimate deliberately charges all input at the regular rate. At the repository's
  previously supplied rates of $2 regular input, $0.10 cached input, $10 output per
  million, the baseline's conservative estimate is $0.305218; cache-aware token
  pricing would be $0.0349563. Neither value is a provider invoice or a current price
  verification. Check returned model/service tier and current rates before running.
- Findings were already saved in the journal when submitted and retained on normal
  bounded termination. Full audit completion was never a prerequisite for submission.
  However, the prompt emphasized complete coverage without prioritizing closing each
  investigated finding. Serial evidence gathering consumed the budget before that
  workflow finished. There was no mid-run `report.json` checkpoint.
- Numerical screening and repeated structured lookups need Python, not model reasoning.
  Interpreting contradictory terms, selecting the next useful investigation, judging
  hypotheses and choosing escalation remain model work.

## Updated architecture

All original ten tools remain; two strict-schema, read-only tools are added:

| Capability | Python behavior | OpenAI decision |
| --- | --- | --- |
| `screen_customers()` | Compare every public customer using the original calculator; return compact candidate rows, clean IDs, unassessed IDs. Journal complete calculated comparisons. | Whether/when to screen, candidates or clean controls to investigate, prioritization. |
| `get_customer_evidence(customer_ids)` | Retrieve up to ten selected customers' contract/amendment records, all original signed/unsigned/future/contrary source documents, period invoices and comparison; reuse current-revision comparisons. | Customer selection, interpreting sources, follow-up granular retrieval and contrary-evidence checks. |
| Granular evidence/calculation tools | Same allowlisted records, integrity checks and deterministic arithmetic. | Focused checks and different investigation paths. |
| `summarize_pattern(customer_ids)` | Check selected compared accounts' common template and identical discrepancy; calculate the aggregate. | Which accounts to group; whether correlation supports a causal hypothesis. |
| `submit_finding(...)` | Enforce retrieved sources and invoices, linked citations and revision; attach deterministic amounts; reject clean verified discrepancies. | Propose, verify, revise or retract; rationale and group boundaries. |
| `request_human_review(...)` | Persist a local request only; no approval or billing writes. Conflicts also retain the existing explicitly attributed deterministic guard. | Which model findings to escalate, review versus export. Unresolved conflicts cannot be silently ignored for completion. |

Screening produces no verified findings, legal labels or root-cause determinations.
It does not invoke the old `investigate()` batch audit, load the answer key, select
an investigation order or automatically submit discrepancy findings. Its sole
finding side effect is the pre-existing mandatory signed-conflict guard, attributed
to Python, not the model. Missing usage quantities are reported as unassessed and
prevent full screening/completion; they are never guessed.

Evidence retrieval bundles the sources a selected case requires, including contrary
terms. It cannot bypass source verification. Repeat requests reference already
retrieved documents in the same revision; full text remains in conversation history
and `get_document` can reread it. Existing operator evidence updates clear comparison
and evidence caches and invalidate findings/reviews. No update or retraction is
fabricated for demonstration.

The Responses loop now permits multiple independent function calls per response.
Each executes **serially**, with its original call ID, schema validation, event log,
error handling and individual tool/time budget checks. Dependency-bearing calls
must wait for earlier results; the prompt states this. There are no parallel SQLite
writers or background workers. The model remains free to use granular tools only.

The runtime sends compact finding acknowledgments and pattern summaries to OpenAI,
while retaining complete tool results/findings in the journal. JSON tool results
omit formatting whitespace. Source text is never summarized or silently truncated.
The growing stateless history and encrypted continuation remain intact for caching
and traceability; there is no lossy conversation compaction or hidden memory layer.

After every executed tool, an atomic `report.json` checkpoint contains current
verified findings, reviews and deduplicated financial totals, with `in_progress`
and incomplete status. Normal termination produces the final report. Abrupt process
exit may leave the most recent checkpoint; journal events remain authoritative and
there is still no automatic restart/resume. Verified financial values remain useful
even if full coverage or review completion is pending. Pending review is not approval.

The optional cached-input CLI rate adds `usage_priced_cost_usd`, using returned token
counters only. Missing cache detail, missing usage or failed API requests leaves that
value unknown. `estimated_api_cost_usd` and the budget reserve remain conservative
full-input estimates. Reasoning tokens are a subset of output and are not charged
again. `actual_billed_cost_usd` stays null. Supplied rates must match the returned
model and service tier; there is no billing reconciliation in this repository.

The separate evaluator now checks screening comparisons, bundled comparisons and
bundled source citations, and discards old retrieved-evidence credit after a real
`evidence.updated`. Evaluation/key access still happens only after execution and is
not part of the runtime bundle.

## Validation and performance expectations

The baseline 65 tests are retained (the tool allowlist and parallel-call expectation
are updated). Twelve new offline tests cover screening parity, clean controls,
missing usage, no key reads or dataset writes, bounded multi-customer retrieval,
contrary sources, evidence/calculation reuse, different model-selected orders,
multiple function outputs and budget checks, patterns, escalation, partial reports,
real evidence invalidation/retraction, and cached-token/cost accounting.

A deliberately scripted test interaction—not a live-model benchmark—exercises all
40 comparisons and eight expected groups using 19 tools in six Responses exchanges:
screen, selected evidence bundle, selected pattern, independent submissions,
independent review requests, completion. The separate evaluator checks that test
interaction for financial and evidence correctness. The scripted IDs and expected
groups exist only in tests, never production tools or model instructions.

Expected improvements are fewer retrieval calls, fewer round trips and less repeated
context. The simulation shows the API can carry independent submissions/reviews in
one exchange; it does not prove the model will choose this path, discover every
anomaly or complete within 180 seconds. Larger bundles may increase first-response
input, and a model may still issue redundant calls or fragmented findings. The
conservative reserve may stop early despite effective caching. Causal interpretation
and ambiguous legal terms still require human judgment. Test runtime is not model
latency. Windows/Python 3.13 is not available with the required SDK dependencies here.

Validation command (Linux/Python 3.12.14):

```bash
python -W error::ResourceWarning -m unittest discover -s contract_to_cash/tests -v
python -m pip check
git diff --check
```

Result: **77 tests passed**, no failures or skips. No tests disable cleanup failures.

## Proposed live validation, only after approval

Use the existing secret binding, never a key in a command argument. Verify current
rates independently and set the three non-secret rate variables. Build a new
allowlisted runtime; do not reuse an old bundle or copy the sealed key into it.
These commands are proposals, not executed work:

```bash
# From the repository root with agent dependencies installed:
read -rp 'Current input USD per million: ' AGENT_INPUT_PRICE
read -rp 'Current cached input USD per million: ' AGENT_CACHED_PRICE
read -rp 'Current output USD per million: ' AGENT_OUTPUT_PRICE
python -m scripts.build_agent_runtime ./agent-runtime-phase26-review
cd agent-runtime-phase26-review
python -m contract_to_cash.agent run \
  --model gpt-6.1-sol --period 2026-04 \
  --input-price-per-million "$AGENT_INPUT_PRICE" \
  --cached-input-price-per-million "$AGENT_CACHED_PRICE" \
  --output-price-per-million "$AGENT_OUTPUT_PRICE" \
  --max-tool-calls 35 --max-responses 40 --max-seconds 180 --max-cost-usd 1 \
  --objective 'Investigate contractual billing discrepancies, challenge candidates against all signed terms, examine shared patterns when justified, and persist evidence-backed findings for human review. Do not change billing.' \
  --output runs/phase26-single
# Exit 1 means an incomplete result was preserved; do not automatically rerun.
cd ..
python -m scripts.evaluate_agent_runs \
  --runs agent-runtime-phase26-review/runs/phase26-single \
  --cached-input-price-per-million "$AGENT_CACHED_PRICE" \
  --output runs/phase26-single-evaluation.json
```

For the approved run, compare real customer coverage, independently scored groups,
clean-control flags, financial/citation errors, actual model choices, review queues,
tool/API counts, runtime, returned token/cache counters and both cost estimates.
Inspect actual JSONL and SQLite events. Do not report simulated efficiency as live
accuracy, or conservative estimates as billed cost. Stop after one bounded run.

## Files changed

- `contract_to_cash/agent/tools.py`: screening and selected evidence bundle.
- `contract_to_cash/agent/runtime.py`: independent multi-call responses, compact
  acknowledgments, per-tool report snapshots and optional cache-aware accounting.
- `contract_to_cash/agent/__main__.py`: optional cached-input token price.
- `contract_to_cash/agent/INSTRUCTIONS.md`: efficient tool use and prompt submission.
- `contract_to_cash/agent/README.md`: current tool surface and behavior.
- `contract_to_cash/tests/test_agent.py`: preserve allowlist/protocol assertions.
- `contract_to_cash/tests/test_efficiency.py`: new offline regression coverage.
- `scripts/evaluate_agent_runs.py`: evaluate new calculation and retrieval paths.
- `docs/PHASE26.md`: diagnosis, design, validation, limits and proposed run commands.
