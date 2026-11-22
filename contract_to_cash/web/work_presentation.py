"""Read-only business projections of real work, source evidence and audit events."""

from collections import Counter
from decimal import Decimal


def bucket(work):
    if work["status"] == "Closed":
        return "Completed"
    if work["status"] == "Awaiting Maya Review":
        return "Awaiting My Review"
    if work["status"] == "Review Rejected — Needs Investigation":
        return "Review Rejected"
    if work.get("management", {}).get("review_status") == "Returned to Maya":
        return "Needs My Attention"
    if work.get("oversight") or work["status"] in (
        "Escalated",
        "Awaiting Financial Review",
        "Awaiting Evidence",
    ):
        return "Awaiting Others"
    return "Needs My Attention"


def business(work):
    category = work["category"]
    impact = work.get("financial_impact")
    if category == "contract_price_validation":
        label = (
            "Invoice amount differs from contract pricing"
            if impact and Decimal(impact.get("difference", "0")) != 0
            else "Check invoice against agreed pricing"
        )
    else:
        label = {
            "contract_conflict": "Conflicting signed pricing terms need authority",
            "amendment_review": "Confirm which amendment can govern billing",
            "missing_documentation": "Obtain missing contractual documentation",
            "document_review": "Verify an unreadable or invalid source document",
            "invoice_reconciliation": "Reconcile ambiguous invoice records",
            "payment_matching": "Match payment records to the invoice",
            "credit_review": "Review a proposed customer credit",
            "renewal_review": "Confirm renewal terms before the next period",
            "usage_validation": "Check metered usage against billed quantity",
        }.get(category, work["required_action"])
    waiting = {
        "Escalated": "Sarah / Contract Administration",
        "Awaiting Financial Review": "Finance",
        "Awaiting Evidence": "Missing documentation or authority",
    }.get(work["status"])
    waiting = work.get("waiting_on_department") or waiting
    oversight = "Sarah Chen" if work.get("oversight") or work["status"] == "Escalated" else None
    decision = work.get("current_decision_owner") or waiting or "Maya Tremblay"
    next_action = (
        "No further administrative action"
        if work["status"] == "Closed"
        else (
            "Await the authorized decision"
            if waiting and work["status"] != "Awaiting Evidence"
            else work.get("management", {}).get("required_next_action")
            or work["recommendation"]["suggested_action"]
        )
    )
    if work.get("management", {}).get("review_status") == "Returned to Maya":
        next_action = work["management"]["required_next_action"]
    impact_text = "Not quantified"
    if impact:
        currency = impact.get("currency", "")
        if "difference" in impact:
            impact_text = (
                "Matched; no billing difference"
                if Decimal(impact["difference"]) == 0
                else currency
                + " "
                + impact["difference"]
                + " potential difference (expected − invoiced)"
            )
        elif "proposed_credit" in impact:
            impact_text = (
                currency + " " + impact["proposed_credit"] + " proposed credit; not issued"
            )
        elif "remaining_balance" in impact:
            impact_text = (
                currency + " " + impact["remaining_balance"] + " remaining invoice balance"
            )
    return dict(
        impact_text=impact_text,
        title=label,
        view=bucket(work),
        case_owner="Maya Tremblay",
        waiting_on=waiting,
        management_oversight_owner=oversight,
        current_decision_owner=decision,
        waiting_on_department=work.get("waiting_on_department") or waiting,
        next_action=next_action,
        why_it_matters=(
            "Potential billing exposure requires separate authorization; identification is not recovery."
            if impact
            and (impact.get("difference") not in (None, "0.00") or "proposed_credit" in impact)
            else "Reliable billing depends on consistent source records and appropriate contractual authority. A completed check does not change financial records."
        ),
    )


def queue_counts(items):
    counts = Counter(bucket(w) for w in items)
    return {
        "total": len(items),
        "needs_maya": counts["Needs My Attention"],
        "completed": counts["Completed"],
        "awaiting_review": counts["Awaiting My Review"],
        "review_rejected": counts["Review Rejected"],
        "reviewed_closed": sum(
            w["status"] == "Closed" and w.get("review", {}).get("decision") == "approve"
            for w in items
        ),
        "awaiting_sarah": sum(w["status"] == "Escalated" for w in items),
        "management_oversight": sum(
            bool(w.get("oversight")) or w["status"] == "Escalated" for w in items
        ),
        "awaiting_finance": sum(w["status"] == "Awaiting Financial Review" for w in items),
        "awaiting_evidence": sum(w["status"] == "Awaiting Evidence" for w in items),
        "awaiting_others": counts["Awaiting Others"],
    }


def scenarios(items):
    candidates = {"routine": [], "discrepancy": [], "ambiguity": []}
    for w in items:
        impact = w.get("financial_impact")
        if w["category"] == "contract_price_validation" and impact:
            candidates[
                "routine" if Decimal(impact.get("difference", "0")) == 0 else "discrepancy"
            ].append(w)
        if w["category"] in ("contract_conflict", "amendment_review", "missing_documentation"):
            candidates["ambiguity"].append(w)
    labels = {
        "routine": "Routine invoice check",
        "discrepancy": "Billing discrepancy",
        "ambiguity": "Conflicting contract terms",
    }
    return [
        dict(
            key=k,
            label=labels[k],
            work_item_id=(
                sorted(
                    v,
                    key=lambda w: (
                        bool(w.get("last_disposition")),
                        w["status"] == "Closed",
                        0 if w["category"] == "contract_conflict" else 1,
                        w["work_item_id"],
                    ),
                )[0]["work_item_id"]
                if v
                else None
            ),
        )
        for k, v in candidates.items()
    ]


def walkthrough(detail):
    from .human_review import label as lifecycle_label

    work = detail["item"]
    documents = detail["documents"]
    cards = []
    manual = []
    relevant = {
        "contract": [
            "Contract status",
            "Effective date",
            "Term end",
            "Billing cadence",
            "Subscription amount",
            "Discount percent",
            "Discount valid through",
            "Tax rate",
            "Unit rate",
            "Included quantity",
            "Implementation fee",
        ],
        "pricing": ["Subscription amount", "Billing cadence", "Discount percent", "Tax rate"],
        "invoice": [
            "Period start",
            "Period end",
            "Quantity",
            "Service subtotal",
            "Tax amount",
            "Invoice total",
        ],
        "usage": ["Period start", "Period end", "Quantity"],
        "amendment": ["Contract status", "Effective date", "Subscription amount", "Supersedes"],
        "receipt": ["Payment amount", "Applied invoice", "Allocated amount"],
    }
    for doc in sorted(
        documents,
        key=lambda d: (
            {"contract": 0, "pricing": 1, "amendment": 2, "invoice": 3}.get(d["document_type"], 4),
            d["document_id"],
        ),
    ):
        facts = [
            dict(field=k, value=doc["fields"][k], spans=doc["evidence"].get(k, []))
            for k in relevant.get(doc["document_type"], list(doc["fields"])[:5])
            if k in doc["fields"]
        ]
        cards.append(
            dict(
                document_id=doc["document_id"],
                file_hash=doc["file_hash"],
                document_type=doc["document_type"],
                facts=facts,
                errors=doc["errors"],
            )
        )
        manual.append(
            dict(
                title="Open " + doc["document_type"].replace("_", " "),
                description="Locate the applicable terms, period or allocation in "
                + doc["document_id"]
                + ".",
                file_hash=doc["file_hash"],
                document_id=doc["document_id"],
            )
        )
    manual.extend(
        [
            dict(
                title="Cross-reference the business records",
                description="Compare the applicable dates, authority and extracted amounts. Conflicting authority must remain unresolved.",
            ),
            dict(
                title="Document the result and choose the next decision",
                description="Validate the check, investigate a difference, or request separately authorized review.",
            ),
        ]
    )
    events = work["event_history"]
    recorded = [e for e in events if e.get("type") == "automatic_disposition_applied"]
    latest = recorded[-1]["operation_id"] if recorded else None
    history = [e for e in events if latest and e.get("operation_id") == latest]
    proof = next(
        (e for e in reversed(history) if e.get("type") == "evidence_validation_recorded"), None
    )
    return dict(
        item=work,
        documents=cards,
        manual_steps=manual,
        manual_role=work["original_functional_owner"],
        manual_label="Illustrative traditional workflow — not a measured employee time study",
        business=business(work),
        financial_comparison=work.get("financial_impact"),
        recorded=bool(recorded),
        recorded_operation_id=latest,
        processing_events=history,
        validation=proof,
        read_only=detail["read_only"],
        can_process=not recorded
        and not detail["read_only"]
        and "auto" in detail["permitted_actions"],
        processing_label="Automated document analysis and rule-based processing — no live AI model",
        human_review=work.get("review"),
        outcome=dict(
            lifecycle_label=lifecycle_label(work),
            status=work["status"],
            administratively_completed=work["status"] == "Closed",
            waiting_on=business(work)["waiting_on"],
            financial_action_executed=False,
        ),
    )
