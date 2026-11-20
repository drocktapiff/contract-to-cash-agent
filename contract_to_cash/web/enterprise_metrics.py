"""Deterministic prototype metrics and explicitly hypothetical CAD scenarios."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Literal
from pydantic import Field, model_validator
from .models import Input
from .resolution_evidence import digest
from .store import StoreError


class Scenario(Input):
    traditional_employment_cad: Decimal = Field(default=Decimal("180000"), ge=0, le=1000000000)
    redesigned_employment_cad: Decimal = Field(default=Decimal("90000"), ge=0, le=1000000000)
    annual_software_cad: Decimal = Field(default=Decimal("5000"), ge=0, le=1000000000)
    implementation_total_cad: Decimal = Field(default=Decimal("0"), ge=0, le=1000000000000)
    teams: int = Field(default=1, ge=1, le=10000, strict=True)
    assumed_workload_reduction_percent: Decimal | None = Field(default=None, ge=0, le=100)
    basis: Literal["illustrative_assumptions"] = "illustrative_assumptions"


def roi(scenario):
    s = scenario
    with localcontext() as ctx:
        ctx.prec = 50
        money = lambda n: str(n.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
        previous = s.traditional_employment_cad * s.teams
        recurring = (s.redesigned_employment_cad + s.annual_software_cad) * s.teams
        benefit = previous - recurring
        return dict(
            currency="CAD",
            basis=s.basis,
            previous_recurring_annual_cad=money(previous),
            redesigned_recurring_annual_cad=money(recurring),
            recurring_annual_net_benefit_cad=money(benefit),
            operating_cost_reduction_percent=money(benefit / previous * 100) if previous else None,
            implementation_total_cad=money(s.implementation_total_cad),
            first_year_net_benefit_cad=money(benefit - s.implementation_total_cad),
            payback_months=(
                money(s.implementation_total_cad / benefit * 12) if benefit > 0 else None
            ),
            payback_basis="Uniform monthly realization assumed; no payback when recurring benefit is non-positive",
            disclaimer="Illustrative projection, not measured savings, staffing reduction, revenue collection or an approved budget. All annual costs are per team; implementation is a total. Workload assumption does not discount costs again.",
        )


def operational_snapshot(store, selected=None):
    """One root with replacements, never sum the same customer's exposure across runs."""
    runs = store.list_runs()
    by_id = {r.id: r for r in runs}
    if selected:
        if selected not in by_id:
            raise StoreError(404, "Originating billing review not found")
        root = by_id[selected]
        while root.continuation:
            root = by_id.get(root.continuation["parent_run_id"])
            if root is None:
                raise StoreError(409, "Continuation lineage is unavailable")
    else:
        root = next((r for r in runs if not r.continuation), None)
    if not root:
        return dict(
            root_run_id=None,
            period="2026-04",
            scope="Single-operator prototype; no billing review selected",
            runs=[],
            cases=[],
            metrics=dict(
                customers_screened=0,
                findings_verified=0,
                outstanding_exceptions=0,
                resolved_cases=0,
                unresolved_cases=0,
                human_contributions=0,
                execution_seconds=None,
                estimated_api_cost_usd=None,
            ),
            financial=dict(
                potential_receivables_cad=None,
                potential_credits_cad=None,
                unresolved_quantifiable_exposure_cad=None,
                unquantified_cases=0,
            ),
            patterns=[],
            references={},
            limitations=[
                "No persisted investigation results; no departmental or realized financial claims are supported."
            ],
            revisions=[],
        )
    family = [
        r
        for r in runs
        if r.id == root.id or (r.continuation and r.continuation["parent_run_id"] == root.id)
    ]
    family.sort(key=lambda r: (r.created_at, r.id))
    valid = {}
    for r in family:
        try:
            if r.mode == "live":
                store.validate_current(r.id)
            valid[r.id] = not (r.status in ("queued", "running") or r.data_revision is None)
        except StoreError:
            valid[r.id] = False
    chosen = {cid: root for f in root.findings for cid in f["customer_ids"]}
    # Only completed scoped continuations supersede originals; partial attempts remain disclosed.
    for r in family:
        if r.continuation and r.status == "completed" and valid[r.id]:
            for cid in r.continuation["customer_ids"]:
                chosen[cid] = r
    refs, cases, amounts, unknown, verified_ids, groups = {}, [], {}, set(), set(), []
    for r in family:
        for f in r.findings:
            relevant = [cid for cid in f["customer_ids"] if chosen.get(cid, root).id == r.id]
            if not relevant or f["state"] == "retracted":
                continue
            reviews = [v for v in r.reviews if v["finding_id"] == f["finding_id"]]
            human = [v for v in r.interventions if v["finding_id"] == f["finding_id"]]
            last = human[-1] if human else None
            if last and last["action"] == "dismiss":
                state = "dismissed"
            elif last and last["action"] == "escalate":
                state = "awaiting_clarification"
            elif last and last["action"] == "resolve":
                state = "documented_not_reinvestigated"
            elif any(v["status"] == "approved" for v in reviews):
                state = "reviewed"
            elif any(v["status"] == "rejected" for v in reviews):
                state = "dismissed"
            elif any(v["status"] == "needs_information" for v in reviews):
                state = "awaiting_clarification"
            else:
                state = "needs_review"
            verified = bool(
                valid[r.id]
                and f["state"] == "verified"
                and f.get("evidence_verified")
                and not f.get("requires_revalidation")
                and f["data_revision"] == r.data_revision
            )
            cidref = f"case:{r.id}:{f['finding_id']}:{f['version']}"
            case = dict(
                provenance=r.provenance,
                reference_id=cidref,
                run_id=r.id,
                finding_id=f["finding_id"],
                customer_ids=relevant,
                state=state,
                evidence_verified=verified,
                evidence_ids=f["evidence_ids"],
                data_revision=f["data_revision"],
                finding_version=f["version"],
                comparison=f.get("comparison"),
                comparisons=f.get("comparisons", []),
                recommendation=f.get("recommendation"),
                human_contributions=human,
                review_history=reviews,
                model_hypothesis=f.get("model_hypothesis"),
                pattern=f.get("pattern"),
            )
            cases.append(case)
            refs[cidref] = dict(kind="case", body=case)
            if verified:
                verified_ids.add(cidref)
            rows = f.get("comparisons") or [f.get("comparison", {})]
            for row in rows:
                cid = row.get("customer_id")
                if cid not in relevant:
                    continue
                if (
                    verified
                    and row.get("status") == "discrepancy"
                    and row.get("difference_cad") is not None
                ):
                    amount = Decimal(row["difference_cad"])
                    if cid in amounts and amounts[cid] != amount:
                        unknown.add(cid)
                    else:
                        amounts[cid] = amount
                elif row.get("status") != "clean":
                    unknown.add(cid)
            if (
                f.get("pattern", {}).get("shared_pattern_verified")
                if isinstance(f.get("pattern"), dict)
                else False
            ):
                if verified:
                    groups.append(
                        dict(
                            provenance=r.provenance,
                reference_id=cidref,
                            customer_ids=relevant,
                            pattern=f["pattern"],
                            caveat="Shared characteristics are correlation; configuration root cause remains unproven.",
                        )
                    )
    for cid in unknown:
        amounts.pop(cid, None)
    # Model-selected shared-template candidates are not invented; derive comparable patterns from saved comparisons only.
    patterns = {}
    for case in cases:
        if not case["evidence_verified"]:
            continue
        for row in case["comparisons"] or [case.get("comparison") or {}]:
            cid = row.get("customer_id")
            if cid not in amounts:
                continue
            key = (row.get("pricing_template"), row.get("difference_cad"))
            if key[0]:
                patterns.setdefault(key, {})[cid] = case["reference_id"]
    for (template, amount), members in patterns.items():
        if len(members) >= 3:
            groups.append(
                dict(
                    pricing_template=template,
                    difference_per_customer_cad=amount,
                    customer_ids=sorted(members),
                    references=sorted(set(members.values())),
                    caveat="Deterministically shared template/discrepancy; a systemic cause is a hypothesis, not a proven root cause.",
                )
            )
    # One shared group is one pattern even if both a finding and the row aggregation identify it.
    groups = list(
        {
            tuple(sorted(g["customer_ids"])): g
            for g in groups
            if not (set(g["customer_ids"]) & unknown)
        }.values()
    )
    screening = set()
    for r in family:
        for event in store.events(r.id):
            if event["type"] == "screening.completed":
                screening.update(
                    row["customer_id"] for row in event.get("payload", {}).get("comparisons", [])
                )
        screening.update(r.customers_compared)
    durations = [r.metrics.get("duration_seconds") for r in family]
    costs = [r.metrics.get("estimated_api_cost_usd") for r in family]
    resolved = sum(c["state"] in ("reviewed", "dismissed") for c in cases)
    # Replaced cases are not counted again; original contributions are retained separately.
    human_history = [dict(h, run_id=r.id) for r in family for h in r.interventions] + [
        dict(e.get("payload", {}), run_id=r.id)
        for r in family
        for e in store.events(r.id)
        if e["type"] == "human_review.decided"
    ]
    contributions = len(human_history)
    financial = dict(
        potential_receivables_cad=str(sum((a for a in amounts.values() if a > 0), Decimal("0.00"))),
        potential_credits_cad=str(-sum((a for a in amounts.values() if a < 0), Decimal("0.00"))),
        unresolved_quantifiable_exposure_cad=(str(sum((abs(a) for a in amounts.values()), Decimal("0.00"))) if amounts else None),
        unquantified_cases=len(unknown),
        disclaimer="Potential differences only; receivables are not collected revenue and credits are not savings. No amount is assigned to unresolved conflicts or duplicate records.",
    )
    covered_candidates = {cid for c in cases for cid in c["customer_ids"]}
    covered_candidates.update(
        cid
        for r in family
        if r.continuation and r.status == "completed" and valid[r.id]
        for cid in r.customers_compared
    )
    uninvestigated_candidates = sorted(
        {
            row["customer_id"]
            for row in root.candidates
            if row["customer_id"] not in covered_candidates
        }
    )
    unresolved = sum(c["state"] not in ("reviewed", "dismissed") for c in cases)
    limitations = [
        "Single-operator prototype measurements, not department staffing, productivity or historical trends.",
        "No proven systemic root cause, realized collections, issued credits or measured workforce savings.",
        "USD investigation cost estimates and CAD exposures are separate; no FX conversion is assumed.",
    ]
    if any(not valid[r.id] for r in family):
        limitations.append(
            "Some runs are active or their source/authority revision is stale. Their unverified exposure is excluded."
        )
    if uninvestigated_candidates:
        limitations.append(
            f"{len(uninvestigated_candidates)} structured screening candidates have no saved investigated finding; their financial exposure is not asserted."
        )
    if any(r.status != "completed" for r in family):
        limitations.append(
            "Some source reviews/attempts are incomplete or interrupted; saved work does not establish a completed period-wide investigation."
        )
    return dict(
        human_history=human_history,
        root_run_id=root.id,
        provenance=root.provenance,
        period=root.period,
        scope="One originating review and its scoped continuations; overlapping financial cases deduplicated",
        runs=[
            dict(
                id=r.id,
                status=r.status,
                reason=r.reason,
                created_at=r.created_at,
                data_revision=r.data_revision,
                current=valid[r.id],
                continuation=r.continuation,
                metrics=r.metrics,
            )
            for r in family
        ],
        cases=cases,
        metrics=dict(
            customers_screened=len(screening),
            findings_verified=len(verified_ids),
            outstanding_exceptions=unresolved,
            screened_candidates_without_findings=len(uninvestigated_candidates),
            resolved_cases=resolved,
            unresolved_cases=unresolved,
            human_contributions=contributions,
            execution_seconds=(
                str(sum((Decimal(str(d)) for d in durations), Decimal(0)))
                if all(d is not None for d in durations)
                else None
            ),
            estimated_api_cost_usd=(
                str(sum((Decimal(str(c)) for c in costs), Decimal(0)))
                if all(c is not None for c in costs)
                else None
            ),
            cost_accounting_complete=all(
                r.metrics.get("cost_accounting_complete", False) for r in family
            ),
        ),
        financial=financial,
        patterns=groups,
        references=refs,
        limitations=limitations,
        revisions=[
            dict(
                run_id=r.id,
                revision=r.data_revision,
                last_event=r.last_event_sequence,
                status=r.status,
                current=valid[r.id],
            )
            for r in family
        ],
    )
