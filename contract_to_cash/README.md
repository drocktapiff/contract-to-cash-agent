# Contract-to-Cash: Foundation and investigation backend

**Demo thesis:** With OpenAI-powered investigations and deterministic billing tools, one human could supervise contract administration **and** billing analysis. Phase 1 provides the tested financial foundation. Phase 2 adds a Responses API investigation backend; live API validation requires credentials.

## What is implemented

- **Synthetic company:** 40 fictional B2B SaaS customers, 40 base contracts, 20 signed amendments (60 text documents), 121 invoice records across February–April 2026.
- **Deterministic billing engine:** Decimal arithmetic, effective/expiry-date rules, discounts, uplifts, usage tiers, conflicting-contract detection and cross-account pattern grouping.
- **Eight planted issues:** Individual over/underbilling, expired discount, missed uplift, wrong usage tier, duplicate invoice, conflicting signed amendments (human hold), and three customers sharing a faulty legacy pricing template.
- **Negative control:** A legitimate price change for C011 must **not** be flagged.
- **Sealed key:** `data/sealed_answer_key.json`, intentionally separate from the agent-visible data. `data/document_hashes.json` enables verification that evidence has not changed.
- **Agent operating instructions and operator prompts** in `agent/`.

## Run from the parent directory

```bash
python -m contract_to_cash.generate_data
python -m contract_to_cash.billing_engine
python -m unittest discover -s contract_to_cash/tests -v
```

Requires Python 3.10+ and **no third-party packages or API key**. The investigator writes nothing to billing records. `generate_data` creates the fixed synthetic fixture.

## What the investigation proves

The engine discovers **eight exception groups** from signed contract terms and invoices. The A8 systemic finding contains **three affected customers**, with a potential CAD 3,000 underbilling correction across them. The conflicting C007 amendments cannot be automatically resolved. C011 remains clean.

Financial classifications matter: additional receivables are not collected money, overbilling creates potential credit obligations, and duplicate charges require review rather than being counted as savings. Any headcount/capacity claim requires measured workload and oversight assumptions.

## Next phases

1. **Phase 2 — actual OpenAI agent:** Connect tool calling/structured outputs to the read-only functions; implement an event stream, evidence retrieval, contradiction checks and a human review queue. Do not expose the sealed key to the agent.
2. **Phase 3 — human-in-loop stage UI:** Live case timeline, source excerpts, finding retraction, systemic issue reveal and approval gates.
3. **Phase 4 — evaluation:** Run repeated trials, compare agent findings to the sealed key, measure recall, false positives, runtime and API cost, and prepare safe replay fallback.

The eight known outcomes validate the system, but the agent must **discover** them from accessible records—not receive the key or a scripted list.

## Phase 1 input and evidence guarantees

Git text files and generated UTF-8 fixtures use LF line endings on every platform.
The original document manifest contained hashes of CRLF versions of all 60 files;
the repository contained LF documents. The repaired manifest hashes the actual LF
bytes. Generation explicitly writes LF before computing hashes. Integrity tests
check every document and compare regenerated fixtures byte for byte without
rewriting the checked-in dataset.

The calculator raises `BillingInputError` (a `ValueError`) for unsupported or
malformed inputs. Supported scope is signed monthly CAD contracts active at the
first day of the billing month, nonnegative integer usage, all-units usage tiers,
and signed set-price, discount, or uplift amendments. Draft/unsigned amendments
are validated but do not authorize pricing. Dates and periods require exact ISO
formats. Amendments must belong to their customer and have valid date ranges.
Discounts cannot exceed 100%. Contract end dates/proration, other currencies,
other billing cycles, and signed set-price amendments on usage contracts are
rejected rather than interpreted silently. Legacy contracts without a currency
field are CAD by schema; invoices must explicitly specify CAD.

Numeric inputs accept decimal strings, integers, or `Decimal`, never floats or
booleans. Values and calculated charges are bounded to CAD 10^12; usage and tier
thresholds are bounded to 10^9. Arithmetic uses a local precision of 50 digits
and rounds half up to cents. Investigation validates all supplied records before
classifying findings, including record identities, references, currencies and
quantities. Duplicate invoice IDs are invalid; distinct invoice IDs for the same
customer/month still produce the existing duplicate-charge review finding.

Run the complete suite from the repository root:

```bash
python -m unittest discover -s contract_to_cash/tests -v
python -m contract_to_cash.billing_engine
```

Independent handwritten tests cover arithmetic and the checked-in financial
outcomes without deriving expected amounts from the fixture generator or sealed
key. The original tests remain as regression coverage. This is still a narrow
synthetic billing engine: discrepancy labels and shared-template root causes are
heuristics, and duplicate-charge findings do not also audit other discrepancies
on the same account. The Phase 2 agent and local review/export queue are documented in
[agent/README.md](agent/README.md). No billing mutation exists. The runtime bundle
excludes evaluation keys, generators, tests and demonstration prompts.

## Phase 2 backend

See [the agent guide](agent/README.md) for installation, isolated runtime packaging,
API credentials, CLI commands, event schemas, limits, human review and validation.
The complete Phase 1 + Phase 2 test suite requires `requirements-agent.txt`.
