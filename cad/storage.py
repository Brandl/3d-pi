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
            # Persistent cursor orders HTTP and websocket snapshots, including
            # ready builds and attachments that do not change the saved generation.
            db.executescript("""
                CREATE TABLE IF NOT EXISTS live_sequence (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), value INTEGER NOT NULL);
                INSERT OR IGNORE INTO live_sequence VALUES (1, 0);
            """)
            for table, operation in (
                ("revisions", "INSERT"),
                ("revisions", "UPDATE"),
                ("publications", "INSERT"),
                ("state", "UPDATE"),
                ("design_commits", "INSERT"),
                ("design_state", "UPDATE"),
                ("design_assets", "INSERT"),
            ):
                db.execute(f"""CREATE TRIGGER IF NOT EXISTS live_{table}_{operation}
                    AFTER {operation} ON {table} BEGIN
                    UPDATE live_sequence SET value=value+1 WHERE singleton=1;
                    END""")

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
            # Keep head, history and derived live previews in one read snapshot.
            db.execute("BEGIN")
            state = dict(db.execute("SELECT revision,generation FROM state").fetchone())
            state["event_sequence"] = db.execute("SELECT value FROM live_sequence").fetchone()[0]
            state["history"] = [
                dict(r)
                for r in db.execute(
                    "SELECT id,parent,base_generation,created,status,json_extract(document, '$.name') AS name,json_extract(result, '$.report.valid') AS valid FROM revisions ORDER BY created DESC LIMIT 100"
                )
            ]
            for build in state["history"]:
                if build["valid"] is not None:
                    build["valid"] = bool(build["valid"])
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
            # Live previews are derived, never new commits or publication events.
            # Only ready geometry whose declared checks pass, built after the saved
            # head, is eligible. Registered print/inspection assets are not drafts.
            commits = state["workspace"]["commits"]
            cutoff = (
                commits[-1]["created"]
                if commits
                else (state["publications"][0]["created"] if state["publications"] else 0)
            )
            head = state["workspace"]["revision"] or state["revision"]
            head_row = db.execute(
                "SELECT content_hash FROM revisions WHERE id=?", (head,)
            ).fetchone()
            head_hash = head_row["content_hash"] if head_row else ""
            eligible = db.execute(
                """SELECT id AS revision, created, json_extract(document, '$.name') AS name
                   FROM revisions WHERE status='ready' AND created>?
                   AND json_extract(result, '$.report.valid')=1 AND content_hash!=?
                   AND id NOT IN (
                       SELECT revision FROM design_commits UNION SELECT revision FROM design_assets
                       UNION SELECT revision FROM publications)
                   ORDER BY created DESC, id DESC LIMIT 32""",
                (cutoff, head_hash),
            )
            state["intermediates"] = list(reversed([dict(row) for row in eligible]))
            for item in state["intermediates"]:
                if item["revision"] not in state["candidates"]:
                    state["candidates"].append(item["revision"])
                state["candidate_names"][item["revision"]] = item["name"]
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
