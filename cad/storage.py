"""SQLite transactions protect the published pointer and optimistic generation counter."""

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "artifacts").mkdir(exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    revision TEXT, generation INTEGER NOT NULL);
                INSERT OR IGNORE INTO state VALUES (1, NULL, 0);
                CREATE TABLE IF NOT EXISTS revisions (
                    id TEXT PRIMARY KEY, parent TEXT, base_generation INTEGER NOT NULL,
                    created REAL NOT NULL, document TEXT NOT NULL, content_hash TEXT NOT NULL,
                    request_key TEXT UNIQUE NOT NULL, status TEXT NOT NULL, result TEXT);
                CREATE TABLE IF NOT EXISTS publications (
                    generation INTEGER PRIMARY KEY, revision TEXT NOT NULL,
                    operation TEXT NOT NULL, created REAL NOT NULL);
            """)
            from cad.workspace import DDL

            db.executescript(DDL)
            from cad.uploads import DDL as UPLOAD_DDL

            db.executescript(UPLOAD_DDL)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.root / "project.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            raise Missing("Revision not found")
        result = dict(row)
        result["document"] = json.loads(result["document"])
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def get(self, revision):
        with self.connection() as db:
            return self.decode(
                db.execute("SELECT * FROM revisions WHERE id=?", (revision,)).fetchone()
            )

    def state(self):
        with self.connection() as db:
            state = dict(db.execute("SELECT revision,generation FROM state").fetchone())
            state["history"] = [
                dict(r)
                for r in db.execute(
                    "SELECT id,parent,base_generation,created,status,json_extract(document, '$.name') AS name FROM revisions ORDER BY created DESC LIMIT 100"
                )
            ]
            state["publications"] = [
                dict(r)
                for r in db.execute("""SELECT p.*, json_extract(r.document, '$.name') AS name
                    FROM publications p JOIN revisions r ON r.id=p.revision
                    ORDER BY p.generation DESC""")
            ]
            from cad.workspace import snapshot

            state["workspace"] = snapshot(db)
            registered = {
                r["revision"]
                for r in state["workspace"]["commits"]
                + state["workspace"]["assets"]
                + state["publications"]
            }
            state["candidates"] = [
                r["id"]
                for r in state["history"]
                if r["status"] == "ready" and r["id"] not in registered
            ]
            state["candidate_names"] = {r["id"]: r["name"] for r in state["history"]}
            return state

    def create(self, document, expected_generation, request_key):
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT * FROM revisions WHERE request_key=?", (request_key,)
            ).fetchone()
            if prior:
                if (
                    prior["content_hash"] != digest
                    or prior["base_generation"] != expected_generation
                ):
                    raise Conflict("Request key already used for different input")
                return self.decode(prior), False
            state = db.execute("SELECT * FROM state").fetchone()
            if state["generation"] != expected_generation:
                raise Conflict("Stale generation; inspect current state before rebuilding")
            if (
                db.execute(
                    "SELECT count(*) FROM revisions WHERE status IN ('queued','building')"
                ).fetchone()[0]
                >= 4
            ):
                raise Conflict("Build queue is full (4 jobs maximum)")
            revision = uuid.uuid4().hex
            db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    revision,
                    state["revision"],
                    expected_generation,
                    time.time(),
                    encoded,
                    digest,
                    request_key,
                    "queued",
                    None,
                ),
            )
        return self.get(revision), True

    def update(self, revision, status, result=None):
        with self.connection() as db:
            db.execute(
                "UPDATE revisions SET status=?,result=? WHERE id=? AND status IN ('queued','building')",
                (status, json.dumps(result) if result else None, revision),
            )

    def publish(self, revision, expected_generation, restore=False):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT * FROM state").fetchone()
            operation = "restore" if restore else "publish"
            last = db.execute(
                "SELECT * FROM publications WHERE generation=?", (state["generation"],)
            ).fetchone()
            if (
                state["revision"] == revision
                and state["generation"] == expected_generation + 1
                and last
                and last["operation"] == operation
            ):
                return {"revision": revision, "generation": state["generation"]}
            if state["generation"] != expected_generation:
                raise Conflict("Stale generation; publication was not applied")
            row = self.decode(
                db.execute("SELECT * FROM revisions WHERE id=?", (revision,)).fetchone()
            )
            if row["status"] != "ready" or not row["result"]["report"]["valid"]:
                raise Conflict("Only ready revisions with passing checks can be published")
            if restore:
                if not db.execute(
                    "SELECT 1 FROM publications WHERE revision=?", (revision,)
                ).fetchone():
                    raise Conflict("Restore requires a previously published revision")
            elif row["base_generation"] != expected_generation:
                raise Conflict("Candidate was built against an older generation; rebuild it")
            generation = expected_generation + 1
            db.execute("UPDATE state SET revision=?,generation=?", (revision, generation))
            db.execute(
                "INSERT INTO publications VALUES (?,?,?,?)",
                (generation, revision, operation, time.time()),
            )
            return {"revision": revision, "generation": generation}

    def recover(self):
        with self.connection() as db:
            db.execute(
                "UPDATE revisions SET status='failed',result=? WHERE status IN ('queued','building')",
                (
                    json.dumps(
                        {"error": "Build interrupted by service restart; submit a new request key"}
                    ),
                ),
            )

    def directory(self, revision):
        # Never construct artifact paths from unvalidated client input.
        if len(revision) != 32 or any(c not in "0123456789abcdef" for c in revision):
            raise Missing("Invalid revision ID")
        return self.root / "artifacts" / revision
