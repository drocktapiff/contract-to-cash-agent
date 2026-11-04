"""Durable human interventions and auditable, separately paid continuation requests."""

from contextlib import closing
from datetime import datetime, timezone
import json
import sqlite3
from uuid import UUID, uuid4
from typing import Literal
from pydantic import Field, model_validator
from .models import Input
from .resolution_evidence import digest, select_evidence, scoped_data
from .store import StoreError


class HumanIntervention(Input):
    idempotency_key: str = Field(pattern=r"^[0-9a-f-]{32,36}$")
    expected_revision: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)
    expected_workflow_version: int = Field(default=0, ge=0)
    action: Literal["resolve", "escalate", "dismiss"]
    rationale: str = Field(min_length=5, max_length=1000)
    evidence_id: str | None = Field(default=None, max_length=100)
    governing_amendment_id: str | None = Field(default=None, max_length=100)
    clarification_owner: str | None = Field(default=None, max_length=200)
    missing_information: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def sufficient_fields(self):
        if not self.rationale.strip() or len(self.rationale.strip()) < 5:
            raise ValueError("Explain your decision")
        if self.action == "resolve" and not (self.evidence_id and self.governing_amendment_id):
            raise ValueError(
                "Resolution requires registered supporting evidence and its governing amendment"
            )
        if self.action == "escalate" and not (
            self.clarification_owner
            and self.clarification_owner.strip()
            and self.missing_information
            and self.missing_information.strip()
        ):
            raise ValueError("Record who should clarify and what information is missing")
        if self.action != "resolve" and (self.evidence_id or self.governing_amendment_id):
            raise ValueError("Supporting authority is only applied by Resolve with evidence")
        return self


class ContinueInvestigation(Input):
    idempotency_key: UUID
    intervention_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    acknowledge_paid: Literal[True]


SCHEMA = """CREATE TABLE IF NOT EXISTS human_interventions (
    id TEXT PRIMARY KEY, finding_id TEXT NOT NULL, finding_version INTEGER NOT NULL,
    workflow_version INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL, UNIQUE(finding_id, workflow_version))"""


def interventions(directory):
    database = directory / "events.sqlite3"
    if not database.exists():
        return []
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        with closing(db.cursor()) as cursor:
            if not cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE name='human_interventions'"
            ).fetchone():
                return []
            return [
                json.loads(row[0])
                for row in cursor.execute(
                    "SELECT body FROM human_interventions ORDER BY rowid"
                ).fetchall()
            ]


def append_event(cursor, run_id, event_type, payload, actor="human"):
    if not cursor.connection.in_transaction:
        cursor.execute("BEGIN IMMEDIATE")
    sequence = cursor.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM events").fetchone()[0]
    event = dict(
        schema_version=1,
        event_id=uuid4().hex,
        run_id=run_id,
        sequence=sequence,
        timestamp=datetime.now(timezone.utc).isoformat(),
        type=event_type,
        actor=actor,
        correlation_id=None,
        payload=payload,
    )
    cursor.execute("INSERT INTO events VALUES (?, ?)", (sequence, json.dumps(event)))
    return event


def mirror(directory, event):
    # SQLite is authoritative. A mirror failure must not make a committed action look retryable.
    try:
        with (directory / "events.jsonl").open("a", encoding="utf-8", newline="\n") as output:
            output.write(json.dumps(event) + "\n")
    except OSError:
        import logging

        logging.getLogger(__name__).warning(
            "JSONL mirror could not be updated; the committed SQLite event remains authoritative"
        )


def record_intervention(store, run_id, finding_id, body):
    with store.lock:
        directory = store.directory(run_id)
        store.meta(run_id)
        rows = interventions(directory)
        request_hash = digest(dict(finding_id=finding_id, **body.model_dump()))
        prior = next((r for r in rows if r["idempotency_key"] == body.idempotency_key), None)
        if prior:
            if prior["request_hash"] != request_hash:
                raise StoreError(
                    409, "This submission key was already used for a different decision"
                )
            return prior
        if store.active:
            raise StoreError(409, "Wait for the active investigation to settle")
        run = store.snapshot(run_id)
        finding = next((f for f in run.findings if f["finding_id"] == finding_id), None)
        if not finding or finding["state"] == "retracted" or finding.get("requires_revalidation"):
            raise StoreError(409, "Select a current active finding")
        store.validate_current(run_id)
        if (
            finding["version"] != body.expected_version
            or run.data_revision != body.expected_revision
        ):
            raise StoreError(409, "The finding or evidence changed; reload before deciding")
        history = [r for r in rows if r["finding_id"] == finding_id]
        latest = history[-1] if history else None
        if body.expected_workflow_version != (latest["workflow_version"] if latest else 0):
            raise StoreError(409, "Another human decision was saved; reload before deciding")
        if latest and latest["action"] in ("resolve", "dismiss"):
            raise StoreError(
                409,
                "This finding already has a final intervention; inspect its history or continuation",
            )
        record = dict(
            id=uuid4().hex,
            run_id=run_id,
            finding_id=finding_id,
            finding_version=finding["version"],
            data_revision=run.data_revision,
            finding_sha256=digest(finding),
            base_revision=store.public_data().revision,
            workflow_version=(latest["workflow_version"] + 1 if latest else 1),
            idempotency_key=body.idempotency_key,
            request_hash=request_hash,
            action=body.action,
            rationale=body.rationale,
            reviewer=store.settings.reviewer,
            created_at=datetime.now(timezone.utc).isoformat(),
            clarification_owner=body.clarification_owner,
            missing_information=body.missing_information,
        )
        if body.action == "resolve":
            comparisons = finding.get("comparisons") or [finding.get("comparison", {})]
            if not any(row.get("status") == "conflict" for row in comparisons):
                raise StoreError(
                    422, "This resolution path supports only a saved signed-amendment conflict"
                )
            if len(finding["customer_ids"]) != 1:
                raise StoreError(
                    409,
                    "Resolve individual customer ambiguity; grouped findings need clarification",
                )
            try:
                authority = select_evidence(
                    store.settings.root,
                    store.public_data(),
                    body.evidence_id,
                    finding["customer_ids"][0],
                    body.governing_amendment_id,
                )
            except (ValueError, OSError, KeyError):
                raise StoreError(
                    422,
                    "Supporting evidence is missing, contradictory or does not establish these current terms",
                ) from None
            record.update(
                authority=authority,
                evidence_id=body.evidence_id,
                governing_amendment_id=body.governing_amendment_id,
            )
            record["effective_revision"] = scoped_data(
                store.public_data(), record, authority
            ).revision
        with closing(sqlite3.connect(directory / "events.sqlite3")) as db:
            with db, closing(db.cursor()) as cursor:
                cursor.execute(SCHEMA)
                cursor.execute(
                    "INSERT INTO human_interventions VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        record["id"],
                        finding_id,
                        finding["version"],
                        record["workflow_version"],
                        body.idempotency_key,
                        json.dumps(record),
                    ),
                )
                event = append_event(cursor, run_id, "human_resolution." + body.action, record)
        mirror(directory, event)
        return record


def continuation_context(store, parent_id, intervention_id):
    parent = store.snapshot(parent_id)
    record = next((r for r in parent.interventions if r["id"] == intervention_id), None)
    if not record or record["action"] != "resolve":
        raise StoreError(409, "A documented resolution is required before continuing")
    if store.active:
        raise StoreError(409, "Wait for the active investigation to settle")
    finding = next((f for f in parent.findings if f["finding_id"] == record["finding_id"]), None)
    if (
        not finding
        or finding["version"] != record["finding_version"]
        or parent.data_revision != record["data_revision"]
        or digest(finding) != record["finding_sha256"]
    ):
        raise StoreError(409, "The original finding changed; this resolution cannot be continued")
    data = store.public_data()
    if record["base_revision"] != data.revision:
        raise StoreError(409, "Sources changed; obtain new evidence and a new investigation")
    try:
        authority = select_evidence(
            store.settings.root,
            data,
            record["evidence_id"],
            finding["customer_ids"][0],
            record["governing_amendment_id"],
        )
        if authority != record["authority"]:
            raise ValueError("Authority changed")
    except (ValueError, OSError, KeyError):
        raise StoreError(
            409, "Supporting authority changed or failed validation; do not continue"
        ) from None
    return record, scoped_data(data, record, authority), finding


def outcome_summary(store, run_id):
    run = store.snapshot(run_id)
    children = [
        m for m in store.metadata() if (m.get("continuation") or {}).get("parent_run_id") == run_id
    ]
    results = []
    for meta in children:
        child = store.snapshot(meta["id"])
        results.append(
            dict(
                run_id=child.id,
                intervention_id=meta["continuation"]["intervention_id"],
                status=child.status,
                reason=child.reason,
                customers_compared=child.customers_compared,
                findings=child.findings,
                financial_totals=child.financial_totals,
                tool_calls=child.metrics.get("agent_tool_calls", 0),
                ready_for_review=bool(
                    any(r["status"] == "pending" for r in child.reviews)
                    and child.status not in ("queued", "running")
                ),
                billing_changes=0,
            )
        )
    return dict(
        original_run_id=run_id,
        original_findings=run.findings,
        human_contributions=run.interventions,
        continued_investigations=results,
        disclaimer="Only persisted actions and results are shown. No billing changes or cash recovery.",
    )


class PrepareGuidance(Input):
    expected_revision: str = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


def saved_guidance(store, run_id, finding_id):
    run = store.snapshot(run_id)
    finding = next((f for f in run.findings if f["finding_id"] == finding_id), None)
    if not finding:
        raise StoreError(404, "Finding not found")
    if finding.get("recommendation"):
        return finding["recommendation"]
    database = store.directory(run_id) / "events.sqlite3"
    if not database.exists():
        return None
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        with closing(db.cursor()) as cursor:
            if not cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE name='finding_guidance'"
            ).fetchone():
                return None
            row = cursor.execute(
                "SELECT body FROM finding_guidance WHERE finding_id=? AND version=?",
                (finding_id, finding["version"]),
            ).fetchone()
    record = json.loads(row[0]) if row else None
    return (
        record["recommendation"] if record and record["finding_sha256"] == digest(finding) else None
    )


def prepare_guidance(store, run_id, finding_id, body):
    from contract_to_cash.agent.tools import Tools

    with store.lock:
        if store.active:
            raise StoreError(409, "Wait for the current investigation to settle")
        run = store.validate_current(run_id)
        finding = next((f for f in run.findings if f["finding_id"] == finding_id), None)
        if (
            not finding
            or finding["state"] == "retracted"
            or finding["version"] != body.expected_version
            or run.data_revision != body.expected_revision
        ):
            raise StoreError(409, "Finding changed; reload before preparing guidance")
        previous = saved_guidance(store, run_id, finding_id)
        if previous:
            return previous
        recommendation = Tools.select_procedural_recommendation(finding)
        record = dict(
            finding_id=finding_id, finding_sha256=digest(finding), recommendation=recommendation
        )
        directory = store.directory(run_id)
        with closing(sqlite3.connect(directory / "events.sqlite3")) as db:
            with db, closing(db.cursor()) as cursor:
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS finding_guidance (finding_id TEXT, version INTEGER, body TEXT, PRIMARY KEY(finding_id, version))"
                )
                cursor.execute(
                    "INSERT INTO finding_guidance VALUES (?, ?, ?)",
                    (finding_id, finding["version"], json.dumps(record)),
                )
                event = append_event(cursor, run_id, "guidance.prepared", record, actor="tool")
        mirror(directory, event)
        return recommendation
