"""Shared SQL store. PostgreSQL in production; SQLite for local integration tests."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS tg_sessions (id TEXT PRIMARY KEY, seed TEXT NOT NULL, address TEXT NOT NULL, created_at BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS tg_requests (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, article_id TEXT NOT NULL, cap BIGINT NOT NULL, status TEXT NOT NULL, result TEXT, created_at BIGINT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS tg_requests_session ON tg_requests(session_id, article_id)",
    "CREATE TABLE IF NOT EXISTS tg_ledger (tx_hash TEXT PRIMARY KEY, article_id TEXT NOT NULL, payer TEXT NOT NULL, result TEXT NOT NULL, created_at BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS tg_rates (id TEXT PRIMARY KEY, count BIGINT NOT NULL)",
]


class Connection:
    def __init__(self, raw, postgres):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, params=()):
        return self.raw.execute(
            sql.replace("?", "%s") if self.postgres else sql, params
        )

    def lock_session(self, session_id):
        sql = "SELECT id FROM tg_sessions WHERE id=?" + (
            " FOR UPDATE" if self.postgres else ""
        )
        return self.execute(sql, (session_id,)).fetchone()


class Store:
    def __init__(self, url):
        self.url = url
        self.postgres = url.startswith(("postgres://", "postgresql://"))
        if not self.postgres:
            if not url.startswith("sqlite:///"):
                raise ValueError("DATABASE_URL must use PostgreSQL or local SQLite")
            self.path = Path(url.removeprefix("sqlite:///"))
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            for statement in SCHEMA:
                db.execute(statement)

    @contextmanager
    def transaction(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            raw = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10)
        else:
            raw = sqlite3.connect(self.path, timeout=20)
            raw.row_factory = sqlite3.Row
            raw.execute("BEGIN IMMEDIATE")
        try:
            yield Connection(raw, self.postgres)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()
