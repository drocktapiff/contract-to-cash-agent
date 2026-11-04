"""Local-only launcher. No remote binding, automatic investigation, or credential echo."""

import argparse
import os
from pathlib import Path
import uvicorn
from .app import create_app
from .store import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=Path("agent-runtime-web/contract_to_cash/data")
    )
    parser.add_argument("--runs", type=Path, default=Path("runs/web"))
    parser.add_argument("--recordings", type=Path, default=Path("recordings"))
    parser.add_argument("--frontend", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--mode", choices=["operator", "recorded"], default="operator")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    app = create_app(
        Settings(
            data=args.data,
            root=args.runs,
            recordings=args.recordings,
            frontend=args.frontend,
            mode=args.mode,
            reviewer=os.environ.get("CONTRACT_WEB_REVIEWER", "Local operator"),
            origins=(
                f"http://127.0.0.1:{args.port}",
                f"http://localhost:{args.port}",
                "http://127.0.0.1:5173",
                "http://localhost:5173",
            ),
        )
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
