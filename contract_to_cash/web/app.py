"""Same-origin local operator API. No privileged unauthenticated network endpoints."""

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


def create_app(settings=None, runner=None):
    settings = settings or Settings(
        operator_token=os.environ.get("CONTRACT_WEB_OPERATOR_TOKEN", ""),
        reviewer=os.environ.get("CONTRACT_WEB_REVIEWER", "Local operator"),
    )
    if settings.mode not in ("operator", "recorded"):
        raise ValueError("Mode must be operator or recorded")
    store = Store(settings, runner)
    sessions, attempts = {}, {}

    @asynccontextmanager
    async def lifespan(app):
        store.open()
        try:
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
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )

    @app.middleware("http")
    async def boundary(request, call_next):
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
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

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
            raise HTTPException(401, "Sign in as the local operator")
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
        operator = valid_operator_password(settings.operator_token)
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
                else "Local operator service. Authentication does not verify OpenAI API authorization."
            ),
        )

    @app.get("/api/session")
    async def current_session(request: Request):
        try:
            item = session(request)
        except HTTPException:
            item = None
        return dict(
            authenticated=item is not None,
            csrf_token=item["csrf"] if item else None,
            reviewer=settings.reviewer if item else None,
            mode=settings.mode,
        )

    @app.post("/api/session")
    async def login(body: Login, request: Request, response: Response):
        if settings.mode != "operator" or not valid_operator_password(settings.operator_token):
            raise HTTPException(503, "Operator login is not configured")
        address = request.client.host if request.client else "local"
        recent = [t for t in attempts.get(address, []) if time.monotonic() - t < 60]
        attempts[address] = recent + [time.monotonic()]
        if len(recent) >= 5:
            raise HTTPException(429, "Too many login attempts; wait one minute")
        if not secrets.compare_digest(body.token.encode(), settings.operator_token.encode()):
            raise HTTPException(401, "Operator credential was not accepted")
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
        )  # Loopback HTTP only; HTTPS deployment requires Secure.
        return dict(
            authenticated=True, csrf_token=csrf, reviewer=settings.reviewer, mode=settings.mode
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

    @app.get("/api/runs", response_model=list[RunView], dependencies=[Depends(reader)])
    async def runs():
        return store.list_runs()

    @app.post("/api/runs", response_model=RunView, status_code=202, dependencies=[Depends(writer)])
    async def launch(body: Launch):
        return store.launch(body)

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
        revision = store.public_data().revision
        if (
            run.data_revision != revision
            or row.get("data_revision") != revision
            or row.get("requires_revalidation")
        ):
            raise StoreError(
                409,
                "Source revision changed. A new investigation is required; no decision/export was made.",
            )
        return run, row

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
