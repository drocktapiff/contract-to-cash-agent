"""Idempotent, explicitly simulated stage preparation; never impersonates a human."""

from datetime import date, timedelta
import json
from typing import Literal
from pydantic import Field
from .models import Input
from .store import StoreError, now
from .management import command_center
from .enterprise_metrics import operational_snapshot
from .resolution_evidence import digest


class SarahDemo(Input):
    confirmation: Literal["COMPLETE SIMULATED SARAH DEMO"]
    root_run_id: str = Field(pattern="^[0-9a-f]{32}$")


def handoff(enterprise, root):
    with enterprise.database() as cur:
        row = cur.execute(
            "SELECT body FROM enterprise_settings WHERE name=?", ("demo-handoff:" + root,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def complete_sarah(enterprise, body):
    store = enterprise.store
    with store.lock:
        if store.settings.mode != "operator":
            raise StoreError(403, "Recorded mode is read-only")
        if store.active or not store.accepting_launches:
            raise StoreError(409, "Wait for the worker or workspace recovery")
        op = operational_snapshot(store, body.root_run_id)
        if not op.get("provenance") or op["provenance"].get("kind") != "simulated_demo":
            raise StoreError(
                409,
                "Complete Maya Demo first. Genuine investigation records will not be seeded or overwritten.",
            )
        if not all(r["current"] and r["status"] == "completed" for r in op["revisions"]):
            raise StoreError(
                409,
                "Source evidence changed. Complete Maya Demo against the current fixtures first.",
            )
        center = command_center(enterprise, op)
        existing = {a["issue_id"]: a for a in center["actions"]}
        provenance = dict(
            kind="simulated_demo_action",
            label="Simulated Demo Data",
            fixture_version=1,
            basis="Fixture-backed proposed internal actions; no real human decision or external assignment",
        )
        previous = handoff(enterprise, body.root_run_id)
        # This transaction commits all missing seed actions and the handoff together.
        with enterprise.database() as cur:
            for issue in center["issues"]:
                if issue["id"] in existing:
                    continue  # Includes every actual human action and prior fixture action.
                owner = {
                    1: "Billing Configuration Team",
                    2: "Contract Administration",
                    3: "Billing Operations",
                }[issue["priority"]]
                action_id = digest(
                    dict(root=body.root_run_id, issue=issue["id"], fixture="sarah-v1")
                )[:32]
                record = dict(
                    id=action_id,
                    root_run_id=body.root_run_id,
                    issue_id=issue["id"],
                    version=1,
                    expected_revision=center["revision"],
                    expected_version=0,
                    evidence_revision=center["revision"],
                    priority=issue["priority"],
                    owner=owner,
                    target_date=str(date.fromisoformat(op["period"] + "-01") + timedelta(days=45)),
                    status="Proposed",
                    rationale=issue["next_action"],
                    closure_criteria="Obtain source-backed validation and independent financial review; administrative completion cannot establish correction or collection.",
                    closure_references=[],
                    supporting_references=issue["references"],
                    reviewer="Simulated management fixture — not a human decision",
                    timestamp=now(),
                    provenance=provenance,
                    scope="Proposed internal follow-up only; no external assignment, correction, export or strategic authorization.",
                )
                record["history"] = [dict(record)]
                cur.execute(
                    "INSERT INTO management_actions VALUES (?,?)", (action_id, json.dumps(record))
                )
                enterprise.event(
                    cur, "demo.management.action.prepared", action=record, provenance=provenance
                )
                existing[issue["id"]] = record
            fingerprint = digest(
                dict(
                    source_revision=center["revision"],
                    actions=sorted((a["id"], a["version"]) for a in existing.values()),
                )
            )
            if previous and previous["fingerprint"] == fingerprint:
                return previous
            result = dict(
                root_run_id=body.root_run_id,
                fingerprint=fingerprint,
                source_revision=center["revision"],
                version=(previous["version"] if previous else 0) + 1,
                prepared_at=now(),
                provenance=provenance,
                action_versions=sorted((a["id"], a["version"]) for a in existing.values()),
                message="Simulated management handoff prepared for Robert. Proposed actions and unresolved risks are context, not executed corrections or strategic approval.",
            )
            cur.execute(
                "INSERT OR REPLACE INTO enterprise_settings VALUES (?,?)",
                ("demo-handoff:" + body.root_run_id, json.dumps(result)),
            )
            enterprise.event(cur, "demo.management.handoff", handoff=result, provenance=provenance)
        return result
