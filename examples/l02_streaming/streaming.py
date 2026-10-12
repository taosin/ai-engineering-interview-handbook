"""Durable L02 application protocol; local calls, not HTTP/SSE or an LLM."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3


TERMINAL = {"completed", "cancelled"}


class ProtocolError(ValueError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def transaction(self, write=False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def trace(db, kind, run_id, details):
        db.execute("INSERT INTO trace(kind,run_id,details) VALUES(?,?,?)",
                   (kind, run_id, encoded(details)))

    def snapshot(self):
        with self.transaction() as db:
            tables = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name")]
            result = {table: [dict(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                      for table in tables}
        for table in result.values():
            for row in table:
                for field in ("details", "payload", "event_json"):
                    if field in row:
                        row[field] = json.loads(row[field])
        return result


class ServiceStore(Store):
    def __init__(self, path):
        super().__init__(path)
        with self.transaction(write=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs(
                run_id TEXT PRIMARY KEY,input TEXT NOT NULL,seq INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'running',
                minimum_cursor INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS events(
                run_id TEXT NOT NULL,seq INTEGER NOT NULL,type TEXT NOT NULL,payload TEXT NOT NULL,
                PRIMARY KEY(run_id,seq),FOREIGN KEY(run_id) REFERENCES runs(run_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS tool_effects(
                id INTEGER PRIMARY KEY,run_id TEXT NOT NULL,name TEXT NOT NULL,
                UNIQUE(run_id,name),FOREIGN KEY(run_id) REFERENCES runs(run_id))""")
            db.execute("CREATE TABLE IF NOT EXISTS trace(id INTEGER PRIMARY KEY,kind TEXT,run_id TEXT,details TEXT)")

    @staticmethod
    def _run(db, run_id):
        row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ProtocolError("unknown run")
        return dict(row)

    def _emit(self, db, run_id, kind, payload):
        row = self._run(db, run_id)
        if row["state"] in TERMINAL:
            raise ProtocolError("terminal run cannot append")
        seq = row["seq"] + 1
        event = {"run_id": run_id, "seq": seq, "type": kind, "payload": payload}
        text = row["text"] + (payload["text"] if kind == "delta" else "")
        state = kind if kind in TERMINAL else row["state"]
        db.execute("INSERT INTO events VALUES(?,?,?,?)", (run_id, seq, kind, encoded(payload)))
        db.execute("UPDATE runs SET seq=?,text=?,state=? WHERE run_id=?", (seq, text, state, run_id))
        self.trace(db, "event_committed", run_id, event)
        return event

    def create(self, run_id, input_text):
        with self.transaction(write=True) as db:
            db.execute("INSERT INTO runs(run_id,input) VALUES(?,?)", (run_id, input_text))
            return self._emit(db, run_id, "start", {"input": input_text})

    def delta(self, run_id, text):
        if not isinstance(text, str):
            raise ProtocolError("delta text must be a string")
        with self.transaction(write=True) as db:
            return self._emit(db, run_id, "delta", {"text": text})

    def start_tool(self, run_id, name="weather", before_start=None):
        # The hook models a step that is NOT started yet; the authoritative check
        # happens after the barrier, in the same transaction as the local effect.
        if before_start:
            before_start()
        with self.transaction(write=True) as db:
            row = self._run(db, run_id)
            if row["state"] in TERMINAL:
                self.trace(db, "tool_suppressed", run_id, {"name": name, "state": row["state"]})
                return {"started": False, "state": row["state"]}
            previous = db.execute("SELECT id FROM tool_effects WHERE run_id=? AND name=?", (run_id, name)).fetchone()
            if previous:
                return {"started": False, "state": row["state"], "existing_effect_id": previous[0]}
            effect = db.execute("INSERT INTO tool_effects(run_id,name) VALUES(?,?)", (run_id, name)).lastrowid
            event = self._emit(db, run_id, "tool-progress", {"name": name, "effect_id": effect})
            return {"started": True, "effect_id": effect, "event": event}

    def finish(self, run_id, requested):
        if requested not in TERMINAL:
            raise ProtocolError("unknown terminal state")
        with self.transaction(write=True) as db:
            row = self._run(db, run_id)
            accepted = row["state"] == "running"
            if accepted:
                event = self._emit(db, run_id, requested, {})
            else:
                # The ack reports the committed winner, not the requested state.
                event = {"run_id": run_id, "seq": row["seq"], "type": row["state"], "payload": {}}
            ack = {"requested": requested, "accepted": accepted, "state": event["type"], "event": event}
            self.trace(db, "terminal_ack_created", run_id, ack)
            return ack

    def replay(self, run_id, cursor):
        if type(cursor) is not int or cursor < 0:
            raise ProtocolError("invalid cursor")
        # Both the retention decision and the returned state are from one read
        # transaction. No text/seq pair is assembled across separate reads.
        with self.transaction() as db:
            row = self._run(db, run_id)
            if cursor > row["seq"]:
                raise ProtocolError("cursor ahead of server")
            if cursor < row["minimum_cursor"]:
                return {"kind": "snapshot", "reason": "cursor_expired", "snapshot": row}
            events = [{**dict(event), "payload": json.loads(event["payload"])} for event in db.execute(
                "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, cursor))]
            return {"kind": "events", "run_id": run_id, "through_seq": row["seq"], "events": events}

    def prune(self, run_id, through):
        with self.transaction(write=True) as db:
            row = self._run(db, run_id)
            if type(through) is not int or not row["minimum_cursor"] <= through <= row["seq"]:
                raise ProtocolError("invalid retention boundary")
            db.execute("DELETE FROM events WHERE run_id=? AND seq<=?", (run_id, through))
            db.execute("UPDATE runs SET minimum_cursor=? WHERE run_id=?", (through, run_id))
            self.trace(db, "retention_pruned", run_id, {"through": through})


class ClientStore(Store):
    def __init__(self, path):
        super().__init__(path)
        with self.transaction(write=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY,
                seq INTEGER NOT NULL DEFAULT 0,text TEXT NOT NULL DEFAULT '',
                state TEXT NOT NULL DEFAULT 'running',completion_applications INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0)""")
            db.execute("""CREATE TABLE IF NOT EXISTS applied(run_id TEXT,seq INTEGER,event_json TEXT,
                PRIMARY KEY(run_id,seq))""")
            db.execute("CREATE TABLE IF NOT EXISTS trace(id INTEGER PRIMARY KEY,kind TEXT,run_id TEXT,details TEXT)")

    def ensure(self, run_id):
        with self.transaction(write=True) as db:
            db.execute("INSERT OR IGNORE INTO runs(run_id) VALUES(?)", (run_id,))

    def read(self, run_id):
        with self.transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise ProtocolError("unknown client run")
            return dict(row)

    def record(self, kind, run_id, details):
        with self.transaction(write=True) as db:
            self.trace(db, kind, run_id, details)

    def apply(self, event, crash_before_commit=False):
        if (not isinstance(event, dict) or not isinstance(event.get("run_id"), str)
                or type(event.get("seq")) is not int or event["seq"] < 1
                or event.get("type") not in {"start", "delta", "tool-progress", *TERMINAL}
                or not isinstance(event.get("payload"), dict)):
            raise ProtocolError("invalid event")
        if event["type"] == "delta" and not isinstance(event["payload"].get("text"), str):
            raise ProtocolError("invalid delta")
        run_id, seq = event["run_id"], event["seq"]
        with self.transaction(write=True) as db:
            row = dict(db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())
            if seq <= row["seq"]:
                previous = db.execute("SELECT event_json FROM applied WHERE run_id=? AND seq=?", (run_id, seq)).fetchone()
                if previous is not None and previous[0] != encoded(event):
                    raise ProtocolError("same event identity has conflicting content")
                self.trace(db, "duplicate_ignored", run_id, event)
                return "duplicate"
            if seq != row["seq"] + 1:
                self.trace(db, "gap_detected", run_id, {"expected": row["seq"] + 1, "received": event})
                return "gap"
            if row["state"] in TERMINAL:
                raise ProtocolError("event after terminal")
            text = row["text"] + (event["payload"]["text"] if event["type"] == "delta" else "")
            state = event["type"] if event["type"] in TERMINAL else row["state"]
            completed = row["completion_applications"] + int(event["type"] == "completed")
            db.execute("UPDATE runs SET seq=?,text=?,state=?,completion_applications=?,cancel_requested=? WHERE run_id=?",
                       (seq, text, state, completed, 0 if state in TERMINAL else row["cancel_requested"], run_id))
            db.execute("INSERT INTO applied VALUES(?,?,?)", (run_id, seq, encoded(event)))
            self.trace(db, "event_applied", run_id, event)
            if crash_before_commit:
                os._exit(73)  # intentional process death: SQLite rolls back both cursor and text
            return "applied"

    def apply_snapshot(self, snapshot):
        if (type(snapshot.get("seq")) is not int or snapshot["seq"] < 0
                or not isinstance(snapshot.get("text"), str)
                or snapshot.get("state") not in {"running", *TERMINAL}):
            raise ProtocolError("invalid snapshot")
        run_id = snapshot["run_id"]
        with self.transaction(write=True) as db:
            row = dict(db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())
            if snapshot["seq"] < row["seq"]:
                self.trace(db, "stale_snapshot_ignored", run_id, snapshot)
                return "stale"
            if snapshot["seq"] == row["seq"] and (snapshot["text"], snapshot["state"]) != (row["text"], row["state"]):
                raise ProtocolError("same cursor has conflicting snapshot")
            if row["state"] in TERMINAL and (snapshot["state"] != row["state"] or snapshot["text"] != row["text"]):
                raise ProtocolError("snapshot cannot overwrite terminal")
            completed = row["completion_applications"] + int(snapshot["state"] == "completed" and row["state"] != "completed")
            db.execute("UPDATE runs SET seq=?,text=?,state=?,completion_applications=?,cancel_requested=? WHERE run_id=?",
                       (snapshot["seq"], snapshot["text"], snapshot["state"], completed,
                        0 if snapshot["state"] in TERMINAL else row["cancel_requested"], run_id))
            self.trace(db, "snapshot_applied", run_id, snapshot)
            return "snapshot"


class Session:
    """Connection state is ephemeral; task content and cursor are durable."""
    def __init__(self, store):
        self.store = store
        self.active_run = None
        self.connected = False

    def select(self, run_id):
        self.store.ensure(run_id)
        self.active_run = run_id
        self.connected = True
        self.store.record("session_selected", run_id, {"connected": True})

    @property
    def display(self):
        return self.store.read(self.active_run)

    def close(self):
        self.connected = False
        self.store.record("connection_closed", self.active_run, {"task_state_unchanged": True})

    def receive(self, event, **kwargs):
        if event.get("run_id") != self.active_run:
            self.store.record("late_run_ignored", self.active_run, {"event": event})
            return "inactive"
        return self.store.apply(event, **kwargs)

    def receive_snapshot(self, snapshot):
        if snapshot.get("run_id") != self.active_run:
            self.store.record("late_snapshot_ignored", self.active_run, {"snapshot": snapshot})
            return "inactive"
        return self.store.apply_snapshot(snapshot)

    def recover(self, service):
        self.connected = True
        response = service.replay(self.active_run, self.display["seq"])
        self.store.record("recovery_response", self.active_run, response)
        if response["kind"] == "snapshot":
            self.receive_snapshot(response["snapshot"])
        else:
            for event in response["events"]:
                if self.receive(event) == "gap":
                    raise ProtocolError("server replay has a gap; cursor is not advanced")
            if self.display["seq"] != response["through_seq"]:
                raise ProtocolError("incomplete replay; durable cursor keeps only the contiguous prefix")
        return response

    def request_cancel(self, service):
        with self.store.transaction(write=True) as db:
            db.execute("UPDATE runs SET cancel_requested=1 WHERE run_id=? AND state='running'", (self.active_run,))
            self.store.trace(db, "cancel_requested", self.active_run, {})
        # Delivery is deliberately separate: callers may delay this response.
        return service.finish(self.active_run, "cancelled")

    def receive_ack(self, ack):
        return self.receive(ack["event"])


def sample_a(service):
    """The exact six-event stream specified in L02."""
    events = [service.create("run-A", "北京天气"), service.delta("run-A", "北"), service.delta("run-A", "京")]
    events.append(service.start_tool("run-A")["event"])
    events.append(service.delta("run-A", "晴"))
    events.append(service.finish("run-A", "completed")["event"])
    return events
