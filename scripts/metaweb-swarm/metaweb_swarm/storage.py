"""SQLite transactions are authoritative; JSON/Markdown files are portable views."""
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Store:
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._mutex = threading.RLock()
        self.db = sqlite3.connect(self.run_dir / "state.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()

    def load(self):
        row = self.db.execute("SELECT body FROM state WHERE id=1").fetchone()
        if not row:
            raise ValueError("No initialized run state; use init first")
        data = json.loads(row[0])
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported checkpoint schema")
        return data

    def commit(self, state, kind, data=None, agent_id=None):
        with self._mutex:
            state["updated_at"] = now()
            row = self.db.execute("SELECT seq,body FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            event = {"seq": row[0] + 1 if row else 1, "time": now(), "kind": kind,
                     "agent_id": agent_id, "data": data or {},
                     "prev_hash": json.loads(row[1])["hash"] if row else "0" * 64}
            event["hash"] = hashlib.sha256(canonical(event).encode()).hexdigest()
            with self.db:
                self.db.execute("INSERT INTO events VALUES (?,?)", (event["seq"], canonical(event)))
                self.db.execute("INSERT OR REPLACE INTO state VALUES (1,?)", (canonical(state),))
            atomic_write(self.run_dir / "checkpoint.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
            self.export_events()
            return event

    def export_events(self):
        rows = self.db.execute("SELECT body FROM events ORDER BY seq").fetchall()
        atomic_write(self.run_dir / "raw" / "events.jsonl", "".join(row[0] + "\n" for row in rows))

    def verify(self):
        previous = "0" * 64
        expected = 1
        for (body,) in self.db.execute("SELECT body FROM events ORDER BY seq"):
            event = json.loads(body)
            digest = event.pop("hash")
            if event["seq"] != expected or event["prev_hash"] != previous or hashlib.sha256(canonical(event).encode()).hexdigest() != digest:
                raise ValueError("Audit chain is inconsistent")
            expected += 1
            previous = digest
        return {"events": expected - 1, "head_hash": previous}

    def close(self):
        self.db.close()


@contextmanager
def run_lock(run_dir):
    """OS releases this lock after crashes; an old lock file does not block resume."""
    lock_path = Path(run_dir) / ".runner.lock"
    with lock_path.open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Another process owns this run; pause it before changing decisions") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
