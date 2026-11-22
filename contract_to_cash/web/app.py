"""Loopback-only local sessions; CSRF and explicit financial authorization remain mandatory."""

import asyncio
from contextlib import closing
import hashlib
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from contract_to_cash.agent.review import decide
from .models import DatasetView, EventView, Health, Launch, Login, ReviewAction, RunView
from .presentation import event_view, evidence_from_events
from .operator_auth import valid_operator_password
from .store import Settings, Store, StoreError
from .pricing import (
    PricingConfirmation,
    PricingState,
    BillingReviewRequest,
    pricing_state,
    confirm_pricing,
    employee_launch,
)

from .workflow import (
    PrepareGuidance,
    saved_guidance,
    prepare_guidance,
    HumanIntervention,
    ContinueInvestigation,
    record_intervention,
    outcome_summary,
)
from .resolution_evidence import registered_evidence

from .enterprise import AnalysisRequest, EnterpriseDecision, ScenarioUpdate, ResetRequest
from .demo_reset import reset_preview, archive_demo
from .paid_availability import availability
from .demo_prepare import PrepareDemo, prepare
from .management import ActionInput, save_action
from .guided_demo import SarahDemo, complete_sarah
from .document_workspace import DocumentWorkspace, WorkspaceCommand
from .selected_workflow import SelectedCommand, selected_operation
from .human_review import ReviewCommand, review as human_review, preview as review_preview
from .operational_activity import activity
from .work_lifecycle import lifecycle
from .management_center import ManagementCenter, ManagementCommand, CorrectiveCommand
from .document_advisor import DocumentAdvisor, AdvisorRequest, AdvisorScope


def create_app(settings=None, runner=None):
    settings = settings or Settings(
        reviewer=os.environ.get("CONTRACT_WEB_REVIEWER", "Local operator"),
    )
    if settings.mode not in ("operator", "recorded"):
        raise ValueError("Mode must be operator or recorded")
    store = Store(settings, runner)
    sessions, attempts = {}, {}
    documents = DocumentWorkspace(store)
    management = ManagementCenter(documents)
    advisor = DocumentAdvisor(management)
    store.document_advisor = advisor

    @asynccontextmanager
    async def lifespan(app):
        store.open()
        try:
            if settings.mode == "operator":
                documents.initialize()
                advisor.initialize()
            yield
        finally:
            store.close()
            sessions.clear()

    app = FastAPI(
        title="Contract Operations API",
        version="3.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.document_workspace = documents
    app.state.management_center = management
    app.state.document_advisor = advisor
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1"]
        + ([] if settings.local_passwordless else ["testserver"]),
    )

    @app.middleware("http")
    async def boundary(request, call_next):
        if settings.mode in ("operator", "recorded"):
            peer = request.client.host if request.client else None
            bound_host = (request.scope.get("server") or (None,))[0]
            if peer != "127.0.0.1" or (settings.local_passwordless and bound_host != "127.0.0.1"):
                return JSONResponse(
                    {
                        "detail": "Operator mode is restricted to a 127.0.0.1 loopback connection; network access requires proper authentication"
                    },
                    status_code=403,
                )
            if (
                settings.local_passwordless
                and request.headers.get("sec-fetch-site") == "cross-site"
            ):
                return JSONResponse(
                    {"detail": "Cross-site local session access is forbidden"}, status_code=403
                )
        origin = request.headers.get("origin")
        if origin and origin not in settings.origins:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(StoreError)
    async def store_error(request, exc):
        body = {"detail": exc.message}
        paid_path = (
            request.url.path in ("/api/runs", "/api/billing-reviews", "/api/enterprise/analyses")
            or request.url.path.endswith("/continue")
            or request.url.path.endswith("/management/analyses")
        )
        if request.method == "POST" and paid_path and exc.status in (409, 429, 503):
            state = availability(store)
            body.update(
                code=(
                    "paid_launch_retained_failure"
                    if exc.paid_run_created
                    else "paid_launch_rejected"
                ),
                availability=state,
                paid_run_created=exc.paid_run_created,
            )
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default includes rejected input values: those could contain secrets.
        return JSONResponse({"detail": "Request failed schema validation"}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return JSONResponse(
            {"detail": "Operation failed safely; retained data remains available for review"},
            status_code=500,
        )

    def session(request: Request):
        token = request.cookies.get("ctc_session", "")
        item = sessions.get(token)
        if not item or item["expires"] <= time.monotonic():
            sessions.pop(token, None)
            raise HTTPException(401, "Local session expired; reconnect to the local workspace")
        return item

    async def reader(request: Request):
        if settings.mode == "recorded":
            return None
        return session(request)

    async def writer(request: Request):
        if settings.mode != "operator":
            raise HTTPException(
                403, "Recorded mode is read-only; paid execution and decisions are disabled"
            )
        if (settings.root / ".reset-recovery.json").exists():
            raise HTTPException(503, "Workspace reset requires recovery; writes are blocked")
        item = session(request)
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), item["csrf"]):
            raise HTTPException(403, "Operator CSRF token required")
        return item

    @app.get("/api/health", response_model=Health)
    async def health():
        ready = False
        try:
            store.public_data()
            ready = True
        except StoreError:
            pass
        credentials = bool(
            os.environ.get("OPENAI_API_KEY") or os.environ.get("CONTRACT_AGENT_API_KEY")
        )
        operator = settings.local_passwordless or valid_operator_password(settings.operator_token)
        return Health(
            status="ready" if settings.mode == "recorded" or ready else "setup_required",
            mode=settings.mode,
            api_key_configured=credentials if settings.mode == "operator" else False,
            operator_configured=operator if settings.mode == "operator" else False,
            dataset_ready=ready,
            launch_available=settings.mode == "operator" and ready and credentials and operator,
            message=(
                "Recorded Investigation · read-only"
                if settings.mode == "recorded"
                else "Loopback-only local workspace. Local access does not verify identity or OpenAI API authorization."
            ),
        )

    def issue_session(response):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[token] = dict(csrf=csrf, expires=time.monotonic() + 8 * 3600)
        response.set_cookie(
            "ctc_session",
            token,
            httponly=True,
            samesite="strict",
            max_age=8 * 3600,
            secure=False,
            path="/api",
        )
        return sessions[token]

    def throttle_session_creation(request):
        address = request.client.host if request.client else "local"
        recent = [t for t in attempts.get(address, []) if time.monotonic() - t < 60]
        attempts[address] = recent + [time.monotonic()]
        if len(recent) >= 5:
            raise HTTPException(429, "Too many session attempts; wait one minute")

    @app.get("/api/session")
    async def current_session(request: Request, response: Response):
        try:
            item = session(request)
        except HTTPException:
            item = None
        if settings.mode == "operator" and settings.local_passwordless and item is None:
            throttle_session_creation(request)
            item = issue_session(response)
        return dict(
            authenticated=item is not None,
            csrf_token=item["csrf"] if item else None,
            reviewer=settings.reviewer if item else None,
            mode=settings.mode,
            local_passwordless=settings.local_passwordless,
            identity_verified=False,
        )

    @app.post("/api/session")
    async def login(body: Login, request: Request, response: Response):
        if settings.local_passwordless:
            raise HTTPException(409, "No password login is required; open the local workspace")
        if settings.mode != "operator" or not valid_operator_password(settings.operator_token):
            raise HTTPException(503, "Operator login is not configured")
        throttle_session_creation(request)
        if not secrets.compare_digest(body.token.encode(), settings.operator_token.encode()):
            raise HTTPException(401, "Operator credential was not accepted")
        item = issue_session(response)
        return dict(
            authenticated=True,
            csrf_token=item["csrf"],
            reviewer=settings.reviewer,
            mode=settings.mode,
            local_passwordless=False,
            identity_verified=False,
        )

    @app.delete("/api/session", dependencies=[Depends(writer)])
    async def logout(request: Request, response: Response):
        sessions.pop(request.cookies.get("ctc_session", ""), None)
        response.delete_cookie("ctc_session", path="/api")
        return {"ok": True}

    @app.get("/api/schema", dependencies=[Depends(reader)])
    async def schema():
        return app.openapi()

    @app.get("/api/dataset", response_model=DatasetView, dependencies=[Depends(reader)])
    async def dataset():
        return store.dataset()

    @app.get("/api/admin/pricing", response_model=PricingState, dependencies=[Depends(reader)])
    async def administrator_pricing():
        return pricing_state(settings.root, settings.mode)

    @app.put("/api/admin/pricing", response_model=PricingState, dependencies=[Depends(writer)])
    async def administrator_confirm_pricing(body: PricingConfirmation):
        with store.lock:
            if store.active:
                raise StoreError(
                    409, "Wait for the active review to settle before changing pricing"
                )
            return confirm_pricing(settings.root, body, settings.reviewer)

    @app.post(
        "/api/billing-reviews",
        response_model=RunView,
        status_code=202,
        dependencies=[Depends(writer)],
    )
    async def start_employee_review(body: BillingReviewRequest):
        with store.lock:
            state = pricing_state(settings.root, settings.mode)
            request = employee_launch(body, state)
            return store.launch(request, pricing_verification=state["profile"])

    @app.get("/api/runs", response_model=list[RunView], dependencies=[Depends(reader)])
    async def runs():
        return store.list_runs()

    @app.post("/api/runs", response_model=RunView, status_code=202, dependencies=[Depends(writer)])
    async def launch(body: Launch):
        if not settings.local_passwordless:
            return store.launch(body)  # Explicit legacy integration; not the normal UI.
        with store.lock:
            state = pricing_state(settings.root, settings.mode)
            confirmed = employee_launch(
                BillingReviewRequest(idempotency_key=body.idempotency_key, acknowledge_paid=True),
                state,
            )
            if (body.input_price, body.cached_input_price, body.output_price) != (
                confirmed.input_price,
                confirmed.cached_input_price,
                confirmed.output_price,
            ):
                raise StoreError(
                    409, "Launch rates must match current administrator-confirmed pricing"
                )
            return store.launch(body, pricing_verification=state["profile"])

    @app.get("/api/runs/{run_id}", response_model=RunView, dependencies=[Depends(reader)])
    async def detail(run_id: str):
        return store.snapshot(run_id)

    @app.get("/api/runs/{run_id}/events", dependencies=[Depends(reader)])
    async def stream(run_id: str, request: Request, after: int = 0):
        store.snapshot(run_id)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
            if cursor < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Event cursor must be a nonnegative integer") from None

        async def generate():
            nonlocal cursor
            yield "retry: 1500\n\n"
            while True:
                if await request.is_disconnected():
                    break
                events = store.events(run_id, cursor)
                for event in events:
                    view = (
                        EventView.model_validate(event)
                        if settings.mode == "recorded"
                        else event_view(event)
                    )
                    cursor = view.sequence
                    yield f"id: {cursor}\nevent: activity\ndata: {view.model_dump_json()}\n\n"
                snapshot = store.snapshot(run_id)
                if snapshot.status not in ("queued", "running"):
                    # Re-read after the terminal metadata: do not drop the final journal event.
                    if store.events(run_id, cursor):
                        continue
                    yield "event: settled\ndata: {}\n\n"
                    break
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    def finding(run_id, finding_id):
        run = store.snapshot(run_id)
        row = next((f for f in run.findings if f["finding_id"] == finding_id), None)
        if not row:
            raise HTTPException(404, "Finding not found")
        return run, row

    @app.get("/api/runs/{run_id}/findings/{finding_id}/evidence", dependencies=[Depends(reader)])
    async def evidence(run_id: str, finding_id: str):
        run, row = finding(run_id, finding_id)
        if settings.mode == "recorded":
            return store.recording(run_id).evidence.get(finding_id, [])
        return evidence_from_events(store.events(run_id), row["evidence_ids"])

    def current_finding(run_id, finding_id):
        if store.active or store.meta(run_id)["status"] in ("queued", "running"):
            raise StoreError(409, "Wait for the investigation to settle before review/export")
        run, row = finding(run_id, finding_id)
        store.validate_current(run_id)
        if row.get("data_revision") != run.data_revision or row.get("requires_revalidation"):
            raise StoreError(409, "Source revision changed; no decision/export was made")
        if any(r["finding_id"] == finding_id for r in run.interventions):
            raise StoreError(
                409,
                "This original finding has a human intervention; review the updated investigation instead",
            )
        return run, row

    @app.get(
        "/api/runs/{run_id}/findings/{finding_id}/recommendation", dependencies=[Depends(reader)]
    )
    async def recommendation(run_id: str, finding_id: str):
        if settings.mode == "recorded":
            _, row = finding(run_id, finding_id)
            return row.get("recommendation")
        return saved_guidance(store, run_id, finding_id)

    @app.post(
        "/api/runs/{run_id}/findings/{finding_id}/recommendation", dependencies=[Depends(writer)]
    )
    async def prepare_recommendation(run_id: str, finding_id: str, body: PrepareGuidance):
        return prepare_guidance(store, run_id, finding_id, body)

    @app.get("/api/paid-launch-availability", dependencies=[Depends(reader)])
    async def paid_launch_availability():
        return availability(store)

    @app.get("/api/enterprise/state", dependencies=[Depends(reader)])
    async def enterprise_state():
        return dict(
            epoch=store.enterprise.epoch() if settings.mode == "operator" else "recorded",
            active=bool(store.active),
        )

    @app.get("/api/enterprise", dependencies=[Depends(reader)])
    async def enterprise_overview(root_run_id: str | None = None):
        return store.enterprise.overview(root_run_id)

    @app.put("/api/enterprise/scenario", dependencies=[Depends(writer)])
    async def update_scenario(body: ScenarioUpdate):
        return store.enterprise.set_scenario(body)

    @app.post("/api/enterprise/analyses", status_code=202, dependencies=[Depends(writer)])
    async def analyze(body: AnalysisRequest):
        return store.enterprise.start(body, pricing_state(settings.root, settings.mode))

    @app.get("/api/enterprise/analyses/{analysis_id}", dependencies=[Depends(reader)])
    async def analysis_detail(analysis_id: str):
        return store.enterprise.detail(analysis_id)

    @app.post("/api/enterprise/analyses/{analysis_id}/decisions", dependencies=[Depends(writer)])
    async def enterprise_decision(analysis_id: str, body: EnterpriseDecision):
        return store.enterprise.decide(analysis_id, body)

    @app.post("/api/admin/prepare-demo", dependencies=[Depends(writer)])
    async def prepare_demo(body: PrepareDemo):
        return prepare(store)

    @app.post("/api/demo/complete-maya", dependencies=[Depends(writer)])
    async def complete_maya_demo(body: PrepareDemo):
        return prepare(store)

    @app.post("/api/demo/complete-sarah", dependencies=[Depends(writer)])
    async def complete_sarah_demo(body: SarahDemo):
        return complete_sarah(store.enterprise, body)

    @app.post("/api/enterprise/actions", dependencies=[Depends(writer)])
    async def management_action(body: ActionInput):
        return save_action(store.enterprise, body)

    @app.get("/api/admin/reset", dependencies=[Depends(reader)])
    async def preview_reset():
        if settings.mode != "operator":
            raise StoreError(403, "Recorded mode cannot reset a live workspace")
        with store.lock:
            return reset_preview(store)

    @app.post("/api/admin/reset", dependencies=[Depends(writer)])
    async def reset(body: ResetRequest):
        return archive_demo(store, body)

    @app.get("/api/resolution-evidence", dependencies=[Depends(reader)])
    async def authority_records():
        if settings.mode == "recorded":
            return []
        try:
            return registered_evidence(settings.root, store.public_data())
        except (ValueError, OSError, KeyError):
            raise StoreError(
                409, "Registered authority is invalid or contradictory; ask the administrator"
            ) from None

    @app.post(
        "/api/runs/{run_id}/findings/{finding_id}/interventions", dependencies=[Depends(writer)]
    )
    async def intervene(run_id: str, finding_id: str, body: HumanIntervention):
        record = record_intervention(store, run_id, finding_id, body)
        return dict(intervention=record, run=store.snapshot(run_id))

    @app.post(
        "/api/runs/{run_id}/continue",
        response_model=RunView,
        status_code=202,
        dependencies=[Depends(writer)],
    )
    async def continue_review(run_id: str, body: ContinueInvestigation):
        with store.lock:
            return store.continue_investigation(
                run_id, body, pricing_state(settings.root, settings.mode)
            )

    @app.get("/api/runs/{run_id}/outcome", dependencies=[Depends(reader)])
    async def outcome(run_id: str):
        if settings.mode == "recorded":
            raise StoreError(403, "Recorded mode does not claim a live collaborative outcome")
        return outcome_summary(store, run_id)

    @app.post("/api/runs/{run_id}/findings/{finding_id}/review", dependencies=[Depends(writer)])
    async def review(run_id: str, finding_id: str, body: ReviewAction):
        with store.lock:
            run, row = current_finding(run_id, finding_id)
            if (
                body.expected_revision != run.data_revision
                or body.expected_version != row["version"]
            ):
                raise StoreError(409, "Finding version changed; reload before deciding")
            pending = next((r for r in run.reviews if r["finding_id"] == finding_id), None)
            if not pending or pending["status"] != "pending":
                raise StoreError(409, "No pending review for this finding")
            if body.decision == "approved" and (
                row["state"] != "verified" or not row.get("evidence_verified")
            ):
                raise StoreError(
                    409,
                    "Unresolved/proposed findings cannot be approved. Request clarification or reject the hypothesis.",
                )
            try:
                decision = decide(
                    store.directory(run_id),
                    finding_id,
                    body.decision,
                    settings.reviewer,
                    rationale=body.rationale,
                )
            except (ValueError, sqlite3.IntegrityError):
                raise StoreError(409, "Review is no longer pending for this version") from None
            return dict(decision=decision, run=store.snapshot(run_id))

    @app.get("/api/runs/{run_id}/findings/{finding_id}/export", dependencies=[Depends(reader)])
    async def export(run_id: str, finding_id: str):
        if settings.mode != "operator":
            raise HTTPException(403, "Recorded mode does not authorize exports")
        with store.lock:
            run, row = current_finding(run_id, finding_id)
            approval = next((r for r in run.reviews if r["finding_id"] == finding_id), None)
            if (
                not approval
                or approval["status"] != "approved"
                or approval["action"] != "export"
                or approval["finding_version"] != row["version"]
                or row["state"] != "verified"
                or not row.get("evidence_verified")
            ):
                raise StoreError(
                    403, "A current verified finding and explicit export approval are required"
                )
            # Bind exported scope to the durable decision and original finding hash, not
            # just a mutable report label. Legacy unbound approvals remain viewable only.
            decision = approval.get("decision", {})
            try:
                database = store.directory(run_id) / "events.sqlite3"
                with closing(
                    sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
                ) as db:
                    with closing(db.cursor()) as cursor:
                        record = cursor.execute(
                            "SELECT body FROM decisions WHERE finding_id = ? AND version = ?",
                            (finding_id, row["version"]),
                        ).fetchone()
                durable = json.loads(record[0]) if record else None
            except (sqlite3.Error, ValueError):
                durable = None
            digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            if (
                durable != decision
                or decision.get("action") != "export"
                or decision.get("finding_sha256") != digest
            ):
                raise StoreError(
                    403, "Export approval is not durably bound to this finding and scope"
                )
            # A review approval never upgrades its scope to export or financial correction.
            return JSONResponse(
                dict(
                    approval=approval["decision"],
                    finding=row,
                    disclaimer="Evidence review package only. No billing changes or cash recovery.",
                ),
                headers={"Content-Disposition": 'attachment; filename="review-package.json"'},
            )

    @app.get("/api/document-workspace/sessions/{sid}/management", dependencies=[Depends(reader)])
    async def management_overview(sid: str):
        return await asyncio.to_thread(management.overview, sid)

    @app.get("/api/document-workspace/sessions/{sid}/lifecycle", dependencies=[Depends(reader)])
    async def work_lifecycle(sid: str):
        return await asyncio.to_thread(lifecycle, documents, sid)

    @app.get("/api/document-workspace/sessions/{sid}/activity", dependencies=[Depends(reader)])
    async def operational_activity(
        sid: str,
        mode: str = "cumulative",
        group: str = "operation",
        outcome: str = "all",
        series: str = "automation,maya,sarah",
        start: str | None = None,
        end: str | None = None,
        operation: str | None = None,
    ):
        return await asyncio.to_thread(
            activity, documents, sid, mode, group, outcome, series, start, end, operation
        )

    @app.post(
        "/api/document-workspace/sessions/{sid}/review-preview", dependencies=[Depends(writer)]
    )
    async def preview_human_reviews(sid: str, body: SelectedCommand):
        return await asyncio.to_thread(review_preview, documents, sid, body)

    @app.post(
        "/api/document-workspace/sessions/{sid}/human-reviews", dependencies=[Depends(writer)]
    )
    async def save_human_reviews(sid: str, body: ReviewCommand):
        return await asyncio.to_thread(human_review, documents, sid, body)

    @app.post(
        "/api/document-workspace/sessions/{sid}/management/commands", dependencies=[Depends(writer)]
    )
    async def management_command(sid: str, body: ManagementCommand):
        return await asyncio.to_thread(management.command, sid, body)

    @app.post(
        "/api/document-workspace/sessions/{sid}/management/corrective",
        dependencies=[Depends(writer)],
    )
    async def management_corrective(sid: str, body: CorrectiveCommand):
        return await asyncio.to_thread(management.corrective, sid, body)

    @app.post(
        "/api/document-workspace/sessions/{sid}/management/analysis-preview",
        dependencies=[Depends(writer)],
    )
    async def management_preview(sid: str, body: AdvisorScope):
        return await asyncio.to_thread(
            advisor.preview, sid, body.scope, body.case_ids, body.category
        )

    @app.post(
        "/api/document-workspace/sessions/{sid}/management/analyses", dependencies=[Depends(writer)]
    )
    async def management_analyze(sid: str, body: AdvisorRequest):
        return await asyncio.to_thread(advisor.start, sid, body)

    @app.get(
        "/api/document-workspace/sessions/{sid}/management/analyses/{aid}/trace",
        dependencies=[Depends(reader)],
    )
    async def management_analysis_trace(sid: str, aid: str):
        records = [a for a in advisor.records() if a["session_id"] == sid and a["id"] == aid]
        if not records:
            raise StoreError(404, "Unknown scoped analysis")
        path = advisor.ws.root / "analysis-traces" / aid / "events.sqlite3"
        if not path.exists():
            return []

        def read_trace():
            with closing(
                sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            ) as conn, closing(conn.cursor()) as cur:
                return [
                    {**json.loads(row[1]), "sequence": row[0]}
                    for row in cur.execute(
                        "SELECT sequence,body FROM events ORDER BY sequence"
                    ).fetchall()
                ]

        return await asyncio.to_thread(read_trace)

    @app.get(
        "/api/document-workspace/sessions/{sid}/management/analyses", dependencies=[Depends(reader)]
    )
    async def management_analyses(sid: str):
        return await asyncio.to_thread(advisor.list, sid)

    @app.get("/api/document-workspace", dependencies=[Depends(reader)])
    async def document_snapshot():
        return await asyncio.to_thread(documents.snapshot)

    @app.get("/api/document-workspace/sessions/{sid}", dependencies=[Depends(reader)])
    async def document_session(sid: str):
        return await asyncio.to_thread(documents.snapshot, sid)

    @app.post("/api/document-workspace/load", dependencies=[Depends(writer)])
    async def document_load(body: WorkspaceCommand):
        return await asyncio.to_thread(documents.load, command=body)

    @app.post("/api/document-workspace/restart", dependencies=[Depends(writer)])
    async def document_restart(body: WorkspaceCommand):
        return await asyncio.to_thread(documents.load, True, body.expected_session, body)

    @app.get("/api/document-workspace/sessions/{sid}/events", dependencies=[Depends(reader)])
    async def document_events(sid: str):
        def read_events():
            with documents.database(documents.directory(sid) / "journal.sqlite3") as conn:
                return [
                    dict(sequence=row[0], **json.loads(row[1]))
                    for row in documents.rows(
                        conn, "SELECT sequence,body FROM workflow_events ORDER BY sequence"
                    )
                ]

        return await asyncio.to_thread(read_events)

    @app.get(
        "/api/document-workspace/sessions/{sid}/walkthrough/{wid}", dependencies=[Depends(reader)]
    )
    async def document_walkthrough(sid: str, wid: str):
        return await asyncio.to_thread(documents.walkthrough, sid, wid)

    @app.get("/api/document-workspace/sessions/{sid}/items/{wid}", dependencies=[Depends(reader)])
    async def document_item(sid: str, wid: str):
        return await asyncio.to_thread(documents.detail, sid, wid)

    @app.get(
        "/api/document-workspace/sessions/{sid}/evidence/{digest}", dependencies=[Depends(reader)]
    )
    async def document_pdf(sid: str, digest: str):
        path = await asyncio.to_thread(documents.pdf, sid, digest)
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=path.name,
            content_disposition_type="inline",
        )

    @app.get(
        "/api/document-workspace/sessions/{sid}/management-inbox", dependencies=[Depends(reader)]
    )
    async def document_inbox(sid: str):
        return await asyncio.to_thread(documents.inbox, sid)

    @app.post(
        "/api/document-workspace/sessions/{sid}/selected/{action}", dependencies=[Depends(writer)]
    )
    async def selected_document_action(sid: str, action: str, body: SelectedCommand):
        return await asyncio.to_thread(selected_operation, documents, sid, action, body)

    @app.post(
        "/api/document-workspace/sessions/{sid}/process/{mode}", dependencies=[Depends(writer)]
    )
    async def document_batch(sid: str, mode: str, body: WorkspaceCommand):
        if mode not in ("routine", "auto_all"):
            raise StoreError(422, "Unsupported batch disposition")
        return await asyncio.to_thread(documents.perform, sid, mode, body)

    @app.post(
        "/api/document-workspace/sessions/{sid}/items/{wid}/{action}",
        dependencies=[Depends(writer)],
    )
    async def document_action(sid: str, wid: str, action: str, body: WorkspaceCommand):
        if action == "auto_all":
            raise StoreError(422, "Use the batch endpoint")
        return await asyncio.to_thread(documents.perform, sid, action, body, wid)

    @app.get("/{path:path}")
    async def frontend(path: str):
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "API endpoint not found")
        root = settings.frontend.resolve()
        asset = (root / path).resolve()
        if asset.is_relative_to(root) and asset.is_file() and not asset.is_symlink():
            return FileResponse(asset)
        index = root / "index.html"
        if not index.exists():
            raise HTTPException(
                503, "Frontend build is not installed. Follow the local setup guide."
            )
        return FileResponse(index)

    return app
