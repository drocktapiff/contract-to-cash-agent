"""Browser-test server. Always injects the simulated runner, never a real API client."""

import argparse
from pathlib import Path
import os
import tempfile
import uvicorn
from contract_to_cash.web.app import create_app
from contract_to_cash.web.store import Settings
from scripts.build_agent_runtime import build
from tests_web.test_api import ApiTests

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8124)
    parser.add_argument("--recorded", action="store_true")
    parser.add_argument("--slow-test-runner", action="store_true")
    parser.add_argument(
        "--phase32",
        action="store_true",
        help="Simulated authority fixture and elapsed launch cooldown; no production override",
    )
    parser.add_argument(
        "--phase4",
        action="store_true",
        help="Simulated enterprise SDK/source fixtures and browser-only cooldown override",
    )
    parser.add_argument(
        "--paid-ux-limit",
        action="store_true",
        help="Ephemeral test-only persisted admission fixtures, never provider calls",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime = build(root / "runtime")
        settings = Settings(
            data=runtime / "contract_to_cash/data",
            root=root / "runs",
            recordings=root / "recordings",
            frontend=Path("frontend/dist"),
            reviewer="Simulated test operator",
            mode="recorded" if args.recorded else "operator",
            origins=(f"http://127.0.0.1:{args.port}",),
        )
        if args.slow_test_runner:
            import test_agent
            import time

            original = test_agent.FakeClient.create

            def delayed_test_response(self, **kwargs):
                response = original(self, **kwargs)
                time.sleep(0.8)
                return response

            test_agent.FakeClient.create = delayed_test_response
        fixture = ApiTests()
        fixture.settings = settings
        if args.phase32:
            import sys

            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from tests_web.test_workflow import authority_assertion, run_simulated_continuation
            from contract_to_cash.agent.tools import PublicData
            from contract_to_cash.web.resolution_evidence import register_evidence

            data = PublicData(settings.data, "2026-04")
            assertion = authority_assertion(data)
            register_evidence(
                settings.root,
                data,
                assertion,
                "Simulated source verifier",
                True,
                assertion["confirmation_text"],
            )
            root_runner = fixture.simulated_runner

            def phase32_runner(run_id, data, request):
                if hasattr(data, "authority"):
                    return run_simulated_continuation(
                        application.state.store, run_id, data, request
                    )
                return root_runner(run_id, data, request)

            runner = phase32_runner
        else:
            runner = fixture.simulated_runner
        application = create_app(settings, runner)
        fixture.app = application
        if args.phase32:
            from datetime import datetime, timedelta, timezone

            store = application.state.store
            original_continue = store.continue_investigation

            def elapsed_test_cooldown(parent_id, body, pricing):
                for meta in store.metadata():
                    meta["created_at"] = (
                        datetime.now(timezone.utc) - timedelta(minutes=2)
                    ).isoformat()
                    store.write_meta(meta)
                return original_continue(parent_id, body, pricing)

            store.continue_investigation = elapsed_test_cooldown
        if args.phase4:
            import sys

            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from tests_web.test_enterprise import enterprise_root_runner, simulated_analysis

            store = application.state.store
            store.runner = lambda run_id, data, request: enterprise_root_runner(
                store, run_id, data, request
            )
            store.enterprise.runner = lambda analysis: simulated_analysis(
                store.enterprise, analysis
            )
            # Ephemeral simulated browser test only. Independent API tests exercise the real throttle.
            store.check_paid_limits = lambda: None
        if args.phase4 or args.phase32:
            # Explicit existing simulated browser cooldown override, mirrored by admission display.
            # Production availability/limits are exercised by API and dedicated UX tests.
            store = application.state.store
            store.paid_rate_status = lambda at=None: dict(
                available=True,
                reasons=[],
                next_eligible_at=None,
                minute_launches=0,
                hour_launches=0,
            )
        if args.paid_ux_limit:
            import json
            from datetime import datetime, timedelta, timezone
            from uuid import uuid4

            with application.state.store.enterprise.database() as cur:
                for minutes, kind in ((5, "management"), (10, "executive"), (15, "management")):
                    record = dict(
                        id=uuid4().hex,
                        idempotency_key=str(uuid4()),
                        root_run_id="0" * 32,
                        kind=kind,
                        status="incomplete",
                        reason="test_admission_fixture",
                        input_revision="0" * 64,
                        created_at=(
                            datetime.now(timezone.utc) - timedelta(minutes=minutes)
                        ).isoformat(),
                        result=None,
                        provenance=dict(
                            kind="test_admission_fixture",
                            label="Test-only admission history — no provider calls",
                        ),
                    )
                    cur.execute(
                        "INSERT INTO analyses VALUES (?,?,?)",
                        (record["id"], record["idempotency_key"], json.dumps(record)),
                    )
        os.environ["OPENAI_API_KEY"] = "local-test-placeholder"
        uvicorn.run(
            application,
            host="127.0.0.1",
            port=args.port,
            access_log=False,
        )
