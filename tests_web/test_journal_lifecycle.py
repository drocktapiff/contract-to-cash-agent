"""Deterministic reader/writer and shutdown regressions; no paid API or retries."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
from uuid import uuid4
from contract_to_cash.agent.events import Journal
from contract_to_cash.web.store import Settings, Store, now


class JournalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(Settings(root=self.root / "runs"))
        self.store.open()
        self.addCleanup(self.store.close)
        self.run_id = uuid4().hex
        self.store.write_meta(
            dict(id=self.run_id, idempotency_key=str(uuid4()), created_at=now(), status="running")
        )

    def test_reader_cannot_open_a_half_initialized_writer_database(self):
        opened, release_schema, reader_attempted, reader_opened, reader_done = [
            Event() for _ in range(5)
        ]
        errors = []
        connect = sqlite3.connect

        def controlled_connect(*args, **kwargs):
            db = connect(*args, **kwargs)
            if kwargs.get("uri"):
                reader_opened.set()
            else:
                opened.set()
                if not release_schema.wait(5):
                    db.close()
                    raise AssertionError("Test did not release schema initialization")
            return db

        def write():
            try:
                with Journal(self.store.directory(self.run_id), io_lock=self.store.lock) as journal:
                    journal.emit("test.writer_ready")
            except BaseException as exc:
                errors.append(exc)

        def read():
            reader_attempted.set()
            try:
                self.store.events(self.run_id)
            except BaseException as exc:
                errors.append(exc)
            finally:
                reader_done.set()

        writer = Thread(target=write)
        reader = Thread(target=read)
        with patch("contract_to_cash.agent.events.sqlite3.connect", side_effect=controlled_connect):
            writer.start()
            try:
                self.assertTrue(opened.wait(5))
                reader.start()
                self.assertTrue(reader_attempted.wait(5))
                self.assertFalse(
                    reader_opened.wait(0.05),
                    "Reader opened SQLite before writer initialization released the shared I/O lock",
                )
            finally:
                release_schema.set()
                writer.join(5)
                if reader.ident is not None:
                    reader.join(5)
        self.assertFalse(writer.is_alive())
        self.assertFalse(reader.is_alive())
        self.assertTrue(reader_done.is_set())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store.events(self.run_id)), 1)

    def test_shutdown_drains_journal_owner_and_worker_terminal_lock_before_cleanup(self):
        ready, release_worker, closed, shutdown_done = [Event() for _ in range(4)]
        errors = []

        def work():
            try:
                with Journal(self.store.directory(self.run_id), io_lock=self.store.lock) as journal:
                    ready.set()
                    if not release_worker.wait(5):
                        raise AssertionError("Test did not release worker")
                    journal.emit("test.worker_completed")
                with self.store.lock:
                    self.store.active = None
                closed.set()
            except BaseException as exc:
                errors.append(exc)

        def shutdown():
            try:
                self.store.close()
            except BaseException as exc:
                errors.append(exc)
            finally:
                shutdown_done.set()

        self.store.active = self.run_id

        class DeadlineWorker(Thread):
            def join(self, timeout=None):
                # Simulate an expired bounded join without a five-second sleep.
                # Shutdown must not interpret expiry as release of owned handles.
                if timeout is not None:
                    return
                return super().join()

        self.store.worker = DeadlineWorker(target=work)
        self.store.worker.start()
        self.assertTrue(ready.wait(5))
        closing_thread = Thread(target=shutdown)
        closing_thread.start()
        try:
            self.assertFalse(shutdown_done.wait(0.05))
            self.assertIsNotNone(self.store.owner_fd)
        finally:
            release_worker.set()
            closing_thread.join(5)
            Thread.join(self.store.worker, 5)
        self.assertFalse(closing_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(closed.is_set())
        self.assertIsNone(self.store.owner_fd)
        self.assertFalse(self.store.accepting_launches)
        # Rename and removal are real operations, including on Windows CI.
        directory = self.store.directory(self.run_id)
        directory.rename(self.root / "closed-journal")
        with closing(sqlite3.connect(self.root / "closed-journal/events.sqlite3")) as db:
            with closing(db.cursor()) as cursor:
                self.assertEqual(cursor.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_report_replacement_waits_for_reader_lock(self):
        ready, save, finished = [Event() for _ in range(3)]
        errors = []

        def write():
            try:
                with Journal(self.store.directory(self.run_id), io_lock=self.store.lock) as journal:
                    journal.save_report({"version": 1})
                    ready.set()
                    if not save.wait(5):
                        raise AssertionError("Test did not release report writer")
                    journal.save_report({"version": 2})
                    finished.set()
            except BaseException as exc:
                errors.append(exc)

        writer = Thread(target=write)
        writer.start()
        try:
            self.assertTrue(ready.wait(5))
            with self.store.lock:
                with (self.store.directory(self.run_id) / "report.json").open() as report:
                    save.set()
                    self.assertFalse(finished.wait(0.05))
                    self.assertIn("1", report.read())
        finally:
            save.set()
            writer.join(5)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(finished.is_set())

    def test_model_wait_keeps_journal_readable(self):
        idle, release_worker, reader_done = Event(), Event(), Event()
        errors, rows = [], []

        def work():
            try:
                with Journal(self.store.directory(self.run_id), io_lock=self.store.lock) as journal:
                    journal.emit("test.model_wait")
                    idle.set()
                    if not release_worker.wait(5):
                        raise AssertionError("Test did not release simulated model wait")
            except BaseException as exc:
                errors.append(exc)

        def read():
            try:
                rows.extend(self.store.events(self.run_id))
            except BaseException as exc:
                errors.append(exc)
            finally:
                reader_done.set()

        writer, reader = Thread(target=work), Thread(target=read)
        writer.start()
        try:
            self.assertTrue(idle.wait(5))
            reader.start()
            self.assertTrue(reader_done.wait(1), "Model wait must not hold the storage I/O lock")
        finally:
            release_worker.set()
            writer.join(5)
            if reader.ident is not None:
                reader.join(5)
        self.assertEqual(errors, [])
        self.assertEqual([row["type"] for row in rows], ["test.model_wait"])
