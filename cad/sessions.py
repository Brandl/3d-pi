"""Private, bounded website sessions. Store bearer hashes, never bearer tokens."""

import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path


class SessionStore:
    def __init__(self, path, credential):
        self.path = Path(path)
        self.credential = credential
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS auth_meta (id INTEGER PRIMARY KEY, credential TEXT)"
            )
            db.execute("""CREATE TABLE IF NOT EXISTS web_sessions (
                token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL,
                renewed REAL NOT NULL, created REAL NOT NULL)""")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT credential FROM auth_meta WHERE id=1").fetchone()
            if row is None or row[0] != credential:
                db.execute("DELETE FROM web_sessions")
                db.execute("INSERT OR REPLACE INTO auth_meta VALUES (1, ?)", (credential,))

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def active(self, db):
        row = db.execute("SELECT credential FROM auth_meta WHERE id=1").fetchone()
        return row is not None and row[0] == self.credential

    def get(self, key, now):
        with self.connection() as db:
            if not self.active(db):
                return None
            row = db.execute(
                "SELECT csrf, expires, renewed FROM web_sessions WHERE token_hash=? AND expires>?",
                (key, now),
            ).fetchone()
            return dict(row) if row else None

    def put(self, key, session, now):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.active(db):
                raise RuntimeError("Website credentials changed; restart this gateway")
            db.execute("DELETE FROM web_sessions WHERE expires<=?", (now,))
            count = db.execute("SELECT count(*) FROM web_sessions").fetchone()[0]
            if count >= 128:
                db.execute(
                    """DELETE FROM web_sessions WHERE token_hash IN (
                    SELECT token_hash FROM web_sessions ORDER BY created, token_hash LIMIT ?
                )""",
                    (count - 127,),
                )
            db.execute(
                "INSERT INTO web_sessions VALUES (?, ?, ?, ?, ?)",
                (key, session["csrf"], session["expires"], now, now),
            )

    def renew(self, key, now, ttl, interval):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not self.active(db):
                return False
            return (
                db.execute(
                    """UPDATE web_sessions SET expires=?, renewed=?
                WHERE token_hash=? AND expires>? AND renewed<=?""",
                    (now + ttl, now, key, now, now - interval),
                ).rowcount
                == 1
            )

    def revoke(self, key):
        with self.connection() as db:
            db.execute("DELETE FROM web_sessions WHERE token_hash=?", (key,))
