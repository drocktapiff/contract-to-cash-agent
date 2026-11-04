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
        fixture = ApiTests()
        fixture.settings = settings
        os.environ["OPENAI_API_KEY"] = "local-test-placeholder"
        uvicorn.run(
            create_app(settings, fixture.simulated_runner),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
        )
