"""Local human decisions for review/export only; never a model tool or billing action."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def decide(run_directory: Path, finding_id: str, decision: str, reviewer: str, rationale: str = ""):
    if decision not in ('approved', 'rejected', 'needs_information') or not reviewer.strip():
        raise ValueError('An explicit reviewer and supported decision are required')
    report_path = run_directory / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    finding = next((f for f in report['findings'] if f['finding_id'] == finding_id), None)
    review = next((r for r in report['reviews'] if r['finding_id'] == finding_id), None)
    if (not finding or not review or review['status'] != 'pending'
            or finding['state'] == 'retracted' or review['finding_version'] != finding['version']
            or review['data_revision'] != report['data_revision']):
        raise ValueError('No pending review for this finding version and snapshot')
    decision_record = dict(decision_id=uuid4().hex, finding_id=finding_id, finding_version=finding['version'],
                           data_revision=report['data_revision'], decision=decision, reviewer=reviewer, action=review['action'],
                           decided_at=datetime.now(timezone.utc).isoformat(),
                           finding_sha256=hashlib.sha256(json.dumps(finding, sort_keys=True).encode()).hexdigest(),
                           scope='review/export only; not authorization for billing changes')
    if rationale:
        decision_record['rationale'] = rationale
    # SQLite serializes decisions from multiple operator CLI processes.
    # A connection context manages the transaction, not the connection lifetime.
    with closing(sqlite3.connect(run_directory / 'events.sqlite3')) as db:
        with db, closing(db.cursor()) as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS decisions (finding_id TEXT, version INTEGER, body TEXT, PRIMARY KEY (finding_id, version))')
            cursor.execute('INSERT INTO decisions VALUES (?, ?, ?)',
                           (finding_id, finding['version'], json.dumps(decision_record)))
            sequence = cursor.execute('SELECT COALESCE(MAX(sequence), 0) + 1 FROM events').fetchone()[0]
            event = dict(schema_version=1, event_id=uuid4().hex, run_id=report['run_id'],
                         sequence=sequence, timestamp=decision_record['decided_at'],
                         type='human_review.decided', actor='human', correlation_id=None,
                         payload=decision_record)
            cursor.execute('INSERT INTO events VALUES (?, ?)', (sequence, json.dumps(event)))
            interventions = cursor.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]
    with (run_directory / 'events.jsonl').open('a', encoding='utf-8', newline='\n') as output:
        output.write(json.dumps(event) + '\n')
    review['status'] = decision
    review['decision'] = decision_record
    report['metrics']['human_interventions'] = interventions
    report['journal_sequence'] = sequence
    temporary = report_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    temporary.replace(report_path)
    with (run_directory / 'human-decisions.jsonl').open('a', encoding='utf-8', newline='\n') as output:
        output.write(json.dumps(decision_record) + '\n')
    if decision == 'approved' and review['action'] == 'export':
        export = dict(approval=decision_record, finding=finding,
                      disclaimer='Review package only. No invoice, payment, credit, or collection was changed.')
        (run_directory / (decision_record['decision_id'] + '-export.json')).write_text(
            json.dumps(export, indent=2) + '\n', encoding='utf-8')
    return decision_record
