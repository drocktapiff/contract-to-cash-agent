"""Document-derived work, retained sessions and append-only workflow telemetry.

This namespace never calls a provider or writes billing/contract authority records.
"""

from collections import Counter
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from threading import Lock
from time import perf_counter
from uuid import uuid4
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from contract_to_cash.document_ops.intake import ingest
from contract_to_cash.document_ops.parser import read_directory
from contract_to_cash.document_ops.reconcile import reconcile
from .store import StoreError

SAMPLE = Path(__file__).resolve().parents[2] / "examples/ledgerline2/april-2026/documents"


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, sort_keys=True)


class WorkspaceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    actor: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=2000)
    confirmation: str = Field(max_length=100)
    expected_session: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    expected_version: int | None = Field(default=None, ge=1)
    evidence_hashes: list[Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]] = Field(
        default_factory=list, max_length=50
    )


def recommendation(work):
    category = work["category"]
    if work.get("recommendation_rejected"):
        disposition, why = (
            "review",
            "Maya rejected the previous recommendation; human review remains required.",
        )
    elif work.get("evidence_current") is False:
        disposition, why = "request_evidence", work["eligibility_reason"]
    elif work["automation_eligible"]:
        disposition, why = (
            "routine",
            "The supported read-only reconciliation passed. Source evidence must still be revalidated.",
        )
    elif category in ("contract_conflict", "amendment_review"):
        disposition, why = (
            "escalate",
            "Contractual authority or amendment precedence requires management and Contract Administration.",
        )
    elif (
        category in ("missing_documentation", "document_review") or work["intentionally_unresolved"]
    ):
        disposition, why = (
            "request_evidence",
            "Missing, ambiguous or invalid records do not establish an authoritative outcome.",
        )
    elif category == "credit_review" or (
        work["financial_impact"]
        and work["financial_impact"].get("difference") not in (None, "0.00")
    ):
        disposition, why = (
            "financial_review",
            "A potential financial correction needs separately authorized review; no correction is approved here.",
        )
    else:
        disposition, why = "review", "Maya must inspect the unmatched or incomplete reconciliation."
    labels = {
        "routine": "Complete the verified read-only check",
        "escalate": "Escalate contractual authority to Sarah",
        "request_evidence": "Obtain missing or authoritative evidence",
        "financial_review": "Refer for separately authorized financial review",
        "review": "Review the reconciliation and source records",
    }
    return {
        "source": "Deterministic rules — not fresh LLM reasoning",
        "disposition": disposition,
        "suggested_action": labels[disposition],
        "why": why,
        "supporting_documents": work["source_documents"],
        "human_judgment": "No invoice changes, credit issuance, real cash allocation or contractual approval. A human must authorize any subsequent financial or legal decision.",
    }


class DocumentWorkspace:
    def __init__(self, store, source=SAMPLE):
        self.store = store
        self.root = store.settings.root.parent / (store.settings.root.name + "-documents")
        self.source = Path(source)
        self.lock = Lock()
        self.interaction_kind = "human"

    @contextmanager
    def database(self, path):
        with closing(sqlite3.connect(path, timeout=10)) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def rows(self, conn, query, params=()):
        with closing(conn.execute(query, params)) as cursor:
            return cursor.fetchall()

    def execute(self, conn, query, params=()):
        conn.execute(query, params).close()

    @contextmanager
    def guard(self):
        if not self.lock.acquire(blocking=False):
            raise StoreError(409, "Document workspace operation is already active")
        acquired = False
        try:
            acquired = self.store.lock.acquire(blocking=False)
            if not acquired or (self.store.worker and self.store.worker.is_alive()):
                raise StoreError(
                    409, "An investigation or workspace operation is active; try after it finishes"
                )
            if not self.store.accepting_launches:
                raise StoreError(409, "Workspace is shutting down or requires recovery")
            yield
        finally:
            if acquired:
                self.store.lock.release()
            self.lock.release()

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.database(self.root / "catalog.sqlite3") as conn, conn:
            self.execute(
                conn,
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)",
            )
            self.execute(
                conn,
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            )
            self.execute(
                conn,
                "CREATE TABLE IF NOT EXISTS load_operations (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, session_id TEXT NOT NULL)",
            )
        # A crash after publication but before active-pointer commit retains an unselected session.
        for path in self.root.iterdir():
            if (
                len(path.name) == 32
                and all(c in "0123456789abcdef" for c in path.name)
                and (path / "journal.sqlite3").exists()
            ):
                with self.database(path / "journal.sqlite3") as conn, conn:
                    tables = {
                        r[0]
                        for r in self.rows(
                            conn, "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    if "workflow_operations" not in tables:
                        continue
                    for op in self.rows(
                        conn, "SELECT id FROM workflow_operations WHERE status='running'"
                    ):
                        self.execute(
                            conn,
                            "UPDATE workflow_operations SET status='interrupted' WHERE id=?",
                            (op["id"],),
                        )
                        self.event(
                            conn,
                            path.name,
                            None,
                            "processing_failed",
                            "deterministic_automation",
                            "Recovery",
                            "Interrupted operation; retry the same operation ID safely",
                            operation_id=op["id"],
                        )
                    created = self.rows(
                        conn, "SELECT value FROM workflow_meta WHERE key='created_at'"
                    )
                    if not created:
                        continue
                with self.database(self.root / "catalog.sqlite3") as conn, conn:
                    self.execute(
                        conn,
                        "INSERT OR IGNORE INTO sessions VALUES (?,?)",
                        (path.name, created[0][0]),
                    )

    def active(self):
        if not (self.root / "catalog.sqlite3").exists():
            return None
        with self.database(self.root / "catalog.sqlite3") as conn:
            row = self.rows(conn, "SELECT value FROM settings WHERE key='active'")
            return row[0][0] if row else None

    def directory(self, sid):
        if len(sid) != 32 or any(c not in "0123456789abcdef" for c in sid):
            raise StoreError(404, "Unknown document session")
        path = self.root / sid
        if not (path / "journal.sqlite3").is_file():
            raise StoreError(404, "Unknown document session")
        return path

    def event(
        self,
        conn,
        sid,
        work,
        kind,
        actor_kind,
        actor,
        rationale,
        operation_id=None,
        before=None,
        after=None,
        details=None,
    ):
        event = dict(
            id=uuid4().hex,
            session_id=sid,
            item_id=work["work_item_id"] if work else None,
            item_version=work.get("version") if work else None,
            type=kind,
            at=now(),
            actor_kind=actor_kind,
            actor=actor,
            rationale=rationale,
            before=before,
            after=after,
            source_hashes=sorted(work["supporting_facts"]) if work else [],
            operation_id=operation_id,
            synthetic_inputs=True,
            simulated_activity=actor_kind == "simulated_fixture",
            financial_action_executed=False,
            details=details or {},
        )
        self.execute(conn, "INSERT INTO workflow_events (body) VALUES (?)", (encoded(event),))
        if work is not None:
            work["event_history"].append(event)
        return event

    def load(self, restart=False, expected_session=None, command=None):
        with self.guard():
            intake_started = perf_counter()
            self.initialize()
            active = self.active()
            fingerprint = hashlib.sha256(
                encoded(
                    {
                        "restart": restart,
                        "expected_session": expected_session,
                        "command": command.model_dump() if command else None,
                    }
                ).encode()
            ).hexdigest()
            if command:
                if (
                    command.confirmation != "ADMINISTRATIVE WORKFLOW ONLY"
                    or not command.actor.strip()
                    or not command.rationale.strip()
                ):
                    raise StoreError(422, "Confirmation, attribution and rationale required")
                with self.database(self.root / "catalog.sqlite3") as conn:
                    previous = self.rows(
                        conn, "SELECT * FROM load_operations WHERE id=?", (command.operation_id,)
                    )
                    if previous:
                        if previous[0]["fingerprint"] != fingerprint:
                            raise StoreError(
                                409, "Operation ID was already used for another import/restart"
                            )
                        return self.snapshot(previous[0]["session_id"])
            if restart and active != expected_session:
                raise StoreError(409, "Active session changed; refresh before restarting")
            if active and not restart:
                if command:
                    with self.database(self.directory(active) / "journal.sqlite3") as conn, conn:
                        self.event(
                            conn,
                            active,
                            None,
                            "human_command_requested",
                            self.interaction_kind,
                            command.actor,
                            command.rationale,
                            command.operation_id,
                            details={"mode": "repeat_import", "identity_verified": False},
                        )
                    with self.database(self.root / "catalog.sqlite3") as conn, conn:
                        self.execute(
                            conn,
                            "INSERT INTO load_operations VALUES (?,?,?)",
                            (command.operation_id, fingerprint, active),
                        )
                return self.snapshot(active)
            sid = uuid4().hex
            stage = self.root / (sid + ".building")
            stage.mkdir()
            try:
                sources = sorted(self.source.glob("*.pdf"))
                if not sources or len(sources) > 500:
                    raise StoreError(
                        503,
                        "Sample PDF batch is missing or exceeds intake limits; reinstall the Stage 1 sample documents",
                    )
                target = stage / "documents"
                target.mkdir()
                for source in sources:
                    if source.is_symlink():
                        raise StoreError(409, "Sample source links are not accepted")
                    shutil.copyfile(source, target / source.name)
                result = ingest(target, stage / "journal.sqlite3")
                with self.database(stage / "journal.sqlite3") as conn, conn:
                    self.execute(
                        conn,
                        "CREATE TABLE workflow_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL)",
                    )
                    self.execute(
                        conn,
                        'CREATE TRIGGER workflow_events_no_update BEFORE UPDATE ON workflow_events BEGIN SELECT RAISE(ABORT, "Audit events are immutable"); END',
                    )
                    self.execute(
                        conn,
                        'CREATE TRIGGER workflow_events_no_delete BEFORE DELETE ON workflow_events BEGIN SELECT RAISE(ABORT, "Audit events are immutable"); END',
                    )
                    self.execute(
                        conn,
                        "CREATE TABLE workflow_operations (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT)",
                    )
                    self.execute(
                        conn,
                        "CREATE TABLE workflow_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                    )
                    self.execute(
                        conn, "INSERT INTO workflow_meta VALUES (?,?)", ("created_at", now())
                    )
                    self.event(
                        conn,
                        sid,
                        None,
                        "human_command_requested",
                        self.interaction_kind,
                        command.actor if command else "Local operator",
                        command.rationale if command else "Load sample documents",
                        command.operation_id if command else None,
                        details={
                            "mode": "restart" if restart else "load",
                            "previous_session": active,
                            "identity_verified": False,
                        },
                    )
                    for work in result["work_items"]:
                        work.update(
                            version=1,
                            assigned_owner="Maya Tremblay",
                            priority=(
                                "High"
                                if work["category"] in ("contract_conflict", "amendment_review")
                                or (
                                    work["financial_impact"]
                                    and work["financial_impact"].get("difference")
                                    not in (None, "0.00")
                                )
                                else "Normal"
                            ),
                        )
                        customer_names = {
                            f["fields"].get("Customer name")
                            for f in work["supporting_facts"].values()
                            if f["fields"].get("Customer name")
                        }
                        work["customer_name"] = (
                            next(iter(customer_names))
                            if len(customer_names) == 1
                            else work["customer_id"]
                        )
                        # Stage 1 metadata is retained, but contains no fabricated human execution.
                        self.event(
                            conn,
                            sid,
                            work,
                            "item_created",
                            "deterministic_automation",
                            "PDF intake",
                            "Created from actual PDF extraction",
                            details={"routine_eligible": work["automation_eligible"]},
                        )
                        self.event(
                            conn,
                            sid,
                            work,
                            "document_evidence_associated",
                            "deterministic_automation",
                            "PDF intake",
                            "Immutable source hashes and extracted spans associated",
                        )
                        work["recommendation"] = recommendation(work)
                        self.event(
                            conn,
                            sid,
                            work,
                            "recommendation_generated",
                            "deterministic_automation",
                            "Rules baseline",
                            work["recommendation"]["why"],
                        )
                        self.execute(
                            conn,
                            "UPDATE work_items SET body=? WHERE id=?",
                            (encoded(work), work["work_item_id"]),
                        )
                    intake_duration = round(perf_counter() - intake_started, 6)
                    self.execute(
                        conn,
                        "INSERT INTO workflow_meta VALUES (?,?)",
                        ("intake_duration_seconds", str(intake_duration)),
                    )
                    self.event(
                        conn,
                        sid,
                        None,
                        "sample_intake_completed",
                        "deterministic_automation",
                        "PDF intake",
                        "Actual source PDFs extracted and work items persisted",
                        details={
                            "duration_seconds": intake_duration,
                            "document_count": len(result["documents"]),
                            "work_item_count": len(result["work_items"]),
                        },
                    )
                stage.rename(self.root / sid)  # All handles closed before Windows rename.
                with self.database(self.root / "catalog.sqlite3") as conn, conn:
                    self.execute(conn, "INSERT INTO sessions VALUES (?,?)", (sid, now()))
                    self.execute(
                        conn, "INSERT OR REPLACE INTO settings VALUES ('active',?)", (sid,)
                    )
                    if command:
                        self.execute(
                            conn,
                            "INSERT INTO load_operations VALUES (?,?,?)",
                            (command.operation_id, fingerprint, sid),
                        )
            except BaseException:
                # No active pointer was changed. Retain partial staging for inspection/recovery.
                raise
            return self.snapshot(sid)

    def documents(self, conn):
        return [
            json.loads(r[0]) for r in self.rows(conn, "SELECT body FROM documents ORDER BY hash")
        ]

    def works(self, conn):
        return [
            json.loads(r[0]) for r in self.rows(conn, "SELECT body FROM work_items ORDER BY id")
        ]

    def snapshot(self, sid=None):
        active = self.active()
        sid = sid or active
        histories = []
        if (self.root / "catalog.sqlite3").exists():
            with self.database(self.root / "catalog.sqlite3") as conn:
                histories = [
                    dict(r)
                    for r in self.rows(conn, "SELECT * FROM sessions ORDER BY created_at DESC")
                ]
        if not sid:
            return dict(
                session_id=None,
                active_session_id=active,
                sessions=histories,
                items=[],
                metrics={},
                telemetry={},
            )
        directory = self.directory(sid)
        with self.database(directory / "journal.sqlite3") as conn:
            items = self.works(conn)
            events = [
                json.loads(r[0])
                for r in self.rows(conn, "SELECT body FROM workflow_events ORDER BY sequence")
            ]
            operations = self.rows(conn, "SELECT status,result FROM workflow_operations")
            docs = self.documents(conn)
            intake = self.rows(
                conn, "SELECT value FROM workflow_meta WHERE key='intake_duration_seconds'"
            )
        counts = Counter(w["status"] for w in items)
        completions = {
            e["item_id"]
            for e in events
            if e["type"] == "administratively_closed"
            and e["actor_kind"] == "deterministic_automation"
        }
        escalated = sum(w["status"] == "Escalated" for w in items)
        closed = sum(w["status"] == "Closed" for w in items)
        initial_routine = sum(
            e["type"] == "item_created" and e["details"].get("routine_eligible", False)
            for e in events
        )
        telemetry = dict(
            event_count=len(events),
            intake_duration_seconds=float(intake[0][0]) if intake else None,
            throughput=closed,
            routine_completion_rate=len(completions) / initial_routine if initial_routine else 0,
            human_exception_rate=(
                sum(w["human_review_required"] for w in items) / len(items) if items else 0
            ),
            escalation_rate=escalated / len(items) if items else 0,
            status_counts=dict(counts),
            status_transitions=[
                {"item_id": e["item_id"], "before": e["before"], "after": e["after"], "at": e["at"]}
                for e in events
                if e["type"]
                in (
                    "administratively_closed",
                    "escalated",
                    "awaiting_evidence",
                    "human_review_requested",
                )
                and e["before"] != e["after"]
                and e["after"]
            ],
            human_interaction_count=sum(
                e["type"] == "human_command_requested" and e["actor_kind"] == "human"
                for e in events
            ),
            error_count=sum(e["type"] == "processing_failed" for e in events),
            retry_count=sum(e["type"] == "operation_retried" for e in events),
            processing_duration_seconds=sum(
                json.loads(o["result"]).get("duration_seconds", 0)
                for o in operations
                if o["result"]
            ),
            human_labor_seconds=None,
            manual_savings=None,
            api_requests=0,
            api_tokens=0,
            api_cost_usd="0.00",
            measurement_note="Wall-clock command duration, not measured human labor or labor savings.",
        )
        return dict(
            session_id=sid,
            active_session_id=self.active(),
            read_only=sid != self.active(),
            processing_active=any(o["status"] == "running" for o in operations),
            sessions=histories,
            items=items,
            metrics=dict(
                total=len(items),
                automatically_completed=len(completions),
                awaiting_maya=len(items) - closed - escalated,
                escalated=escalated,
                routine_eligible=sum(w["automation_eligible"] for w in items),
                exceptions=sum(not w["automation_eligible"] for w in items),
            ),
            telemetry=telemetry,
            document_count=len(docs),
            customer_count=len({d["customer_id"] for d in docs if d["customer_id"]}),
            provenance="Synthetic source documents · Actual deterministic processing · No provider calls",
        )

    def detail(self, sid, wid):
        with self.database(self.directory(sid) / "journal.sqlite3") as conn:
            rows = self.rows(conn, "SELECT body FROM work_items WHERE id=?", (wid,))
            if not rows:
                raise StoreError(404, "Unknown work item")
            work = json.loads(rows[0][0])
            hashes = set(work["supporting_facts"])
            documents = [d for d in self.documents(conn) if d["file_hash"] in hashes]
        for doc in documents:
            try:
                self.pdf(sid, doc["file_hash"])
            except StoreError:
                work.update(
                    evidence_current=False,
                    automation_eligible=False,
                    automatic_closure_allowed=False,
                    human_review_required=True,
                    financial_impact=None,
                    eligibility_reason="Original source PDF is missing or changed. Saved extracted facts are historical; obtain and revalidate authoritative evidence.",
                )
                work["recommendation"] = recommendation(work)
        return dict(
            item=work,
            documents=documents,
            permitted_actions=self.allowed(work),
            read_only=sid != self.active(),
        )

    def allowed(self, work):
        if work["status"] in ("Closed", "Escalated", "Awaiting Financial Review"):
            return []
        actions = ["auto", "request_evidence", "escalate", "accept", "reject", "review"]
        if work["automation_eligible"]:
            actions.append("routine")
        if work["financial_impact"] and work["category"] in (
            "credit_review",
            "contract_price_validation",
            "invoice_reconciliation",
        ):
            actions.append("financial_review")
        return actions

    def pdf(self, sid, digest):
        with self.database(self.directory(sid) / "journal.sqlite3") as conn:
            rows = self.rows(conn, "SELECT body FROM documents WHERE hash=?", (digest,))
            if not rows:
                raise StoreError(404, "Unknown evidence document")
            doc = json.loads(rows[0][0])
        path = self.directory(sid) / "documents" / doc["filename"]
        if (
            not path.is_file()
            or path.is_symlink()
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise StoreError(
                409, "Source PDF is missing or changed; do not rely on its original evidence"
            )
        return path

    def revalidate(self, sid):
        docs = read_directory(self.directory(sid) / "documents")
        return {w.work_item_id: w.dump() for w in reconcile(docs)}

    def perform(self, sid, mode, body, wid=None):
        if mode not in (
            "routine",
            "auto_all",
            "auto",
            "request_evidence",
            "escalate",
            "financial_review",
            "accept",
            "reject",
            "review",
        ):
            raise StoreError(422, "Unsupported workflow action")
        if not body.actor.strip() or not body.rationale.strip():
            raise StoreError(422, "Reviewer attribution and rationale are required")
        if body.confirmation != "ADMINISTRATIVE WORKFLOW ONLY":
            raise StoreError(422, "Explicit administrative-only confirmation required")
        fingerprint = hashlib.sha256(
            encoded(dict(mode=mode, item_id=wid, command=body.model_dump())).encode()
        ).hexdigest()
        with self.guard():
            if self.active() != sid:
                raise StoreError(409, "Session is no longer active; refresh the workspace")
            database = self.directory(sid) / "journal.sqlite3"
            start = perf_counter()
            with self.database(database) as conn:
                previous = self.rows(
                    conn, "SELECT * FROM workflow_operations WHERE id=?", (body.operation_id,)
                )
                if previous and previous[0]["fingerprint"] != fingerprint:
                    raise StoreError(409, "Operation ID was already used for different input")
                if previous and previous[0]["status"] == "completed":
                    return json.loads(previous[0]["result"])
                with conn:
                    self.execute(conn, "BEGIN IMMEDIATE")
                    if previous:
                        self.event(
                            conn,
                            sid,
                            None,
                            "operation_retried",
                            self.interaction_kind,
                            body.actor,
                            body.rationale,
                            body.operation_id,
                        )
                    else:
                        self.execute(
                            conn,
                            "INSERT INTO workflow_operations VALUES (?,?,?,NULL)",
                            (body.operation_id, fingerprint, "running"),
                        )
                        self.event(
                            conn,
                            sid,
                            None,
                            "human_command_requested",
                            self.interaction_kind,
                            body.actor,
                            body.rationale,
                            body.operation_id,
                            details={"mode": mode, "item_id": wid, "identity_verified": False},
                        )
                    self.execute(
                        conn,
                        "UPDATE workflow_operations SET status='running' WHERE id=?",
                        (body.operation_id,),
                    )
                try:
                    current = self.revalidate(sid)
                    result = dict(
                        automatically_closed=0,
                        routed_to_maya=0,
                        escalated_to_sarah=0,
                        awaiting_evidence_or_authority=0,
                        unchanged_due_to_safeguards=0,
                        failed=0,
                        skipped=0,
                        items_requiring_review=0,
                    )
                    with conn:
                        self.execute(conn, "BEGIN IMMEDIATE")
                        works = self.works(conn)
                        if wid:
                            works = [w for w in works if w["work_item_id"] == wid]
                            if not works:
                                raise StoreError(404, "Unknown work item")
                            if body.expected_version != works[0]["version"]:
                                raise StoreError(
                                    409, "Work-item version changed; reload its current evidence"
                                )
                            if mode not in self.allowed(works[0]):
                                raise StoreError(
                                    409, "This action is not permitted for the current work item"
                                )
                            if mode not in ("routine",) and not set(
                                body.evidence_hashes
                            ).intersection(works[0]["supporting_facts"]):
                                raise StoreError(
                                    422,
                                    "Select at least one associated evidence document for the human disposition",
                                )
                            if any(
                                h not in works[0]["supporting_facts"] for h in body.evidence_hashes
                            ):
                                raise StoreError(422, "Evidence must belong to this work item")
                        for work in works:
                            fresh = current.get(work["work_item_id"])
                            original_version = work["version"]
                            original_state = encoded(
                                {
                                    k: v
                                    for k, v in work.items()
                                    if k not in ("event_history", "version", "updated_at")
                                }
                            )
                            if work["status"] == "Closed" or (
                                mode == "routine"
                                and not work["automation_eligible"]
                                and not (fresh and fresh["automation_eligible"])
                            ):
                                result["skipped"] += 1
                                continue
                            before = work["status"]
                            fresh = current.get(work["work_item_id"])
                            if mode == "accept":
                                work["recommendation_rejected"] = False
                            work["evidence_current"] = fresh is not None
                            if wid:
                                self.event(
                                    conn,
                                    sid,
                                    work,
                                    "human_decision_recorded",
                                    self.interaction_kind,
                                    body.actor,
                                    body.rationale,
                                    body.operation_id,
                                    before=before,
                                    details={
                                        "action": mode,
                                        "evidence_hashes": body.evidence_hashes,
                                        "identity_verified": False,
                                    },
                                )
                            eligible = bool(
                                fresh
                                and fresh["automation_eligible"]
                                and fresh["automatic_closure_allowed"]
                                and not fresh["human_review_required"]
                            )
                            work["automation_eligible"] = eligible
                            work["automatic_closure_allowed"] = eligible
                            work["human_review_required"] = not eligible
                            if not fresh:
                                work["eligibility_reason"] = (
                                    "Source evidence is missing, changed, or has new contradictory records. Original facts are historical, not a current financial determination."
                                )
                                work["financial_impact"] = None
                                disposition = "request_evidence"
                            else:
                                work["eligibility_reason"] = fresh["eligibility_reason"]
                                work["financial_impact"] = fresh["financial_impact"]
                                disposition = recommendation(work)["disposition"]
                            if mode == "reject":
                                work["recommendation_rejected"] = True
                                work["automation_eligible"] = False
                                work["automatic_closure_allowed"] = False
                                work["human_review_required"] = True
                                disposition = "review"
                                self.event(
                                    conn,
                                    sid,
                                    work,
                                    "recommendation_rejected",
                                    self.interaction_kind,
                                    body.actor,
                                    body.rationale,
                                    body.operation_id,
                                )
                            elif mode == "accept":
                                work["recommendation_rejected"] = False
                                disposition = (
                                    recommendation(work)["disposition"]
                                    if fresh
                                    else "request_evidence"
                                )
                                self.event(
                                    conn,
                                    sid,
                                    work,
                                    "recommendation_accepted",
                                    self.interaction_kind,
                                    body.actor,
                                    body.rationale,
                                    body.operation_id,
                                    details={"evidence_hashes": body.evidence_hashes},
                                )
                            elif mode in (
                                "request_evidence",
                                "escalate",
                                "financial_review",
                                "review",
                            ):
                                disposition = mode
                            elif mode == "routine":
                                disposition = (
                                    "routine"
                                    if eligible and not work.get("recommendation_rejected")
                                    else "request_evidence" if not fresh else "review"
                                )
                            # Escalated or financially referred records cannot be silently pulled back by bulk automation.
                            if not wid and work["status"] in (
                                "Escalated",
                                "Awaiting Financial Review",
                            ):
                                result["unchanged_due_to_safeguards"] += 1
                                continue
                            if work.get("recommendation_rejected") and mode in (
                                "auto",
                                "auto_all",
                                "routine",
                            ):
                                result["unchanged_due_to_safeguards"] += 1
                                continue
                            self.event(
                                conn,
                                sid,
                                work,
                                (
                                    "routine_processing_started"
                                    if disposition == "routine"
                                    else "automatic_disposition_started"
                                ),
                                "deterministic_automation",
                                "Rules baseline",
                                work["eligibility_reason"],
                                body.operation_id,
                                before=before,
                            )
                            if disposition == "routine" and eligible:
                                after = "Closed"
                                owner = "Maya Tremblay"
                                key = "automatically_closed"
                                event = "administratively_closed"
                                self.event(
                                    conn,
                                    sid,
                                    work,
                                    "routine_processing_completed",
                                    "deterministic_automation",
                                    "Rules baseline",
                                    "Original PDF evidence re-extracted and eligibility revalidated",
                                    body.operation_id,
                                    before=before,
                                    after=after,
                                )
                            elif disposition == "escalate":
                                after = "Escalated"
                                owner = "Sarah Chen"
                                key = "escalated_to_sarah"
                                event = "escalated"
                            elif disposition == "request_evidence":
                                after = "Awaiting Evidence"
                                owner = "Maya Tremblay"
                                key = "awaiting_evidence_or_authority"
                                event = "awaiting_evidence"
                            elif disposition == "financial_review":
                                after = "Awaiting Financial Review"
                                owner = "Authorized financial review team"
                                key = "awaiting_evidence_or_authority"
                                event = "human_review_requested"
                            else:
                                after = "Human Review Required"
                                owner = "Maya Tremblay"
                                key = "routed_to_maya"
                                event = "human_review_requested"
                            if after == before and work.get("last_disposition") == disposition:
                                result["unchanged_due_to_safeguards"] += 1
                            else:
                                work.update(
                                    status=after,
                                    assigned_owner=owner,
                                    last_disposition=disposition,
                                    version=work["version"] + 1,
                                    updated_at=now(),
                                )
                                result[key] += 1
                                self.event(
                                    conn,
                                    sid,
                                    work,
                                    event,
                                    "deterministic_automation",
                                    "Rules baseline",
                                    body.rationale if wid else recommendation(work)["why"],
                                    body.operation_id,
                                    before=before,
                                    after=after,
                                    details={
                                        "requested_by": body.actor,
                                        "human_evidence_hashes": body.evidence_hashes,
                                    },
                                )
                            if work["status"] in ("Escalated", "Awaiting Financial Review"):
                                work.update(
                                    automation_eligible=False,
                                    automatic_closure_allowed=False,
                                    human_review_required=True,
                                )
                            work["recommendation"] = recommendation(work)
                            if work["version"] == original_version and original_state != encoded(
                                {
                                    k: v
                                    for k, v in work.items()
                                    if k not in ("event_history", "version", "updated_at")
                                }
                            ):
                                work.update(version=original_version + 1, updated_at=now())
                                self.event(
                                    conn,
                                    sid,
                                    work,
                                    "evidence_revalidation_changed",
                                    "deterministic_automation",
                                    "Rules baseline",
                                    "Evidence or eligibility changed; the new item version requires a fresh human review.",
                                    body.operation_id,
                                    before=before,
                                    after=work["status"],
                                )
                            self.event(
                                conn,
                                sid,
                                work,
                                "automatic_disposition_applied",
                                "deterministic_automation",
                                "Rules baseline",
                                "Workflow disposition only; no financial or legal approval",
                                body.operation_id,
                                before=before,
                                after=work["status"],
                            )
                            self.execute(
                                conn,
                                "UPDATE work_items SET body=? WHERE id=?",
                                (encoded(work), work["work_item_id"]),
                            )
                        all_work = self.works(conn)
                        result.update(
                            checks_completed=result["automatically_closed"],
                            items_requiring_review=sum(
                                w["status"] != "Closed" and w["human_review_required"]
                                for w in all_work
                            ),
                            human_queue_remaining=sum(w["status"] != "Closed" for w in all_work),
                            processing_failures=result["failed"],
                            duration_seconds=round(perf_counter() - start, 6),
                            operation_id=body.operation_id,
                        )
                        self.execute(
                            conn,
                            "UPDATE workflow_operations SET status='completed',result=? WHERE id=?",
                            (encoded(result), body.operation_id),
                        )
                    return result
                except BaseException as exc:
                    with conn:
                        self.execute(
                            conn,
                            "UPDATE workflow_operations SET status='interrupted' WHERE id=?",
                            (body.operation_id,),
                        )
                        self.event(
                            conn,
                            sid,
                            None,
                            "processing_failed",
                            "deterministic_automation",
                            "Rules baseline",
                            "Operation rolled back; no partial workflow completions. Retry the same operation ID.",
                            body.operation_id,
                            details={"error_class": type(exc).__name__},
                        )
                    raise

    def inbox(self, sid):
        snap = self.snapshot(sid)
        return dict(
            session_id=sid,
            items=[
                self.detail(sid, w["work_item_id"])
                for w in snap["items"]
                if w["status"] == "Escalated"
            ],
            message="Persisted internal management inbox; not a financial authorization queue",
        )
