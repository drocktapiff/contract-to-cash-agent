"""Synthetic source ledger and independent expected-results oracle; never used by intake."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import random
from .pdf_templates import render_pdf

SCENARIOS = [
    "routine",
    "underbilling",
    "overbilling",
    "conflict",
    "unsigned",
    "partial_payment",
    "unapplied_cash",
    "usage",
    "renewal",
    "credit",
    "expired_discount",
    "invalid_amendment_date",
    "missing_contract",
    "duplicate_invoice",
    "usage_mismatch",
    "implementation",
    "annual",
]
ADJECTIVES = [
    "Alder",
    "Cobalt",
    "Juniper",
    "Lumen",
    "Harbor",
    "Silver",
    "Willow",
    "Cedar",
    "Mariner",
    "Summit",
    "Orchid",
    "Aspen",
    "Copper",
    "Granite",
    "Meadow",
    "River",
    "Birch",
    "Aurora",
    "Larch",
    "Maple",
]
SECTORS = [
    "Analytics",
    "Logistics",
    "Bioworks",
    "Manufacturing",
    "Research",
    "Systems",
    "Distribution",
    "Learning",
]
Q = lambda value: Decimal(str(value)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def document_fields(kind, docid, customer, contract, **extra):
    return {
        "Document ID": docid,
        "Customer account": customer,
        "Contract reference": contract,
        **extra,
    }


def build_ledger(seed=202604, count=40):
    rng = random.Random(seed)
    accounts = []
    for i in range(count):
        scenario = (
            SCENARIOS[i]
            if i < len(SCENARIOS)
            else rng.choice(
                [
                    "routine",
                    "routine",
                    "routine",
                    "usage",
                    "annual",
                    "partial_payment",
                    "credit",
                    "renewal",
                ]
            )
        )
        plan = (
            "usage"
            if scenario in ("usage", "usage_mismatch")
            else "annual" if scenario == "annual" else "monthly"
        )
        base = Q(rng.randrange(20, 100) * 100)
        rate = Q(rng.choice(["1.25", "2.40", "3.50"]))
        quantity = rng.randint(60, 300) if plan == "usage" else 1
        discount = (
            Decimal("10")
            if scenario in ("expired_discount",) or (scenario == "routine" and i % 3 == 0)
            else Decimal("0")
        )
        valid = "2026-03-31" if scenario == "expired_discount" else "2026-12-31"
        effective_discount = Decimal(0) if scenario == "expired_discount" else discount
        price = Q(
            base * (12 if plan == "annual" else 1) + (quantity * rate if plan == "usage" else 0)
        )
        implementation = Q("1500") if scenario == "implementation" else Q(0)
        expected_net = Q(price * (1 - effective_discount / 100))
        billed = expected_net
        if scenario == "underbilling":
            billed -= Q(700)
        if scenario == "overbilling":
            billed += Q(350)
        if scenario == "expired_discount":
            billed = Q(price * (1 - discount / 100))
        invoiced_quantity = quantity + 10 if scenario == "usage_mismatch" else quantity
        if scenario == "usage_mismatch":
            billed = Q(base + invoiced_quantity * rate)
        tax = Decimal("0.13") if i % 4 else Decimal("0")
        total = Q((billed + implementation) * (1 + tax))
        expected = Q((expected_net + implementation) * (1 + tax))
        paid = Q(total / 2) if scenario == "partial_payment" else total
        account = f"NC-{seed%10000:04d}-{i+1:03d}"
        contract = f"AGR-{seed%100000}-{i+1:03d}"
        accounts.append(
            dict(
                customer_id=account,
                contract_id=contract,
                name=f"{ADJECTIVES[i%len(ADJECTIVES)]} {SECTORS[(i//len(ADJECTIVES)+i)%len(SECTORS)]} Group",
                scenario=scenario,
                plan=plan,
                base=str(base),
                rate=str(rate),
                quantity=quantity,
                invoiced_quantity=invoiced_quantity,
                discount=str(discount),
                discount_valid_to=valid,
                implementation=str(implementation),
                tax=str(tax),
                billed_net=str(billed),
                invoice_total=str(total),
                expected_total=(
                    None
                    if scenario
                    in (
                        "conflict",
                        "unsigned",
                        "missing_contract",
                        "invalid_amendment_date",
                        "duplicate_invoice",
                    )
                    else str(expected)
                ),
                paid=str(paid),
                currency="CAD",
                address=f"{100+i*17} Example Avenue, Suite {i+2}, Demo City, ON X0X 0X0",
                contact=f"accounts{i+1}@customer.example",
            )
        )
    for account in accounts:
        account.update(
            contract_effective_date="2026-01-01",
            contract_term_end="2027-03-31",
            invoice_date="2026-04-30",
            due_date="2026-05-30",
            period_start="2026-04-01",
            period_end="2027-03-31" if account["plan"] == "annual" else "2026-04-30",
            receipt_date="2026-05-15",
            amendment_effective_date=(
                "2026-02-30" if account["scenario"] == "invalid_amendment_date" else "2026-04-01"
            ),
            line_items=[
                dict(
                    description="Platform services",
                    quantity=account["invoiced_quantity"],
                    subtotal=account["billed_net"],
                ),
                dict(description="Implementation", quantity=1, subtotal=account["implementation"]),
            ],
        )
    return dict(
        company="Northstar Cloudworks",
        synthetic=True,
        seed=seed,
        period="2026-04",
        accounts=accounts,
    )


def batch_documents(ledger):
    docs = []
    expected = []
    for i, a in enumerate(ledger["accounts"]):
        cid, agr = a["customer_id"], a["contract_id"]
        prefix = f"NS-{ledger['seed']}-{i+1:03d}"
        contract_id = prefix + "-MSA"
        invoice_id = prefix + "-INV"
        receipt_id = prefix + "-PAY"
        scenario = a["scenario"]
        end = a["period_end"]
        common = {"Customer name": a["name"], "Currency": a["currency"]}
        contract = document_fields(
            "contract",
            contract_id,
            cid,
            agr,
            **common,
            **{
                "Contract status": "Awaiting signature" if scenario == "unsigned" else "Executed",
                "Effective date": a["contract_effective_date"],
                "Term end": a["contract_term_end"],
                "Billing cadence": a["plan"],
                "Subscription amount": a["base"],
                "Included quantity": "0",
                "Unit rate": a["rate"],
                "Discount percent": a["discount"],
                "Discount valid through": a["discount_valid_to"],
                "Implementation fee": a["implementation"],
                "Tax rate": a["tax"],
                "Billing address": a["address"],
                "Customer contact": a["contact"],
                "Pricing authority": (
                    "Pricing schedule incorporated"
                    if i % 5 == 0
                    else "Rates stated in this agreement"
                ),
                "Purchase order": f"PO-DEMO-{i+101}",
            },
        )
        clauses = [
            (
                "1. Services and billing scope",
                f"Northstar Cloudworks provides the {['Operations Intelligence','Customer Data Hub','Secure Workflow'][i%3]} service to {a['name']}. Charges follow the stated {a['plan']} cadence. Usage is supported by the dated service statement; quantities must not be inferred from a payment.",
            ),
            (
                "2. Price, discount and implementation",
                "The subscription amount is a monthly base; an annual order bills twelve monthly bases for one annual service period. Metered orders add actual service units at the stated unit rate. A negotiated discount applies only through its stated validity date. Implementation is separately invoiced when the order includes that service.",
            ),
            (
                "3. Change control and authority",
                "Only an executed amendment identifying this agreement can change financial terms. A later email, renewal notice or payment does not itself resolve conflicting signed amendments. Disputed authority must be referred to Contract Administration.",
            ),
            (
                "4. Payment and renewal",
                "Invoices are due within thirty days. Remittance references support allocation but do not change contractual rates. Renewal is subject to the stated term and any duly executed changes; a notice alone is not acceptance.",
            ),
            (
                "5. Fictional execution",
                "Execution notation: synthetic authorized signatory record only. No image or actual person signature is used. Status shown above governs this demonstration record.",
            ),
        ]
        if scenario != "missing_contract":
            docs.append(dict(kind="contract", fields=contract, variant=i % 2, clauses=clauses))
        invoice = document_fields(
            "invoice",
            invoice_id,
            cid,
            agr,
            **common,
            **{
                "Invoice reference": invoice_id,
                "Invoice date": a["invoice_date"],
                "Due date": a["due_date"],
                "Period start": a["period_start"],
                "Period end": end,
                "Quantity": str(a["invoiced_quantity"]),
                "Service description": f"{a['plan'].title()} platform services",
                "Service subtotal": a["billed_net"],
                "Implementation charge": a["implementation"],
                "Tax rate": a["tax"],
                "Tax amount": str(
                    Q((Decimal(a["billed_net"]) + Decimal(a["implementation"])) * Decimal(a["tax"]))
                ),
                "Invoice total": a["invoice_total"],
                "Purchase order": f"PO-DEMO-{i+101}",
                "Payment instructions": "Use customer and invoice references. No real bank details supplied.",
            },
        )
        docs.append(dict(kind="invoice", fields=invoice, variant=(i + 1) % 2, clauses=[]))
        receipt = document_fields(
            "receipt",
            receipt_id,
            cid,
            agr,
            **common,
            **{
                "Receipt date": a["receipt_date"],
                "Payment reference": f"DEMO-CASH-{i+1:04d}",
                "Payment amount": a["paid"],
                "Applied invoice": (
                    invoice_id if scenario != "unapplied_cash" else "UNIDENTIFIED-INVOICE"
                ),
                "Allocated amount": a["paid"] if scenario != "unapplied_cash" else "0.00",
                "Payment method": "Synthetic electronic remittance",
                "Accounting treatment": "Receipt record only; no real banking transaction",
            },
        )
        docs.append(dict(kind="receipt", fields=receipt, variant=i % 2, clauses=[]))
        if scenario == "duplicate_invoice":
            second = dict(invoice)
            second["Document ID"] = prefix + "-INV-COPY"
            second["Service subtotal"] = str(Q(Decimal(a["billed_net"]) + 50))
            second["Tax amount"] = str(
                Q(
                    (Decimal(second["Service subtotal"]) + Decimal(a["implementation"]))
                    * Decimal(a["tax"])
                )
            )
            second["Invoice total"] = str(
                Q(
                    Decimal(second["Service subtotal"])
                    + Decimal(a["implementation"])
                    + Decimal(second["Tax amount"])
                )
            )
            docs.append(
                dict(
                    kind="invoice",
                    fields=second,
                    variant=1,
                    clauses=[
                        (
                            "Reconciliation note",
                            "An alternative invoice record is supplied. Its relationship to the original requires reconciliation; do not assume both amounts were charged or collected.",
                        )
                    ],
                )
            )
        if scenario in ("conflict", "invalid_amendment_date"):
            for n in range(2 if scenario == "conflict" else 1):
                amendment = document_fields(
                    "amendment",
                    prefix + f"-AMD-{n+1}",
                    cid,
                    agr,
                    **common,
                    **{
                        "Contract status": "Executed",
                        "Effective date": "2026-04-01" if scenario == "conflict" else "2026-02-30",
                        "Subscription amount": str(Q(Decimal(a["base"]) + (n + 1) * 200)),
                        "Supersedes": "No specific prior amendment identified",
                        "Execution record": "Synthetic corporate execution notation; not a real signature",
                    },
                )
                docs.append(
                    dict(
                        kind="amendment",
                        fields=amendment,
                        variant=n,
                        clauses=[
                            (
                                "Operative change",
                                "The revised subscription amount applies from the effective date stated above. All other provisions remain unchanged. Conflicting executed terms require written authority; this document supplies no precedence determination.",
                            )
                        ],
                    )
                )
        if a["plan"] == "usage":
            usage = document_fields(
                "usage",
                prefix + "-USG",
                cid,
                agr,
                **common,
                **{
                    "Period start": a["period_start"],
                    "Period end": "2026-04-30",
                    "Quantity": str(a["quantity"]),
                    "Meter reference": f"DEMO-METER-{i+1}",
                    "Service description": "Processed workflow units; actual metered quantity for stated period",
                },
            )
            docs.append(dict(kind="usage", fields=usage, variant=i % 2, clauses=[]))
        if scenario == "renewal":
            renewal = document_fields(
                "renewal",
                prefix + "-REN",
                cid,
                agr,
                **common,
                **{
                    "Notice date": "2026-04-10",
                    "Term end": a["contract_term_end"],
                    "Renewal status": "Review requested; not an executed amendment",
                    "Required action": "Confirm renewal terms and applicable signed order before next term",
                },
            )
            docs.append(dict(kind="renewal", fields=renewal, variant=i % 2, clauses=[]))
        if scenario == "credit":
            credit = document_fields(
                "credit",
                prefix + "-CR",
                cid,
                agr,
                **common,
                **{
                    "Credit reference": prefix + "-CR",
                    "Applied invoice": invoice_id,
                    "Credit amount": "125.00",
                    "Credit status": "Proposed",
                    "Reason": "Service adjustment submitted for financial authorization; not issued by this pipeline",
                },
            )
            docs.append(dict(kind="credit", fields=credit, variant=i % 2, clauses=[]))
        if i % 5 == 0:
            schedule = document_fields(
                "pricing",
                prefix + "-ORD",
                cid,
                agr,
                **common,
                **{
                    "Contract status": "Executed",
                    "Effective date": a["contract_effective_date"],
                    "Billing cadence": a["plan"],
                    "Subscription amount": a["base"],
                    "Included quantity": "0",
                    "Unit rate": a["rate"],
                    "Discount percent": a["discount"],
                    "Discount valid through": a["discount_valid_to"],
                    "Implementation fee": a["implementation"],
                    "Tax rate": a["tax"],
                    "Order reference": f"DEMO-ORDER-{i+1}",
                },
            )
            docs.append(
                dict(
                    kind="pricing",
                    fields=schedule,
                    variant=i % 2,
                    clauses=[
                        (
                            "Order incorporation",
                            "This pricing schedule is incorporated into the identified master agreement. It does not override a contradictory executed amendment; obtain human contractual authority before resolving conflicting records.",
                        )
                    ],
                )
            )
        if i % 7 == 0:
            remittance = document_fields(
                "remittance",
                prefix + "-REM",
                cid,
                agr,
                **common,
                **{
                    "Payment reference": f"DEMO-CASH-{i+1:04d}",
                    "Payment amount": a["paid"],
                    "Applied invoice": invoice_id,
                    "Allocated amount": a["paid"],
                    "Receipt reference": receipt_id,
                    "Remittance note": "Advice duplicates no cash: match the stated receipt before allocation.",
                },
            )
            docs.append(dict(kind="remittance", fields=remittance, variant=i % 2, clauses=[]))
        if scenario in ("missing_contract", "unsigned", "invalid_amendment_date"):
            note = document_fields(
                "correspondence",
                prefix + "-COR",
                cid,
                agr,
                **common,
                **{
                    "Notice date": "2026-04-25",
                    "Required document": "Valid executed agreement or corrected amendment",
                    "Required action": "Obtain appropriate contractual authority; this correspondence is not authority",
                    "Sender": "Contract Administration <contracts@northstar.example>",
                },
            )
            docs.append(dict(kind="correspondence", fields=note, variant=i % 2, clauses=[]))
        if scenario == "invalid_amendment_date":
            expected.append(
                dict(
                    customer_id=cid,
                    contract_id=agr,
                    business_object_id=prefix + "-AMD-1",
                    category="document_review",
                    required_action="Review unsupported or invalid PDF extraction",
                    source_documents=[prefix + "-AMD-1"],
                    financial_impact=None,
                    automation_eligible=False,
                    human_review_required=True,
                    automatic_closure_allowed=False,
                    intentionally_unresolved=True,
                    original_functional_owner="Contract Administrator",
                )
            )
        # Oracle outcomes originate in the ledger, not in parsing/reconciliation code.
        ambiguous = scenario in (
            "conflict",
            "unsigned",
            "missing_contract",
            "invalid_amendment_date",
            "duplicate_invoice",
        )
        category = {
            "conflict": "contract_conflict",
            "unsigned": "missing_documentation",
            "missing_contract": "missing_documentation",
            "invalid_amendment_date": "amendment_review",
            "duplicate_invoice": "invoice_reconciliation",
        }.get(scenario, "contract_price_validation")
        main_sources = [
            d["fields"]["Document ID"]
            for d in docs
            if d["fields"]["Customer account"] == cid
            and d["kind"] in ("contract", "pricing", "invoice", "amendment", "usage")
        ]
        financial = (
            None
            if ambiguous
            else dict(
                currency="CAD",
                expected_total=a["expected_total"],
                invoiced_total=a["invoice_total"],
                difference=str(Q(Decimal(a["expected_total"]) - Decimal(a["invoice_total"]))),
            )
        )
        eligible = not ambiguous and Decimal(a["expected_total"]) == Decimal(a["invoice_total"])
        expected.append(
            dict(
                customer_id=cid,
                contract_id=agr,
                business_object_id="billing:" + cid,
                category=category,
                required_action=(
                    "Validate contractual invoice charges"
                    if not ambiguous
                    else "Obtain authoritative billing evidence"
                ),
                source_documents=sorted(main_sources),
                financial_impact=financial,
                automation_eligible=eligible,
                human_review_required=not eligible,
                automatic_closure_allowed=eligible,
                intentionally_unresolved=ambiguous,
                original_functional_owner=(
                    "Contract Administrator" if ambiguous else "Billing Analyst"
                ),
            )
        )
        payment_ok = scenario not in ("partial_payment", "unapplied_cash", "duplicate_invoice")
        payment_financial = (
            None
            if scenario in ("unapplied_cash", "duplicate_invoice")
            else dict(
                currency="CAD",
                invoice_total=a["invoice_total"],
                payment_amount=a["paid"],
                remaining_balance=str(Q(Decimal(a["invoice_total"]) - Decimal(a["paid"]))),
            )
        )
        payment_sources = (
            [receipt_id]
            + [
                d["fields"]["Document ID"]
                for d in docs
                if d["fields"]["Customer account"] == cid and d["kind"] == "invoice"
            ]
            if scenario != "unapplied_cash"
            else [receipt_id]
        )
        expected.append(
            dict(
                customer_id=cid,
                contract_id=agr,
                business_object_id=receipt_id,
                category="payment_matching",
                required_action="Reconcile receipt allocation",
                source_documents=sorted(payment_sources),
                financial_impact=payment_financial,
                automation_eligible=payment_ok,
                human_review_required=not payment_ok,
                automatic_closure_allowed=payment_ok,
                intentionally_unresolved=scenario in ("unapplied_cash", "duplicate_invoice"),
                original_functional_owner="Billing Analyst",
            )
        )
        for doc in [
            d
            for d in docs
            if d["fields"]["Customer account"] == cid
            and d["kind"]
            in ("amendment", "renewal", "credit", "usage", "remittance", "correspondence")
        ]:
            k = doc["kind"]
            did = doc["fields"]["Document ID"]
            cat = {
                "amendment": "amendment_review",
                "renewal": "renewal_review",
                "credit": "credit_review",
                "usage": "usage_validation",
                "remittance": "payment_matching",
                "correspondence": "missing_documentation",
            }[k]
            routine = k == "usage" and scenario != "usage_mismatch" or k == "remittance"
            src = [did] + (
                [invoice_id]
                if k in ("credit", "usage")
                else (
                    [receipt_id]
                    if k == "remittance"
                    else (
                        [contract_id] if k == "amendment" and scenario != "missing_contract" else []
                    )
                )
            )
            expected.append(
                dict(
                    customer_id=cid,
                    contract_id=agr,
                    business_object_id=did,
                    category=cat,
                    required_action={
                        "amendment": "Review amendment authority and dates",
                        "renewal": "Review renewal terms",
                        "credit": "Review proposed credit authorization",
                        "usage": "Validate invoiced usage quantity",
                        "remittance": "Match advice to receipt without double-counting cash",
                        "correspondence": "Obtain requested signed documentation",
                    }[k],
                    source_documents=sorted(src),
                    financial_impact=(
                        dict(currency="CAD", proposed_credit="125.00") if k == "credit" else None
                    ),
                    automation_eligible=routine,
                    human_review_required=not routine,
                    automatic_closure_allowed=routine,
                    intentionally_unresolved=k in ("amendment", "correspondence"),
                    original_functional_owner=(
                        "Contract Administrator"
                        if k in ("amendment", "renewal", "correspondence")
                        else "Billing Analyst"
                    ),
                )
            )
    return docs, expected


def generate(destination, seed=202604, count=40):
    root = Path(destination)
    if root.exists():
        raise ValueError("Choose a new isolated destination; existing data is never replaced")
    root.mkdir(parents=True)
    ledger = build_ledger(seed, count)
    docs, work = batch_documents(ledger)
    expected_docs = []
    for n, doc in enumerate(docs):
        did = doc["fields"]["Document ID"]
        path = root / "documents" / f"{did}.pdf"
        render_pdf(path, doc["kind"], doc["fields"], doc["variant"], doc["clauses"])
        expected_docs.append(
            dict(
                document_id=did,
                file_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                document_type=doc["kind"],
                customer_id=doc["fields"]["Customer account"],
                contract_id=doc["fields"]["Contract reference"],
                key_fields=doc["fields"],
                relationships={
                    k: doc["fields"][k]
                    for k in (
                        "Customer account",
                        "Contract reference",
                        "Applied invoice",
                        "Receipt reference",
                        "Invoice reference",
                    )
                    if k in doc["fields"]
                },
            )
        )
    oracle = root / "evaluation"
    oracle.mkdir()
    (oracle / "source_ledger.json").write_text(
        json.dumps(ledger, indent=2) + "\n", encoding="utf-8"
    )
    (oracle / "expected.json").write_text(
        json.dumps(
            dict(synthetic=True, seed=seed, documents=expected_docs, work_items=work), indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    return root
