"""Read-only paid-launch admission status; the same rolling windows gate submission."""

from datetime import datetime, timedelta, timezone
import os
import sqlite3


def rate_status(store, at=None):
    current = at or datetime.now(timezone.utc)
    records = store.metadata() + store.enterprise.analyses() + store.archived_paid_records()
    if getattr(store, "document_advisor", None):
        records += store.document_advisor.records()
    times = sorted(
        (
            datetime.fromisoformat(r["created_at"])
            for r in records
            if (r.get("provenance") or {}).get("kind") != "simulated_demo"
        ),
        reverse=True,
    )
    minute = [t for t in times if (current - t).total_seconds() < 60]
    hour = [t for t in times if (current - t).total_seconds() < 3600]
    reasons = []
    deadlines = []
    if minute:
        reasons.append("minute_cooldown")
        deadlines.append(minute[0] + timedelta(seconds=60))
    if len(hour) >= 3:
        reasons.append("hourly_limit")
        deadlines.append(hour[2] + timedelta(hours=1))
    return dict(
        available=not reasons,
        reasons=reasons,
        next_eligible_at=max(deadlines).isoformat() if deadlines else None,
        minute_launches=len(minute),
        hour_launches=len(hour),
    )


MESSAGES = {
    "recorded_mode": "Recorded mode is read-only.",
    "workspace_unavailable": "The workspace is shutting down or requires recovery.",
    "active_worker": "Another investigation or analysis is running. Its completion time is unknown.",
    "credential_missing": "API credential not configured on the server.",
    "pricing_expired": "Administrator pricing confirmation expired.",
    "pricing_missing": "Administrator pricing confirmation is required.",
    "pricing_invalid": "Administrator pricing configuration is invalid.",
    "hourly_limit": "Hourly launch limit reached (three paid launches per rolling hour).",
    "minute_cooldown": "One-minute cooldown active.",
    "history_unavailable": "Launch history could not be verified. Eligibility time is unknown.",
}


def availability(store, at=None):
    from .pricing import pricing_state

    current = at or datetime.now(timezone.utc)
    with store.lock:
        reasons = []
        rate = dict(
            available=True, reasons=[], next_eligible_at=None, minute_launches=0, hour_launches=0
        )
        if store.settings.mode == "recorded":
            reasons.append("recorded_mode")
        else:
            if (
                not store.accepting_launches
                or (store.settings.root / ".reset-recovery.json").exists()
            ):
                reasons.append("workspace_unavailable")
            if store.active:
                reasons.append("active_worker")
            if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("CONTRACT_AGENT_API_KEY")):
                reasons.append("credential_missing")
            pricing = pricing_state(store.settings.root, store.settings.mode, now=current)
            if not pricing["ready"]:
                reasons.append(
                    {
                        "administrator_confirmation_expired": "pricing_expired",
                        "administrator_configuration_invalid": "pricing_invalid",
                    }.get(pricing["reason"], "pricing_missing")
                )
            try:
                rate = store.paid_rate_status(at=current)
                reasons.extend(rate["reasons"])
            except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
                reasons.append("history_unavailable")
        # Rate capacity is exact; do not promise a launch time while other gates are blocked.
        predictable = bool(reasons) and all(
            r in ("minute_cooldown", "hourly_limit") for r in reasons
        )
        return dict(
            available=not reasons,
            checked_at=current.isoformat(),
            reasons=[dict(code=r, message=MESSAGES[r]) for r in reasons],
            next_eligible_at=rate["next_eligible_at"] if predictable else None,
            limits=dict(per_minute=1, per_hour=3, shared=True),
            usage=dict(
                minute_launches=rate["minute_launches"], hour_launches=rate["hour_launches"]
            ),
            informational=True,
        )
