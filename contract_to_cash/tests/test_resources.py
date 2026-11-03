"""Resource lifetime regressions; retained connections cannot rely on GC to close."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from contract_to_cash.agent.events import Journal
from contract_to_cash.agent.review import decide
import test_agent


@contextmanager
def tracked_connections():
    connect = sqlite3.connect
    connections = []

    def track(*args, **kwargs):
        db = connect(*args, **kwargs)
        connections.append(db)
        return db

    try:
        with patch('sqlite3.connect', side_effect=track):
            yield connections
    finally:
        # Emergency cleanup only after assertions, so a regression fails on Linux too.
        for db in connections:
            db.close()


class ResourceLifetimeTests(unittest.TestCase):
    def assert_closed(self, connections):
        self.assertTrue(connections)
        for db in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.cursor()

    def test_journal_context_closes_on_success_and_exception(self):
        with tempfile.TemporaryDirectory() as tmp, tracked_connections() as connections:
            for fail in (False, True):
                with self.subTest(fail=fail):
                    directory = Path(tmp) / str(fail)
                    try:
                        with Journal(directory) as journal:
                            journal.emit('test.event')
                            if fail:
                                raise RuntimeError('interrupted')
                    except RuntimeError:
                        if not fail:
                            raise
                    journal.close()  # Idempotent even after context exit.
                    self.assert_closed(connections)
                    (directory / 'events.sqlite3').unlink()

    def test_journal_initialization_failure_closes_connection(self):
        class FailingConnection(sqlite3.Connection):
            def cursor(self):
                raise sqlite3.OperationalError('schema setup failed')

        connect = sqlite3.connect
        with tempfile.TemporaryDirectory() as tmp:
            db = connect(Path(tmp) / 'setup.sqlite3', factory=FailingConnection)
            try:
                with patch('contract_to_cash.agent.events.sqlite3.connect', return_value=db):
                    with self.assertRaises(sqlite3.OperationalError):
                        Journal(Path(tmp) / 'run')
                # Use the base method because the overridden cursor always raises.
                with self.assertRaises(sqlite3.ProgrammingError):
                    sqlite3.Connection.cursor(db)
            finally:
                db.close()

    def make_review(self, directory):
        with Journal(directory) as journal:
            journal.emit('investigation.started')
            journal.save_report(dict(run_id=journal.run_id, data_revision='revision',
                findings=[dict(finding_id='finding', state='verified', version=1)],
                reviews=[dict(finding_id='finding', status='pending', finding_version=1,
                              data_revision='revision', action='export')], metrics={}))

    def test_review_commits_and_closes_before_return(self):
        with tempfile.TemporaryDirectory() as tmp, tracked_connections() as connections:
            directory = Path(tmp) / 'run'
            self.make_review(directory)
            decide(directory, 'finding', 'approved', 'Test Operator')
            self.assert_closed(connections)
            with closing(sqlite3.connect(directory / 'events.sqlite3')) as db:
                with closing(db.cursor()) as cursor:
                    self.assertEqual(cursor.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 1)
                    self.assertEqual(cursor.execute('SELECT COUNT(*) FROM events').fetchone()[0], 2)
            self.assertEqual(len(list(directory.glob('*-export.json'))), 1)
            (directory / 'events.sqlite3').unlink()

    def test_review_rolls_back_and_closes_on_transaction_failure(self):
        with tempfile.TemporaryDirectory() as tmp, tracked_connections() as connections:
            directory = Path(tmp) / 'run'
            self.make_review(directory)
            with closing(sqlite3.connect(directory / 'events.sqlite3')) as db:
                with db, closing(db.cursor()) as cursor:
                    cursor.execute("CREATE TRIGGER fail_review BEFORE INSERT ON events "
                                   "BEGIN SELECT RAISE(ABORT, 'review event rejected'); END")
            before = (directory / 'report.json').read_bytes()
            with self.assertRaises(sqlite3.IntegrityError):
                decide(directory, 'finding', 'approved', 'Test Operator')
            self.assert_closed(connections)
            with closing(sqlite3.connect(directory / 'events.sqlite3')) as db:
                with closing(db.cursor()) as cursor:
                    self.assertEqual(cursor.execute('SELECT COUNT(*) FROM decisions').fetchone()[0], 0)
                    self.assertEqual(cursor.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)
            self.assertEqual((directory / 'report.json').read_bytes(), before)
            self.assertFalse((directory / 'human-decisions.jsonl').exists())
            (directory / 'events.sqlite3').unlink()

    def test_agent_fixture_cleans_up_after_setup_failure(self):
        case = test_agent.AgentTests('test_exact_allowlist_and_no_batch_audit')
        with tracked_connections() as connections:
            try:
                with patch('test_agent.PublicData', side_effect=ValueError('invalid data')):
                    with self.assertRaises(ValueError):
                        case.setUp()
            finally:
                case.doCleanups()
            self.assert_closed(connections)
            self.assertFalse(case.root.exists())

    def test_cli_closes_client_when_journal_setup_fails(self):
        from openai import OpenAI
        from contract_to_cash.agent.__main__ import main
        from scripts.build_agent_runtime import build

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = build(root / 'runtime')
            client = OpenAI(api_key='local-test-placeholder', base_url='https://example.invalid/v1')
            try:
                with patch.dict('os.environ', {'OPENAI_API_KEY': 'local-test-placeholder'}), \
                        patch('openai.OpenAI', return_value=client), patch('sys.stderr'):
                    result = main(['run', '--model', 'test-model', '--data', str(runtime / 'contract_to_cash/data'),
                                   '--output', str(root), '--input-price-per-million', '1',
                                   '--output-price-per-million', '4'])
                self.assertEqual(result, 2)
                self.assertTrue(client.is_closed())
            finally:
                client.close()
