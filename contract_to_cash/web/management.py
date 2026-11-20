"""Internal human action records linked to current immutable operational evidence."""

from datetime import date
from decimal import Decimal
import json
from typing import Literal
from uuid import uuid4
from pydantic import Field, model_validator
from .models import Input
from .enterprise_metrics import operational_snapshot
from .resolution_evidence import digest
from .store import StoreError, now

STATUSES = Literal[
    "Proposed",
    "Assigned",
    "Investigating",
    "Awaiting Evidence",
    "Ready for Review",
    "Closed — Verified",
    "Closed — No Change Required",
]


class ActionInput(Input):
    root_run_id: str = Field(pattern="^[0-9a-f]{32}$")
    issue_id: str = Field(min_length=1, max_length=200)
    expected_revision: str = Field(pattern="^[0-9a-f]{64}$")
    expected_version: int = Field(ge=0)
    owner: str = Field(min_length=1, max_length=200)
    priority: int = Field(ge=1, le=3)
    target_date: date
    rationale: str = Field(min_length=5, max_length=1000)
    closure_criteria: str = Field(min_length=5, max_length=1000)
    status: STATUSES = "Proposed"
    closure_references: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def valid(self):
        if (
            not self.owner.strip()
            or len(self.rationale.strip()) < 5
            or len(self.closure_criteria.strip()) < 5
        ):
            raise ValueError("Record an owner, rationale and verification criteria")
        if self.status.startswith("Closed") and not self.closure_references:
            raise ValueError(
                "Closure requires supporting source references; it never asserts billing correction"
            )
        return self


def actions(enterprise, root=None):
    if enterprise.store.settings.mode == "recorded":
        return []
    with enterprise.database() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS management_actions (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        records = [
            json.loads(row[0])
            for row in cur.execute("SELECT body FROM management_actions ORDER BY rowid").fetchall()
        ]
    return [r for r in records if root is None or r["root_run_id"] == root]


def command_center(enterprise, op):
    """Derive priorities only from saved current comparisons, never known fixture amounts."""
    issues = []
    grouped = set()
    for pattern in op["patterns"]:
        ids = sorted(pattern["customer_ids"])
        if len(ids) < 3:
            continue
        grouped.update(ids)
        cases = [c for c in op["cases"] if set(ids) & set(c["customer_ids"])]
        issues.append(
            dict(
                id="shared:" + ":".join(ids),
                title="Investigate shared pricing configuration",
                priority=1,
                customer_ids=ids,
                references=[c["reference_id"] for c in cases],
                next_action="Investigate template mapping and invoice-generation configuration. Common cause is unproven.",
                evidence_status="Verified discrepancy; suspected shared cause",
                pattern=pattern,
            )
        )
    for case in op["cases"]:
        if set(case["customer_ids"]) <= grouped:
            continue
        rows = case["comparisons"] or [case.get("comparison") or {}]
        conflict = any(r.get("status") == "conflict" for r in rows)
        issues.append(
            dict(
                id=case["reference_id"],
                title=(
                    "Resolve conflicting contractual authority"
                    if conflict
                    else "Reconcile customer-impact and invoice issues"
                ),
                priority=2 if conflict else 3,
                customer_ids=case["customer_ids"],
                references=[case["reference_id"]],
                next_action=(case.get("recommendation") or {}).get(
                    "suggested_action", "Inspect original evidence with the responsible team."
                ),
                evidence_status=(
                    "Verified discrepancy"
                    if case["evidence_verified"]
                    else "Unresolved; exposure unknown"
                ),
            )
        )
    customer_issues = [i for i in issues if i["priority"] == 3]
    if len(customer_issues) > 1:
        members = sorted({cid for issue in customer_issues for cid in issue["customer_ids"]})
        issues = [i for i in issues if i["priority"] != 3] + [
            dict(
                id="customer-impact:" + ":".join(members),
                title="Reconcile customer-impact and invoice issues",
                priority=3,
                customer_ids=members,
                references=sorted(
                    {ref for issue in customer_issues for ref in issue["references"]}
                ),
                evidence_status="Evidence-backed differences; unresolved invoice ambiguity stays unknown",
                next_action="Review potential credits and other saved discrepancies. Reconcile multiple invoice records before asserting duplicate charges. Obtain separate financial review before correction.",
            )
        ]
    for issue in issues:
        rows = {
            r.get("customer_id"): r
            for c in op["cases"]
            for r in (c["comparisons"] or [c.get("comparison") or {}])
            if r.get("customer_id") in issue["customer_ids"] and c["evidence_verified"]
        }
        issue["comparisons"] = list(rows.values())
        issue["unknown_exposure_accounts"] = sorted(set(issue["customer_ids"]) - set(rows))
        issue["potential_exposure_cad"] = (
            str(sum((abs(Decimal(r["difference_cad"])) for r in rows.values()), Decimal("0.00")))
            if rows and all(r.get("difference_cad") is not None for r in rows.values())
            else None
        )
    records = actions(enterprise, op["root_run_id"]) if op["root_run_id"] else []
    revision = digest(dict(epoch=enterprise.epoch(), revisions=op["revisions"], issues=issues))
    return dict(
        issues=sorted(issues, key=lambda i: (i["priority"], i["id"])),
        actions=records,
        revision=revision,
        observed=dict(
            customers_screened=op["metrics"]["customers_screened"],
            exceptions_identified=len(op["cases"]),
            verified_exceptions=op["metrics"]["findings_verified"],
            exceptions_awaiting_review=op["metrics"]["outstanding_exceptions"],
            resolved_with_supporting_evidence=None,
            corrected_exposure_cad=None,
            potential_financial_exposure_identified_cad=op["financial"][
                "unresolved_quantifiable_exposure_cad"
            ],
        ),
        measurement_required=[
            "Human investigation/review time",
            "Time to identify shared patterns",
            "Baseline productivity",
            "Collections and issued credits",
            "Verified financial correction outcomes",
        ],
        caveat="Administrative task status is not evidence of a corrected invoice, resolved contract authority or collected cash.",
    )


def save_action(enterprise, body):
    store = enterprise.store
    with store.lock:
        if store.settings.mode != "operator":
            raise StoreError(403, "Recorded mode is read-only")
        if not store.accepting_launches:
            raise StoreError(503, "Workspace writes are unavailable during shutdown or recovery")
        if store.active:
            raise StoreError(409, "Wait for the active worker")
        op = operational_snapshot(store, body.root_run_id)
        center = command_center(enterprise, op)
        if center["revision"] != body.expected_revision:
            raise StoreError(409, "Source evidence changed; refresh before deciding")
        issue = next((i for i in center["issues"] if i["id"] == body.issue_id), None)
        if not issue or not all(r["current"] for r in op["revisions"]):
            raise StoreError(409, "A current evidence-backed issue is required")
        if not set(body.closure_references) <= set(issue["references"]):
            raise StoreError(422, "Closure references must belong to this issue")
        old = next((a for a in center["actions"] if a["issue_id"] == body.issue_id), None)
        if body.expected_version != (old["version"] if old else 0):
            raise StoreError(409, "This action changed; refresh before saving")
        change = dict(
            **body.model_dump(mode="json"),
            reviewer=store.settings.reviewer,
            timestamp=now(),
            version=body.expected_version + 1,
            provenance=dict(
                kind="human_internal_decision", scenario_provenance=op.get("provenance")
            )
        )
        record = dict(
            id=old["id"] if old else uuid4().hex,
            **change,
            evidence_revision=center["revision"],
            supporting_references=issue["references"],
            scope="Internal management task only; no billing, contract approval, external assignment or export authorization.",
            history=(old["history"] if old else []) + [change]
        )
        with enterprise.database() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO management_actions VALUES (?,?)",
                (record["id"], json.dumps(record)),
            )
            enterprise.event(cur, "management.action.saved", action=record)
        return record
