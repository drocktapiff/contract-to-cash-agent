"""Allowlisted browser projections. No raw provider output, arguments or reasoning."""

from .models import EventView

LABELS = {
    "human_resolution.resolve": "Documented human resolution saved; continuation requires separate authorization",
    "human_resolution.escalate": "Clarification requested; dependent calculations remain paused",
    "human_resolution.dismiss": "Hypothesis dismissed; original evidence retained",
    "continuation.authorized": "Bounded new continuation explicitly authorized",
    "guidance.prepared": "Procedural guidance saved from the historical comparison; no model request",
    "recommendation.created": "Evidence-grounded model suggestion saved",
    "investigation.started": "Investigation started",
    "screening.completed": "Structured customer screening finished",
    "evidence.retrieved": "Source evidence retrieved",
    "evidence.updated": "Source revision changed; prior verification invalidated",
    "finding.proposed": "Finding proposed — interpretation requires review",
    "finding.verified": "Evidence-backed finding verified",
    "finding.retracted": "Finding retracted",
    "human_review.requested": "Human judgment requested",
    "human_review.decided": "Operator review decision recorded",
    "api.requested": "Responses request started",
    "api.completed": "Responses exchange completed",
    "api.failed": "Responses request failed; details withheld",
    "tool.failed": "Tool failed; affected conclusions remain unverified",
    "investigation.error": "Investigation interrupted",
}


def event_view(event):
    payload = event.get("payload", {})
    tool = payload.get("tool") if event["type"].startswith("tool.") else None
    finding = payload.get("finding", {})
    review = payload.get("review", {})
    decision = payload if event["type"] == "human_review.decided" or event["type"].startswith("human_resolution.") else {}
    summary = LABELS.get(event["type"], "Recorded activity")
    if event["type"] == "tool.requested":
        summary = "Model selected " + str(tool)
    elif event["type"] == "tool.completed":
        summary = "Tool completed: " + str(tool)
    elif event["type"] == "investigation.completed":
        summary = (
            "Investigation "
            + str(payload.get("status", "incomplete"))
            + ": "
            + str(payload.get("reason", "unknown"))
        )
    return EventView(
        sequence=event["sequence"],
        timestamp=event["timestamp"],
        type=event["type"],
        actor=event.get("actor", "orchestrator"),
        summary=summary,
        tool=tool,
        customer_ids=finding.get("customer_ids", []),
        finding_id=finding.get("finding_id", review.get("finding_id", decision.get("finding_id"))),
        decision=decision.get("decision", decision.get("action")),
        reviewer=decision.get("reviewer"),
        rationale=decision.get("rationale"),
        finding_version=decision.get("finding_version"),
        data_revision=payload.get(
            "data_revision", finding.get("data_revision", review.get("data_revision"))
        ),
    )


def finding_view(finding):
    keys = (
        "finding_id",
        "customer_ids",
        "state",
        "version",
        "evidence_ids",
        "evidence_verified",
        "comparisons",
        "comparison",
        "pattern",
        "model_hypothesis",
        "data_revision",
        "origin",
        "requires_revalidation",
        "recommendation",
        "recommendation_history",
    )
    return {key: finding[key] for key in keys if key in finding}


def review_view(review):
    keys = (
        "finding_id",
        "finding_version",
        "action",
        "status",
        "data_revision",
        "decision",
        "boundary",
    )
    return {key: review[key] for key in keys if key in review}


def evidence_from_events(events, evidence_ids):
    wanted = set(evidence_ids)
    sources = {}
    for event in events:
        if event["type"] != "tool.completed":
            continue
        payload = event["payload"]
        result = payload.get("result", {})
        if payload["tool"] == "get_document" and result["document_id"] in wanted:
            sources[result["document_id"]] = {
                k: result[k] for k in ("document_id", "customer_id", "sha256", "text")
            }
        if payload["tool"] == "get_invoices":
            for row in result:
                if row["invoice_id"] in wanted:
                    sources[row["invoice_id"]] = dict(
                        document_id=row["invoice_id"], kind="invoice", record=row
                    )
        if payload["tool"] == "get_customer_evidence":
            for case in result["cases"]:
                for doc in case["documents"]:
                    if doc["document_id"] in wanted and "text" in doc:
                        sources[doc["document_id"]] = {
                            k: doc[k] for k in ("document_id", "customer_id", "sha256", "text")
                        }
                for row in case["invoices"]:
                    if row["invoice_id"] in wanted:
                        sources[row["invoice_id"]] = dict(
                            document_id=row["invoice_id"], kind="invoice", record=row
                        )
    return [sources[key] for key in sorted(sources)]
