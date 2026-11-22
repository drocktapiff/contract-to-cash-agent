"""Shared management coordination, deterministic metrics and internal corrective actions."""

from collections import Counter, defaultdict
from datetime import datetime, timezone, date
from decimal import Decimal
import hashlib
import json
from uuid import uuid4
from typing import Literal
from pydantic import Field, model_validator
from .document_workspace import WorkspaceCommand, encoded, now
from .selected_workflow import SelectedItem
from .store import StoreError
from .work_presentation import business

TEAMS = (
    "Revenue Operations",
    "Billing Operations",
    "Contract Administration",
    "Finance coordination",
)


class ManagementCommand(WorkspaceCommand):
    expected_session: str = Field(pattern=r"^[a-f0-9]{32}$")
    selected: list[SelectedItem] = Field(min_length=1, max_length=500)
    action: Literal[
        "prioritize",
        "assign",
        "return",
        "evidence",
        "finance",
        "complete",
        "auto",
        "accept_insight",
        "dismiss_insight",
    ]
    priority: Literal["High", "Normal", "Low"] = "Normal"
    owner: Literal[
        "Revenue Operations",
        "Billing Operations",
        "Contract Administration",
        "Finance coordination",
    ] = "Revenue Operations"
    required_next_action: str = Field(min_length=5, max_length=1200)
    insight_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def unique(self):
        if len({s.id for s in self.selected}) != len(self.selected):
            raise ValueError("Duplicate selected IDs")
        return self


class CorrectiveCommand(WorkspaceCommand):
    expected_session: str = Field(pattern=r"^[a-f0-9]{32}$")
    action_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    action_version: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=5, max_length=160)
    description: str = Field(min_length=5, max_length=1600)
    origin_insight: str = Field(min_length=1, max_length=200)
    related_ids: list[str] = Field(min_length=1, max_length=100)
    document_ids: list[str] = Field(min_length=1, max_length=100)
    owner: Literal[
        "Revenue Operations",
        "Billing Operations",
        "Contract Administration",
        "Finance coordination",
    ]
    priority: Literal["High", "Normal", "Low"]
    due_date: date | None = None
    status: Literal[
        "Proposed",
        "Approved for Internal Investigation",
        "In Progress",
        "Awaiting Evidence",
        "Completed",
        "Dismissed",
    ] = "Proposed"
    acceptance_criteria: str = Field(min_length=5, max_length=1600)
    outcome: str = Field(default="", max_length=1600)


def aging(work, at):
    transitions = [
        e
        for e in work["event_history"]
        if e.get("after") == work["status"] and e.get("before") != e.get("after")
    ]
    stamp = transitions[-1]["at"] if transitions else work["created_at"]
    return dict(
        since=stamp,
        seconds=max(0, (at - datetime.fromisoformat(stamp)).total_seconds()),
        basis="Actual saved state-transition timestamp; not an employee time study",
    )


def financial_exposure(works, current):
    groups = {}
    credit = {}
    payments = defaultdict(list)
    unknown = set()
    for w in {w["work_item_id"]: w for w in works}.values():
        fresh = current.get(w["work_item_id"])
        f = fresh.get("financial_impact") if fresh else None
        if not f:
            if w["category"] in (
                "contract_price_validation",
                "contract_conflict",
                "invoice_reconciliation",
                "missing_documentation",
                "amendment_review",
                "payment_matching",
            ):
                unknown.add((w["customer_id"], w["contract_id"]))
            continue
        if "difference" in f:
            groups[(w["business_object_id"], f["currency"])] = Decimal(f["difference"])
        if "proposed_credit" in f:
            credit[(w["business_object_id"], f["currency"])] = Decimal(f["proposed_credit"])
        if "remaining_balance" in f:
            refs = {
                v["fields"].get("Applied invoice")
                for v in w["supporting_facts"].values()
                if v["fields"].get("Applied invoice")
            }
            if len(refs) == 1:
                payments[(next(iter(refs)), f["currency"])].append(Decimal(f["remaining_balance"]))
            else:
                unknown.add((w["customer_id"], w["contract_id"]))
    # The current intake supports CAD. Never combine currencies or unlike accounting categories.
    under = sum((v for (obj, c), v in groups.items() if c == "CAD" and v > 0), Decimal("0.00"))
    over = -sum((v for (obj, c), v in groups.items() if c == "CAD" and v < 0), Decimal("0.00"))
    proposed = sum((v for (obj, c), v in credit.items() if c == "CAD"), Decimal("0.00"))
    payment = sum(
        (values[0] for (obj, c), values in payments.items() if c == "CAD" and len(values) == 1),
        Decimal("0.00"),
    )
    return dict(
        currency="CAD",
        potential_underbilling=str(under),
        potential_overbilling=str(over),
        proposed_credits=str(proposed),
        payment_review_balances=str(payment),
        unknown_customer_contracts=len(unknown),
        ambiguous_payment_groups=sum(len(v) > 1 for v in payments.values()),
        limitations="Separate review categories, not a net amount. Proposed credits can overlap billing differences. Payment balances are counted only for unique single-receipt invoice scopes. No cash recovery, issued credit or correction is established.",
    )


class ManagementCenter:
    def __init__(self, ws):
        self.ws = ws
        self.store = ws.store

    def tables(self, conn):
        for sql in (
            "CREATE TABLE IF NOT EXISTS management_operations (id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS corrective_actions (id TEXT PRIMARY KEY,origin TEXT UNIQUE NOT NULL,body TEXT NOT NULL)",
        ):
            self.ws.execute(conn, sql)

    def read_actions(self, sid):
        with self.ws.database(self.ws.directory(sid) / "journal.sqlite3") as conn, conn:
            if not self.ws.rows(
                conn,
                "SELECT name FROM sqlite_master WHERE type='table' AND name='corrective_actions'",
            ):
                return []
            return [
                json.loads(r[0])
                for r in self.ws.rows(
                    conn, "SELECT body FROM corrective_actions ORDER BY rowid DESC"
                )
            ]

    def overview(self, sid, *, snapshot=None, current=None):
        snap = snapshot if snapshot is not None else self.ws.snapshot(sid)
        works = snap["items"]
        at = datetime.now(timezone.utc)
        cases = [w for w in works if w.get("oversight") or w["status"] == "Escalated"]
        current = current if current is not None else self.ws.revalidate(sid)
        for w in works:
            w["evidence_status"] = (
                "Current source PDFs verified"
                if w["work_item_id"] in current
                else "Source changed or missing — saved facts are historical"
            )
            if w["work_item_id"] not in current:
                w["financial_impact"] = None
                w["business"] = business(w)
            w["age"] = aging(w, at)
            w["management"] = w.get(
                "management", {"review_status": "New", "coordination_owner": "Revenue Operations"}
            )
        auto = snap["metrics"]["automatically_completed"]
        closed = sum(w["status"] == "Closed" for w in works)
        bycat = Counter(w["category"] for w in cases)
        owners = Counter(
            (
                "Finance"
                if w["status"] == "Awaiting Financial Review"
                else (
                    "Evidence / contract authority"
                    if w["status"] == "Awaiting Evidence"
                    else (
                        "Maya"
                        if w.get("management", {}).get("review_status") == "Returned to Maya"
                        else "Sarah"
                    )
                )
            )
            for w in cases
            if w["status"] != "Closed"
        )
        groups = [
            dict(
                id="rule:" + cat,
                title=cat.replace("_", " ").capitalize(),
                source="Rule-based operational overview",
                case_ids=[w["work_item_id"] for w in cases if w["category"] == cat],
                observation=(
                    "Multiple saved cases share this work category."
                    if n > 1
                    else "A saved case requires this operational review."
                ),
                hypothesis="A shared process cause is not established by category similarity.",
                count=n,
            )
            for cat, n in sorted(bycat.items())
        ]
        operations = []
        with self.ws.database(self.ws.directory(sid) / "journal.sqlite3") as conn:
            events = [
                json.loads(r[0])
                for r in self.ws.rows(conn, "SELECT body FROM workflow_events ORDER BY sequence")
            ]
        with self.ws.database(self.ws.directory(sid) / "journal.sqlite3") as conn:
            for row in self.ws.rows(
                conn, "SELECT id,status,result FROM workflow_operations ORDER BY rowid"
            ):
                result = json.loads(row["result"]) if row["result"] else {}
                operations.append(
                    dict(
                        id=row["id"],
                        status=row["status"],
                        duration_seconds=result.get("duration_seconds"),
                        examined=result.get("total_examined"),
                        completed=result.get("checks_completed", 0),
                        case_ids=sorted(
                            {
                                e["item_id"]
                                for e in events
                                if e.get("operation_id") == row["id"] and e.get("item_id")
                            }
                        ),
                    )
                )
        analyses = (
            [
                a
                for a in getattr(self.store, "document_advisor", self).records()
                if a["session_id"] == sid
            ]
            if hasattr(self.store, "document_advisor")
            else []
        )
        telemetry = dict(snap["telemetry"])
        telemetry.update(
            api_requests=sum((a.get("metrics") or {}).get("api_requests", 0) for a in analyses),
            api_tokens=sum(
                (a.get("metrics") or {}).get("input_tokens", 0)
                + (a.get("metrics") or {}).get("output_tokens", 0)
                for a in analyses
            ),
            api_cost_usd=str(
                sum(
                    (
                        Decimal((a.get("metrics") or {}).get("estimated_api_cost_usd", "0"))
                        for a in analyses
                    ),
                    Decimal("0"),
                )
            ),
            api_cost_complete=all(
                a.get("metrics") and a["metrics"].get("cost_accounting_complete") for a in analyses
            ),
            management_human_events=sum(
                e["actor_kind"] == "human"
                and e["type"]
                in (
                    "management_review_started",
                    "corrective_action_created",
                    "corrective_action_updated",
                    "corrective_action_completed",
                )
                for e in events
            ),
            corrective_action_count=len(self.read_actions(sid)),
        )
        return dict(
            session_id=sid,
            read_only=snap["read_only"],
            cases=cases,
            work_items=works,
            metrics=dict(
                total=len(works),
                completed=closed,
                automatically_completed=auto,
                human_completed=snap["metrics"]["reviewed_closed"],
                automated_checks_prepared=snap["metrics"]["automated_checks_prepared"],
                awaiting_maya_review=snap["metrics"]["awaiting_review"],
                review_rejected=snap["metrics"]["review_rejected"],
                reviewed_closed=snap["metrics"]["reviewed_closed"],
                legacy_closed=snap["metrics"]["legacy_closed"],
                automation_rate=(
                    snap["metrics"]["automated_checks_prepared"] / len(works) if works else 0
                ),
                outstanding=len(works) - closed,
                handoffs=len(cases),
                sarah_direct=sum(
                    w["status"] == "Escalated"
                    and w.get("management", {}).get("review_status")
                    not in ("Completed", "Returned to Maya")
                    for w in cases
                ),
                awaiting_finance=sum(w["status"] == "Awaiting Financial Review" for w in cases),
                awaiting_evidence=sum(w["status"] == "Awaiting Evidence" for w in cases),
                management_reviews_completed=sum(
                    w.get("management", {}).get("review_status") == "Completed" for w in cases
                ),
            ),
            charts=dict(
                categories=dict(bycat),
                decision_owners=dict(owners),
                workload={
                    "Legacy automatic closure": snap["metrics"]["legacy_closed"],
                    "Human-reviewed closure": snap["metrics"]["reviewed_closed"],
                    "Outstanding": len(works) - closed,
                },
                flow={
                    "Incoming": len(works),
                    "Completed": closed,
                    "Outstanding with oversight": sum(w["status"] != "Closed" for w in cases),
                    "Outstanding without oversight": sum(
                        w["status"] != "Closed"
                        and not (w.get("oversight") or w["status"] == "Escalated")
                        for w in works
                    ),
                },
            ),
            groups=groups,
            exposure=financial_exposure(cases, current),
            aging_groups={
                label: [w["work_item_id"] for w in cases if low <= w["age"]["seconds"] < high]
                for label, low, high in [
                    ("Under one hour", 0, 3600),
                    ("One to twenty-four hours", 3600, 86400),
                    ("One to seven days", 86400, 604800),
                    ("Seven days or more", 604800, float("inf")),
                ]
            },
            operations=operations,
            telemetry=telemetry,
            corrective_actions=self.read_actions(sid),
            human_labor="Not Measured",
            sla_policy=dict(
                target_hours=48,
                basis="Illustrative prospective policy assumption; not an observed benchmark",
                configurable=True,
            ),
            checked_at=at.isoformat(),
            changed_source_cases=sum(w["work_item_id"] not in current for w in cases),
        )

    def command(self, sid, body):
        with self.ws.guard():
            if self.ws.active() != sid or body.expected_session != sid:
                raise StoreError(
                    409, "Session changed; management decisions are read-only for retained sessions"
                )
            if (
                body.confirmation != "ADMINISTRATIVE WORKFLOW ONLY"
                or not body.actor.strip()
                or not body.rationale.strip()
            ):
                raise StoreError(422, "Confirmation, rationale and attribution required")
            if len(body.required_next_action.strip()) < 5:
                raise StoreError(422, "A substantive required next action is mandatory")
            request = hashlib.sha256(encoded(body.model_dump(mode="json")).encode()).hexdigest()
            with self.ws.database(self.ws.directory(sid) / "journal.sqlite3") as conn, conn:
                self.tables(conn)
                self.ws.execute(conn, "BEGIN IMMEDIATE")
                previous = self.ws.rows(
                    conn, "SELECT * FROM management_operations WHERE id=?", (body.operation_id,)
                )
                if previous:
                    if previous[0]["fingerprint"] != request:
                        raise StoreError(409, "Management operation key reused for different input")
                    return json.loads(previous[0]["result"])
                current = self.ws.revalidate(sid)
                outcomes = []
                self.ws.event(
                    conn,
                    sid,
                    None,
                    "management_review_started",
                    self.ws.interaction_kind,
                    body.actor,
                    body.rationale,
                    body.operation_id,
                    details={
                        "action": body.action,
                        "selected": [s.model_dump() for s in body.selected],
                    },
                )
                for choice in body.selected:
                    rows = self.ws.rows(
                        conn, "SELECT body FROM work_items WHERE id=?", (choice.id,)
                    )
                    if not rows:
                        outcomes.append(
                            dict(id=choice.id, outcome="blocked", reason="Unknown case")
                        )
                        continue
                    w = json.loads(rows[0][0])
                    before = w["status"]
                    prior = dict(w.get("management", {}))
                    if w["version"] != choice.version or not (
                        w.get("oversight") or w["status"] == "Escalated"
                    ):
                        outcomes.append(
                            dict(
                                id=choice.id,
                                outcome="blocked",
                                reason="Stale version or missing management handoff",
                            )
                        )
                        continue
                    if choice.id not in current:
                        outcomes.append(
                            dict(
                                id=choice.id,
                                outcome="blocked",
                                reason="Source integrity changed; obtain valid evidence",
                            )
                        )
                        continue
                    action = body.action
                    if action == "auto":
                        action = (
                            "finance"
                            if w["status"] == "Awaiting Financial Review"
                            else (
                                "evidence"
                                if w["status"] == "Awaiting Evidence"
                                or w["category"] in ("contract_conflict", "amendment_review")
                                else "assign"
                            )
                        )
                    if action == "finance" and w["status"] != "Awaiting Financial Review":
                        outcomes.append(
                            dict(
                                id=choice.id,
                                outcome="blocked",
                                reason="No pending Finance decision; no authority transferred",
                            )
                        )
                        continue
                    if action in ("accept_insight", "dismiss_insight"):
                        catalog = self.insight_catalog(
                            sid, {x["work_item_id"]: x for x in self.ws.works(conn)}
                        )
                        if not body.insight_id or choice.id not in catalog.get(body.insight_id, []):
                            outcomes.append(
                                dict(
                                    id=choice.id,
                                    outcome="blocked",
                                    reason="Insight is missing, stale or outside this case scope",
                                )
                            )
                            continue
                    management = w.setdefault("management", {})
                    management.update(
                        coordination_owner=body.owner,
                        required_next_action=body.required_next_action,
                        last_reviewer=body.actor,
                    )
                    event = {
                        "prioritize": "priority_changed",
                        "assign": "coordination_owner_assigned",
                        "return": "returned_to_maya",
                        "evidence": "management_evidence_requested",
                        "finance": "financial_review_coordinated",
                        "complete": "management_review_completed",
                        "accept_insight": "insight_accepted",
                        "dismiss_insight": "insight_dismissed",
                    }[action]
                    if action == "prioritize":
                        w["priority"] = body.priority
                        management["review_status"] = management.get("review_status", "In Progress")
                    elif action == "assign":
                        management["review_status"] = "In Progress"
                    elif action == "return":
                        management.update(
                            review_status="Returned to Maya", coordination_owner="Maya Tremblay"
                        )
                    elif action == "evidence":
                        management["review_status"] = "Awaiting Evidence"
                    elif action == "finance":
                        if w["status"] != "Awaiting Financial Review":
                            outcomes.append(
                                dict(
                                    id=choice.id,
                                    outcome="blocked",
                                    reason="No pending Finance decision; no authority transferred",
                                )
                            )
                            continue
                        management.update(
                            review_status="Awaiting Finance",
                            coordination_owner="Finance coordination",
                        )
                    elif action == "complete":
                        management["review_status"] = "Completed"
                    elif action in ("accept_insight", "dismiss_insight"):
                        management["insight_decision"] = dict(
                            id=body.insight_id, decision=action, at=now()
                        )
                    w.update(version=w["version"] + 1, updated_at=now())
                    self.ws.event(
                        conn,
                        sid,
                        w,
                        event,
                        self.ws.interaction_kind,
                        body.actor,
                        body.rationale,
                        body.operation_id,
                        before=before,
                        after=w["status"],
                        details={
                            "prior_priority": json.loads(rows[0][0])["priority"],
                            "priority": w["priority"],
                            "prior_management": prior,
                            "management": management,
                            "underlying_case_resolved": False,
                            "financial_authority_transferred": False,
                        },
                    )
                    self.ws.execute(
                        conn, "UPDATE work_items SET body=? WHERE id=?", (encoded(w), choice.id)
                    )
                    outcomes.append(
                        dict(
                            id=choice.id,
                            outcome=action,
                            status=w["status"],
                            management_status=management.get("review_status"),
                        )
                    )
                result = dict(
                    operation_id=body.operation_id,
                    per_item=outcomes,
                    completed_management_actions=sum(r["outcome"] == "complete" for r in outcomes),
                    returned=sum(r["outcome"] == "return" for r in outcomes),
                    referrals=sum(r["outcome"] in ("finance", "evidence") for r in outcomes),
                    blocked=sum(r["outcome"] == "blocked" for r in outcomes),
                    financial_actions_executed=0,
                    underlying_cases_unchanged=len(outcomes),
                    unchanged=sum(r["outcome"] == "blocked" for r in outcomes),
                    failures=0,
                )
                self.ws.execute(
                    conn,
                    "INSERT INTO management_operations VALUES (?,?,?)",
                    (body.operation_id, request, encoded(result)),
                )
                return result

    def corrective(self, sid, body):
        with self.ws.guard():
            if self.ws.active() != sid or body.expected_session != sid:
                raise StoreError(409, "Cannot apply an old session insight to the current session")
            if (
                body.confirmation != "ADMINISTRATIVE WORKFLOW ONLY"
                or not body.actor.strip()
                or not body.rationale.strip()
            ):
                raise StoreError(
                    422, "Explicit internal action confirmation and attribution required"
                )
            if any(
                len(value.strip()) < 5
                for value in (body.title, body.description, body.acceptance_criteria)
            ):
                raise StoreError(
                    422, "Meaningful title, description and acceptance criteria are required"
                )
            if body.status == "Completed" and len(body.outcome.strip()) < 5:
                raise StoreError(422, "Record an outcome against the acceptance criteria")
            with self.ws.database(self.ws.directory(sid) / "journal.sqlite3") as conn, conn:
                self.tables(conn)
                self.ws.execute(conn, "BEGIN IMMEDIATE")
                request = hashlib.sha256(encoded(body.model_dump(mode="json")).encode()).hexdigest()
                old = self.ws.rows(
                    conn, "SELECT * FROM management_operations WHERE id=?", (body.operation_id,)
                )
                if old:
                    if old[0]["fingerprint"] != request:
                        raise StoreError(409, "Operation key used for another action")
                    return json.loads(old[0]["result"])
                works = {w["work_item_id"]: w for w in self.ws.works(conn)}
                if (
                    len(set(body.related_ids)) != len(body.related_ids)
                    or not set(body.related_ids) <= works.keys()
                ):
                    raise StoreError(422, "Corrective action cases must be unique session records")
                if any(
                    not (works[i].get("oversight") or works[i]["status"] == "Escalated")
                    for i in body.related_ids
                ):
                    raise StoreError(422, "Link actual management handoffs")
                docs = {
                    d["document_id"]
                    for d in self.ws.documents(conn)
                    if any(d["file_hash"] in works[i]["supporting_facts"] for i in body.related_ids)
                }
                if not set(body.document_ids) <= docs or len(set(body.document_ids)) != len(
                    body.document_ids
                ):
                    raise StoreError(422, "Source documents must belong to the linked cases")
                fresh = self.ws.revalidate(sid)
                if not set(body.related_ids) <= fresh.keys():
                    raise StoreError(
                        409,
                        "Source integrity changed; cannot authorize an action from outdated evidence",
                    )
                # Bind accepted insights to a real rule group or a validated current live analysis.
                existing = self.ws.rows(
                    conn,
                    "SELECT body FROM corrective_actions WHERE origin=?",
                    (body.origin_insight,),
                )
                catalog = self.insight_catalog(sid, works)
                if not (existing and body.action_id) and (
                    body.origin_insight not in catalog
                    or not set(body.related_ids) <= set(catalog[body.origin_insight])
                ):
                    raise StoreError(409, "Insight is unavailable or stale for the selected scope")
                existing = self.ws.rows(
                    conn,
                    "SELECT body FROM corrective_actions WHERE origin=?",
                    (body.origin_insight,),
                )
                if existing and not body.action_id:
                    self.ws.execute(
                        conn,
                        "INSERT INTO management_operations VALUES (?,?,?)",
                        (body.operation_id, request, existing[0][0]),
                    )
                    return json.loads(existing[0][0])
                action = json.loads(existing[0][0]) if existing else None
                if body.action_id and (
                    not action
                    or action["id"] != body.action_id
                    or action["version"] != body.action_version
                ):
                    raise StoreError(409, "Corrective action version changed")
                if action and (
                    set(body.related_ids) != set(action["related_ids"])
                    or set(body.document_ids) != set(action["document_ids"])
                ):
                    raise StoreError(
                        422, "Existing actions retain their immutable source references"
                    )
                if not action:
                    self.ws.event(
                        conn,
                        sid,
                        None,
                        "insight_accepted",
                        self.ws.interaction_kind,
                        body.actor,
                        body.rationale,
                        body.operation_id,
                        details={
                            "insight_id": body.origin_insight,
                            "related_ids": body.related_ids,
                            "document_ids": body.document_ids,
                        },
                    )
                previous = dict(action) if action else None
                record = dict(
                    id=action["id"] if action else uuid4().hex,
                    version=action["version"] + 1 if action else 1,
                    session_id=sid,
                    created_at=action["created_at"] if action else now(),
                    updated_at=now(),
                    originating_insight=body.origin_insight,
                    title=body.title,
                    description=body.description,
                    related_ids=body.related_ids,
                    document_ids=body.document_ids,
                    owner=body.owner,
                    priority=body.priority,
                    due_date=body.due_date.isoformat() if body.due_date else None,
                    status=body.status,
                    acceptance_criteria=body.acceptance_criteria,
                    outcome=body.outcome,
                    provenance=(
                        "Simulated fixture management action — no genuine employee approval"
                        if self.ws.interaction_kind == "simulated_fixture"
                        else "Human-confirmed internal operational action; no billing or contract authorization"
                    ),
                    event_history=action["event_history"][:] if action else [],
                )
                event = self.ws.event(
                    conn,
                    sid,
                    None,
                    (
                        "corrective_action_created"
                        if not action
                        else (
                            "corrective_action_completed"
                            if body.status == "Completed"
                            else "corrective_action_updated"
                        )
                    ),
                    self.ws.interaction_kind,
                    body.actor,
                    body.rationale,
                    body.operation_id,
                    details={
                        "action_id": record["id"],
                        "prior_version": previous["version"] if previous else None,
                        "before_action": (
                            {k: v for k, v in previous.items() if k != "event_history"}
                            if previous
                            else None
                        ),
                        "after_action": {k: v for k, v in record.items() if k != "event_history"},
                        "version": record["version"],
                        "status": record["status"],
                        "related_ids": body.related_ids,
                        "document_ids": body.document_ids,
                        "financial_action_executed": False,
                    },
                )
                record["event_history"].append(event)
                self.ws.execute(
                    conn,
                    "INSERT OR REPLACE INTO corrective_actions VALUES (?,?,?)",
                    (record["id"], body.origin_insight, encoded(record)),
                )
                self.ws.execute(
                    conn,
                    "INSERT INTO management_operations VALUES (?,?,?)",
                    (body.operation_id, request, encoded(record)),
                )
                return record

    def insight_catalog(self, sid, works):
        catalog = defaultdict(list)
        for w in works.values():
            if w.get("oversight") or w["status"] == "Escalated":
                catalog["rule:" + w["category"]].append(w["work_item_id"])
        advisor = getattr(self.store, "document_advisor", None)
        if advisor:
            for analysis in advisor.records():
                if (
                    analysis["session_id"] == sid
                    and analysis.get("status") == "completed"
                    and advisor.current(analysis)
                ):
                    for i, insight in enumerate(analysis["result"]["insights"]):
                        catalog[analysis["id"] + ":" + str(i)] = insight["case_ids"]
        return catalog
