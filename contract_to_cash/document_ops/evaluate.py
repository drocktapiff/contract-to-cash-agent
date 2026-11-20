"""Independent oracle comparison. Intake never imports this module or accesses its input."""

import json
from pathlib import Path


def evaluate(actual, manifest):
    expected = json.loads(Path(manifest).read_text(encoding="utf-8"))
    docs = {d["file_hash"]: d for d in actual["documents"]}
    failures = []
    scores = {}

    def score(name, checks):
        checks = list(checks)
        scores[name] = {
            "correct": sum(bool(v) for v in checks),
            "total": len(checks),
            "accuracy": sum(bool(v) for v in checks) / len(checks) if checks else None,
        }

    score(
        "document_classification",
        (
            docs.get(d["file_hash"], {}).get("document_type") == d["document_type"]
            for d in expected["documents"]
        ),
    )
    score(
        "customer_contract_matching",
        (
            (
                docs.get(d["file_hash"], {}).get("customer_id"),
                docs.get(d["file_hash"], {}).get("contract_id"),
            )
            == (d["customer_id"], d["contract_id"])
            for d in expected["documents"]
        ),
    )
    score(
        "key_field_extraction",
        (
            docs.get(d["file_hash"], {}).get("fields", {}).get(k) == v
            for d in expected["documents"]
            for k, v in d["key_fields"].items()
        ),
    )
    score(
        "document_relationships",
        (
            all(
                docs.get(d["file_hash"], {}).get("fields", {}).get(k) == v
                for k, v in d.get("relationships", {}).items()
            )
            for d in expected["documents"]
        ),
    )

    def key(w):
        return tuple(
            w.get(k) for k in ("customer_id", "contract_id", "category", "business_object_id")
        )

    wanted = {key(w): w for w in expected["work_items"]}
    found = {key(w): w for w in actual["work_items"]}
    duplicates = len(actual["work_items"]) - len(found)
    hits = len(wanted.keys() & found.keys())
    scores["work_item_precision"] = {
        "correct": hits,
        "total": len(actual["work_items"]),
        "accuracy": hits / len(actual["work_items"]) if actual["work_items"] else None,
    }
    scores["work_item_recall"] = {
        "correct": hits,
        "total": len(wanted),
        "accuracy": hits / len(wanted) if wanted else None,
    }
    fields = {
        "financial_accuracy": ["financial_impact"],
        "automation_eligibility": ["automation_eligible", "automatic_closure_allowed"],
        "routing_review": [
            "original_functional_owner",
            "human_review_required",
            "intentionally_unresolved",
        ],
        "action_evidence": ["required_action", "source_documents"],
    }
    for name, columns in fields.items():
        checks = []
        for identity, w in wanted.items():
            other = found.get(identity)
            ok = other is not None and all(other.get(c) == w[c] for c in columns)
            checks.append(ok)
            if not ok:
                failures.append(
                    {
                        "metric": name,
                        "work_item": list(identity),
                        "expected": {c: w[c] for c in columns},
                        "actual": {c: other.get(c) for c in columns} if other else None,
                    }
                )
        score(name, checks)
    score(
        "determinate_financial_calculations",
        (
            found.get(identity, {}).get("financial_impact") == w["financial_impact"]
            for identity, w in wanted.items()
            if w["financial_impact"] is not None
        ),
    )

    def valid_span(span):
        doc = docs.get(span.get("file_hash"))
        try:
            return bool(
                doc
                and doc["document_id"] == span["document_id"]
                and span["page"] >= 1
                and 0 <= span["start"] < span["end"]
                and doc["pages"][span["page"] - 1][span["start"] : span["end"]] == span["text"]
            )
        except (KeyError, IndexError, TypeError):
            return False

    score(
        "evidence_integrity",
        (
            bool(w["evidence"])
            and all(
                valid_span(s) and s["document_id"] in w["source_documents"] for s in w["evidence"]
            )
            for w in actual["work_items"]
        ),
    )
    for identity in found.keys() - wanted.keys():
        failures.append({"unexpected_work_item": list(identity)})
    for identity in wanted.keys() - found.keys():
        failures.append({"missing_work_item": list(identity)})
    unsafe = sum(
        w["status"] in ("Closed", "Resolved")
        and (key(w) not in wanted or not wanted[key(w)]["automatic_closure_allowed"])
        for w in actual["work_items"]
    )
    return {
        "metrics": scores,
        "unsafe_automatic_closures": unsafe,
        "duplicate_work_items": duplicates,
        "parse_failures": sum(bool(d["errors"]) for d in actual["documents"]),
        "expected_documents": len(expected["documents"]),
        "actual_documents": len(actual["documents"]),
        "failures": failures,
        "passed": all(s["correct"] == s["total"] for s in scores.values())
        and not unsafe
        and not duplicates,
        "paid_model_calls": actual["paid_model_calls"],
    }
