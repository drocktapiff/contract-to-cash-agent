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
                    return run_simulated_continuation(settings, run_id, data, request)
                return root_runner(run_id, data, request)

            runner = phase32_runner
        else:
            runner = fixture.simulated_runner
        application = create_app(settings, runner)
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
        os.environ["OPENAI_API_KEY"] = "local-test-placeholder"
        uvicorn.run(
            application,
            host="127.0.0.1",
            port=args.port,
            access_log=False,
        )
