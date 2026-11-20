"""Explicit fixture preparation. No model client, provider events or financial mutation."""

from decimal import Decimal
import hashlib
import json
from uuid import uuid4
from typing import Literal
from .models import Input
from contract_to_cash.agent.events import Journal
from .store import StoreError, now

PROVENANCE = dict(
    kind="simulated_demo",
    label="Simulated Demo Data",
    fixture_version=1,
    execution="Deterministic Python fixture preparation; no model execution or real human approvals",
)


class PrepareDemo(Input):
    confirmation: Literal["PREPARE SIMULATED DEMO"]


class DemoJournal(Journal):
    def _emit(self, event_type, actor, correlation_id, **payload):
        payload["provenance"] = PROVENANCE
        if "finding" in payload:
            payload["finding"] = dict(
                payload["finding"], origin="simulated_demo", provenance=PROVENANCE
            )
        return super()._emit(event_type, "demo_fixture", correlation_id, **payload)


def prepare(store):
    with store.lock:
        if store.settings.mode != "operator":
            raise StoreError(403, "Recorded mode cannot prepare a scenario")
        if store.active or not store.accepting_launches:
            raise StoreError(
                409, "Wait for the active worker or workspace recovery before preparing"
            )
        data = store.public_data()
        run_id = hashlib.sha256(("ledgerline-full-demo-v1:" + data.revision).encode()).hexdigest()[
            :32
        ]
        indexed = store.index / (run_id + ".json")
        if indexed.exists():
            return store.snapshot(run_id)
        destination = store.settings.root / run_id
        if not destination.exists():
            stage = store.settings.root / ".demo-preparation" / uuid4().hex
            with DemoJournal(stage, io_lock=store.lock) as journal:
                journal.run_id = run_id
                journal.emit("demo.preparation.started", provenance=PROVENANCE)
                tools = store.investigation_tools(data, journal)

                def execute(name, **arguments):
                    result = tools.execute(name, arguments)
                    if name == "submit_finding":
                        result.update(origin="simulated_demo", provenance=PROVENANCE)
                    journal.emit("demo.tool.completed", tool=name, result=result)
                    return result

                execute("screen_customers")
                candidates = [
                    cid for cid, row in tools.comparisons.items() if row["status"] != "clean"
                ]
                execute("get_customer_evidence", customer_ids=candidates)
                # Group only actual saved template/difference matches. Never assert a root cause.
                groups = {}
                for cid in candidates:
                    row = tools.comparisons[cid]
                    if row["status"] == "discrepancy":
                        groups.setdefault(
                            (row["pricing_template"], row["difference_cad"]), []
                        ).append(cid)
                grouped = set()
                for ids in groups.values():
                    if len(ids) < 3:
                        continue
                    execute(
                        "submit_finding",
                        customer_ids=ids,
                        evidence_ids=sorted(set().union(*(tools._required(cid) for cid in ids))),
                        state="verified",
                        rationale="Simulated Demo Data: matching discrepancies; configuration cause remains a hypothesis.",
                    )
                    grouped.update(ids)
                for cid in candidates:
                    if cid in grouped:
                        continue
                    execute(
                        "submit_finding",
                        customer_ids=[cid],
                        evidence_ids=sorted(tools._required(cid)),
                        state=(
                            "verified"
                            if tools.comparisons[cid]["status"] == "discrepancy"
                            else "proposed"
                        ),
                        rationale="Simulated Demo Data: deterministic comparison; unresolved authority/invoice ambiguity requires human judgment.",
                    )
                for finding in tools.findings.values():
                    finding.update(origin="simulated_demo", provenance=PROVENANCE)
                    execute(
                        "request_human_review", finding_id=finding["finding_id"], action="review"
                    )
                    tools.reviews[finding["finding_id"]]["provenance"] = PROVENANCE
                    journal.emit(
                        "demo.review.decided",
                        finding_id=finding["finding_id"],
                        decision=(
                            "needs_information"
                            if finding["state"] != "verified"
                            else "evidence_inspected"
                        ),
                        reviewer="Simulated demo reviewer",
                        rationale="Fixture-backed review illustration only. No export, billing correction or strategic authorization.",
                    )
                amounts = [
                    Decimal(row["difference_cad"])
                    for row in tools.comparisons.values()
                    if row["status"] == "discrepancy"
                ]
                totals = dict(
                    additional_receivables_cad=str(
                        sum((a for a in amounts if a > 0), Decimal("0.00"))
                    ),
                    potential_credits_cad=str(-sum((a for a in amounts if a < 0), Decimal("0.00"))),
                )
                journal.emit(
                    "demo.preparation.completed", status="completed", unresolved_exceptions=True
                )
                journal.save_report(
                    dict(
                        run_id=run_id,
                        provenance=PROVENANCE,
                        data_revision=data.revision,
                        journal_sequence=journal.sequence,
                        status="completed",
                        reason="simulated_demo_prepared",
                        screening_complete=True,
                        customers_compared=sorted(tools.comparisons),
                        customers_with_retrieved_documents=sorted(candidates),
                        findings=list(tools.findings.values()),
                        reviews=list(tools.reviews.values()),
                        financial_totals=totals,
                        metrics=dict(
                            api_requests=0,
                            agent_tool_calls=0,
                            input_tokens=0,
                            output_tokens=0,
                            estimated_api_cost_usd="0",
                            actual_billed_cost_usd=None,
                            cost_accounting_complete=True,
                            duration_seconds=None,
                            fixture_tool_operations=sum(
                                e["type"] == "demo.tool.completed" for e in journal.events
                            ),
                        ),
                    )
                )
            stage.replace(destination)  # Closed SQLite handles before Windows directory rename.
        # Publication is last. A crash after rename is recoverable by repeating preparation.
        report = json.loads((destination / "report.json").read_text(encoding="utf-8"))
        if report.get("data_revision") != data.revision or report.get("provenance") != PROVENANCE:
            raise StoreError(409, "Retained scenario requires administrator inspection")
        store.write_meta(
            dict(
                id=run_id,
                idempotency_key="demo:" + run_id,
                created_at=now(),
                status="completed",
                reason="simulated_demo_prepared",
                provenance=PROVENANCE,
                reviewer="Simulated demo reviewer",
                continuation=None,
            )
        )
        return store.snapshot(run_id)
