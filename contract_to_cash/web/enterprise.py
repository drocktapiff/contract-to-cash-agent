"""Shared, bounded enterprise analyses, scenarios and internal demo decisions."""

from contextlib import contextmanager, closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from threading import Thread
from uuid import UUID, uuid4
from typing import Literal
from pydantic import Field, model_validator
from .models import Input
from .enterprise_metrics import Scenario, roi, operational_snapshot
from .resolution_evidence import digest
from .store import StoreError
from .presentation import evidence_from_events

PERSONAS = {
    "maya": dict(name="Maya Tremblay", role="Revenue Operations Specialist", level="Operational"),
    "sarah": dict(name="Sarah Chen", role="Director of Revenue Operations", level="Management"),
    "robert": dict(name="Robert Mitchell", role="Chief Financial Officer", level="Executive"),
}


class AnalysisRequest(Input):
    idempotency_key: UUID
    acknowledge_paid: Literal[True]
    kind: Literal["management", "executive"]
    root_run_id: str = Field(pattern="^[0-9a-f]{32}$")
    expected_revision: str = Field(pattern="^[0-9a-f]{64}$")


class EnterpriseDecision(Input):
    idempotency_key: UUID
    recommendation_index: int = Field(ge=0, le=7)
    expected_revision: str = Field(pattern="^[0-9a-f]{64}$")
    action: Literal[
        "prioritize",
        "follow_up",
        "assign_owner",
        "request_investigation",
        "dismiss",
        "approve_pilot",
        "request_validation",
        "defer",
    ]
    rationale: str = Field(min_length=5, max_length=1000)
    owner: str | None = Field(default=None, max_length=200)
    supporting_references: list[str] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def valid(self):
        if len(self.rationale.strip()) < 5:
            raise ValueError("Explain the decision")
        if self.action in ("follow_up", "assign_owner", "request_investigation") and not (
            self.owner and self.owner.strip()
        ):
            raise ValueError("Record an internal follow-up owner")
        return self


class ScenarioUpdate(Input):
    expected_epoch: str
    expected_version: int = Field(ge=0)
    scenario: Scenario


class ResetRequest(Input):
    acknowledge_archive: Literal[True]
    confirmation: Literal["ARCHIVE DEMO HISTORY"]
    expected_epoch: str


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Enterprise:
    def __init__(self, store):
        self.store = store
        self.path = store.settings.root / "enterprise.sqlite3"
        self.runner = self.run_analysis

    @contextmanager
    def database(self):
        with self.store.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path)) as db:
                with db, closing(db.cursor()) as cur:
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, body TEXT NOT NULL)"
                    )
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS enterprise_decisions (id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, analysis_id TEXT, body TEXT NOT NULL, UNIQUE(analysis_id, id))"
                    )
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS enterprise_events (sequence INTEGER PRIMARY KEY, body TEXT NOT NULL)"
                    )
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS enterprise_settings (name TEXT PRIMARY KEY, body TEXT NOT NULL)"
                    )
                    yield cur

    def event(self, cur, event_type, **payload):
        row = dict(type=event_type, timestamp=timestamp(), payload=payload)
        cur.execute("INSERT INTO enterprise_events(body) VALUES (?)", (json.dumps(row),))

    def epoch(self):
        with self.store.lock:
            path = self.store.settings.root / "admin/workspace.json"
            if not path.exists():
                return "initial"
            return json.loads(path.read_text(encoding="utf-8"))["epoch"]

    def analyses(self):
        if self.store.settings.mode == "recorded":
            return []
        if not self.path.exists():
            return []
        with self.database() as cur:
            return [
                json.loads(r[0])
                for r in cur.execute("SELECT body FROM analyses ORDER BY rowid DESC").fetchall()
            ]

    def decisions(self):
        if self.store.settings.mode == "recorded":
            return []
        if not self.path.exists():
            return []
        with self.database() as cur:
            return [
                json.loads(r[0])
                for r in cur.execute(
                    "SELECT body FROM enterprise_decisions ORDER BY rowid"
                ).fetchall()
            ]

    def recover(self):
        for item in self.analyses():
            if item["status"] in ("queued", "running"):
                item.update(status="interrupted", reason="server_restart_no_resume")
                with self.database() as cur:
                    cur.execute(
                        "UPDATE analyses SET body=? WHERE id=?", (json.dumps(item), item["id"])
                    )
                    self.event(cur, "analysis.interrupted", analysis_id=item["id"])

    def scenario(self):
        if self.path.exists() and self.store.settings.mode != "recorded":
            with self.database() as cur:
                row = cur.execute(
                    "SELECT body FROM enterprise_settings WHERE name='scenario'"
                ).fetchone()
                if row:
                    return json.loads(row[0])
        s = Scenario()
        return dict(
            version=0,
            assumptions=s.model_dump(mode="json"),
            outputs=roi(s),
            basis="Illustrative assumptions, not measured prototype savings",
        )

    def set_scenario(self, body):
        if self.store.settings.mode != "operator":
            raise StoreError(403, "Recorded mode is read-only")
        with self.store.lock:
            if self.store.active:
                raise StoreError(409, "Wait for active work before changing its scenario inputs")
            if body.expected_epoch != self.epoch():
                raise StoreError(409, "Workspace changed; reload scenario assumptions")
            previous = self.scenario()
            if previous["version"] != body.expected_version:
                raise StoreError(409, "Scenario changed; reload before saving")
            record = dict(
                version=previous["version"] + 1,
                assumptions=body.scenario.model_dump(mode="json"),
                outputs=roi(body.scenario),
                saved_at=timestamp(),
                reviewer=self.store.settings.reviewer,
                basis="Explicit illustrative assumptions, not measured savings",
            )
            with self.database() as cur:
                cur.execute(
                    "INSERT OR REPLACE INTO enterprise_settings VALUES ('scenario',?)",
                    (json.dumps(record),),
                )
                self.event(cur, "scenario.saved", scenario=record)
            return record

    def inputs(self, root_run_id, kind):
        operational = operational_snapshot(self.store, root_run_id)
        references = dict(operational["references"])
        overview = dict(
            metrics=operational["metrics"],
            financial=operational["financial"],
            patterns=operational["patterns"],
            limitations=operational["limitations"],
            revisions=operational["revisions"],
        )
        overview_ref = "overview:" + digest(overview)
        references[overview_ref] = dict(kind="observed_prototype_metrics", body=overview)
        workflow_ref = "workflow:" + digest(operational.get("human_history", []))
        references[workflow_ref] = dict(
            kind="persisted_human_workflow",
            body=dict(
                contributions=operational.get("human_history", []),
                caveat="Recorded local judgments and clarification needs, not independently verified identity or executed financial changes",
            ),
        )
        for case in operational["cases"]:
            sources = evidence_from_events(self.store.events(case["run_id"]), case["evidence_ids"])
            case["source_references"] = []
            for source in sources:
                ref = "source:" + digest(dict(run_id=case["run_id"], source=source))
                references[ref] = dict(
                    kind="original_evidence",
                    body=source,
                    run_id=case["run_id"],
                    data_revision=case["data_revision"],
                )
                case["source_references"].append(ref)
        scenario = self.scenario() if kind == "executive" else None
        management = None
        scenario_ref = management_ref = None
        if kind == "executive":
            current_management_revision = self.inputs(root_run_id, "management")["revision"]
            scenario_ref = "scenario:" + digest(scenario)
            references[scenario_ref] = dict(
                kind="illustrative_financial_assumptions", body=scenario
            )
            management = dict(
                analyses=[
                    dict(
                        id=a["id"],
                        status=a["status"],
                        current=a["input_revision"] == current_management_revision,
                        input_revision=a["input_revision"],
                        result=a.get("result"),
                        metrics=a.get("metrics"),
                    )
                    for a in self.analyses()
                    if a["kind"] == "management"
                    and a["root_run_id"] == root_run_id
                    and a["status"] == "completed"
                ],
                decisions=[
                    d
                    for d in self.decisions()
                    if d["kind"] == "management" and d["root_run_id"] == root_run_id
                ],
                caveat="Internal demo records; no assignments, emails or tickets were transmitted. Prior model recommendations are hypotheses, not verified facts.",
            )
            management_ref = "management:" + digest(management)
            references[management_ref] = dict(kind="persisted_management_context", body=management)
        payload = dict(
            epoch=self.epoch(),
            kind=kind,
            operational=operational,
            scenario=scenario,
            management=management,
            references=references,
            overview_reference=overview_ref,
            scenario_reference=scenario_ref,
            management_reference=management_ref,
        )
        payload["revision"] = digest(payload)
        return payload

    def overview(self, root=None):
        with self.store.lock:
            op = operational_snapshot(self.store, root)
            if self.store.settings.mode == "recorded":
                return dict(
                    active=False,
                    epoch="recorded",
                    personas=PERSONAS,
                    operational=op,
                    scenario=self.scenario(),
                    analyses=[],
                    decisions=[],
                    analysis_revisions={},
                )
            return dict(
                active=bool(self.store.active),
                epoch=self.epoch(),
                personas=PERSONAS,
                operational=op,
                scenario=self.scenario(),
                analyses=[self.view(a) for a in self.analyses()],
                decisions=self.decisions(),
                analysis_revisions=(
                    {
                        k: self.inputs(op["root_run_id"], k)["revision"]
                        for k in ("management", "executive")
                    }
                    if op["root_run_id"]
                    else {}
                ),
            )

    def view(self, a):
        return {k: v for k, v in a.items() if k not in ("inputs", "request_hash")}

    def detail(self, analysis_id):
        if self.store.settings.mode == "recorded":
            raise StoreError(403, "Recorded mode exposes only imported investigation artifacts")
        with self.store.lock:
            a = next((a for a in self.analyses() if a["id"] == analysis_id), None)
            if not a:
                raise StoreError(404, "Analysis not found")
            current = self.inputs(a["root_run_id"], a["kind"])["revision"] == a["input_revision"]
            events = []
            directory = self.store.settings.root / "analyses" / a["id"]
            path = directory / "events.sqlite3"
            if path.exists():
                with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                    with closing(db.cursor()) as cur:
                        if cur.execute(
                            "SELECT 1 FROM sqlite_master WHERE name='events' AND type='table'"
                        ).fetchone():
                            events = [
                                json.loads(r[0])
                                for r in cur.execute(
                                    "SELECT body FROM events ORDER BY sequence"
                                ).fetchall()
                            ]
            # Project actual event types/tool choices, never provider arguments/private reasoning.
            return dict(
                **self.view(a),
                current=current,
                references=a["inputs"]["references"],
                activity=[
                    dict(
                        sequence=e["sequence"],
                        timestamp=e["timestamp"],
                        type=e["type"],
                        tool=e["payload"].get("tool"),
                    )
                    for e in events
                ]
            )

    def start(self, body, pricing):
        if self.store.settings.mode != "operator":
            raise StoreError(403, "Recorded mode is read-only")
        with self.store.lock:
            request_hash = digest(body.model_dump(mode="json"))
            prior = next(
                (a for a in self.analyses() if a["idempotency_key"] == str(body.idempotency_key)),
                None,
            )
            if prior:
                if prior["request_hash"] != request_hash:
                    raise StoreError(409, "This key belongs to a different paid analysis request")
                return self.view(prior)
            self.store.ensure_new_paid_key(body.idempotency_key, "analysis")
            if not self.store.accepting_launches:
                raise StoreError(503, "Workspace is shutting down or requires reset recovery")
            if self.store.active:
                raise StoreError(409, "One investigation or analysis is already running")
            if not pricing["ready"]:
                raise StoreError(503, "Administrator pricing confirmation is required")
            if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("CONTRACT_AGENT_API_KEY")):
                raise StoreError(503, "Configure server-side API credentials first")
            self.store.check_paid_limits()
            inputs = self.inputs(body.root_run_id, body.kind)
            if inputs["operational"]["root_run_id"] != body.root_run_id:
                raise StoreError(422, "Select the originating billing review")
            if inputs["revision"] != body.expected_revision:
                raise StoreError(
                    409, "Source inputs changed; review the current scope before authorizing"
                )
            if not inputs["operational"]["cases"]:
                raise StoreError(
                    409, "Persisted findings are required for a grounded enterprise analysis"
                )
            if any(
                r["status"] in ("queued", "running") or not r["current"]
                for r in inputs["operational"]["runs"]
            ):
                raise StoreError(
                    409, "Wait for current, settled source investigations before analyzing"
                )
            aid = uuid4().hex
            a = dict(
                id=aid,
                idempotency_key=str(body.idempotency_key),
                request_hash=request_hash,
                kind=body.kind,
                root_run_id=body.root_run_id,
                created_at=timestamp(),
                status="queued",
                reason="waiting_for_worker",
                input_revision=inputs["revision"],
                inputs=inputs,
                pricing_verification=pricing["profile"],
                reviewer=self.store.settings.reviewer,
                limits=dict(max_tool_calls=35, max_responses=40, max_seconds=180, max_cost_usd="1"),
                result=None,
            )
            with self.database() as cur:
                cur.execute(
                    "INSERT INTO analyses VALUES (?,?,?)",
                    (aid, a["idempotency_key"], json.dumps(a)),
                )
                self.event(
                    cur,
                    "analysis.authorized",
                    analysis_id=aid,
                    acknowledge_paid=True,
                    kind=body.kind,
                    input_revision=a["input_revision"],
                    reviewer=a["reviewer"],
                    limits=a["limits"],
                )
            self.store.active = "analysis:" + aid
            self.store.worker = Thread(target=self.work, args=(a,), daemon=True)
            try:
                self.store.worker.start()
            except Exception:
                self.store.active = None
                a.update(status="failed", reason="worker_start_failed")
                with self.database() as cur:
                    cur.execute("UPDATE analyses SET body=? WHERE id=?", (json.dumps(a), aid))
                raise StoreError(
                    503, "Analysis could not start; authorization is retained"
                ) from None
            return self.view(a)

    def work(self, a):
        try:
            with self.store.lock:
                a.update(status="running", reason="analyzing")
                with self.database() as cur:
                    cur.execute("UPDATE analyses SET body=? WHERE id=?", (json.dumps(a), a["id"]))
            report = self.runner(a)
            with self.store.lock:
                current = (
                    self.inputs(a["root_run_id"], a["kind"])["revision"] == a["input_revision"]
                )
                a.update(
                    status=report["status"] if current else "incomplete",
                    reason=report["reason"] if current else "source_inputs_changed",
                    result=report.get("analysis_result"),
                    result_history=report.get("analysis_history", []),
                    metrics=report["metrics"],
                )
                with self.database() as cur:
                    cur.execute("UPDATE analyses SET body=? WHERE id=?", (json.dumps(a), a["id"]))
                    self.event(
                        cur,
                        "analysis.settled",
                        analysis_id=a["id"],
                        status=a["status"],
                        reason=a["reason"],
                    )
        except Exception:
            with self.store.lock:
                a.update(status="failed", reason="analysis_failed_retained_journal")
                with self.database() as cur:
                    cur.execute("UPDATE analyses SET body=? WHERE id=?", (json.dumps(a), a["id"]))
        finally:
            with self.store.lock:
                self.store.active = None

    def run_analysis(self, a):
        from openai import OpenAI
        from contract_to_cash.agent.runtime import Investigator, Limits
        from contract_to_cash.agent.events import Journal
        from .analysis_tools import AnalysisTools, INSTRUCTIONS
        from decimal import Decimal

        rates = a["pricing_verification"]["rates"]
        limits = Limits(
            max_tool_calls=35,
            max_responses=40,
            max_seconds=180,
            max_cost_usd=Decimal("1"),
            input_usd_per_million=Decimal(rates["input_price"]),
            output_usd_per_million=Decimal(rates["output_price"]),
            cached_input_usd_per_million=Decimal(rates["cached_input_price"]),
            service_tier="default",
        )
        with OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("CONTRACT_AGENT_API_KEY"),
            base_url="https://api.openai.com/v1",
            max_retries=0,
        ) as client:
            with Journal(self.store.settings.root / "analyses" / a["id"]) as journal:
                journal.run_id = a["id"]
                return Investigator(
                    client,
                    "gpt-6.1-sol",
                    AnalysisTools(a["inputs"], a["kind"], journal),
                    journal,
                    limits,
                    instructions=INSTRUCTIONS,
                ).run(
                    "Analyze "
                    + a["kind"]
                    + " evidence. Save a qualified recommendation using the supplied snapshot tools."
                )

    def decide(self, aid, body):
        if self.store.settings.mode != "operator":
            raise StoreError(403, "Recorded mode is read-only")
        with self.store.lock:
            if self.store.active:
                raise StoreError(409, "Wait for active work to settle before deciding")
            prior = next(
                (d for d in self.decisions() if d["idempotency_key"] == str(body.idempotency_key)),
                None,
            )
            reqhash = digest(dict(analysis_id=aid, **body.model_dump(mode="json")))
            if prior:
                if prior["request_hash"] != reqhash:
                    raise StoreError(409, "Decision key already used for a different action")
                return prior
            a = next((a for a in self.analyses() if a["id"] == aid), None)
            if not a:
                raise StoreError(404, "Analysis not found")
            if (
                a["status"] != "completed"
                or self.inputs(a["root_run_id"], a["kind"])["revision"] != a["input_revision"]
                or body.expected_revision != a["input_revision"]
            ):
                raise StoreError(
                    409,
                    "A completed current analysis is required; stale recommendations cannot authorize decisions",
                )
            if body.recommendation_index >= len(a["result"]["recommendations"]):
                raise StoreError(422, "Select a saved recommendation")
            if not set(body.supporting_references) <= set(
                a["result"]["recommendations"][body.recommendation_index]["citations"]
            ):
                raise StoreError(
                    422, "Support the decision with that recommendation's cited inputs"
                )
            allowed = (
                ("prioritize", "follow_up", "assign_owner", "request_investigation", "dismiss")
                if a["kind"] == "management"
                else ("approve_pilot", "request_validation", "defer")
            )
            if body.action not in allowed:
                raise StoreError(422, "This action belongs to a different demonstration role")
            if any(
                d["analysis_id"] == aid and d["recommendation_index"] == body.recommendation_index
                for d in self.decisions()
            ):
                raise StoreError(409, "A decision is already retained for this recommendation")
            d = dict(
                id=uuid4().hex,
                idempotency_key=str(body.idempotency_key),
                request_hash=reqhash,
                analysis_id=aid,
                kind=a["kind"],
                root_run_id=a["root_run_id"],
                input_revision=a["input_revision"],
                recommendation_index=body.recommendation_index,
                action=body.action,
                rationale=body.rationale,
                owner=body.owner,
                supporting_references=body.supporting_references,
                persona=PERSONAS["sarah" if a["kind"] == "management" else "robert"],
                reviewer=self.store.settings.reviewer,
                created_at=timestamp(),
                scope="Internal local demo decision only; no external assignment, budget allocation, workforce change, billing mutation or export approval",
            )
            with self.database() as cur:
                cur.execute(
                    "INSERT INTO enterprise_decisions VALUES (?,?,?,?)",
                    (d["id"], d["idempotency_key"], aid, json.dumps(d)),
                )
                self.event(cur, "enterprise_decision.saved", decision=d)
            return d
