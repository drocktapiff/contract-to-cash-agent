"""Generate -> actual PDFs -> independent rules -> separate oracle evaluation."""

import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter
from contract_to_cash.document_ops.generator import generate
from contract_to_cash.document_ops.intake import ingest
from contract_to_cash.document_ops.evaluate import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New isolated directory; never an existing workspace",
    )
    parser.add_argument("--seed", type=int, default=202604)
    args = parser.parse_args()
    start = perf_counter()
    root = generate(args.output, args.seed)
    result = ingest(root / "documents", root / "processing" / "journal.sqlite3")
    report = evaluate(result, root / "evaluation" / "expected.json")
    (root / "processing" / "results.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    (root / "evaluation" / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "documents": len(result["documents"]),
        "document_types": dict(
            Counter(d["document_type"] or "unsupported" for d in result["documents"])
        ),
        "customers_matched": len(
            {d["customer_id"] for d in result["documents"] if d["customer_id"]}
        ),
        "work_items": len(result["work_items"]),
        "routine": sum(w["automation_eligible"] for w in result["work_items"]),
        "exceptions": sum(not w["automation_eligible"] for w in result["work_items"]),
        "unresolved": sum(w["intentionally_unresolved"] for w in result["work_items"]),
        "metrics": report["metrics"],
        "evaluation_passed": report["passed"],
        "parse_failures": report["parse_failures"],
        "duration_seconds": round(perf_counter() - start, 3),
        "paid_model_calls": 0,
    }
    (root / "evaluation" / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
