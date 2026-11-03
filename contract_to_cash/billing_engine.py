"""Deterministic financial rules and evidence-based April 2026 investigation.

No model is involved in arithmetic or in the ground-truth audit. An eventual
OpenAI agent can call these functions as tools and explain sourced findings.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path

CENT = Decimal("0.01")


class ConflictError(ValueError):
    """Signed contract evidence is contradictory; never guess a payable amount."""


class BillingInputError(ValueError):
    """Malformed input or a billing rule outside the supported monthly CAD scope."""


def _text(record: dict, field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BillingInputError(f"{field} must be a nonempty string")
    return value


def _date(value: object) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise BillingInputError("Dates must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise BillingInputError("Invalid calendar date") from exc


def _period(value: object) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        raise BillingInputError("Billing period must use YYYY-MM")
    return _date(value + "-01")


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise BillingInputError("Amounts must be decimal strings, integers, or Decimal values")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise BillingInputError("Invalid decimal value") from exc
    if not result.is_finite() or not 0 <= result <= Decimal("1000000000000"):
        raise BillingInputError("Values must be finite and between zero and 10^12")
    return result


def money(value: object) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return _decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _quantity(value: object) -> None:
    if type(value) is not int or not 0 <= value <= 1000000000:
        raise BillingInputError("Usage quantities must be integers between zero and 10^9")


def _validate_contract(contract: dict, first: date) -> None:
    if not isinstance(contract, dict):
        raise BillingInputError("Contract must be an object")
    for field in ("customer_id", "contract_id", "pricing_template"):
        _text(contract, field)
    if contract.get("status") != "signed" or contract.get("billing_cycle") != "monthly":
        raise BillingInputError("Only signed monthly contracts are supported")
    if contract.get("currency", "CAD") != "CAD":
        raise BillingInputError("Only CAD is supported")
    if _date(contract.get("start_date")) > first:
        raise BillingInputError("Contract is not active at the period start; proration is unsupported")
    if contract.get("end_date") is not None:
        raise BillingInputError("Contract end dates and proration are unsupported")
    money(contract.get("base_monthly_cad"))
    if "usage_tier" in contract:
        tier = contract["usage_tier"]
        if not isinstance(tier, dict):
            raise BillingInputError("usage_tier must be an object")
        _quantity(tier.get("threshold"))
        _decimal(tier.get("unit_rate_above"))
        _decimal(tier.get("unit_rate_at_or_below"))


def _validate_amendments(contract: dict, amendments: list[dict]) -> None:
    if not isinstance(amendments, list):
        raise BillingInputError("Amendments must be a list")
    seen = set()
    for amendment in amendments:
        if not isinstance(amendment, dict):
            raise BillingInputError("Amendment must be an object")
        aid = _text(amendment, "amendment_id")
        if aid in seen:
            raise BillingInputError("Duplicate amendment ID")
        seen.add(aid)
        if amendment.get("customer_id") != contract["customer_id"]:
            raise BillingInputError("Amendment belongs to another customer")
        if amendment.get("status") not in ("signed", "unsigned", "draft"):
            raise BillingInputError("Unsupported amendment status")
        kind = amendment.get("kind")
        if kind not in ("set_price", "discount_percent", "uplift_percent"):
            raise BillingInputError("Unsupported amendment kind")
        effective = _date(amendment.get("effective_date"))
        end = amendment.get("end_date")
        if end is not None and _date(end) < effective:
            raise BillingInputError("Amendment expires before it takes effect")
        value = _decimal(amendment.get("value"))
        if kind == "discount_percent" and value > 100:
            raise BillingInputError("Discount must be between zero and 100 percent")
        if "usage_tier" in contract and kind == "set_price" and amendment["status"] == "signed":
            raise BillingInputError("Set-price amendments on usage contracts are unsupported")


def expected_amount(contract: dict, amendments: list[dict], period: str, quantity: int = 0) -> Decimal:
    """Calculate a supported charge independently of the caller's Decimal precision."""
    try:
        with localcontext() as context:
            context.prec = 50
            return _expected_amount(contract, amendments, period, quantity)
    except DecimalException as exc:
        raise BillingInputError("Calculation exceeds supported decimal arithmetic") from exc


def _expected_amount(contract: dict, amendments: list[dict], period: str, quantity: int) -> Decimal:
    """Calculate correct monthly amount from signed, effective contract terms."""
    first = _period(period)
    _quantity(quantity)
    _validate_contract(contract, first)
    _validate_amendments(contract, amendments)
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
    return money(base)


def investigate(contracts: list[dict], amendments: list[dict], invoices: list[dict], period: str = "2026-04") -> dict:
    """Discover exceptions from records; anomaly/customer IDs are not hardcoded."""
    first = _period(period)
    if not all(isinstance(rows, list) for rows in (contracts, amendments, invoices)):
        raise BillingInputError("Record collections must be lists")
    customers = {}
    contract_ids = set()
    for contract in contracts:
        _validate_contract(contract, first)
        cid = contract["customer_id"]
        if cid in customers or contract["contract_id"] in contract_ids:
            raise BillingInputError("Duplicate customer or contract ID")
        customers[cid] = contract
        contract_ids.add(contract["contract_id"])
    amendment_ids = set()
    for amendment in amendments:
        if not isinstance(amendment, dict) or amendment.get("customer_id") not in customers:
            raise BillingInputError("Amendment references an unknown customer")
        _validate_amendments(customers[amendment["customer_id"]], [amendment])
        if amendment["amendment_id"] in amendment_ids:
            raise BillingInputError("Duplicate amendment ID")
        amendment_ids.add(amendment["amendment_id"])
    invoice_ids = set()
    for invoice in invoices:
        if not isinstance(invoice, dict) or invoice.get("customer_id") not in customers:
            raise BillingInputError("Invoice references an unknown customer")
        iid = _text(invoice, "invoice_id")
        if iid in invoice_ids:
            raise BillingInputError("Duplicate invoice ID")
        invoice_ids.add(iid)
        _period(invoice.get("period"))
        if invoice.get("currency") != "CAD":
            raise BillingInputError("Only CAD invoices are supported")
        _quantity(invoice.get("usage_quantity"))
        money(invoice.get("billed_amount"))
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
            expected = expected_amount(contract, changes[cid], period, invoice["usage_quantity"])
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
