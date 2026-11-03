"""Deterministic financial rules and evidence-based April 2026 investigation.

No model is involved in arithmetic or in the ground-truth audit. An eventual
OpenAI agent can call these functions as tools and explain sourced findings.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

CENT = Decimal("0.01")


class ConflictError(ValueError):
    """Signed contract evidence is contradictory; never guess a payable amount."""


def money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def expected_amount(contract: dict, amendments: list[dict], period: str, quantity: int = 0) -> Decimal:
    """Calculate correct monthly amount from signed, effective contract terms."""
    first = date.fromisoformat(period + "-01")
    active = [a for a in amendments if a["status"] == "signed"
              and date.fromisoformat(a["effective_date"]) <= first
              and (not a.get("end_date") or date.fromisoformat(a["end_date"]) >= first)]
    price_changes = [a for a in active if a["kind"] == "set_price"]
    by_date = defaultdict(set)
    for amendment in price_changes:
        by_date[amendment["effective_date"]].add(money(amendment["value"]))
    if any(len(values) > 1 for values in by_date.values()):
        raise ConflictError("Contradictory signed set-price amendments with the same effective date")

    base = money(contract["base_monthly_cad"])
    if price_changes:
        latest = max(price_changes, key=lambda a: (a["effective_date"], a["amendment_id"]))
        base = money(latest["value"])
    if "usage_tier" in contract:
        tier = contract["usage_tier"]
        rate = tier["unit_rate_above"] if quantity > int(tier["threshold"]) else tier["unit_rate_at_or_below"]
        base = Decimal(quantity) * Decimal(rate)
    for amendment in sorted(active, key=lambda a: a["amendment_id"]):
        percent = Decimal(amendment["value"]) / 100
        if amendment["kind"] == "uplift_percent":
            base *= 1 + percent
        elif amendment["kind"] == "discount_percent":
            base *= 1 - percent
    return base.quantize(CENT, rounding=ROUND_HALF_UP)


def investigate(contracts: list[dict], amendments: list[dict], invoices: list[dict], period: str = "2026-04") -> dict:
    """Discover exceptions from records; anomaly/customer IDs are not hardcoded."""
    changes = defaultdict(list)
    charges = defaultdict(list)
    for amendment in amendments:
        changes[amendment["customer_id"]].append(amendment)
    for invoice in invoices:
        if invoice["period"] == period:
            charges[invoice["customer_id"]].append(invoice)

    findings = []
    mismatches = []
    clean = []
    for contract in contracts:
        cid = contract["customer_id"]
        rows = charges[cid]
        evidence = [contract["contract_id"]] + [a["amendment_id"] for a in changes[cid]] + [i["invoice_id"] for i in rows]
        if not rows:
            findings.append({"type": "missing_invoice", "customers": [cid], "evidence": evidence, "status": "human_review"})
            continue
        if len(rows) > 1:
            findings.append({"type": "duplicate_invoice", "customers": [cid], "evidence": evidence,
                             "amount_at_risk_cad": str(sum((money(i["billed_amount"]) for i in rows[1:]), Decimal(0))),
                             "status": "human_review"})
            continue
        invoice = rows[0]
        try:
            expected = expected_amount(contract, changes[cid], period, int(invoice["usage_quantity"]))
        except ConflictError:
            findings.append({"type": "conflicting_signed_amendments", "customers": [cid],
                             "evidence": evidence, "status": "human_review", "amount_at_risk_cad": None})
            continue
        billed = money(invoice["billed_amount"])
        if expected == billed:
            clean.append(cid)
            continue
        difference = expected - billed  # positive = additional receivable; negative = refund/credit
        kind = "underbilling" if difference > 0 else "overbilling"
        if contract.get("usage_tier"):
            kind = "usage_tier_error"
        elif any(a["kind"] == "uplift_percent" and a["effective_date"] <= period + "-01" for a in changes[cid]):
            kind = "missed_uplift"
        elif any(a["kind"] == "discount_percent" and a.get("end_date") and a["end_date"] < period + "-01" for a in changes[cid]):
            kind = "expired_discount"
        mismatches.append({"type": kind, "customers": [cid], "evidence": evidence,
                           "expected_cad": str(expected), "billed_cad": str(billed),
                           "difference_cad": str(difference), "status": "review_required",
                           "pricing_template": contract["pricing_template"]})

    # Cross-account investigation: shared template plus an identical discrepancy.
    groups = defaultdict(list)
    for mismatch in mismatches:
        groups[(mismatch["pricing_template"], mismatch["difference_cad"])].append(mismatch)
    grouped_ids = set()
    for (template, discrepancy), group in groups.items():
        if len(group) >= 3:
            grouped_ids.update(g["customers"][0] for g in group)
            findings.append({"type": "shared_pricing_template_error",
                             "customers": [g["customers"][0] for g in group],
                             "evidence": [item for g in group for item in g["evidence"]],
                             "pricing_template": template,
                             "difference_per_customer_cad": discrepancy,
                             "total_difference_cad": str(sum((Decimal(g["difference_cad"]) for g in group), Decimal(0))),
                             "status": "review_required"})
    findings.extend({k: v for k, v in m.items() if k != "pricing_template"}
                    for m in mismatches if m["customers"][0] not in grouped_ids)
    findings.sort(key=lambda f: f["customers"][0])
    return {"period": period, "customers_checked": len(contracts), "findings": findings,
            "clean_customers": clean, "finding_count": len(findings),
            "disclaimer": "Flagged differences are review candidates, not automatically recovered cash."}


def load_records(directory: Path) -> tuple[list[dict], list[dict], list[dict]]:
    return tuple(json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
                 for name in ("contracts", "amendments", "invoices"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only deterministic contract-to-cash investigation")
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--period", default="2026-04")
    args = parser.parse_args()
    print(json.dumps(investigate(*load_records(args.data), period=args.period), indent=2))


if __name__ == "__main__":
    main()
