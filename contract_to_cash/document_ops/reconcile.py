"""Conservative cross-document rules. Financial outcomes never execute transactions."""

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from contract_to_cash.billing_engine import money
from .models import WorkItem


def amount(doc, key):
    return Decimal(doc.fields[key])


def day(doc, key):
    return date.fromisoformat(doc.fields[key])


def cash(n):
    return str(money(n))


def item(
    sources,
    category,
    action,
    business_id,
    financial=None,
    eligible=False,
    unresolved=False,
    owner="Billing Analyst",
    reason="Human authority or additional evidence required",
):
    sources = sorted(
        {d.file_hash: d for d in sources}.values(), key=lambda d: (d.document_id, d.file_hash)
    )
    first = sources[0]
    now = datetime.now(timezone.utc).isoformat()
    identity = [
        category,
        business_id,
        first.customer_id,
        first.contract_id,
        [(d.document_id, d.file_hash) for d in sources],
    ]
    wid = "WI-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
    evidence = [s for d in sources for spans in d.evidence.values() for s in spans]
    return WorkItem(
        wid,
        [d.document_id for d in sources],
        first.customer_id,
        first.contract_id,
        {
            "contract_price_validation": "invoice",
            "invoice_reconciliation": "invoice",
            "contract_conflict": "contract",
            "missing_documentation": "contract",
            "amendment_review": "contract_amendment",
            "payment_matching": "payment",
            "credit_review": "credit_memo",
            "usage_validation": "usage_statement",
            "renewal_review": "renewal",
            "document_review": "document",
        }[category],
        business_id,
        category,
        action,
        owner,
        "Revenue Operations Specialist",
        (
            "Ready for Processing"
            if eligible
            else "Awaiting Evidence" if unresolved else "Human Review Required"
        ),
        {
            d.file_hash: {
                "document_id": d.document_id,
                "fields": d.fields,
                "validation_errors": d.errors,
            }
            for d in sources
        },
        evidence,
        financial,
        action,
        eligible,
        "Read-only reconciliation passed; no financial action authorized" if eligible else reason,
        not eligible,
        eligible,
        unresolved,
        now,
        now,
        [
            {
                "event": "generated_from_pdf_evidence",
                "at": now,
                "actor": "deterministic_rules",
                "financial_action_executed": False,
            }
        ],
        {
            "source": "actual_pdf_processing",
            "synthetic": all(d.provenance["synthetic"] for d in sources),
            "simulation": "synthetic inputs; genuine deterministic processing",
            "paid_model_calls": 0,
        },
    )


def validate_price(docs):
    """Full-month/annual CAD contracts only; no proration or legal precedence guesses."""
    invoices = [d for d in docs if d.document_type == "invoice"]
    contracts = [d for d in docs if d.document_type == "contract"]
    amendments = [d for d in docs if d.document_type == "amendment"]
    category = "contract_price_validation"
    reason = ""
    if len(invoices) != 1:
        category = "invoice_reconciliation"
        reason = "Multiple invoice records or missing invoice; relationship unresolved"
    elif len(contracts) != 1 or contracts[0].fields.get("Contract status") != "Executed":
        category = "missing_documentation"
        reason = "Exactly one executed agreement required"
    elif any(d.errors for d in amendments):
        category = "amendment_review"
        reason = "Invalid amendment date or incomplete amendment"
    elif amendments:
        category = "contract_conflict"
        reason = "Executed amendment precedence requires human contractual authority"
    elif any(d.errors for d in docs):
        category = "missing_documentation"
        reason = "Invalid or incomplete source fields"
    if reason:
        return category, None, False, True, reason
    invoice, contract = invoices[0], contracts[0]
    try:
        if any(d.fields.get("Currency") != "CAD" for d in docs):
            raise ValueError("Only consistent CAD sources supported")
        start, end = day(invoice, "Period start"), day(invoice, "Period end")
        if not day(contract, "Effective date") <= start <= end <= day(contract, "Term end"):
            raise ValueError("Service period outside executed contract term")
        if day(invoice, "Due date") < day(invoice, "Invoice date"):
            raise ValueError("Invalid invoice due date")
        if (
            contract.fields.get("Purchase order")
            and invoice.fields.get("Purchase order")
            and contract.fields["Purchase order"] != invoice.fields["Purchase order"]
        ):
            raise ValueError("Purchase-order references conflict")
        quantity_matches = True
        cadence = contract.fields["Billing cadence"]
        if start.day != 1:
            raise ValueError("Prorated periods unsupported")
        if cadence in ("monthly", "usage"):
            if end != date(start.year, start.month, monthrange(start.year, start.month)[1]):
                raise ValueError("Expected complete monthly period")
            multiplier = 1
        elif cadence == "annual":
            if start.month != 4 or end != date(start.year + 1, 3, 31):
                raise ValueError("Unsupported annual service boundary")
            multiplier = 12
        else:
            raise ValueError("Unsupported billing cadence")
        for schedule in [d for d in docs if d.document_type == "pricing"]:
            if (
                schedule.fields.get("Contract status") != "Executed"
                or day(schedule, "Effective date") > start
            ):
                raise ValueError("Pricing authority not effective")
            for key in (
                "Subscription amount",
                "Billing cadence",
                "Unit rate",
                "Discount percent",
                "Discount valid through",
                "Implementation fee",
                "Tax rate",
            ):
                if schedule.fields.get(key) != contract.fields.get(key):
                    raise ValueError("Conflicting pricing schedule")
        if contract.fields.get("Pricing authority") == "Pricing schedule incorporated" and not any(
            d.document_type == "pricing" for d in docs
        ):
            raise ValueError("Incorporated schedule missing")
        net = amount(contract, "Subscription amount") * multiplier
        if cadence == "usage":
            usages = [d for d in docs if d.document_type == "usage"]
            if len(usages) != 1:
                raise ValueError("Exactly one usage statement required")
            usage = usages[0]
            quantity_matches = amount(usage, "Quantity") == amount(invoice, "Quantity")
            if (day(usage, "Period start"), day(usage, "Period end")) != (start, end):
                raise ValueError("Usage period mismatch")
            net += max(
                Decimal(0), amount(usage, "Quantity") - amount(contract, "Included quantity")
            ) * amount(contract, "Unit rate")
        elif amount(invoice, "Quantity") != 1:
            raise ValueError("Subscription quantity unsupported")
        discount = (
            amount(contract, "Discount percent")
            if start <= day(contract, "Discount valid through")
            else Decimal(0)
        )
        net = money(net * (1 - discount / 100))
        implementation = amount(invoice, "Implementation charge")
        if implementation != amount(contract, "Implementation fee"):
            raise ValueError("Implementation charge requires scoped order confirmation")
        if amount(invoice, "Tax rate") != amount(contract, "Tax rate"):
            raise ValueError("Tax treatment mismatch")
        tax = money(
            (amount(invoice, "Service subtotal") + implementation) * amount(invoice, "Tax rate")
        )
        if tax != amount(invoice, "Tax amount") or money(
            amount(invoice, "Service subtotal") + implementation + tax
        ) != amount(invoice, "Invoice total"):
            raise ValueError("Invoice arithmetic inconsistent")
        expected = money((net + implementation) * (1 + amount(contract, "Tax rate")))
        actual = amount(invoice, "Invoice total")
        financial = dict(
            currency="CAD",
            expected_total=str(expected),
            invoiced_total=cash(actual),
            difference=str((expected - actual).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)),
        )
        return (
            category,
            financial,
            expected == actual and quantity_matches,
            False,
            "Deterministic contract comparison identifies a discrepancy",
        )
    except (ValueError, KeyError, ArithmeticError) as exc:
        return "missing_documentation", None, False, True, str(exc)


def reconcile(documents):
    # Repeated copies of identical bytes cannot create duplicate business work.
    documents = list({d.file_hash: d for d in documents}.values())
    ids = defaultdict(list)
    for doc in documents:
        ids[doc.document_id].append(doc)
    for group in ids.values():
        if len(group) > 1:
            for doc in group:
                doc.errors.append("Document identifier has conflicting file contents")
    groups = defaultdict(list)
    items = []
    for doc in documents:
        if doc.customer_id and doc.contract_id:
            groups[(doc.customer_id, doc.contract_id)].append(doc)
        if doc.errors or not doc.document_type:
            items.append(
                item(
                    [doc],
                    "document_review",
                    "Review unsupported or invalid PDF extraction",
                    doc.document_id,
                    unresolved=True,
                    owner="Contract Administrator",
                )
            )
    for (customer, contract), docs in groups.items():
        by = defaultdict(list)
        for doc in docs:
            by[doc.document_type].append(doc)
        main = [
            d
            for d in docs
            if d.document_type in ("invoice", "contract", "pricing", "amendment", "usage", None)
        ]
        if by["invoice"]:
            category, financial, eligible, unresolved, reason = validate_price(main)
            ambiguous = financial is None
            items.append(
                item(
                    main,
                    category,
                    (
                        "Obtain authoritative billing evidence"
                        if ambiguous
                        else "Validate contractual invoice charges"
                    ),
                    "billing:" + customer,
                    financial,
                    eligible,
                    unresolved,
                    "Contract Administrator" if ambiguous else "Billing Analyst",
                    reason,
                )
            )
        for receipt in by["receipt"]:
            matched = [
                d
                for d in by["invoice"]
                if d.fields.get("Invoice reference") == receipt.fields.get("Applied invoice")
            ]
            financial = None
            eligible = False
            unresolved = True
            if len(matched) == 1 and not receipt.errors and not matched[0].errors:
                inv = matched[0]
                if inv.fields.get("Currency") == receipt.fields.get("Currency") == "CAD":
                    total, paid, allocation = (
                        amount(inv, "Invoice total"),
                        amount(receipt, "Payment amount"),
                        amount(receipt, "Allocated amount"),
                    )
                    if allocation == paid and 0 <= paid <= total:
                        financial = dict(
                            currency="CAD",
                            invoice_total=cash(total),
                            payment_amount=cash(paid),
                            remaining_balance=cash(total - paid),
                        )
                        eligible = total == paid
                        unresolved = False
            items.append(
                item(
                    [receipt] + matched,
                    "payment_matching",
                    "Reconcile receipt allocation",
                    receipt.document_id,
                    financial,
                    eligible,
                    unresolved,
                )
            )
        for kind in ("amendment", "renewal", "credit", "usage", "remittance", "correspondence"):
            for doc in by[kind]:
                category = {
                    "amendment": "amendment_review",
                    "renewal": "renewal_review",
                    "credit": "credit_review",
                    "usage": "usage_validation",
                    "remittance": "payment_matching",
                    "correspondence": "missing_documentation",
                }[kind]
                action = {
                    "amendment": "Review amendment authority and dates",
                    "renewal": "Review renewal terms",
                    "credit": "Review proposed credit authorization",
                    "usage": "Validate invoiced usage quantity",
                    "remittance": "Match advice to receipt without double-counting cash",
                    "correspondence": "Obtain requested signed documentation",
                }[kind]
                sources = [doc]
                eligible = False
                financial = None
                if kind == "amendment":
                    sources += by["contract"]
                if kind in ("usage", "credit"):
                    matched = [
                        d
                        for d in by["invoice"]
                        if kind == "usage"
                        or d.fields.get("Invoice reference") == doc.fields.get("Applied invoice")
                    ]
                    sources += matched
                    if len(matched) == 1 and not doc.errors and not matched[0].errors:
                        inv = matched[0]
                        if kind == "usage":
                            eligible = all(
                                doc.fields.get(k) == inv.fields.get(k)
                                for k in ("Quantity", "Period start", "Period end", "Currency")
                            )
                        elif doc.fields.get("Currency") == inv.fields.get(
                            "Currency"
                        ) == "CAD" and amount(doc, "Credit amount") <= amount(inv, "Invoice total"):
                            financial = dict(
                                currency="CAD", proposed_credit=cash(amount(doc, "Credit amount"))
                            )
                if kind == "remittance":
                    receipts = [
                        d
                        for d in by["receipt"]
                        if d.document_id == doc.fields.get("Receipt reference")
                    ]
                    sources += receipts
                    eligible = (
                        len(receipts) == 1
                        and not doc.errors
                        and not receipts[0].errors
                        and all(
                            doc.fields.get(k) == receipts[0].fields.get(k)
                            for k in (
                                "Currency",
                                "Payment reference",
                                "Payment amount",
                                "Applied invoice",
                                "Allocated amount",
                            )
                        )
                    )
                items.append(
                    item(
                        sources,
                        category,
                        action,
                        doc.document_id,
                        financial,
                        eligible,
                        kind in ("amendment", "correspondence") or bool(doc.errors),
                        (
                            "Contract Administrator"
                            if kind in ("amendment", "renewal", "correspondence")
                            else "Billing Analyst"
                        ),
                    )
                )
    return items
