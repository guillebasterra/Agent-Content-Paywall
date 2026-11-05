"""Store for writers, articles and the purchase log: SQLite in demo mode, Postgres in Supabase mode.

SQL is written once, in the dialect both understand, with ? placeholders. Timestamps are
ISO text and totals are cast to BIGINT, so results have the same shape on either database.
"""

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

TABLES = ["writers", "articles", "purchases"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS writers (
    id                TEXT PRIMARY KEY,
    auth_user_id      TEXT UNIQUE,
    name              TEXT NOT NULL,
    email             TEXT,
    payout_method     TEXT,
    xrpl_address      TEXT,
    stripe_account_id TEXT
);
CREATE TABLE IF NOT EXISTS articles (
    id                TEXT PRIMARY KEY,
    writer_id         TEXT NOT NULL REFERENCES writers(id),
    title             TEXT NOT NULL,
    abstract          TEXT NOT NULL DEFAULT '',
    body              TEXT NOT NULL,
    preview_mode      TEXT NOT NULL DEFAULT 'w50',
    keywords          TEXT NOT NULL DEFAULT '[]',
    price_drops       BIGINT NOT NULL,
    license           TEXT NOT NULL DEFAULT 'ai-input',
    train_price_drops BIGINT,
    allowed_agents    TEXT NOT NULL DEFAULT '["*"]',
    storage_path      TEXT,
    created_at        TEXT NOT NULL DEFAULT {now}
);
CREATE TABLE IF NOT EXISTS purchases (
    id          {serial},
    tx_hash     TEXT UNIQUE NOT NULL,
    article_id  TEXT NOT NULL,
    payer       TEXT,
    pay_to      TEXT NOT NULL,
    price_drops BIGINT NOT NULL,
    network     TEXT NOT NULL,
    receipt     TEXT NOT NULL,
    agent       TEXT NOT NULL DEFAULT 'unknown',
    created_at  TEXT NOT NULL DEFAULT {now}
)
"""

SQLITE_DDL = {"serial": "INTEGER PRIMARY KEY AUTOINCREMENT", "now": "(strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"}
POSTGRES_DDL = {
    "serial": "BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY",
    "now": """(to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))""",
}

# Columns added since the first release, for databases that predate them.
ADDED_COLUMNS = [
    ("purchases", "agent", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("writers", "auth_user_id", "TEXT"),
    ("articles", "storage_path", "TEXT"),
]

ARTICLE_SELECT = """
SELECT a.*, w.name AS author, w.xrpl_address AS pay_to,
       COALESCE(p.reads, 0) AS reads, COALESCE(p.earned, 0) AS earned_drops
FROM articles a
JOIN writers w ON w.id = a.writer_id
LEFT JOIN (
    SELECT article_id, COUNT(*) AS reads, CAST(SUM(price_drops) AS BIGINT) AS earned
    FROM purchases GROUP BY article_id
) p ON p.article_id = a.id
"""

SORTS = {
    "reads": "reads DESC, a.created_at DESC, a.id",
    "earned": "earned_drops DESC, a.created_at DESC, a.id",
    "new": "a.created_at DESC, a.id",
}


def _article(row) -> dict:
    article = dict(row)
    article["keywords"] = json.loads(article["keywords"])
    article["allowed_agents"] = json.loads(article["allowed_agents"])
    return article


class _SQLite:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self) -> Iterator["_SQLite"]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create_schema(self) -> None:
        with self.connection() as c:
            for statement in SCHEMA.format(**SQLITE_DDL).split(";"):
                c.execute(statement)
            for table, column, definition in ADDED_COLUMNS:
                if column not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS writers_auth_user ON writers (auth_user_id)")

    def close(self) -> None:
        pass


class _PostgresConnection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()):
        return self._conn.execute(sql.replace("?", "%s"), params)


class _Postgres:
    def __init__(self, url: str):
        # prepare_threshold=None: Supabase's poolers don't keep prepared statements.
        self.pool = ConnectionPool(
            url, min_size=1, max_size=5, open=True, timeout=15, check=ConnectionPool.check_connection,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
        )

    @contextmanager
    def connection(self) -> Iterator[_PostgresConnection]:
        with self.pool.connection() as conn:
            yield _PostgresConnection(conn)

    def create_schema(self) -> None:
        with self.connection() as c:
            for statement in SCHEMA.format(**POSTGRES_DDL).split(";"):
                c.execute(statement)
            for table, column, definition in ADDED_COLUMNS:
                c.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
            # Supabase serves the public schema to anyone holding the browser's key. RLS with no
            # policies shuts that door. The backend connects as the table owner, which RLS skips.
            for table in TABLES:
                c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    def close(self) -> None:
        self.pool.close()


class Database:
    SERIAL_TABLES = {"purchases"}  # Tables whose id the database assigns.

    def __init__(self, target: Path | str):
        is_postgres = isinstance(target, str) and target.startswith(("postgres://", "postgresql://"))
        self._backend = _Postgres(target) if is_postgres else _SQLite(Path(target))
        self.is_postgres = is_postgres
        self._backend.create_schema()

    def _conn(self):
        return self._backend.connection()

    def close(self) -> None:
        self._backend.close()

    def reset(self) -> None:
        """Delete everything. Only `make demo-reset` calls this."""
        with self._conn() as c:
            for table in reversed(TABLES):
                c.execute(f"DELETE FROM {table}")

    # --- writers ---

    def ensure_writer(self, *, id, name, email, xrpl_address) -> None:
        """Create the writer once. A payout address set later is never overwritten."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO writers (id, name, email, payout_method, xrpl_address) "
                "VALUES (?, ?, ?, 'xrpl', ?) ON CONFLICT DO NOTHING",
                (id, name, email, xrpl_address),
            )

    def writer(self, writer_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM writers WHERE id = ?", (writer_id,)).fetchone()
        return dict(row) if row else None

    def writer_for_auth_user(self, auth_user_id: str, email: str | None) -> dict:
        """The writer behind a sign-in, created on first login. Safe when two requests race."""
        name = (email or "").split("@")[0] or "New writer"
        with self._conn() as c:
            c.execute(
                "INSERT INTO writers (id, auth_user_id, name, email) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (str(uuid.uuid4()), auth_user_id, name, email),
            )
            row = c.execute("SELECT * FROM writers WHERE auth_user_id = ?", (auth_user_id,)).fetchone()
        return dict(row)

    def set_name(self, writer_id: str, name: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE writers SET name = ? WHERE id = ?", (name, writer_id))

    def set_payout(self, writer_id: str, *, payout_method: str, xrpl_address: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE writers SET payout_method = ?, xrpl_address = ? WHERE id = ?",
                (payout_method, xrpl_address, writer_id),
            )

    # --- articles ---

    def add_article(self, article: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO articles (id, writer_id, title, abstract, body, preview_mode, keywords, "
                "price_drops, license, train_price_drops, allowed_agents, storage_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article["id"], article["writer_id"], article["title"], article["abstract"], article["body"],
                    article["preview_mode"], json.dumps(article["keywords"]), article["price_drops"],
                    article["license"], article["train_price_drops"], json.dumps(article["allowed_agents"]),
                    article.get("storage_path"),
                ),
            )

    def set_storage_path(self, article_id: str, path: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE articles SET storage_path = ? WHERE id = ?", (path, article_id))

    def article_exists(self, article_id: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone() is not None

    def article(self, article_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(f"{ARTICLE_SELECT} WHERE a.id = ?", (article_id,)).fetchone()
        return _article(row) if row else None

    def articles(self, sort: str = "reads") -> list[dict]:
        with self._conn() as c:
            rows = c.execute(f"{ARTICLE_SELECT} ORDER BY {SORTS[sort]}").fetchall()
        return [_article(r) for r in rows]

    # --- purchases ---

    def record(self, *, tx_hash, article_id, payer, pay_to, price_drops, network, receipt, agent) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO purchases "
                "(tx_hash, article_id, payer, pay_to, price_drops, network, receipt, agent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (tx_hash, article_id, payer, pay_to, price_drops, network, json.dumps(receipt), agent),
            )

    def recent(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM purchases ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "receipt": json.loads(r["receipt"])} for r in rows]

    def earnings(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT pay_to, COUNT(*) AS reads, CAST(SUM(price_drops) AS BIGINT) AS drops "
                "FROM purchases GROUP BY pay_to ORDER BY drops DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # --- dashboard ---

    def dashboard(self, writer_id: str) -> dict:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self._conn() as c:
            mine = "FROM purchases p JOIN articles a ON a.id = p.article_id WHERE a.writer_id = ?"
            totals = c.execute(
                "SELECT COUNT(*) AS reads, CAST(COALESCE(SUM(p.price_drops), 0) AS BIGINT) AS earned_drops, "
                "CAST(COALESCE(SUM(CASE WHEN substr(p.created_at, 1, 7) = ? "
                f"THEN p.price_drops END), 0) AS BIGINT) AS month_drops {mine}",
                (month, writer_id),
            ).fetchone()
            latest = c.execute(
                "SELECT p.tx_hash, p.price_drops, p.agent, p.created_at, a.title "
                f"{mine} ORDER BY p.id DESC LIMIT 1",
                (writer_id,),
            ).fetchone()
            by_agent = c.execute(
                "SELECT p.agent AS name, COUNT(*) AS reads, CAST(SUM(p.price_drops) AS BIGINT) AS earned_drops "
                f"{mine} GROUP BY p.agent ORDER BY earned_drops DESC, name",
                (writer_id,),
            ).fetchall()
            agents_per_piece = c.execute(
                "SELECT p.article_id, p.agent, CAST(SUM(p.price_drops) AS BIGINT) AS earned "
                f"{mine} GROUP BY p.article_id, p.agent ORDER BY earned DESC, p.agent",
                (writer_id,),
            ).fetchall()
            pieces = c.execute(
                f"{ARTICLE_SELECT} WHERE a.writer_id = ? ORDER BY earned_drops DESC, a.created_at DESC, a.id",
                (writer_id,),
            ).fetchall()

        agents: dict[str, list[str]] = {}
        for row in agents_per_piece:
            agents.setdefault(row["article_id"], []).append(row["agent"])
        return {
            "totals": dict(totals),
            "latest": dict(latest) if latest else None,
            "pieces": [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "price_drops": p["price_drops"],
                    "reads": p["reads"],
                    "earned_drops": p["earned_drops"],
                    "agents": agents.get(p["id"], []),
                }
                for p in pieces
            ],
            "by_agent": [dict(a) for a in by_agent],
        }
