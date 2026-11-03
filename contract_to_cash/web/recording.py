"""Offline import of a manually reviewed, genuine run. No sample discoveries bundled."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator
from .models import EventView, RunView
from .presentation import event_view, evidence_from_events, finding_view, review_view


class Recording(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal[1] = 1
    label: Literal["Recorded Investigation"] = "Recorded Investigation"
    source_run_id: str
    operator_attests_genuine_and_reviewed: Literal[True]
    run: RunView
    events: list[EventView]
    evidence: dict[str, list[dict]]

    @model_validator(mode="after")
    def validate_recording(self):
        if self.run.mode != "recorded" or self.source_run_id != self.run.id:
            raise ValueError("Recording identity/mode mismatch")
        if self.run.status in ("queued", "running"):
            raise ValueError("Import a settled investigation, not a live worker")
        sequences = [e.sequence for e in self.events]
        if sequences != sorted(set(sequences)):
            raise ValueError("Events must retain their original unique sequence order")
        if sanitize(self.model_dump()) != self.model_dump():
            raise ValueError("Recording contains unsanitized private fields or identifiers")
        return self


def sanitize(value):
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, dict):
        return {
            k: ("Recorded operator" if k == "reviewer" else sanitize(v))
            for k, v in value.items()
            if not re.search(
                r"(?i)(api.?key|password|secret|encrypted|reasoning_content|authorization)", k
            )
        }
    if isinstance(value, str):
        value = re.sub(
            r"(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,})", "[REDACTED CREDENTIAL]", value
        )
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED EMAIL]", value)
        value = re.sub(
            r'(?:/(?:workspace|home|tmp|Users)/[^\s"<>]+|[A-Za-z]:\\[^\n"<>]+)',
            "[REDACTED PATH]",
            value,
        )
    return value


def import_recording(source, destination, reviewed=False):
    if not reviewed:
        raise ValueError("Explicit attestation and manual review are required before import")
    report = json.loads((source / "report.json").read_text(encoding="utf-8"))
    run_id = report["run_id"]
    if not re.fullmatch("[0-9a-f]{32}", run_id):
        raise ValueError("Run identity is not an original journal UUID")
    with closing(
        sqlite3.connect((source / "events.sqlite3").resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        with closing(db.cursor()) as cursor:
            events = [
                json.loads(row[0])
                for row in cursor.execute("SELECT body FROM events ORDER BY sequence").fetchall()
            ]
    if (
        not events
        or any(e["run_id"] != run_id for e in events)
        or events[0]["type"] != "investigation.started"
    ):
        raise ValueError("Report and journal identity do not agree")
    if not any(
        e["type"] == "api.completed"
        and bool(e["payload"].get("model"))
        and str(e["payload"].get("response_id", "")).startswith("resp_")
        and not str(e["payload"].get("model", "")).startswith(("test", "simulated"))
        for e in events
    ):
        raise ValueError(
            "No real API response provenance; do not import test fixtures as genuine recordings"
        )
    allowed_metrics = (
        "duration_seconds",
        "agent_tool_calls",
        "tool_failures",
        "api_requests",
        "human_interventions",
        "human_review_requests",
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
        "estimated_api_cost_usd",
        "usage_priced_cost_usd",
        "actual_billed_cost_usd",
        "cost_accounting_complete",
    )
    findings = [finding_view(f) for f in report.get("findings", [])]
    started = events[0]
    candidates = []
    for event in events:
        if event["type"] == "tool.completed" and event["payload"]["tool"] == "screen_customers":
            candidates = event["payload"]["result"]["candidates"]
    run = RunView(
        id=run_id,
        mode="recorded",
        status=report["status"],
        reason=report["reason"],
        created_at=started["timestamp"],
        period=report["period"],
        model=started["payload"]["model"],
        data_revision=report["data_revision"],
        report_event_sequence=report.get("journal_sequence", 0),
        last_event_sequence=events[-1]["sequence"],
        screening_complete=report.get("screening_complete", False),
        customers_compared=report.get("customers_compared", []),
        customers_with_retrieved_documents=report.get("customers_with_retrieved_documents", []),
        findings=findings,
        reviews=[review_view(r) for r in report.get("reviews", [])],
        candidates=candidates,
        financial_totals={
            k: v
            for k, v in report.get("financial_totals", {}).items()
            if k in ("additional_receivables_cad", "potential_credits_cad", "disclaimer")
        },
        metrics={k: v for k, v in report["metrics"].items() if k in allowed_metrics},
    )
    payload = dict(
        format_version=1,
        label="Recorded Investigation",
        source_run_id=run_id,
        operator_attests_genuine_and_reviewed=True,
        run=run.model_dump(),
        events=[event_view(e).model_dump() for e in events],
        evidence={
            f["finding_id"]: evidence_from_events(events, f["evidence_ids"]) for f in findings
        },
    )
    clean = sanitize(payload)
    for fid, documents in clean["evidence"].items():
        original = {doc["document_id"]: doc for doc in payload["evidence"][fid]}
        for doc in documents:
            if doc != original[doc["document_id"]]:
                doc["redacted"] = True
    recording = Recording.model_validate(clean)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / (run_id + ".json")
    with output.open("x", encoding="utf-8") as stream:
        stream.write(recording.model_dump_json(indent=2) + "\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--confirm-genuine-and-manually-reviewed", action="store_true")
    args = parser.parse_args()
    try:
        path = import_recording(
            args.source, args.destination, args.confirm_genuine_and_manually_reviewed
        )
        print(
            "Sanitized recording written. Inspect every field before public use; no upload/deployment occurred."
        )
    except Exception:
        parser.exit(
            1,
            "Import refused. Verify original settled run, provenance, attestation and destination; no raw artifact was published.\n",
        )
