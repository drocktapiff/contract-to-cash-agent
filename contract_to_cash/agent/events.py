"""Append-only observable events, suitable for JSONL streaming and later UI replay."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


class Journal:
    def __init__(self, directory: Path, sink=None):
        directory.mkdir(parents=True, exist_ok=False)
        self.directory = directory
        self.run_id = uuid4().hex
        self.sequence = 0
        self.sink = sink
        self.db = sqlite3.connect(directory / 'events.sqlite3')
        self.db.execute('CREATE TABLE events (sequence INTEGER PRIMARY KEY, body TEXT NOT NULL)')
        self.events = []

    def emit(self, event_type, actor='orchestrator', correlation_id=None, **payload):
        self.sequence += 1
        event = dict(schema_version=1, event_id=uuid4().hex, run_id=self.run_id,
                     sequence=self.sequence, timestamp=datetime.now(timezone.utc).isoformat(),
                     type=event_type, actor=actor, correlation_id=correlation_id, payload=payload)
        line = json.dumps(event, ensure_ascii=True, allow_nan=False)
        self.db.execute('INSERT INTO events VALUES (?, ?)', (self.sequence, line))
        self.db.commit()
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(line + '\n')
        self.events.append(event)
        if self.sink:
            self.sink(line)
        return event

    def save_report(self, report):
        temporary = self.directory / 'report.tmp'
        temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        temporary.replace(self.directory / 'report.json')

    def close(self):
        self.db.close()
