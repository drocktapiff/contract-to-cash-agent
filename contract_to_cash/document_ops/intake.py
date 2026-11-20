"""Standalone journal. Every SQLite connection is explicitly closed, including failures."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from .parser import read_directory
from .reconcile import reconcile


def ingest(directory, database, advisor=None):
    docs = read_directory(directory)
    unique = list({d.file_hash: d for d in docs}.values())
    items = reconcile(unique)
    batch_id = hashlib.sha256("".join(sorted(d.file_hash for d in unique)).encode()).hexdigest()
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as conn:
        with conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS documents (hash TEXT PRIMARY KEY, body TEXT NOT NULL)"
            ).close()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS work_items (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            ).close()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            ).close()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS proposals (hash TEXT PRIMARY KEY, body TEXT NOT NULL)"
            ).close()
            for doc in unique:
                conn.execute(
                    "INSERT OR IGNORE INTO documents VALUES (?,?)",
                    (doc.file_hash, json.dumps(doc.dump())),
                ).close()
                if advisor is not None:
                    # Proposals are segregated; never flow back into authoritative rules.
                    proposal = advisor.propose(doc.dump())
                    conn.execute(
                        "INSERT OR IGNORE INTO proposals VALUES (?,?)",
                        (
                            doc.file_hash,
                            json.dumps({"unverified_proposal": proposal, "authority": False}),
                        ),
                    ).close()
            persisted = []
            for work in items:
                with closing(
                    conn.execute("SELECT body FROM work_items WHERE id=?", (work.work_item_id,))
                ) as cursor:
                    row = cursor.fetchone()
                if row:
                    persisted.append(json.loads(row[0]))
                else:
                    body = work.dump()
                    persisted.append(body)
                    conn.execute(
                        "INSERT INTO work_items VALUES (?,?)", (work.work_item_id, json.dumps(body))
                    ).close()
            summary = {
                "batch_id": batch_id,
                "documents": [d.dump() for d in unique],
                "work_items": persisted,
                "duplicate_files_skipped": len(docs) - len(unique),
                "paid_model_calls": 0 if advisor is None else None,
                "processing": "genuine deterministic PDF extraction",
                "provider_adapter": (
                    "none"
                    if advisor is None
                    else "explicit non-authoritative advisor; usage unknown"
                ),
            }
            conn.execute(
                "INSERT OR IGNORE INTO batches VALUES (?,?)", (batch_id, json.dumps(summary))
            ).close()
    return summary


def close_routine(database, work_item_id, actor, rationale):
    """Administrative read-only check closure, never financial execution or authorization."""
    if not actor.strip() or not rationale.strip():
        raise ValueError("Actor and rationale required")
    with closing(sqlite3.connect(database)) as conn:
        with conn:
            with closing(
                conn.execute("SELECT body FROM work_items WHERE id=?", (work_item_id,))
            ) as cursor:
                row = cursor.fetchone()
            if not row:
                raise ValueError("Unknown work item")
            body = json.loads(row[0])
            if not body["automatic_closure_allowed"] or body["human_review_required"]:
                raise ValueError("Human review/authority required; automatic closure forbidden")
            if body["status"] == "Closed":
                return body
            now = datetime.now(timezone.utc).isoformat()
            body.update(status="Closed", updated_at=now)
            body["event_history"].append(
                {
                    "event": "administrative_check_closed",
                    "at": now,
                    "actor": actor,
                    "rationale": rationale,
                    "financial_action_executed": False,
                }
            )
            conn.execute(
                "UPDATE work_items SET body=? WHERE id=?", (json.dumps(body), work_item_id)
            ).close()
            return body
