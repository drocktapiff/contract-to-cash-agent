# Contract-to-Cash: Phase 1 Foundation

**Demo thesis:** With OpenAI-powered investigations and deterministic billing tools, one human could supervise contract administration **and** billing analysis. Phase 1 builds the testable financial foundation; it is **not yet a live OpenAI agent**.

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
