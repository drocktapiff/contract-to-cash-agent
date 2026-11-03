"""Generate a deterministic, entirely fictional contract-to-cash audit fixture.

Run: python -m contract_to_cash.generate_data
The public data excludes the sealed answer key, which is stored separately.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MONTHS = ("2026-02", "2026-03", "2026-04")


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def build_fixture() -> tuple[list[dict], list[dict], list[dict], dict]:
    contracts, amendments, invoices = [], [], []
    for n in range(1, 41):
        cid = f"C{n:03d}"
        monthly = 10000 + (n % 5) * 500
        if n == 1: monthly = 12000
        if n == 2: monthly = 10000
        if n == 3: monthly = 8000
        if n == 4: monthly = 10000
        if n == 5: monthly = 1000
        if n in (8, 9, 10): monthly = 10000
        if n == 11: monthly = 10000
        if n == 7: monthly = 12000
        contract = {
            "customer_id": cid, "customer_name": f"Demo Customer {n:02d}",
            "contract_id": f"CTR-{cid}", "base_monthly_cad": str(monthly),
            "start_date": "2026-01-01", "status": "signed",
            "plan": "Enterprise", "billing_cycle": "monthly",
            "pricing_template": "legacy-2025" if n in (8, 9, 10) else "standard-2026",
        }
        if n == 5:
            contract["usage_tier"] = {"threshold": 100, "unit_rate_above": "9.00", "unit_rate_at_or_below": "10.00"}
        contracts.append(contract)

    def amend(cid: str, suffix: str, kind: str, effective: str, value: str, end: str | None = None) -> None:
        amendments.append({"amendment_id": f"AMD-{cid}-{suffix}", "customer_id": cid,
                           "kind": kind, "effective_date": effective, "value": value,
                           "end_date": end, "status": "signed"})

    amend("C003", "01", "discount_percent", "2026-01-01", "10", "2026-02-28")
    amend("C004", "01", "uplift_percent", "2026-04-01", "10")
    amend("C007", "01", "set_price", "2026-04-01", "13000")
    amend("C007", "02", "set_price", "2026-04-01", "14000")
    amend("C011", "01", "set_price", "2026-04-01", "9500")
    for n in range(12, 27):
        amend(f"C{n:03d}", "01", "set_price", "2026-07-01", str(10000 + (n % 5) * 500))

    from .billing_engine import expected_amount, ConflictError
    amendments_by_customer = {}
    for a in amendments:
        amendments_by_customer.setdefault(a["customer_id"], []).append(a)

    for contract in contracts:
        cid = contract["customer_id"]
        for month in MONTHS:
            quantity = 110 if cid == "C005" else 0
            try:
                amount = expected_amount(contract, amendments_by_customer.get(cid, []), month, quantity)
            except ConflictError:
                # An ambiguous contract cannot safely yield an authorized amount.
                amount = 12000
            billed = amount
            if month == "2026-04":
                if cid == "C001": billed = 12500
                if cid == "C002": billed = 9500
                if cid == "C003": billed = 7200
                if cid == "C004": billed = 10000
                if cid == "C005": billed = 1100
                if cid in ("C008", "C009", "C010"): billed = 9000
            invoices.append({"invoice_id": f"INV-{cid}-{month}", "customer_id": cid,
                             "period": month, "currency": "CAD", "usage_quantity": quantity,
                             "billed_amount": f"{billed:.2f}",
                             "pricing_template": contract["pricing_template"]})
    # Sixth issue: a duplicate charge, even when both invoices are individually correct.
    invoices.append({**next(i for i in invoices if i["customer_id"] == "C006" and i["period"] == "2026-04"),
                     "invoice_id": "INV-C006-2026-04-DUP"})

    answer_key = {
        "fixture_version": "phase1-v1", "period": "2026-04",
        "issues": [
            {"id": "A1", "customers": ["C001"], "type": "overbilling"},
            {"id": "A2", "customers": ["C002"], "type": "underbilling"},
            {"id": "A3", "customers": ["C003"], "type": "expired_discount"},
            {"id": "A4", "customers": ["C004"], "type": "missed_uplift"},
            {"id": "A5", "customers": ["C005"], "type": "usage_tier_error"},
            {"id": "A6", "customers": ["C006"], "type": "duplicate_invoice"},
            {"id": "A7", "customers": ["C007"], "type": "conflicting_signed_amendments", "requires_human": True},
            {"id": "A8", "customers": ["C008", "C009", "C010"], "type": "shared_pricing_template_error"},
        ],
        "negative_control": {"customer": "C011", "reason": "Valid signed April price amendment; do not flag"},
    }
    return contracts, amendments, invoices, answer_key


def generate(output_dir: Path = DATA) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    contracts, amendments, invoices, key = build_fixture()
    public = {"contracts": contracts, "amendments": amendments, "invoices": invoices}
    for name, rows in public.items():
        write_json(output_dir / f"{name}.json", rows)
    docs = output_dir / "documents"
    docs.mkdir(exist_ok=True)
    for c in contracts:
        details = [f"CONTRACT {c['contract_id']}", f"Customer: {c['customer_name']} ({c['customer_id']})",
                   f"Status: Signed", f"Start: {c['start_date']}",
                   f"Base subscription charge: CAD {c['base_monthly_cad']} per month.",
                   f"Billing cycle: Monthly. Pricing template: {c['pricing_template']}."]
        if c.get("usage_tier"):
            details.append("For usage above 100 units in a month, all units are priced at CAD 9.00 each; otherwise CAD 10.00 each. This replaces the base charge for this customer's measured service.")
        (docs / f"{c['contract_id']}.txt").write_text("\n".join(details) + "\n", encoding="utf-8", newline="\n")
    for a in amendments:
        terms = {"discount_percent": "discount percentage", "uplift_percent": "price increase percentage", "set_price": "monthly price CAD"}
        body = [f"SIGNED AMENDMENT {a['amendment_id']}", f"Customer: {a['customer_id']}",
                f"Effective: {a['effective_date']}", f"Term: {terms[a['kind']]} = {a['value']}"]
        if a["end_date"]: body.append(f"Expires: {a['end_date']}")
        (docs / f"{a['amendment_id']}.txt").write_text("\n".join(body) + "\n", encoding="utf-8", newline="\n")
    write_json(output_dir / "sealed_answer_key.json", key)
    manifest = {}
    for path in sorted(docs.glob("*.txt")):
        manifest[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(output_dir / "document_hashes.json", manifest)
    return {"customers": len(contracts), "documents": len(manifest), "amendments": len(amendments),
            "invoices": len(invoices), "planted_issues": len(key["issues"])}


if __name__ == "__main__":
    print(json.dumps(generate(), indent=2))
