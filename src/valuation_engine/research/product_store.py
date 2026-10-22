"""Durable local product queue and immutable artifacts, separate from formal QVE."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, dedupe TEXT NOT NULL UNIQUE,
 payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 due REAL NOT NULL, started REAL, finished REAL, error TEXT, output_ref TEXT);
CREATE TABLE IF NOT EXISTS artifacts (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, identity TEXT NOT NULL,
 payload TEXT NOT NULL, created REAL NOT NULL, previous_id TEXT);
CREATE TABLE IF NOT EXISTS pointers (name TEXT PRIMARY KEY, artifact_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (
 dedupe TEXT PRIMARY KEY, kind TEXT NOT NULL, message TEXT NOT NULL,
 artifact_id TEXT, created REAL NOT NULL, delivery TEXT NOT NULL DEFAULT 'in_app');
CREATE TABLE IF NOT EXISTS observations (
 key TEXT PRIMARY KEY, value TEXT NOT NULL, at REAL NOT NULL);
"""


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class ProductStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "operations.sqlite"
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("unsupported_product_store_version")
            db.executescript(SCHEMA)
            if version == 0:
                db.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, kind: str, dedupe: str, payload: dict, at: float) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO jobs(kind,dedupe,payload,status,due) VALUES(?,?,?,'Queued',?)",
                (kind, dedupe, encode(payload), at),
            )

    def recover(self, at: float) -> None:
        # Caller holds the OS worker lock: no other worker can still own these jobs.
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status=CASE WHEN attempts<3 THEN 'Queued' ELSE 'Failed' END, "
                "due=?, error='interrupted_worker' WHERE status='Running'",
                (at,),
            )

    def claim(self, at: float):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status IN ('Queued','RetryableFailed') AND due<=? "
                "ORDER BY CASE kind WHEN 'COLLECT_QUOTES' THEN 0 WHEN 'VERIFY_RESEARCH' THEN 1 "
                "ELSE 2 END,id LIMIT 1",
                (at,),
            ).fetchone()
            if row is None:
                return None
            db.execute(
                "UPDATE jobs SET status='Running',attempts=attempts+1,started=? WHERE id=?",
                (at, row["id"]),
            )
            return {
                **dict(row),
                "payload": json.loads(row["payload"]),
                "attempts": row["attempts"] + 1,
            }

    def finish(self, job: dict, at: float, output: str | None = None, error: str | None = None):
        with self.connect() as db:
            state = (
                "Succeeded"
                if error is None
                else "RetryableFailed"
                if job["attempts"] < 3
                else "Failed"
            )
            db.execute(
                "UPDATE jobs SET status=?,finished=?,output_ref=?,error=?,due=? WHERE id=?",
                (state, at, output, error, at + 60 * 2 ** job["attempts"], job["id"]),
            )
            if state == "Failed":
                self._alert(
                    db,
                    "failure:" + job["kind"] + ":" + error,
                    "operation_failed",
                    "更新失敗，保留上一份研究；請查看更新狀態。",
                    None,
                    at,
                )

    def observe(self, key: str, value, at: float):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO observations VALUES(?,?,?)", (key, encode(value), at)
            )

    def observation(self, key: str):
        with self.connect() as db:
            row = db.execute("SELECT value,at FROM observations WHERE key=?", (key,)).fetchone()
        return {"value": json.loads(row["value"]), "at": row["at"]} if row else None

    @staticmethod
    def _alert(db, key, kind, message, artifact_id, at):
        db.execute(
            "INSERT OR IGNORE INTO alerts(dedupe,kind,message,artifact_id,created) VALUES(?,?,?,?,?)",
            (key, kind, message, artifact_id, at),
        )

    def publish(
        self,
        kind: str,
        identity: str,
        payload: dict,
        at: float,
        *,
        pointer=None,
        message=None,
        alert_key=None,
    ):
        artifact_id = digest([kind, identity, payload])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = (
                db.execute("SELECT artifact_id FROM pointers WHERE name=?", (pointer,)).fetchone()
                if pointer
                else None
            )
            db.execute(
                "INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?,?)",
                (
                    artifact_id,
                    kind,
                    identity,
                    encode(payload),
                    at,
                    previous[0] if previous else None,
                ),
            )
            if pointer:
                db.execute("INSERT OR REPLACE INTO pointers VALUES(?,?)", (pointer, artifact_id))
            if message:
                self._alert(
                    db, alert_key or "artifact:" + artifact_id, kind, message, artifact_id, at
                )
        return artifact_id

    def latest(self, pointer: str):
        with self.connect() as db:
            row = db.execute(
                "SELECT a.* FROM artifacts a JOIN pointers p ON p.artifact_id=a.id WHERE p.name=?",
                (pointer,),
            ).fetchone()
        return self._artifact(row)

    @staticmethod
    def _artifact(row):
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        if digest([result["kind"], result["identity"], result["payload"]]) != result["id"]:
            raise ValueError("product_artifact_hash_mismatch")
        return result

    def artifact(self, identity: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (identity,)).fetchone()
        return self._artifact(row)

    def history(self, kind: str, limit=40):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM artifacts WHERE kind=? ORDER BY created DESC,rowid DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        return [self._artifact(row) for row in rows]

    def current(self, kind: str, limit=40):
        """Limit current documents, not historical revisions of the same document."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT DISTINCT a.* FROM artifacts a JOIN pointers p ON p.artifact_id=a.id "
                "WHERE a.kind=? ORDER BY a.created DESC,a.rowid DESC LIMIT ?",
                (kind, limit),
            ).fetchall()
        return [self._artifact(row) for row in rows]

    def jobs(self, limit=30):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,kind,status,attempts,started,finished,error,output_ref FROM jobs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def alerts(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM alerts ORDER BY created DESC LIMIT 30")
            ]
