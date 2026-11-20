"""Ingest PDFs without any source ledger or answer manifest."""

import argparse
import json
from pathlib import Path
from contract_to_cash.document_ops.intake import ingest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = ingest(args.input, args.database)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "documents": len(result["documents"]),
                "work_items": len(result["work_items"]),
                "paid_model_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
