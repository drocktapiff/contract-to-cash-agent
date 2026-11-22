"""Read-only activity analytics from immutable events; overlapping stages are not closures."""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from .store import StoreError
from .human_review import PENDING, REJECTED

SERIES = {
    "automation": {"label": "Ledgerline Automation", "colour": "#2463c5"},
    "maya": {"label": "Maya", "colour": "#187849"},
    "sarah": {"label": "Sarah", "colour": "#b95313"},
}
OUTCOMES = {
    "all",
    "prepared",
    "awaiting_review",
    "approved_individual",
    "approved_bulk",
    "rejected",
    "closed",
    "escalated",
    "management_complete",
    "returned",
    "corrective",
    "legacy_closed",
    "management_coordination",
    "evidence_requested",
    "review_escalated",
}


def activity(
    ws,
    sid,
    mode="cumulative",
    group="operation",
    outcome="all",
    series="automation,maya,sarah",
    start=None,
    end=None,
    operation=None,
):
    if (
        mode not in ("cumulative", "interval")
        or group not in ("operation", "second", "minute", "hour")
        or outcome not in OUTCOMES
    ):
        raise StoreError(422, "Unsupported activity metric or grouping")
    chosen = set(filter(None, series.split(",")))
    if not chosen <= SERIES.keys():
        raise StoreError(422, "Unknown activity series")

    def stamp(value):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if d.tzinfo is None:
                raise ValueError()
            return d.timestamp()
        except (ValueError, TypeError, AttributeError):
            raise StoreError(
                422, "Activity time bounds require timezone-aware timestamps"
            ) from None

    lo = stamp(start) if start else None
    hi = stamp(end) if end else None
    if lo is not None and hi is not None and lo > hi:
        raise StoreError(422, "Time range is reversed")
    snap = ws.snapshot(sid)
    works = {w["work_item_id"]: w for w in snap["items"]}
    with ws.database(ws.directory(sid) / "journal.sqlite3") as conn:
        events = [
            json.loads(r[0])
            for r in ws.rows(conn, "SELECT body FROM workflow_events ORDER BY sequence")
        ]
    handoffs = {
        (e["operation_id"], e["item_id"])
        for e in events
        if e["type"] == "management_handoff_received"
    }
    contributions = []
    for e in events:
        kind = e["type"]
        details = e["details"]
        ids = (
            [e["item_id"]]
            if e.get("item_id") in works
            else [i for i in details.get("related_ids", []) if i in works]
        )
        if not ids:
            continue
        if kind == "automated_check_prepared":
            actor = "automation"
            tags = ["prepared"]
            marker = "circle"
        elif kind == "human_review_approved":
            actor = "maya"
            tags = [
                (
                    "approved_bulk"
                    if details["attestation"] == "bulk_attested"
                    else "approved_individual"
                ),
                "closed",
            ]
            marker = "square" if tags[0] == "approved_bulk" else "diamond"
        elif kind == "human_review_rejected":
            actor = "maya"
            tags = ["rejected"]
            marker = "cross"
        elif (
            kind == "management_handoff_received"
            or kind == "escalated"
            and (e["operation_id"], e["item_id"]) not in handoffs
        ):
            actor = "sarah"
            tags = ["escalated"]
            marker = "triangle"
        elif kind in (
            "priority_changed",
            "coordination_owner_assigned",
            "management_evidence_requested",
            "financial_review_coordinated",
        ):
            actor = "sarah"
            tags = ["management_coordination"]
            marker = "diamond"
        elif kind in ("human_review_evidence_requested", "maya_followup_evidence_requested"):
            actor = "maya"
            tags = ["evidence_requested"]
            marker = "square"
        elif kind == "human_review_escalated":
            actor = "maya"
            tags = ["review_escalated"]
            marker = "triangle"
        elif kind == "management_review_completed":
            actor = "sarah"
            tags = ["management_complete"]
            marker = "diamond"
        elif kind == "returned_to_maya":
            actor = "sarah"
            tags = ["returned"]
            marker = "cross"
        elif kind.startswith("corrective_action_"):
            actor = "sarah"
            tags = ["corrective"]
            marker = "square"
        elif kind == "administratively_closed" and not works[ids[0]].get("review"):
            actor = "automation"
            tags = ["legacy_closed"]
            marker = "square"
        else:
            continue
        if kind == "automated_check_prepared" and any(works[i]["status"] == PENDING for i in ids):
            tags.append("awaiting_review")
        contributions.append(
            dict(series=actor, outcomes=tags, marker=marker, event=e, ids=ids, t=stamp(e["at"]))
        )
    # Metrics use actual decisions and distinct work identities, not plotted stage sums.
    approved = [c for c in contributions if c["event"]["type"] == "human_review_approved"]
    rejected = [c for c in contributions if c["event"]["type"] == "human_review_rejected"]

    def union(rows):
        return sorted({i for c in rows for i in c["ids"]})

    prepared = [c for c in contributions if "prepared" in c["outcomes"]]
    decisions = [
        c
        for c in contributions
        if c["event"]["type"]
        in (
            "human_review_approved",
            "human_review_rejected",
            "human_review_evidence_requested",
            "human_review_escalated",
        )
    ]
    duration = []
    timed_decisions = []
    for c in decisions:
        p = next(
            (e for e in events if e["id"] == c["event"]["details"].get("preparation_event_id")),
            None,
        )
        if p:
            elapsed = c["t"] - stamp(p["at"])
            if elapsed >= 0:
                duration.append(elapsed)
                timed_decisions.append(c)
    metrics = {
        "prepared": dict(label="Automated checks prepared", ids=union(prepared)),
        "awaiting_review": dict(
            label="Awaiting Maya Review",
            ids=sorted(i for i, w in works.items() if w["status"] == PENDING),
        ),
        "approved_individual": dict(
            label="Individually approved reviews",
            ids=union([c for c in approved if "approved_individual" in c["outcomes"]]),
        ),
        "approved_bulk": dict(
            label="Bulk-attested approvals",
            ids=union([c for c in approved if "approved_bulk" in c["outcomes"]]),
        ),
        "rejected": dict(label="Rejected results", ids=union(rejected)),
        "closed": dict(
            label="Reviewed & Closed",
            ids=sorted(
                i
                for i, w in works.items()
                if w["status"] == "Closed" and w.get("review", {}).get("decision") == "approve"
            ),
        ),
        "escalated": dict(
            label="Management escalations received",
            ids=union([c for c in contributions if "escalated" in c["outcomes"]]),
        ),
        "outstanding_management": dict(
            label="Outstanding management decisions",
            ids=sorted(
                i
                for i, w in works.items()
                if w.get("oversight")
                and w.get("management", {}).get("review_status") != "Completed"
            ),
        ),
    }
    for m in metrics.values():
        m["value"] = len(m["ids"])
    metrics["acceptance_rate"] = dict(
        label="Review acceptance rate",
        value=len(approved) / (len(approved) + len(rejected)) if approved or rejected else None,
        ids=union(approved + rejected),
        basis="Approved decisions / (approved + rejected decisions); pending reviews excluded",
    )
    metrics["turnaround"] = dict(
        label="Mean review turnaround (seconds)",
        value=sum(duration) / len(duration) if duration else None,
        ids=union(timed_decisions),
        basis="Actual non-negative preparation-to-decision intervals; not hands-on labor",
    )
    selected = [
        c
        for c in contributions
        if c["series"] in chosen
        and (outcome == "all" or outcome in c["outcomes"])
        and (lo is None or c["t"] >= lo)
        and (hi is None or c["t"] <= hi)
        and (not operation or c["event"]["operation_id"] == operation)
    ]
    groups = defaultdict(list)
    for c in selected:
        bucket = (
            (c["event"]["operation_id"] or c["event"]["id"])
            if group == "operation"
            else int(c["t"] // {"second": 1, "minute": 60, "hour": 3600}[group])
        )
        groups[(c["series"], bucket)].append(c)
    points = []
    seen = defaultdict(set)
    event_counts = defaultdict(int)
    for (actor, bucket), rows in sorted(
        groups.items(), key=lambda item: (max(r["t"] for r in item[1]), item[0][0], str(item[0][1]))
    ):
        ids = union(rows)
        seen[actor].update(ids)
        event_counts[actor] += len(rows)
        last = max(rows, key=lambda r: r["t"])
        points.append(
            dict(
                id=hashlib.sha256(f"{actor}:{group}:{bucket}".encode()).hexdigest()[:24],
                series=actor,
                at=last["event"]["at"],
                first_at=min(rows, key=lambda r: r["t"])["event"]["at"],
                count=len(ids),
                value=len(seen[actor]) if mode == "cumulative" else len(ids),
                cumulative_events=event_counts[actor],
                event_count=len(rows),
                marker=last["marker"] if len({r["marker"] for r in rows}) == 1 else "diamond",
                outcomes=sorted({o for r in rows for o in r["outcomes"]}),
                operation_ids=sorted(
                    {r["event"]["operation_id"] for r in rows if r["event"]["operation_id"]}
                ),
                items=[
                    dict(
                        id=i,
                        customer_id=works[i]["customer_id"],
                        status=works[i]["status"],
                        lifecycle_label=works[i]["lifecycle_label"],
                    )
                    for i in ids
                ],
                events=[r["event"] for r in sorted(rows, key=lambda r: (r["t"], r["event"]["id"]))],
            )
        )
    ordered = sorted(contributions, key=lambda c: c["t"])
    return dict(
        session_id=sid,
        mode=mode,
        group=group,
        outcome=outcome,
        series=SERIES,
        points=points,
        metrics=metrics,
        range=dict(
            start=ordered[0]["event"]["at"] if ordered else None,
            end=ordered[-1]["event"]["at"] if ordered else None,
        ),
        operations=sorted(
            {c["event"]["operation_id"] for c in contributions if c["event"]["operation_id"]}
        ),
        distinct_closed=sum(w["status"] == "Closed" for w in works.values()),
        legacy_closed=sum(w["status"] == "Closed" and not w.get("review") for w in works.values()),
        methodology="Stage contributions overlap. Each point counts distinct work IDs in its actual-time group; cumulative lines count unique work IDs per actor in the selected range, not closures or summed stages. Bulk attestations are not individual inspections. Escalations received are not resolutions. Awaiting-review filters select the current pending cohort. Operation points use the latest contributing event timestamp; timestamps are never spaced artificially. Turnaround is elapsed wall-clock time, not labor.",
    )
