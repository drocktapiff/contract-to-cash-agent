# Phase 2: model-directed investigation backend

Phase 2.6 adds efficient structured screening and bundled evidence retrieval.
See [the design, offline validation and proposed live commands](../../docs/PHASE26.md).
No Phase 2.6 live performance result is claimed.

This is a Python CLI using OpenAI Responses API function calling. The model
chooses the next tool and customers; no anomaly IDs, findings or prescribed
investigation sequence are in its instructions. The existing complete
`investigate()` batch result is never called or exposed by the agent.
The agent CLI has no deployment, billing connector, or billing mutation.
An optional local React/FastAPI operations console is documented in
[Phase 3](../../docs/PHASE3.md); its adapter is excluded from the model runtime bundle.

## Install and isolate the runtime

From the repository root, with Python 3.10+:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-agent.txt
python -m unittest discover -s contract_to_cash/tests -v
python -m scripts.build_agent_runtime ./agent-runtime
cd agent-runtime
```

The builder requires a new destination and never merges or overwrites a directory.
It copies an explicit allowlist: agent code, the unchanged billing engine, three
public record files, the integrity manifest and its public documents. It excludes
the sealed key, fixture generator, tests, README outcome descriptions and operator
prompts. No Git worktree is needed. Source assets are unchanged.

Run from this bundle so the key and evaluation code are absent from the runtime
working directory. The run CLI rejects data directories containing the sealed
key. The model has only the twelve tools below, with no shell, file-search, arbitrary
path, network or code-execution tool. This is a model/tool access boundary, not an
OS sandbox protecting files from a human running arbitrary Python on the host.

## Credentials and a real investigation

Set `OPENAI_API_KEY` securely in your shell or secret manager. For example, in Bash:

```bash
read -rsp 'OpenAI API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
```

No credential file is required. `.env` files are ignored, but not automatically
loaded. Never commit keys. A managed proxy binding may instead use
`CONTRACT_AGENT_API_KEY`, sent only to `https://api.openai.com/v1`.
The CLI fixes the official API base URL and disables automatic retries.
Allow HTTPS egress to `api.openai.com`; pip installation also needs its package
registries. The environment now provides `OPENAI_API_KEY`; model listing succeeds, but both
the bounded pilot and a minimal Responses diagnostic returned HTTP 401
`invalid_api_key`. See [the live validation status](../../docs/LIVE_VALIDATION.md).

Select an available function-calling model and enter its **current USD token
prices per million**. Prices are explicit inputs, not hardcoded claims:

```bash
read -rp 'Model ID: ' AGENT_MODEL
read -rp 'Input USD per million tokens: ' AGENT_INPUT_PRICE
read -rp 'Output USD per million tokens: ' AGENT_OUTPUT_PRICE
python -m contract_to_cash.agent run \
  --model "$AGENT_MODEL" \
  --input-price-per-million "$AGENT_INPUT_PRICE" \
  --output-price-per-million "$AGENT_OUTPUT_PRICE" \
  --period 2026-04 \
  --max-tool-calls 500 --max-responses 600 --max-seconds 900 --max-cost-usd 5 \
  --output runs/first-live
```

Choose a fresh output directory for each run. stdout streams actual JSON events
as they occur, not fabricated progress or hidden model reasoning. stderr gives
the final report path. Exit status is 0 for completed/verified scope, 1 for an
incomplete investigation, and 2 for configuration/CLI errors.

A custom `--objective` controls the investigation objective. Phase 2 completion
currently requires coverage of the whole selected public dataset for the selected
period, even if the objective asks for a smaller subset. Use a separately scoped
public dataset for a smaller audit; no customer filter is silently inferred.

## Tools and authority

All schemas use strict function calling, required properties, and
`additionalProperties: false`; JSON Schema validation also runs locally. Duplicate
IDs/JSON keys are rejected server-side. Dispatch uses an explicit mapping.

| Tool | Inputs | Behavior |
|---|---|---|
| `screen_customers` | none | Screen structured records using authoritative comparisons; compact candidates, clean IDs and unassessed IDs; never source verification or legal conclusions |
| `get_customer_evidence` | up to ten selected customer IDs | Retrieve selected records, original contract and all amendment sources, invoices and comparisons; reuse current-revision evidence |
| `list_customers` | none | Public customer inventory, no anomaly results |
| `get_contract` | customer ID | Structured authoritative contract |
| `get_amendments` | customer ID | All amendments, including contrary/future evidence |
| `get_invoices` | customer ID | This audit period's invoice records |
| `get_document` | document ID | Exact allowlisted, SHA-256 verified source text |
| `calculate_expected` | customer ID | Existing calculator with recorded quantities |
| `compare_invoices` | customer ID | Deterministic comparison of the selected account |
| `summarize_pattern` | selected customer IDs | Aggregate already compared accounts |
| `submit_finding` | customer IDs, evidence IDs, state, rationale | Propose, verify or retract an evidence-linked finding |
| `request_human_review` | finding ID, review/export | Queue local human review; never approve |

There are no model-supplied amount, currency, price, quantity, executable code or
file path arguments. Financial fields and totals come from authoritative records
and deterministic calculation. Free-text `model_hypothesis` is explicitly a model
claim, not a validated financial assertion. Final model prose is not published as
authoritative findings; the persisted report is built from server-validated tools.

Verification requires prior comparison, retrieved invoices, original contract
text and all amendment text. Citations must belong to those customers. Clean
comparisons cannot become verified discrepancy findings. Signed-term conflicts
immediately create a **deterministic guard** proposal and human-review request,
clearly attributed as tool actions rather than model discoveries. Their amount
remains unknown. Model verification then requires sources as for any other case.

Shared-pattern verification requires at least three selected accounts with the
same template and nonzero discrepancy. That is correlation, not proof of root
cause. The server does not force the model to discover a pattern or achieve a
known finding count. Separate evaluation remains responsible for measuring recall.

## Events, results, metrics and completion

Every event includes `schema_version`, `event_id`, `run_id`, monotonic `sequence`,
UTC `timestamp`, `type`, `actor`, `correlation_id`, and `payload`. Tool request and
completion/failure use the actual API `call_id`. No reasoning items are logged.

Core types are `investigation.started`, `investigation.completed` (with explicit
completed/incomplete status), `tool.requested`, `tool.completed`, `tool.failed`,
`evidence.retrieved`, `evidence.updated`, `finding.proposed`, `finding.verified`,
`finding.retracted`, `human_review.requested`, and `human_review.decided`.
Additional API/error events expose counts and error classes, not provider error
bodies or credentials. JSONL is ready for a later SSE adapter; no HTTP server is
implemented in Phase 2.

Independent calls may share a Responses exchange; execution and budget checks remain
serial. Full results stay in the event log; repeated finding/pattern data is omitted
from compact model acknowledgments. Reports checkpoint after each executed tool.
`--cached-input-price-per-million` optionally records usage-priced cost separately
from the conservative full-input budget estimate; neither is an actual bill.

Each run writes:

- `events.sqlite3`: authoritative append-only event journal and local decisions.
- `events.jsonl`: JSON event stream for inspection or later UI replay.
- `report.json`: current investigation result, findings, review queue and metrics.
- Human decisions and approved export packages, when explicitly requested later.

Metrics include elapsed duration, agent tool calls, API requests, input/output
tokens, estimated API cost, tool failures, review requests and human interventions.
Human interventions start at zero and increase only through the separate local
operator command. Verified financial discrepancies are deduplicated per customer
in report totals, even if individual/group findings overlap. Potential receivables
and credits remain separate; conflicts and duplicates are not assigned invented
payable amounts. Proposed/retracted/outdated findings contribute no validated sum.

A completed run means all customers were compared, all nonclean results are
covered by source-verified findings and every verified finding has a current
pending human-review request. It does not imply approval, collection, proven root
causes, or perfect recall against the evaluation key. Any tool failure makes the
run incomplete, even if later corrected; retained findings remain available.

Budgets bound tool attempts and response counts, and check elapsed time between
steps. API timeouts are capped by the remaining duration (at most 60 seconds per
request). These are cooperative limits, not a process-killing hard deadline.
The preflight cost reserve uses a conservative byte-based input estimate and the
output-token cap. Actual token usage updates the estimate, including reported
reasoning tokens. Cached-input discounts are not assumed. This is **not a provider
billing guarantee**: token estimates, chosen rates and failed-request billing may
differ; unknown usage is labeled incomplete. No automatic retries can conceal
extra requests. Context-window growth or provider errors end the run honestly.

## Human review/export

The model may only request review. An operator uses a separate command:

```bash
python -m contract_to_cash.agent review \
  --run runs/first-live \
  --finding-id FINDING_ID_FROM_REPORT \
  --decision approved \
  --reviewer 'Operator name'
```

Decisions are `approved`, `rejected`, or `needs_information`. Approval covers only
the exact finding version and data revision. If the pending action was `export`,
an approved decision writes a JSON evidence package. No other execution occurs.
An unresolved contract conflict can be acknowledged/reviewed without deciding its
correct charge. Duplicate decisions are rejected. This is a single-operator local
prototype with a self-declared reviewer name, not production authentication or a
multiuser approval service. Complete the investigation before using review CLI.

## Genuine evidence updates

`--watch-data` reloads validated public snapshots at response boundaries. An
operator may replace public records/documents with genuinely updated evidence;
changed document bytes require a matching integrity manifest. Publish a stable,
complete snapshot rather than editing multiple files while they are being read.
Inconsistent/tampered snapshots stop the affected run instead of being accepted.

Only a detected content revision emits `evidence.updated`. It clears comparisons,
invalidates verification/reviews, and informs the model of the real change. The
model then chooses how to investigate again and whether to retract a finding.
There is no timed update, planted wrong answer, or automatic model retraction.
The unit test demonstrates this using a real invoice update with a simulated model
interaction; it is not a claim of live API behavior. Updates received during a
request are seen before the next request and rechecked before final completion.

## Validation and current limitations

```bash
# From the repository root with agent dependencies installed:
python -m unittest discover -s contract_to_cash/tests -v
python -m contract_to_cash.billing_engine
python -m pip check
```

Tests exercise actual local tools and use explicitly simulated Responses replies.
An additional SDK MockTransport test verifies real SDK request serialization and
function-call continuation without a network request or credential. Neither is a
live OpenAI run. No model accuracy or successful investigation benchmark is claimed. The first
credentialed pilot failed before tools ran; its authentication failure and timing
are documented separately from the simulated tests.

The Phase 1 monthly CAD scope still applies. Structured records are calculation
authority; text supports citations and model investigation, not automatic legal
extraction. Duplicate cases do not resolve which invoice is payable; missing
usage quantities cannot be inferred. There is no HTTP/SSE server, resume after
process restart, background worker, frontend, or deployment. Local files are not
an adversarial multiuser security boundary. Evaluation-only answer keys remain
outside the model runtime.

## Official implementation references

Verified against current official OpenAI sources during implementation:

- [OpenAI Python SDK: Responses is the primary API](https://github.com/openai/openai-python#usage)
- [OpenAI cookbook: function-call continuation with call IDs](https://github.com/openai/openai-cookbook/blob/main/examples/reasoning_function_calls.ipynb)
- [Official Responses request definitions](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_create_params.py)

The implementation uses `store=False`, retains API output items privately for
stateless continuation, and requests `reasoning.encrypted_content` so reasoning
models can continue without exposing hidden reasoning. The official definitions
confirm that the output-token cap includes reasoning tokens. The documentation website became accessible after network configuration; the
current catalog and prices are recorded in the live validation guide. Official
GitHub sources also supplied SDK and request-format references. The CLI requires a model ID instead of assuming one is available
to your account, and explicit current token prices instead of silently guessing.

## Phase 2.5 live validation

See [the live validation guide](../../docs/LIVE_VALIDATION.md) for Windows/Git Bash
setup, bounded pilot and three-run commands, secure API access, and separate
answer-key evaluation. API telemetry now includes cached-input and reasoning-token
counts; actual billed cost is never inferred from the conservative budget estimate.
