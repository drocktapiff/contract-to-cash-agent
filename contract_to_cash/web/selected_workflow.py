"""One server-authoritative selected command; per-item savepoints, no financial writes."""

import hashlib
import json
from time import perf_counter
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .document_workspace import (
    WorkspaceCommand,
    encoded,
    now,
    recommendation,
    financial_referral_supported,
)
from .store import StoreError
from .work_presentation import queue_counts


class SelectedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^WI-[a-f0-9]{24}$")
    version: int = Field(ge=1, strict=True)
    note: str = Field(default="", max_length=1000)


class SelectedCommand(WorkspaceCommand):
    expected_session: str = Field(pattern=r"^[a-f0-9]{32}$")
    selected: list[SelectedItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({s.id for s in self.selected}) != len(self.selected):
            raise ValueError("Selected IDs must be unique")
        return self


def can_complete(work, fresh):
    return bool(
        work["status"] not in ("Closed", "Escalated", "Awaiting Financial Review")
        and not work.get("oversight")
        and not work.get("recommendation_rejected")
        and fresh
        and fresh["automation_eligible"]
        and fresh["automatic_closure_allowed"]
        and not fresh["human_review_required"]
    )


def selected_operation(ws, sid, action, body):
    if action not in ("close", "escalate"):
        raise StoreError(422, "Unsupported selected action")
    if (
        not body.actor.strip()
        or not body.rationale.strip()
        or body.confirmation != "ADMINISTRATIVE WORKFLOW ONLY"
    ):
        raise StoreError(
            422, "Attribution, rationale and administrative-only confirmation required"
        )
    fingerprint = hashlib.sha256(
        encoded({"kind": "selected", "action": action, "body": body.model_dump()}).encode()
    ).hexdigest()
    with ws.guard():
        if ws.active() != sid or body.expected_session != sid:
            raise StoreError(409, "Selection belongs to a different active session; refresh")
        database = ws.directory(sid) / "journal.sqlite3"
        started = perf_counter()
        with ws.database(database) as conn:
            old = ws.rows(
                conn, "SELECT * FROM workflow_operations WHERE id=?", (body.operation_id,)
            )
            if old and old[0]["fingerprint"] != fingerprint:
                raise StoreError(409, "Operation ID already used for different input")
            if old and old[0]["status"] == "completed":
                return json.loads(old[0]["result"])
            stub = {
                "kind": "selected",
                "session_id": sid,
                "action": action,
                "operation_id": body.operation_id,
                "status": "running",
            }
            with conn:
                ws.execute(conn, "BEGIN IMMEDIATE")
                if old:
                    ws.event(
                        conn,
                        sid,
                        None,
                        "operation_retried",
                        ws.interaction_kind,
                        body.actor,
                        body.rationale,
                        body.operation_id,
                    )
                else:
                    ws.execute(
                        conn,
                        "INSERT INTO workflow_operations VALUES (?,?,?,?)",
                        (body.operation_id, fingerprint, "running", encoded(stub)),
                    )
                    ws.event(
                        conn,
                        sid,
                        None,
                        "human_command_requested",
                        ws.interaction_kind,
                        body.actor,
                        body.rationale,
                        body.operation_id,
                        details={
                            "mode": "selected_" + action,
                            "selected": [s.model_dump() for s in body.selected],
                            "identity_verified": False,
                        },
                    )
                ws.execute(
                    conn,
                    "UPDATE workflow_operations SET status='running',result=? WHERE id=?",
                    (encoded(stub), body.operation_id),
                )
            try:
                current = ws.revalidate(sid)
                outcomes = []
                with conn:
                    ws.execute(conn, "BEGIN IMMEDIATE")
                    for choice in body.selected:
                        ws.execute(conn, "SAVEPOINT selected_item")
                        try:
                            row = ws.rows(
                                conn, "SELECT body FROM work_items WHERE id=?", (choice.id,)
                            )
                            if not row:
                                raise StoreError(404, "Item is not part of this session")
                            work = json.loads(row[0][0])
                            before = work["status"]
                            fresh = current.get(choice.id)
                            if work["version"] != choice.version:
                                raise StoreError(
                                    409, "Item version changed; review its current state"
                                )
                            if work["status"] == "Closed":
                                outcome = "skipped"
                                reason = "Already completed; no second closure or oversight handoff"
                            elif action == "escalate" and (
                                work.get("oversight") or work["status"] == "Escalated"
                            ):
                                outcome = "handoff_reused"
                                reason = "Sarah already has this handoff; decision authority is unchanged"
                            elif not fresh:
                                work.update(
                                    status="Awaiting Evidence",
                                    automation_eligible=False,
                                    automatic_closure_allowed=False,
                                    human_review_required=True,
                                    financial_impact=None,
                                    evidence_current=False,
                                    eligibility_reason="Original evidence is missing, changed, or inconsistent; obtain valid source records before proceeding",
                                )
                                ws.event(
                                    conn,
                                    sid,
                                    work,
                                    "awaiting_evidence",
                                    "deterministic_automation",
                                    "Rules baseline",
                                    work["eligibility_reason"],
                                    body.operation_id,
                                    before=before,
                                    after=work["status"],
                                )
                                ws.event(
                                    conn,
                                    sid,
                                    work,
                                    "evidence_validation_recorded",
                                    "deterministic_automation",
                                    "Rules baseline",
                                    "Source integrity or reconciliation validation failed",
                                    body.operation_id,
                                    details={
                                        "evidence_current": False,
                                        "financial_comparison": None,
                                        "automation_eligible": False,
                                        "eligibility_reason": work["eligibility_reason"],
                                    },
                                )
                                ws.event(
                                    conn,
                                    sid,
                                    work,
                                    "automatic_disposition_applied",
                                    "deterministic_automation",
                                    "Rules baseline",
                                    "Blocked pending valid evidence; no closure or handoff",
                                    body.operation_id,
                                    before=before,
                                    after=work["status"],
                                )
                                outcome = "blocked"
                                reason = work["eligibility_reason"]
                            else:
                                work.update(
                                    evidence_current=True,
                                    financial_impact=fresh["financial_impact"],
                                    eligibility_reason=fresh["eligibility_reason"],
                                )
                                ws.event(
                                    conn,
                                    sid,
                                    work,
                                    "evidence_validation_recorded",
                                    "deterministic_automation",
                                    "Rules baseline",
                                    "Actual PDFs re-extracted and reconciled",
                                    body.operation_id,
                                    details={
                                        "evidence_current": True,
                                        "source_hashes": sorted(work["supporting_facts"]),
                                        "financial_comparison": fresh["financial_impact"],
                                        "automation_eligible": can_complete(work, fresh),
                                        "eligibility_reason": fresh["eligibility_reason"],
                                        "parser": "pypdf text extraction",
                                        "reconciliation": "Stage 1 deterministic Python rules",
                                    },
                                )
                                if action == "close":
                                    if can_complete(work, fresh):
                                        ws.event(
                                            conn,
                                            sid,
                                            work,
                                            "routine_processing_started",
                                            "deterministic_automation",
                                            "Rules baseline",
                                            body.rationale,
                                            body.operation_id,
                                            before=before,
                                        )
                                        work.update(
                                            status="Closed",
                                            automation_eligible=True,
                                            automatic_closure_allowed=True,
                                            human_review_required=False,
                                            last_disposition="routine",
                                        )
                                        ws.event(
                                            conn,
                                            sid,
                                            work,
                                            "routine_processing_completed",
                                            "deterministic_automation",
                                            "Rules baseline",
                                            "Supported deterministic read-only check passed",
                                            body.operation_id,
                                            before=before,
                                            after="Closed",
                                        )
                                        ws.event(
                                            conn,
                                            sid,
                                            work,
                                            "administratively_closed",
                                            "deterministic_automation",
                                            "Rules baseline",
                                            "Administrative check only; no financial action authorized or executed",
                                            body.operation_id,
                                            before=before,
                                            after="Closed",
                                        )
                                        outcome = "completed"
                                        reason = "Evidence-validated administrative check completed"
                                    else:
                                        work.update(
                                            automation_eligible=False,
                                            automatic_closure_allowed=False,
                                            human_review_required=True,
                                            last_disposition="review",
                                        )
                                        ws.event(
                                            conn,
                                            sid,
                                            work,
                                            "human_review_requested",
                                            "deterministic_automation",
                                            "Rules baseline",
                                            "Evidence checked; the existing human or authority requirement remains open",
                                            body.operation_id,
                                            before=before,
                                            after=work["status"],
                                        )
                                        outcome = "requires_review"
                                        reason = "Human review, existing handoff or rejection safeguard prevents automatic closure"
                                else:
                                    # A supported potential correction still requires Finance, even if not yet referred.
                                    if (
                                        financial_referral_supported(work)
                                        and work["status"] != "Awaiting Evidence"
                                    ):
                                        work.update(
                                            status="Awaiting Financial Review",
                                            assigned_owner="Authorized financial review team",
                                        )
                                    # Oversight is independent of Finance/evidence decision ownership.
                                    if work["status"] not in (
                                        "Awaiting Financial Review",
                                        "Awaiting Evidence",
                                        "Escalated",
                                    ) or work["category"] in (
                                        "contract_conflict",
                                        "amendment_review",
                                    ):
                                        work["status"] = "Escalated"
                                        work["assigned_owner"] = "Sarah Chen"
                                    decision = (
                                        "Finance"
                                        if work["status"] == "Awaiting Financial Review"
                                        else (
                                            "Evidence provider / Contract Administration"
                                            if work["status"] == "Awaiting Evidence"
                                            else (
                                                "Sarah / Contract Administration"
                                                if work["category"]
                                                in (
                                                    "contract_conflict",
                                                    "amendment_review",
                                                    "missing_documentation",
                                                )
                                                else "Sarah / Revenue Operations"
                                            )
                                        )
                                    )
                                    work.update(
                                        case_owner="Maya Tremblay",
                                        management_oversight_owner="Sarah Chen",
                                        current_decision_owner=decision,
                                        waiting_on_department=decision,
                                        automation_eligible=False,
                                        automatic_closure_allowed=False,
                                        human_review_required=True,
                                    )
                                    work["oversight"] = {
                                        "id": uuid4().hex,
                                        "owner": "Sarah Chen",
                                        "requested_by": body.actor,
                                        "requested_at": now(),
                                        "reason": body.rationale,
                                        "item_note": choice.note,
                                        "operation_id": body.operation_id,
                                        "decision_owner": decision,
                                        "financial_authority_transferred": False,
                                    }
                                    ws.event(
                                        conn,
                                        sid,
                                        work,
                                        "human_decision_recorded",
                                        ws.interaction_kind,
                                        body.actor,
                                        body.rationale,
                                        body.operation_id,
                                        before=before,
                                        details={
                                            "action": "management_oversight",
                                            "note": choice.note,
                                            "expected_version": choice.version,
                                            "identity_verified": False,
                                        },
                                    )
                                    ws.event(
                                        conn,
                                        sid,
                                        work,
                                        "escalated",
                                        "deterministic_automation",
                                        "Internal workflow",
                                        body.rationale,
                                        body.operation_id,
                                        before=before,
                                        after=work["status"],
                                        details={
                                            "handoff": work["oversight"],
                                            "financial_authority_transferred": False,
                                        },
                                    )
                                    outcome = "handoff_created"
                                    reason = "Sarah received management oversight; the required decision remains separately authorized"
                                if outcome in ("completed", "handoff_created", "requires_review"):
                                    ws.event(
                                        conn,
                                        sid,
                                        work,
                                        "automatic_disposition_applied",
                                        "deterministic_automation",
                                        "Rules baseline",
                                        reason,
                                        body.operation_id,
                                        before=before,
                                        after=work["status"],
                                    )
                            if outcome not in ("skipped", "handoff_reused"):
                                work.update(
                                    version=work["version"] + 1,
                                    updated_at=now(),
                                    recommendation=recommendation(work),
                                )
                                ws.execute(
                                    conn,
                                    "UPDATE work_items SET body=? WHERE id=?",
                                    (encoded(work), choice.id),
                                )
                            outcomes.append(
                                dict(
                                    id=choice.id,
                                    outcome=outcome,
                                    reason=reason,
                                    status=work["status"],
                                    version=work["version"],
                                    decision_owner=work.get("current_decision_owner"),
                                    oversight_id=work.get("oversight", {}).get("id"),
                                )
                            )
                            ws.execute(conn, "RELEASE selected_item")
                        except Exception as exc:
                            ws.execute(conn, "ROLLBACK TO selected_item")
                            ws.execute(conn, "RELEASE selected_item")
                            blocked = isinstance(exc, StoreError)
                            outcomes.append(
                                dict(
                                    id=choice.id,
                                    outcome="blocked" if blocked else "failed",
                                    reason=(
                                        exc.message
                                        if blocked
                                        else "Processing failed safely for this item; retained evidence and prior state are unchanged"
                                    ),
                                )
                            )
                            ws.event(
                                conn,
                                sid,
                                None,
                                "selected_item_blocked" if blocked else "processing_failed",
                                "deterministic_automation",
                                "Rules baseline",
                                outcomes[-1]["reason"],
                                body.operation_id,
                                details={"item_id": choice.id, "error_class": type(exc).__name__},
                            )
                    all_work = ws.works(conn)
                    success_ids = {
                        r["id"]
                        for r in outcomes
                        if r["outcome"] in ("handoff_created", "handoff_reused")
                    }
                    result = dict(
                        kind="selected",
                        session_id=sid,
                        action=action,
                        status="completed",
                        operation_id=body.operation_id,
                        total_examined=len(outcomes),
                        per_item=outcomes,
                        checks_completed=sum(r["outcome"] == "completed" for r in outcomes),
                        requires_review=sum(r["outcome"] == "requires_review" for r in outcomes),
                        handoffs_created=sum(r["outcome"] == "handoff_created" for r in outcomes),
                        handoffs_reused=sum(r["outcome"] == "handoff_reused" for r in outcomes),
                        blocked=sum(r["outcome"] == "blocked" for r in outcomes),
                        failed=sum(r["outcome"] == "failed" for r in outcomes),
                        skipped=sum(r["outcome"] == "skipped" for r in outcomes),
                        awaiting_finance=sum(
                            w["work_item_id"] in success_ids
                            and w["status"] == "Awaiting Financial Review"
                            for w in all_work
                        ),
                        awaiting_evidence=sum(
                            w["work_item_id"] in success_ids and w["status"] == "Awaiting Evidence"
                            for w in all_work
                        ),
                        sarah_direct=sum(
                            w["work_item_id"] in success_ids and w["status"] == "Escalated"
                            for w in all_work
                        ),
                        queue_outcome=queue_counts(all_work),
                        duration_seconds=round(perf_counter() - started, 6),
                    )
                    result.update(
                        automatically_closed=result["checks_completed"],
                        escalated_to_sarah=result["handoffs_created"],
                        human_queue_remaining=sum(w["status"] != "Closed" for w in all_work),
                        items_requiring_review=sum(
                            w["human_review_required"] and w["status"] != "Closed" for w in all_work
                        ),
                    )
                    result["partial"] = bool(result["blocked"] or result["failed"])
                    actual_events = [
                        json.loads(r[0])
                        for r in ws.rows(
                            conn,
                            "SELECT body FROM workflow_events WHERE json_extract(body,'$.operation_id')=?",
                            (body.operation_id,),
                        )
                    ]
                    result["financial_actions_executed"] = sum(
                        bool(e["financial_action_executed"]) for e in actual_events
                    )
                    ws.execute(
                        conn,
                        "UPDATE workflow_operations SET status='completed',result=? WHERE id=?",
                        (encoded(result), body.operation_id),
                    )
                return result
            except BaseException as exc:
                with conn:
                    ws.execute(
                        conn,
                        "UPDATE workflow_operations SET status='interrupted' WHERE id=?",
                        (body.operation_id,),
                    )
                    ws.event(
                        conn,
                        sid,
                        None,
                        "processing_failed",
                        "deterministic_automation",
                        "Recovery",
                        "Selected operation rolled back; retry the same operation ID. No partial success was committed.",
                        body.operation_id,
                        details={"error_class": type(exc).__name__},
                    )
                raise
