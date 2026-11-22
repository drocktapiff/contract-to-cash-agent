"""Read-only, consistent journal projection of recorded lifecycle and current disposition.

Lifecycle sets overlap; current-state sets form an exhaustive partition. No financial
calculations, state changes, provider requests, or reconstructed human approvals.
"""

from collections import defaultdict
import json
from .human_review import PENDING, REJECTED

# Central semantics shared by graph, metrics, link membership and drill-down.
STAGES = {
    "documents": (
        "Source documents received",
        "intake",
        0,
        "Original fictional PDFs · not work items",
        "Document intake",
    ),
    "created": (
        "Work items created",
        "intake",
        0,
        "Distinct persisted cases",
        "Revenue Operations",
    ),
    "prepared": (
        "Automated checks prepared",
        "automation",
        1,
        "Deterministic checks · not approvals",
        "Ledgerline",
    ),
    "investigation": (
        "Requires Human Investigation",
        "investigation",
        1,
        "Recorded exceptions · not evidence of manual triage",
        "Maya / required decision team",
    ),
    "manual": (
        "Manual Investigation Started",
        "investigation",
        2,
        "Explicit attributed investigation activity",
        "Maya",
    ),
    "queue": (
        "Maya review queue entered",
        "maya",
        2,
        "Prepared results sent for verification · includes later decisions",
        "Maya",
    ),
    "individual": ("Individually approved", "maya", 3, "Recorded individual human review", "Maya"),
    "bulk": (
        "Bulk-attested",
        "maya",
        3,
        "Explicit group attestation · not individual inspection",
        "Maya",
    ),
    "rejected": (
        "Review Rejected",
        "blocked",
        3,
        "Recorded rejection · needs investigation",
        "Maya",
    ),
    "further": (
        "Requires Further Investigation",
        "investigation",
        3,
        "Recorded review evidence request",
        "Maya / evidence provider",
    ),
    "closed": (
        "Reviewed & Closed",
        "maya",
        4,
        "Administrative closure · no invoice changes",
        "Maya · Human Verified",
    ),
    "handoff": (
        "Escalated to Sarah",
        "management",
        4,
        "Actual management handoffs · not resolutions",
        "Sarah",
    ),
    "management_complete": (
        "Management Review Completed",
        "management",
        5,
        "Oversight completed · underlying case may remain unresolved",
        "Sarah",
    ),
    "finance": (
        "Awaiting Finance",
        "investigation",
        5,
        "Recorded financial coordination · no approval granted",
        "Authorized Finance team",
    ),
    "evidence": (
        "Awaiting Evidence",
        "investigation",
        5,
        "Recorded management evidence request",
        "Evidence provider",
    ),
    "returned": ("Returned to Maya", "management", 5, "Recorded return for follow-up", "Maya"),
    "corrective": (
        "Linked corrective actions",
        "management",
        5,
        "Case contributions · not corrected invoices",
        "Internal responsible team",
    ),
    "legacy": (
        "Legacy automated closure — no recorded human review",
        "intake",
        4,
        "Historical closure retained without fabricated approval",
        "Legacy automation",
    ),
}
BUCKETS = {
    "closed": ("Reviewed & Closed", "maya"),
    "legacy": ("Legacy automated closure — no recorded human review", "intake"),
    "pending": ("Awaiting Maya Review", "maya"),
    "ready": ("Ready for Processing", "automation"),
    "rejected": ("Review Rejected / Needs Investigation", "blocked"),
    "finance": ("Awaiting Finance Decision", "investigation"),
    "evidence": ("Awaiting Evidence", "investigation"),
    "returned": ("Returned to Maya", "management"),
    "sarah": ("Awaiting Sarah’s Action", "management"),
    "managed": ("Management reviewed · case unresolved", "management"),
    "investigation": ("Requires Human Investigation", "investigation"),
    "other": ("Other unresolved state", "investigation"),
    "unclassified": ("Unclassified / Requires Investigation", "blocked"),
}
HUMAN = {"human", "simulated_fixture"}


def current_bucket(w):
    """Closure first; outstanding financial/evidence authority precedes coordination.

    Missing/conflicting closure provenance is unclassified. Management completion
    never closes work and never overrides an outstanding Finance/evidence decision.
    """
    status = w.get("status")
    if status not in {
        "Closed",
        "Awaiting Financial Review",
        "Awaiting Evidence",
        "Escalated",
        PENDING,
        REJECTED,
        "New",
        "Ready",
        "Human Review Required",
        "Ready for Processing",
    }:
        return "unclassified"
    management = w.get("management") or {}
    decision = str(w.get("current_decision_owner") or "").lower()
    if status == "Closed":
        review = w.get("review") or {}
        if review.get("decision") == "approve":
            return "closed"
        return "unclassified" if review else "legacy"
    if (
        status == "Awaiting Financial Review"
        or management.get("review_status") == "Awaiting Finance"
        or "finance" in decision
        or "financial" in decision
    ):
        return "finance"
    if status == "Awaiting Evidence" or management.get("review_status") == "Awaiting Evidence":
        return "evidence"
    if management.get("review_status") == "Returned to Maya":
        return "returned"
    if (
        status == REJECTED
        or (w.get("review") or {}).get("decision") == "reject"
        or w.get("recommendation_rejected")
    ):
        return "rejected"
    if status == PENDING:
        return "pending"
    if w.get("oversight") or status == "Escalated":
        return "managed" if management.get("review_status") == "Completed" else "sarah"
    if status == "Ready for Processing":
        return "ready"
    if (
        status in ("New", "Ready", "Human Review Required", "Ready for Processing")
        or w.get("automation_eligible") is False
    ):
        return "investigation"
    return "other"


def project(sid, works, documents, events, actions, active=None):
    """Pure projection; input order is the persisted journal sequence, never guessed time."""
    items = {w["work_item_id"]: w for w in works}
    docs = {d["document_id"]: d for d in documents}
    hashes = {d["file_hash"]: d["document_id"] for d in documents}
    memberships = defaultdict(set)
    node_events = defaultdict(set)
    links = {}
    diagnostics = []
    previous = {}
    prepared_events = {}
    seen_handoffs = set()
    evidence_links = defaultdict(set)
    for w in works:
        for h in w.get("supporting_facts", {}):
            if h in hashes:
                evidence_links[hashes[h]].add(w["work_item_id"])
            else:
                diagnostics.append(
                    dict(code="missing_document", item_id=w["work_item_id"], reference=h)
                )

    def add(node, wid, e):
        memberships[node].add(wid)
        node_events[node].add(e["id"])

    def edge(source, target, wid, support):
        if source == target:
            return
        key = (source, target)
        link = links.setdefault(
            key,
            dict(
                id=source + "--" + target,
                source=source,
                target=target,
                item_ids=set(),
                event_ids=set(),
            ),
        )
        link["item_ids"].add(wid)
        link["event_ids"].update(support)

    def move(node, wid, e, source=None):
        add(node, wid, e)
        prior = source or previous.get(wid)
        if prior:
            edge(prior[0], node, wid, [prior[1], e["id"]])
        previous[wid] = (node, e["id"])

    for e in events:
        wid = e.get("item_id")
        kind = e.get("type")
        if e.get("session_id") != sid:
            diagnostics.append(dict(code="foreign_session_event", event_id=e["id"]))
            continue
        details = e.get("details") or {}
        if wid and wid not in items:
            diagnostics.append(dict(code="foreign_event_item", event_id=e["id"], item_id=wid))
            continue
        if not wid:
            if kind.startswith("corrective_action_"):
                for i in details.get("related_ids", []):
                    if i in items:
                        add("corrective", i, e)
                        handoff = next(
                            (
                                x
                                for x in events
                                if x.get("item_id") == i
                                and x.get("type") in ("management_handoff_received", "escalated")
                            ),
                            None,
                        )
                        if handoff and events.index(handoff) < events.index(e):
                            edge("handoff", "corrective", i, [handoff["id"], e["id"]])
            continue
        if kind == "item_created":
            move("created", wid, e)
            if details.get("routine_eligible") is False:
                move("investigation", wid, e)
        elif kind == "document_evidence_associated":
            actual = [hashes[h] for h in e.get("source_hashes", []) if h in hashes]
            if actual and wid in memberships["created"]:
                add("documents", wid, e)
                edge("documents", "created", wid, [e["id"]])
        elif kind == "automated_check_prepared":
            move("prepared", wid, e)
            prepared_events[e["id"]] = wid
            if e.get("after") == PENDING:
                move("queue", wid, e)
        elif kind.startswith("human_review_") and kind in (
            "human_review_approved",
            "human_review_rejected",
            "human_review_evidence_requested",
            "human_review_escalated",
        ):
            p = details.get("preparation_event_id")
            valid = e.get("actor_kind") in HUMAN and prepared_events.get(p) == wid
            if not valid:
                diagnostics.append(dict(code="unbound_review_event", item_id=wid, event_id=e["id"]))
                continue
            source = ("queue", p) if wid in memberships["queue"] else ("prepared", p)
            if kind == "human_review_approved":
                if (
                    details.get("attestation") not in ("individual", "bulk_attested")
                    or e.get("after") != "Closed"
                ):
                    diagnostics.append(
                        dict(code="ambiguous_approval", item_id=wid, event_id=e["id"])
                    )
                    continue
                move(
                    "bulk" if details["attestation"] == "bulk_attested" else "individual",
                    wid,
                    e,
                    source,
                )
                move("closed", wid, e)
            elif kind == "human_review_rejected":
                move("rejected", wid, e, source)
            elif kind == "human_review_evidence_requested":
                move("further", wid, e, source)
            # Escalation is represented by its actual handoff, not an invented manual triage.
        elif kind == "management_handoff_received" or kind == "escalated":
            pair = (wid, e.get("operation_id"))
            if pair not in seen_handoffs:
                move("handoff", wid, e)
                seen_handoffs.add(pair)
            elif kind == "management_handoff_received":
                add("handoff", wid, e)
        elif (
            kind == "human_decision_recorded"
            and e.get("actor_kind") in HUMAN
            and details.get("action") in ("review", "request_evidence", "reject")
        ):
            move("manual", wid, e)
        elif kind == "maya_followup_evidence_requested" and e.get("actor_kind") in HUMAN:
            move("manual", wid, e)
        elif (
            kind
            in (
                "management_review_completed",
                "returned_to_maya",
                "management_evidence_requested",
                "financial_review_coordinated",
            )
            and e.get("actor_kind") in HUMAN
        ):
            node = {
                "management_review_completed": "management_complete",
                "returned_to_maya": "returned",
                "management_evidence_requested": "evidence",
                "financial_review_coordinated": "finance",
            }[kind]
            # A handoff must already exist; never infer management authority.
            if wid in memberships["handoff"]:
                move(node, wid, e)
            else:
                diagnostics.append(
                    dict(code="management_without_handoff", item_id=wid, event_id=e["id"])
                )
        elif kind == "administratively_closed" and not items[wid].get("review"):
            move("legacy", wid, e)

    def node(
        key, label, category, ids, column=0, subtitle="", owner="", event_ids=(), document_ids=()
    ):
        return dict(
            id=key,
            label=label,
            category=category,
            column=column,
            subtitle=subtitle,
            owner=owner,
            count=len(document_ids) if key == "documents" else len(ids),
            work_item_count=len(ids),
            document_count=len(document_ids),
            item_ids=sorted(ids),
            document_ids=sorted(document_ids),
            event_ids=sorted(event_ids),
        )

    nodes = []
    for key, (label, category, column, subtitle, owner) in STAGES.items():
        ids = memberships[key]
        document_ids = (
            set(docs)
            if key == "documents"
            else {d for d, linked in evidence_links.items() if linked & ids}
        )
        if ids or key in ("documents", "created", "prepared", "queue", "closed", "handoff"):
            nodes.append(
                node(
                    key,
                    label,
                    category,
                    ids,
                    column,
                    subtitle,
                    owner,
                    node_events[key],
                    document_ids,
                )
            )
    buckets = defaultdict(set)
    for wid, w in items.items():
        key = current_bucket(w)
        # An apparent reviewed closure with no real approved event is not audit-verified.
        if key == "closed" and wid not in memberships["closed"]:
            key = "unclassified"
            diagnostics.append(dict(code="closure_without_review_event", item_id=wid))
        buckets[key].add(wid)
    current = [
        node(
            "state-" + key,
            label,
            category,
            buckets[key],
            subtitle="Current disposition · counted exactly once",
        )
        for key, (label, category) in BUCKETS.items()
        if buckets[key]
    ]
    accounted = sum(len(ids) for ids in buckets.values())
    for wid in items.keys() - memberships["created"]:
        diagnostics.append(dict(code="missing_creation_event", item_id=wid))
    for n in nodes:
        if n["id"] == "created" and len(n["item_ids"]) != len(items):
            n["subtitle"] = "Recorded creation events; missing history is diagnosed below"
    case_rows = []
    for wid, w in items.items():
        m = w.get("management") or {}
        case_rows.append(
            dict(
                id=wid,
                customer_id=w.get("customer_id"),
                customer_name=w.get("customer_name"),
                issue=(w.get("category") or "").replace("_", " "),
                status=w.get("status"),
                case_owner=w.get("case_owner") or w.get("assigned_owner"),
                reviewer=(w.get("review") or {}).get("actor") or m.get("last_reviewer"),
                decision_owner=w.get("current_decision_owner") or w.get("assigned_owner"),
                oversight_status=m.get("review_status")
                or ("Received" if w.get("oversight") else "No handoff"),
                document_ids=sorted(d for d, linked in evidence_links.items() if wid in linked),
                automated_result=w.get("automated_result"),
                review=w.get("review"),
                event_ids=[
                    e["id"]
                    for e in events
                    if e.get("item_id") == wid and e.get("session_id") == sid
                ],
                corrective_action_ids=[a["id"] for a in actions if wid in a.get("related_ids", [])],
            )
        )
    doc_rows = [
        dict(
            id=d["document_id"],
            filename=d["filename"],
            hash=d["file_hash"],
            customer_id=d.get("customer_id"),
            item_ids=sorted(evidence_links[d["document_id"]]),
            pdf_url=f"/api/document-workspace/sessions/{sid}/evidence/{d['file_hash']}",
        )
        for d in documents
    ]
    # Supporting metrics use precisely the same centrally defined membership sets,
    # including empty sets; zero is visible without inventing a lifecycle transition.
    metric_keys = (
        "documents",
        "created",
        "prepared",
        "closed",
        "state-pending",
        "individual",
        "bulk",
        "rejected",
        "investigation",
        "handoff",
        "state-finance",
        "state-evidence",
        "management_complete",
    )
    lookup = {n["id"]: n for n in nodes + current}
    metrics = []
    for key in metric_keys:
        if key in lookup:
            metrics.append(dict(lookup[key]))
        elif key.startswith("state-"):
            label, category = BUCKETS[key[6:]]
            metrics.append(node(key, label, category, set(), subtitle="Current disposition"))
        else:
            label, category, column, subtitle, owner = STAGES[key]
            metrics.append(node(key, label, category, set(), column, subtitle, owner))
    visible_events = [
        e
        for e in events
        if e.get("session_id") == sid and (not e.get("item_id") or e["item_id"] in items)
    ]
    return dict(
        session_id=sid,
        read_only=sid != active,
        provenance="Synthetic source documents · Actual persisted workflow; actor provenance shown per event",
        nodes=nodes,
        edges=[
            {
                **v,
                "item_ids": sorted(v["item_ids"]),
                "event_ids": sorted(v["event_ids"]),
                "count": len(v["item_ids"]),
            }
            for v in links.values()
        ],
        current_state=current,
        metrics=metrics,
        items=case_rows,
        documents=doc_rows,
        events=visible_events,
        corrective_actions=actions,
        integrity=dict(
            total=len(items),
            accounted=accounted,
            reconciled=accounted == len(items),
            unclassified=len(buckets["unclassified"]),
            diagnostics=diagnostics,
        ),
        methodology="Lifecycle contributions overlap and must not be summed. Connections require ordered recorded events for the same work ID; document associations use recorded evidence hashes, not one-to-one transformations. Current-state precedence: closed with provenance; outstanding Finance; evidence; returned; rejection; pending Maya; management oversight; investigation; other; unclassified. Management completion never resolves an outstanding financial decision. Bulk attestation is not individual inspection. Persona selection is not authenticated RBAC.",
    )


def lifecycle(ws, sid):
    # One SQLite read transaction prevents cross-request snapshots mixing versions.
    with ws.database(ws.directory(sid) / "journal.sqlite3") as conn:
        ws.execute(conn, "BEGIN")
        works = ws.works(conn)
        documents = ws.documents(conn)
        events = [
            json.loads(r[0])
            for r in ws.rows(conn, "SELECT body FROM workflow_events ORDER BY sequence")
        ]
        exists = ws.rows(
            conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='corrective_actions'"
        )
        actions = (
            [json.loads(r[0]) for r in ws.rows(conn, "SELECT body FROM corrective_actions")]
            if exists
            else []
        )
    return project(sid, works, documents, events, actions, ws.active())
