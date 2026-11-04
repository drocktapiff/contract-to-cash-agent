"""Register source-verified authority assertions without modifying financial fixtures."""

import argparse
import json
from pathlib import Path
from contract_to_cash.agent.tools import PublicData
from contract_to_cash.web.resolution_evidence import register_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=Path("agent-runtime-web/contract_to_cash/data")
    )
    parser.add_argument("--runs", type=Path, default=Path("runs/web"))
    parser.add_argument("--assertion", type=Path, required=True)
    parser.add_argument(
        "--document",
        type=Path,
        required=True,
        help="Original written confirmation, UTF-8 text; never a model summary",
    )
    parser.add_argument("--verified-by", required=True)
    parser.add_argument("--verified-source-and-authority", action="store_true")
    args = parser.parse_args()
    try:
        evidence = register_evidence(
            args.runs,
            PublicData(args.data, "2026-04"),
            json.loads(args.assertion.read_text(encoding="utf-8")),
            args.verified_by,
            args.verified_source_and_authority,
            args.document.read_bytes().decode("utf-8"),
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(evidence["evidence_id"])


if __name__ == "__main__":
    main()
