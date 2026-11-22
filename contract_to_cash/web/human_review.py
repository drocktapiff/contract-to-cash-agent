"""Two-stage administrative completion. No financial or contractual authorization."""

import hashlib
import json
from time import perf_counter
from uuid import uuid4
from typing import Literal
from pydantic import Field, model_validator
from .document_workspace import WorkspaceCommand, encoded, now
from .selected_workflow import SelectedItem
from .store import StoreError

PENDING = "Awaiting Maya Review"
REJECTED = "Review Rejected — Needs Investigation"


class ReviewItem(SelectedItem):
    evidence_hashes: list[str] = Field(min_length=1, max_length=50)


class ReviewCommand(WorkspaceCommand):
    expected_session: str = Field(pattern=r"^[a-f0-9]{32}$")
    selected: list[ReviewItem] = Field(min_length=1, max_length=500)
    decision: Literal["approve", "reject", "evidence", "escalate"]
    attestation: Literal["individual", "bulk"]
    acknowledge_review: Literal[True]

    @model_validator(mode="after")
    def valid_selection(self):
        if len({x.id for x in self.selected}) != len(self.selected):
            raise ValueError("Duplicate review IDs")
        if self.attestation == "individual" and len(self.selected) != 1:
            raise ValueError("Individual review requires exactly one item")
        if self.attestation == "bulk" and self.decision != "approve":
            raise ValueError("Only low-risk approval supports bulk attestation")
        return self


def tables(ws, conn):
    ws.execute(
        conn,
        "CREATE TABLE IF NOT EXISTS human_review_decisions (id TEXT PRIMARY KEY, preparation TEXT UNIQUE NOT NULL, body TEXT NOT NULL)",
    )
    for verb in ("UPDATE", "DELETE"):
        ws.execute(
            conn,
            f"CREATE TRIGGER IF NOT EXISTS human_reviews_no_{verb.lower()} BEFORE {verb} ON human_review_decisions BEGIN SELECT RAISE(ABORT, 'Review decisions are immutable'); END",
        )


def prepare(ws, conn, sid, work, fresh, body):
    """Called only after shared deterministic eligibility checks; never closes a case."""
    before = work["status"]
    work.update(
        status=PENDING,
        automation_eligible=False,
        automatic_closure_allowed=False,
        human_review_required=True,
        last_disposition="prepared",
    )
    result = dict(
        prepared_at=now(),
        operation_id=body.operation_id,
        source_version=work["version"],
        prepared_version=work["version"] + 1,
        evidence_hashes=sorted(work["supporting_facts"]),
        financial_comparison=fresh["financial_impact"],
        mechanism="Deterministic Python PDF validation and reconciliation; no live model",
        finding="Supported read-only administrative check passed; human verification is required.",
    )
    event = ws.event(
        conn,
        sid,
        work,
        "automated_check_prepared",
        "deterministic_automation",
        "Ledgerline rules",
        result["finding"],
        body.operation_id,
        before=before,
        after=PENDING,
        details=dict(result),
    )
    result["event_id"] = event["id"]
    work["automated_result"] = result
    return result


def eligibility(work, fresh, version=None):
    if version is not None and work["version"] != version:
        return "Item version changed; inspect the current result"
    if work.get("review", {}).get("decision") == "reject" or work["status"] == REJECTED:
        return "Previously rejected; individual investigation is required"
    if work["status"] == "Closed":
        return (
            "Already closed; legacy closures cannot be retroactively human-approved"
            if not work.get("review")
            else "Already reviewed and closed"
        )
    if work["status"] != PENDING or not work.get("automated_result"):
        return "No pending automated result; individual investigation or separate authority is required"
    if work.get("oversight") or work.get("recommendation_rejected"):
        return "Management handoff or rejected recommendation requires investigation"
    if (
        not fresh
        or not fresh["automation_eligible"]
        or not fresh["automatic_closure_allowed"]
        or fresh["human_review_required"]
    ):
        return "Current evidence is changed, uncertain or not a low-risk administrative check"
    result = work["automated_result"]
    if (
        work["version"] != result["prepared_version"]
        or sorted(work["supporting_facts"]) != result["evidence_hashes"]
        or fresh["financial_impact"] != result["financial_comparison"]
    ):
        return "Automated result or evidence version changed; revalidation is required"
    return None


def preparation_matches(work, event):
    result = work.get("automated_result") or {}
    return bool(
        event
        and event["type"] == "automated_check_prepared"
        and event["actor_kind"] == "deterministic_automation"
        and event["item_id"] == work["work_item_id"]
        and event["operation_id"] == result.get("operation_id")
        and event["source_hashes"] == result.get("evidence_hashes")
        and event["details"].get("source_version") == result.get("source_version")
        and event["details"].get("prepared_version") == result.get("prepared_version")
        and event["details"].get("financial_comparison") == result.get("financial_comparison")
    )


def preview(ws, sid, body):
    snap = ws.snapshot(sid)
    works = {w["work_item_id"]: w for w in snap["items"]}
    fresh = ws.revalidate(sid)
    with ws.database(ws.directory(sid) / "journal.sqlite3") as conn:
        proofs = {
            e["id"]: e
            for e in (
                json.loads(r[0])
                for r in ws.rows(
                    conn,
                    "SELECT body FROM workflow_events WHERE json_extract(body,'$.type')='automated_check_prepared'",
                )
            )
        }
    rows = []
    for choice in body.selected:
        w = works.get(choice.id)
        reason = (
            eligibility(w, fresh.get(choice.id), choice.version)
            if w
            else "Item does not belong to this session"
        )
        if reason is None and not preparation_matches(
            w, proofs.get(w["automated_result"]["event_id"])
        ):
            reason = "Prepared result has no matching immutable automation event"
        rows.append(
            dict(
                id=choice.id,
                version=w["version"] if w else choice.version,
                eligible=reason is None,
                reason=reason,
                evidence_hashes=sorted(w["supporting_facts"]) if w else [],
                automated_result=w.get("automated_result") if w else None,
                status=w["status"] if w else None,
                previously_rejected=bool(
                    w
                    and (w.get("review", {}).get("decision") == "reject" or w["status"] == REJECTED)
                ),
                source_changed=bool(w and choice.id not in fresh),
                requires_individual=bool(w and reason and w["status"] != "Closed"),
                documents=(
                    ws.detail(sid, choice.id)["documents"] if w and len(body.selected) == 1 else []
                ),
            )
        )
    return dict(
        session_id=sid,
        read_only=snap["read_only"],
        selected=len(rows),
        eligible=sum(r["eligible"] for r in rows),
        excluded=sum(not r["eligible"] for r in rows),
        changed_evidence=sum(r["source_changed"] for r in rows),
        previously_rejected=sum(r["previously_rejected"] for r in rows),
        individual_review_required=sum(r["requires_individual"] for r in rows),
        items=rows,
        methodology="Only current low-risk prepared results can be approved. Bulk attestation does not claim individual inspection.",
    )


def review(ws, sid, body):
    if (
        body.confirmation != "ADMINISTRATIVE WORKFLOW ONLY"
        or not body.actor.strip()
        or len(body.rationale.strip()) < 5
    ):
        raise StoreError(422, "Explicit attribution, rationale and review acknowledgement required")
    fingerprint = hashlib.sha256(
        encoded({"review": body.model_dump(mode="json")}).encode()
    ).hexdigest()
    started = perf_counter()
    with ws.guard():
        if ws.active() != sid or body.expected_session != sid:
            raise StoreError(409, "Review belongs to another active session")
        with ws.database(ws.directory(sid) / "journal.sqlite3") as conn:
            tables(ws, conn)
            old = ws.rows(
                conn, "SELECT * FROM workflow_operations WHERE id=?", (body.operation_id,)
            )
            if old and old[0]["fingerprint"] != fingerprint:
                raise StoreError(409, "Review operation ID reused for different input")
            if old and old[0]["status"] == "completed":
                return json.loads(old[0]["result"])
            with conn:
                if not old:
                    ws.execute(
                        conn,
                        "INSERT INTO workflow_operations VALUES (?,?,?,NULL)",
                        (body.operation_id, fingerprint, "running"),
                    )
                else:
                    ws.execute(
                        conn,
                        "UPDATE workflow_operations SET status='running' WHERE id=?",
                        (body.operation_id,),
                    )
                ws.event(
                    conn,
                    sid,
                    None,
                    "human_review_requested",
                    ws.interaction_kind,
                    body.actor,
                    body.rationale,
                    body.operation_id,
                    details={
                        "attestation": body.attestation,
                        "decision": body.decision,
                        "selected": [x.model_dump() for x in body.selected],
                    },
                )
            try:
                fresh = ws.revalidate(sid)
                rows = []
                with conn:
                    ws.execute(conn, "BEGIN IMMEDIATE")
                    for choice in body.selected:
                        ws.execute(conn, "SAVEPOINT human_review_item")
                        try:
                            found = ws.rows(
                                conn, "SELECT body FROM work_items WHERE id=?", (choice.id,)
                            )
                            if not found:
                                raise StoreError(404, "Unknown session item")
                            w = json.loads(found[0][0])
                            before = w["status"]
                            reason = eligibility(w, fresh.get(choice.id), choice.version)
                            # Approvals need full current low-risk proof. Rejection/evidence/escalation
                            # can retain a now-invalid result, but must bind its original evidence.
                            if body.decision == "approve" and reason:
                                raise StoreError(409, reason)
                            if body.decision != "approve" and (
                                w["version"] != choice.version
                                or w["status"] != PENDING
                                or not w.get("automated_result")
                            ):
                                raise StoreError(409, "No current pending result to review")
                            if len(set(choice.evidence_hashes)) != len(
                                choice.evidence_hashes
                            ) or sorted(choice.evidence_hashes) != sorted(
                                w["automated_result"]["evidence_hashes"]
                            ):
                                raise StoreError(
                                    422,
                                    "Attest every presented source hash; foreign or missing evidence is not accepted",
                                )
                            proof = ws.rows(
                                conn,
                                "SELECT body FROM workflow_events WHERE json_extract(body,'$.id')=?",
                                (w["automated_result"]["event_id"],),
                            )
                            if not preparation_matches(
                                w, json.loads(proof[0][0]) if proof else None
                            ):
                                raise StoreError(
                                    409,
                                    "Prepared result has no matching immutable automation event",
                                )
                            decision = dict(
                                decision=body.decision,
                                attestation=(
                                    "bulk_attested" if body.attestation == "bulk" else "individual"
                                ),
                                actor=body.actor,
                                rationale=body.rationale,
                                at=now(),
                                reviewed_version=w["version"],
                                evidence_hashes=choice.evidence_hashes,
                                preparation_event_id=w["automated_result"]["event_id"],
                                preparation_operation_id=w["automated_result"]["operation_id"],
                                financial_authorization=False,
                                identity_verified=False,
                            )
                            if body.decision == "approve":
                                after = "Closed"
                                kind = "human_review_approved"
                            elif body.decision == "reject":
                                after = REJECTED
                                kind = "human_review_rejected"
                                w["recommendation_rejected"] = True
                            elif body.decision == "evidence":
                                after = "Awaiting Evidence"
                                kind = "human_review_evidence_requested"
                            else:
                                after = "Escalated"
                                kind = "human_review_escalated"
                                w["oversight"] = dict(
                                    id=uuid4().hex,
                                    owner="Sarah Chen",
                                    requested_by=body.actor,
                                    requested_at=now(),
                                    reason=body.rationale,
                                    operation_id=body.operation_id,
                                    decision_owner="Sarah / Contract Administration",
                                    financial_authority_transferred=False,
                                )
                                w.update(
                                    case_owner="Maya Tremblay",
                                    management_oversight_owner="Sarah Chen",
                                    current_decision_owner="Sarah / Contract Administration",
                                    waiting_on_department="Sarah / Contract Administration",
                                )
                            decision.update(
                                session_id=sid, item_id=choice.id, before=before, after=after
                            )
                            w.update(
                                status=after,
                                review=decision,
                                version=w["version"] + 1,
                                updated_at=now(),
                                automation_eligible=False,
                                automatic_closure_allowed=False,
                                human_review_required=after != "Closed",
                            )
                            event = ws.event(
                                conn,
                                sid,
                                w,
                                kind,
                                ws.interaction_kind,
                                body.actor,
                                body.rationale,
                                body.operation_id,
                                before=before,
                                after=after,
                                details=dict(decision),
                            )
                            decision["event_id"] = event["id"]
                            ws.execute(
                                conn,
                                "INSERT INTO human_review_decisions VALUES (?,?,?)",
                                (event["id"], decision["preparation_event_id"], encoded(decision)),
                            )
                            if body.decision == "escalate":
                                ws.event(
                                    conn,
                                    sid,
                                    w,
                                    "management_handoff_received",
                                    "deterministic_automation",
                                    "Internal management inbox",
                                    body.rationale,
                                    body.operation_id,
                                    before=after,
                                    after=after,
                                    details={"handoff": w["oversight"]},
                                )
                            ws.execute(
                                conn,
                                "UPDATE work_items SET body=? WHERE id=?",
                                (encoded(w), choice.id),
                            )
                            rows.append(
                                dict(
                                    id=choice.id,
                                    outcome=body.decision,
                                    status=after,
                                    review=decision,
                                )
                            )
                            ws.execute(conn, "RELEASE human_review_item")
                        except Exception as exc:
                            ws.execute(conn, "ROLLBACK TO human_review_item")
                            ws.execute(conn, "RELEASE human_review_item")
                            rows.append(
                                dict(
                                    id=choice.id,
                                    outcome="excluded" if isinstance(exc, StoreError) else "failed",
                                    reason=(
                                        exc.message
                                        if isinstance(exc, StoreError)
                                        else "Local review persistence failed; prior state retained"
                                    ),
                                )
                            )
                            ws.event(
                                conn,
                                sid,
                                None,
                                "human_review_blocked",
                                ws.interaction_kind,
                                body.actor,
                                rows[-1]["reason"],
                                body.operation_id,
                                details={"item_id": choice.id},
                            )
                    result = dict(
                        kind="human_review",
                        operation_id=body.operation_id,
                        session_id=sid,
                        per_item=rows,
                        total_examined=len(rows),
                        approved=sum(r["outcome"] == "approve" for r in rows),
                        rejected=sum(r["outcome"] == "reject" for r in rows),
                        excluded=sum(r["outcome"] == "excluded" for r in rows),
                        failed=sum(r["outcome"] == "failed" for r in rows),
                        financial_actions_executed=0,
                        duration_seconds=round(perf_counter() - started, 6),
                    )
                    ws.execute(
                        conn,
                        "UPDATE workflow_operations SET status='completed',result=? WHERE id=?",
                        (encoded(result), body.operation_id),
                    )
                return result
            except BaseException:
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
                        "Interrupted review; uncommitted decisions rolled back",
                        body.operation_id,
                    )
                raise


def label(work):
    if work["status"] == "Closed":
        return (
            "Reviewed & Closed"
            if work.get("review", {}).get("decision") == "approve"
            else "Legacy automated closure — no recorded human review"
        )
    return work["status"]
