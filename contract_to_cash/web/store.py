"""One local process, one bounded worker; SQLite is the authoritative event stream."""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock, Thread
from uuid import uuid4

from contract_to_cash.agent.events import Journal
from contract_to_cash.agent.runtime import Investigator, Limits
from contract_to_cash.agent.tools import PublicData, Tools
from .models import DatasetView, RunView
from .presentation import finding_view, review_view


def now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Settings:
    data: Path = Path("agent-runtime-web/contract_to_cash/data")
    root: Path = Path("runs/web")
    recordings: Path = Path("recordings")
    frontend: Path = Path("frontend/dist")
    mode: str = "operator"
    operator_token: str = ""
    reviewer: str = "Local operator"
    origins: tuple = (
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )


class StoreError(ValueError):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class Store:
    def __init__(self, settings, runner=None):
        self.settings = settings
        self.lock = RLock()
        self.worker = None
        self.runner = runner or self.run_agent
        self.active = None
        self.owner_fd = None
        self.index = settings.root / "index"

    def open(self):
        if self.settings.mode == "recorded":
            return
        self.index.mkdir(parents=True, exist_ok=True)
        try:
            self.owner_fd = os.open(
                self.settings.root / ".server.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError:
            raise RuntimeError(
                "Run store is already owned or requires recovery; see local operations documentation"
            ) from None
        # A prior process cannot resume a paid call. Mark retained requests honestly.
        for meta in self.metadata():
            if meta["status"] in ("queued", "running"):
                meta.update(status="interrupted", reason="server_restart_no_resume")
                self.write_meta(meta)

    def close(self):
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=5)
        # Do not release ownership while an in-flight worker still writes.
        if self.owner_fd is not None and not (self.worker and self.worker.is_alive()):
            os.close(self.owner_fd)
            self.owner_fd = None
            (self.settings.root / ".server.lock").unlink()

    def public_data(self):
        if (self.settings.data / "sealed_answer_key.json").exists():
            raise StoreError(
                503, "Build an isolated public runtime before starting the web adapter"
            )
        try:
            return PublicData(self.settings.data, "2026-04")
        except Exception:
            raise StoreError(
                503, "Public dataset is unavailable or failed integrity validation"
            ) from None

    def dataset(self):
        if self.settings.mode == "recorded":
            return DatasetView(
                period="2026-04",
                customer_count=None,
                invoice_count=None,
                message="Recorded mode: only explicitly imported investigation artifacts are available.",
            )
        data = self.public_data()
        return DatasetView(
            period=data.period,
            customer_count=len(data.customers),
            invoice_count=sum(len(rows) for rows in data.rows.values()),
            data_revision=data.revision,
            message="Source inventory only. Potential financial differences require an investigation.",
        )

    def metadata(self):
        if not self.index.exists():
            return []
        return [
            json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.index.glob("*.json"))
        ]

    def write_meta(self, meta):
        path = self.index / (meta["id"] + ".json")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tmp.replace(path)

    def directory(self, run_id):
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise StoreError(404, "Investigation not found")
        path = self.settings.root / run_id
        if path.is_symlink():
            raise StoreError(404, "Investigation not found")
        return path

    def recording(self, run_id):
        self.directory(run_id)  # Same strict identifier validation; no caller paths.
        path = self.settings.recordings / (run_id + ".json")
        if not path.is_file() or path.is_symlink():
            raise StoreError(404, "Recorded investigation not found")
        from .recording import Recording

        try:
            return Recording.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            raise StoreError(503, "Recording failed validation") from None

    def meta(self, run_id):
        self.directory(run_id)
        path = self.index / (run_id + ".json")
        if not path.is_file() or path.is_symlink():
            raise StoreError(404, "Investigation not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def events(self, run_id, after=0):
        if self.settings.mode == "recorded":
            return [e.model_dump() for e in self.recording(run_id).events if e.sequence > after]
        directory = self.directory(run_id)
        self.meta(run_id)
        database = directory / "events.sqlite3"
        if not database.exists():
            return []
        # No connection escapes this method; readers never create/write SQLite files.
        with closing(
            sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        ) as db:
            with closing(db.cursor()) as cursor:
                rows = cursor.execute(
                    "SELECT body FROM events WHERE sequence > ? ORDER BY sequence", (after,)
                ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def snapshot(self, run_id):
        with self.lock:
            if self.settings.mode == "recorded":
                return self.recording(run_id).run
            meta = self.meta(run_id)
            report_file = self.directory(run_id) / "report.json"
            report = (
                json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
            )
            events = self.events(run_id)
            status = meta["status"]
            # A final worker state is written only after journal/report closure.
            reason = meta.get("reason", report.get("reason", "starting"))
            candidates = []
            for event in events:
                if (
                    event["type"] == "tool.completed"
                    and event["payload"]["tool"] == "screen_customers"
                ):
                    candidates = event["payload"]["result"]["candidates"]
            metrics = dict(report.get("metrics", {}))
            # While the agent awaits its next response, count only actual persisted events.
            if status in ("queued", "running", "interrupted", "failed"):
                apis = [e["payload"] for e in events if e["type"] == "api.completed"]
                metrics.update(
                    agent_tool_calls=sum(e["type"] == "tool.requested" for e in events),
                    api_requests=sum(e["type"] == "api.requested" for e in events)
                    or len(apis) + sum(e["type"] == "api.failed" for e in events),
                    input_tokens=sum(e["input_tokens"] for e in apis),
                    output_tokens=sum(e["output_tokens"] for e in apis),
                    cached_input_tokens=sum(e.get("cached_input_tokens", 0) for e in apis),
                    actual_billed_cost_usd=None,
                )
            if status in ("failed", "interrupted"):
                metrics["cost_accounting_complete"] = False
                metrics["usage_priced_cost_usd"] = None
            if status in ("queued", "running"):
                metrics["duration_seconds"] = round(
                    (
                        datetime.now(timezone.utc) - datetime.fromisoformat(meta["created_at"])
                    ).total_seconds(),
                    3,
                )
            return RunView(
                id=run_id,
                mode="live",
                status=status,
                reason=reason,
                created_at=meta["created_at"],
                period="2026-04",
                model="gpt-6.1-sol",
                data_revision=report.get("data_revision"),
                report_event_sequence=report.get("journal_sequence", 0),
                last_event_sequence=events[-1]["sequence"] if events else 0,
                screening_complete=report.get("screening_complete", False),
                customers_compared=report.get("customers_compared", []),
                customers_with_retrieved_documents=report.get(
                    "customers_with_retrieved_documents", []
                ),
                findings=[finding_view(f) for f in report.get("findings", [])],
                reviews=[review_view(r) for r in report.get("reviews", [])],
                candidates=candidates,
                financial_totals=report.get("financial_totals", {}),
                metrics=metrics,
            )

    def list_runs(self):
        if self.settings.mode == "recorded":
            return [
                self.recording(p.stem).run for p in sorted(self.settings.recordings.glob("*.json"))
            ]
        return sorted(
            [self.snapshot(meta["id"]) for meta in self.metadata()],
            key=lambda r: r.created_at,
            reverse=True,
        )

    def launch(self, request):
        with self.lock:
            previous = self.metadata()
            for meta in previous:
                if meta["idempotency_key"] == str(request.idempotency_key):
                    return self.snapshot(meta["id"])
            if self.active:
                raise StoreError(
                    409, "An investigation is already running; no second paid run was started"
                )
            if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("CONTRACT_AGENT_API_KEY")):
                raise StoreError(
                    503,
                    "OpenAI credentials are absent. Configure them on the server before launching.",
                )
            timestamp = datetime.now(timezone.utc)
            recent = [
                (timestamp - datetime.fromisoformat(meta["created_at"])).total_seconds()
                for meta in previous
            ]
            if any(age < 60 for age in recent) or sum(age < 3600 for age in recent) >= 3:
                raise StoreError(
                    429, "Local launch limit reached. At most one per minute and three per hour."
                )
            data = self.public_data()
            run_id = uuid4().hex
            meta = dict(
                id=run_id,
                idempotency_key=str(request.idempotency_key),
                created_at=now(),
                status="queued",
                reason="waiting_for_worker",
                reviewer=self.settings.reviewer,
            )
            self.write_meta(meta)
            self.active = run_id
            self.worker = Thread(target=self.work, args=(meta, data, request), daemon=True)
            try:
                self.worker.start()
            except Exception:
                self.active = None
                meta.update(status="failed", reason="worker_start_failed")
                self.write_meta(meta)
                raise StoreError(
                    503, "Investigation could not start; request is retained for audit"
                ) from None
            return self.snapshot(run_id)

    def work(self, meta, data, request):
        try:
            with self.lock:
                meta.update(status="running", reason="investigating")
                self.write_meta(meta)
            report = self.runner(meta["id"], data, request)
            with self.lock:
                meta.update(status=report["status"], reason=report["reason"])
                self.write_meta(meta)
        except Exception:
            with self.lock:
                meta.update(status="failed", reason="worker_failed_retained_partial_results")
                self.write_meta(meta)
        finally:
            with self.lock:
                self.active = None

    def run_agent(self, run_id, data, request):
        from openai import OpenAI

        limits = Limits(
            max_tool_calls=request.max_tool_calls,
            max_seconds=request.max_seconds,
            max_cost_usd=request.max_cost_usd,
            input_usd_per_million=request.input_price,
            output_usd_per_million=request.output_price,
            max_responses=request.max_responses,
            cached_input_usd_per_million=request.cached_input_price,
        )
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("CONTRACT_AGENT_API_KEY")
        with OpenAI(api_key=key, base_url="https://api.openai.com/v1", max_retries=0) as client:
            with Journal(self.directory(run_id)) as journal:
                journal.run_id = run_id
                return Investigator(
                    client, "gpt-6.1-sol", Tools(data, journal), journal, limits
                ).run(request.objective)
