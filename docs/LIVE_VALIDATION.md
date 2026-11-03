# Phase 2.5: live agent validation

## Current status

Live validation is **blocked by Responses authentication**, not passed.
`OPENAI_API_KEY` is configured, network access is enabled, and authenticated model
listing succeeds. The first bounded investigation using `gpt-6.1-sol` failed on
its first Responses request with HTTP 401, before any tool ran. It lasted 0.748
seconds and produced no findings or review requests. Token usage was not returned;
the recorded zero estimated cost has incomplete accounting and is not a billing
confirmation. The three full investigations have not run.

A subsequent diagnostic made exactly one no-tools Responses request with the
same model and a 16-token output limit. Model listing again succeeded, while
Responses returned this sanitized error:

```json
{
  "type": "invalid_request_error",
  "code": "invalid_api_key",
  "message": "Incorrect API key provided: [REDACTED_API_KEY] You can find your API key at https://platform.openai.com/account/api-keys.",
  "param": null
}
```

Both endpoints used the same `OPENAI_API_KEY`, SDK authorization configuration,
and `https://api.openai.com/v1/` base URL. Organization and project were not
explicitly configured. The application does not override authentication headers
or these environment variables. The error identifies invalid authentication,
not an explicit endpoint-permission or project-mismatch error; its precise cause
remains unresolved. Verify or replace the securely configured API project key.
If a managed proxy injects credentials, verify that injection applies to
`POST /v1/responses` as well as `GET /v1/models`. Do not paste keys into chat.

No architecture changes or full investigation retries followed the diagnostic.
Only this sanitized summary is published; raw logs and runtime bundles remain
ignored. See [the machine-readable status](phase25-status.json). The commands
below are for use after authentication is corrected, not evidence of successful
live validation.

The smallest execution path is the existing CLI in an allowlisted runtime bundle.
It preserves all 40 customers and the original data bytes. The pilot uses a small
call/time/cost budget on that same dataset; no favorable sample is curated.
Three full runs then start separate conversations under identical settings.

## Official model/API verification

The official model catalog was accessed after network configuration and recommends
GPT-6.1 Sol for balancing intelligence and cost. `gpt-6.1-sol` was available to the
configured key through model listing. Official standard pricing at validation was
USD 2 per million input tokens, USD 10 per million output tokens, and USD 0.10
per million cached-input tokens. Availability through model listing does not
establish permission to create Responses, as the diagnostic demonstrates.
Recheck model availability and prices before a future trial:

- https://developers.openai.com/api/docs/models
- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.openai.com/api/docs/pricing

Use an available tool-calling model, preferably an explicit snapshot when the
catalog offers one. Keep the exact same model, prices and limits across all three
full runs. Do not silently switch models between trials.

The existing implementation is consistent with official sources:

- `client.responses.create` with strict function schemas;
- actual `function_call` outputs followed by matching `function_call_output` IDs;
- explicit ten-tool dispatch, no batch audit, shell, search or arbitrary files;
- `store=False` and private stateless continuation, including encrypted reasoning;
- no hidden reasoning in the event log, no automatic request retries.

See the [official Responses request definitions](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_create_params.py)
and [official function-calling example](https://github.com/openai/openai-cookbook/blob/main/examples/reasoning_function_calls.ipynb).
No optional reasoning/temperature setting is guessed for an unverified model.

## Windows + Git Bash

Install Python 3.12 from python.org and Git for Windows. Open Git Bash and enter
your checkout. Commands below run in Git Bash, not PowerShell:

```bash
cd /c/path/to/contract-to-cash-agent
py -3.12 -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements-agent.txt
python -m unittest discover -s contract_to_cash/tests -v
python -m scripts.build_agent_runtime ./agent-runtime-validation
cd agent-runtime-validation
```

Use a new runtime directory; the builder deliberately refuses to overwrite one.
On Linux/cloud use `python -m venv .venv` and `source .venv/bin/activate` instead.
The bundle excludes evaluation code, the answer key, outcome descriptions and
fixture generation. Do not copy the evaluation key into this directory.

Enter the credential without echoing it:

```bash
read -rsp 'OpenAI API key: ' OPENAI_API_KEY
printf '\n'
export OPENAI_API_KEY
```

Do not use `set -x`, `env`, `printenv`, or key-bearing command arguments. Do not
commit credentials. A ChatGPT subscription does not establish API project access;
use an API project with billing and model access configured. Managed-cloud proxy
bindings in this environment use `OPENAI_API_KEY`. The implementation retains a
legacy `CONTRACT_AGENT_API_KEY` fallback, but it was not selected in these trials.

Read current model and standard text token prices from the official catalog and
pricing pages. These are non-secret configuration values:

```bash
read -rp 'Verified model or snapshot ID: ' AGENT_MODEL
read -rp 'Input USD per million tokens: ' AGENT_INPUT_PRICE
read -rp 'Cached input USD per million tokens: ' AGENT_CACHED_PRICE
read -rp 'Output USD per million tokens: ' AGENT_OUTPUT_PRICE
```

Do not run until these values are known. The CLI uses the official
`https://api.openai.com/v1` endpoint. No `.env` file or credential logging is needed.

### Pilot: small, bounded live investigation

```bash
python -m contract_to_cash.agent run \
  --model "$AGENT_MODEL" \
  --input-price-per-million "$AGENT_INPUT_PRICE" \
  --output-price-per-million "$AGENT_OUTPUT_PRICE" \
  --max-tool-calls 35 --max-responses 40 --max-seconds 180 --max-cost-usd 1 \
  --objective 'Investigate a small sample of your choosing. Use authoritative calculations, challenge potential findings with documents, and submit evidence-backed findings for human review when justified. Do not change billing.' \
  --output runs/pilot
```

The original 40-customer scope is preserved. The pilot may intentionally finish
with `incomplete` because the backend requires full coverage for completion; that
is not a claim that the whole dataset was audited. A budget stop is a measured
outcome, not permission to increase the spend automatically. If no finding fits
within these limits, record that result and diagnose latency/call cost before
spending on the full runs.

Inspect **all** `runs/pilot/events.jsonl` exchanges and `report.json`. Before full
runs, require successful API responses and real model-selected function calls,
correct deterministic financial results, at least one source-verified submission,
and no unexplained tool/API failures. Do not infer model autonomy from a unit test.
The backend returns 1 for incomplete, 2 for configuration error, 0 for completion.

### Three independent full runs

Only after the pilot is understood:

```bash
for trial in 1 2 3; do
  python -m contract_to_cash.agent run \
    --model "$AGENT_MODEL" \
    --input-price-per-million "$AGENT_INPUT_PRICE" \
    --output-price-per-million "$AGENT_OUTPUT_PRICE" \
    --max-tool-calls 500 --max-responses 600 --max-seconds 900 --max-cost-usd 5 \
    --output "runs/full-$trial"
  trial_status=$?
  printf 'Trial %s exit status: %s\n' "$trial" "$trial_status"
  if [ "$trial_status" -eq 2 ]; then break; fi
 done
```

The stated caps total USD 16 including the pilot. These are estimated cooperative
budgets, not a provider-enforced billing ceiling. Long growing conversations can
reach the cap before full coverage. Record partial runs rather than fabricating
success. If the pilot fails, do not launch this loop blindly. No human approval,
evidence-update injection or dataset modification is performed during these trials.

## Separate offline evaluation

After the live processes exit, return to the repository root. Only this separate,
non-network evaluation process reads the key:

```bash
cd ..
python -m scripts.evaluate_agent_runs \
  --runs agent-runtime-validation/runs/full-1 \
         agent-runtime-validation/runs/full-2 \
         agent-runtime-validation/runs/full-3 \
  --cached-input-price-per-million "$AGENT_CACHED_PRICE" \
  --output runs/phase25-evaluation.json
```

The evaluator is not copied into the runtime and never sends anything to OpenAI.
It reports, per run:

- True positives and missed anomalies using exact customer-group matching.
- Unmatched/false-positive groups separately from genuinely false-positive customers.
  Fragmented systemic findings count as missed group detection, even if individual
  customers were found. Overlapping groups are not silently credited twice.
- Negative-control flags, comparison checks and financial mismatches.
- Evidence/citation checks against retrieved documents and invoice results.
- Escalations, duration, API calls, tool-call counts, failures and missing outcomes.
- Usage-priced cost from actual counters and the supplied current token rates.

The current finding schema has no structured root-cause classification. Therefore
exact group detection is scored; labels such as expired discount/missed uplift
require separate human assessment of the cited hypothesis. The evaluator does not
pretend free text is a validated classification. Adding a validated classification
field would be a separate small correction if the live results justify it.

The financial checker recomputes expected amounts through the authoritative billing
engine, independently of the agent's orchestration/tools. It is not an independent
financial implementation; the existing handwritten Phase 1 arithmetic tests supply
that complementary check. Financial correctness and detection accuracy remain
separate: a verified discrepancy can be correctly calculated yet incompletely
explained by the model.

## Cost and evidence standards

Telemetry now preserves cached-input and reasoning-token counts, the returned model
ID and service tier. The existing conservative budget estimate remains unchanged.
`usage_priced_cost_usd` uses actual returned token usage with supplied rates; it is
not a guessed token count. `actual_billed_cost_usd` remains null until reconciled
with the OpenAI project's billing/cost records. Failed requests may lack usage.
Do not present a conservative full-input estimate as actual billed cost. Pricing
must match the returned model/service tier; no cache discount or promotional credit
is invented. API project billing is the authority for actual charges.

Retain every trial's original report, SQLite journal and JSONL log. Attribute
conflict-guard events to deterministic code, not model discoveries. No automatic
correction, prompt tuning or rerun replaces an unsuccessful trial in the results.
If a correction is needed, report the failure, implement the smallest approved
change, and identify subsequent runs as a new version.

A credible demonstration needs reproducible full coverage, zero false-positive
customers, correct financial values, sourced findings, appropriate conflict review,
and tolerable runtime/cost in all three trials. Until the actual trials execute,
accuracy, reliability and readiness for the executive demonstration are unknown.
Phase 3 is not started.
