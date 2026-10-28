"""SQLite is the source of truth; event and counter updates commit together."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "benchmark.sqlite"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, created REAL NOT NULL, heartbeat REAL NOT NULL,
                  status TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
                  config TEXT NOT NULL, dataset_hash TEXT NOT NULL, tasks TEXT NOT NULL,
                  prompts TEXT NOT NULL, memory_snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                  task_id TEXT NOT NULL, repetition INTEGER NOT NULL, domain TEXT NOT NULL,
                  status TEXT NOT NULL, step INTEGER NOT NULL DEFAULT 0,
                  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
                  estimated_calls INTEGER NOT NULL DEFAULT 0, started REAL, finished REAL,
                  agent TEXT, phase TEXT, error TEXT, verification TEXT,
                  UNIQUE(run_id,task_id,repetition));
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                  attempt_id TEXT, ts REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id, seq);
                CREATE TABLE IF NOT EXISTS memories (
                  id TEXT PRIMARY KEY, created REAL NOT NULL, collection TEXT NOT NULL,
                  task_id TEXT NOT NULL, domain TEXT NOT NULL, kind TEXT NOT NULL,
                  text TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
                  source_attempt TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(id UNINDEXED, text);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def new_run(self, config, dataset_hash, tasks, prompts, memories, run_id=None):
        run_id = run_id or uuid.uuid4().hex[:12]
        now = time.time()
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (run_id, now, now, "running", 0, encoded(config), dataset_hash,
                        encoded(tasks), encoded(prompts), encoded(memories)))
            for task in tasks:
                for n in range(config["attempts"]):
                    db.execute("INSERT INTO attempts(id,run_id,task_id,repetition,domain,status) "
                               "VALUES (?,?,?,?,?,?)", (uuid.uuid4().hex, run_id, task["uuid"], n,
                                                       task["subdomain"], "pending"))
        return run_id

    def run(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown run: {run_id}")
        result = dict(row)
        for key in ("config", "tasks", "prompts", "memory_snapshot"):
            result[key] = json.loads(result[key])
        return result

    def attempts(self, run_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM attempts WHERE run_id=? "
                                               "ORDER BY task_id,repetition", (run_id,))]

    def event(self, run_id, attempt_id, kind, payload=None, **updates):
        allowed = {"status", "step", "input_tokens", "output_tokens", "estimated_calls", "started",
                   "finished", "agent", "phase", "error", "verification"}
        if set(updates) - allowed:
            raise ValueError("Invalid attempt update")
        with self.connect() as db:
            db.execute("INSERT INTO events(run_id,attempt_id,ts,kind,payload) VALUES (?,?,?,?,?)",
                       (run_id, attempt_id, time.time(), kind, encoded(payload or {})))
            if updates:
                clause = ",".join(f"{key}=?" for key in updates)
                db.execute(f"UPDATE attempts SET {clause} WHERE id=? AND run_id=?",
                           (*updates.values(), attempt_id, run_id))

    def heartbeat(self, run_id):
        with self.connect() as db:
            db.execute("UPDATE runs SET heartbeat=? WHERE id=? AND status='running'", (time.time(), run_id))

    def cancelled(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT cancel_requested FROM runs WHERE id=?", (run_id,)).fetchone()
            return bool(row[0])

    def cancel(self, run_id):
        self.run(run_id)
        with self.connect() as db:
            db.execute("UPDATE runs SET cancel_requested=1 WHERE id=?", (run_id,))

    def finish_run(self, run_id, status):
        with self.connect() as db:
            db.execute("UPDATE runs SET status=?,heartbeat=? WHERE id=?", (status, time.time(), run_id))

    def recover(self, run_id, stale_after=30):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown run")
            if row["status"] != "running" or time.time() - row["heartbeat"] <= stale_after:
                raise ValueError("Recovery requires a running run with an expired heartbeat")
            db.execute("UPDATE attempts SET status='interrupted',finished=? WHERE run_id=? "
                       "AND status='running'", (time.time(), run_id))
            db.execute("UPDATE runs SET status='interrupted' WHERE id=?", (run_id,))

    def resume(self, run_id, config, dataset_hash, prompts):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["status"] == "running":
                raise ValueError("Run missing or still running; recover stale runs first")
            if (json.loads(row["config"]) != config or row["dataset_hash"] != dataset_hash
                    or json.loads(row["prompts"]) != prompts):
                raise ValueError("Resume requires identical configuration, tasks, and initial prompts")
            # Completed attempts (including failures) are immutable. Interrupted attempts rerun from scratch.
            db.execute("UPDATE attempts SET status='pending',finished=NULL,error=NULL,verification=NULL "
                       "WHERE run_id=? AND status IN ('interrupted','cancelled')", (run_id,))
            db.execute("UPDATE runs SET status='running',heartbeat=?,cancel_requested=0 WHERE id=?",
                       (time.time(), run_id))

    def events(self, run_id, after=0, limit=500):
        with self.connect() as db:
            return [dict(r) | {"payload": json.loads(r["payload"])} for r in db.execute(
                "SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?",
                (run_id, after, limit))]

    def overview(self):
        with self.connect() as db:
            runs = [dict(r) for r in db.execute("SELECT id,created,heartbeat,status,config,dataset_hash "
                                               "FROM runs ORDER BY created DESC")]
        for run in runs:
            run["config"] = json.loads(run["config"])
            attempts = self.attempts(run["id"])
            run["counts"] = {s: sum(a["status"] == s for a in attempts) for s in
                             ("pending", "running", "passed", "failed", "error", "cancelled", "interrupted")}
            run["total"] = len(attempts)
            run["passed_tasks"] = len({a["task_id"] for a in attempts if a["status"] == "passed"})
            run["tokens"] = sum(a["input_tokens"] + a["output_tokens"] for a in attempts)
            run["stale"] = run["status"] == "running" and time.time() - run["heartbeat"] > 30
        return runs
