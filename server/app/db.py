"""SQLite store: writers, articles and the purchase log."""

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS writers (
    id                TEXT PRIMARY KEY,
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
    price_drops       INTEGER NOT NULL,
    license           TEXT NOT NULL DEFAULT 'ai-input',
    train_price_drops INTEGER,
    allowed_agents    TEXT NOT NULL DEFAULT '["*"]',
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TABLE IF NOT EXISTS purchases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash     TEXT UNIQUE NOT NULL,
    article_id  TEXT NOT NULL,
    payer       TEXT,
    pay_to      TEXT NOT NULL,
    price_drops INTEGER NOT NULL,
    network     TEXT NOT NULL,
    receipt     TEXT NOT NULL,
    agent       TEXT NOT NULL DEFAULT 'unknown',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""

ARTICLE_SELECT = """
SELECT a.*, w.name AS author, w.xrpl_address AS pay_to,
       COALESCE(p.reads, 0) AS reads, COALESCE(p.earned, 0) AS earned_drops
FROM articles a
JOIN writers w ON w.id = a.writer_id
LEFT JOIN (
    SELECT article_id, COUNT(*) AS reads, SUM(price_drops) AS earned
    FROM purchases GROUP BY article_id
) p ON p.article_id = a.id
"""

SORTS = {
    "reads": "reads DESC, a.created_at DESC, a.id",
    "earned": "earned_drops DESC, a.created_at DESC, a.id",
    "new": "a.created_at DESC, a.id",
}


def _article(row: sqlite3.Row) -> dict:
    article = dict(row)
    article["keywords"] = json.loads(article["keywords"])
    article["allowed_agents"] = json.loads(article["allowed_agents"])
    return article


class Database:
    def __init__(self, path: Path):
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)
            # Databases from before agent tracking keep their purchases.
            columns = {r["name"] for r in c.execute("PRAGMA table_info(purchases)")}
            if "agent" not in columns:
                c.execute("ALTER TABLE purchases ADD COLUMN agent TEXT NOT NULL DEFAULT 'unknown'")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- writers ---

    def ensure_writer(self, *, id, name, email, xrpl_address) -> None:
        """Create the writer once. A payout address set later is never overwritten."""
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO writers (id, name, email, payout_method, xrpl_address) "
                "VALUES (?, ?, ?, 'xrpl', ?)",
                (id, name, email, xrpl_address),
            )

    def writer(self, writer_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM writers WHERE id = ?", (writer_id,)).fetchone()
        return dict(row) if row else None

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
                "price_drops, license, train_price_drops, allowed_agents) "
                "VALUES (:id, :writer_id, :title, :abstract, :body, :preview_mode, :keywords, "
                ":price_drops, :license, :train_price_drops, :allowed_agents)",
                {
                    **article,
                    "keywords": json.dumps(article["keywords"]),
                    "allowed_agents": json.dumps(article["allowed_agents"]),
                },
            )

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
                "INSERT OR IGNORE INTO purchases "
                "(tx_hash, article_id, payer, pay_to, price_drops, network, receipt, agent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tx_hash, article_id, payer, pay_to, price_drops, network, json.dumps(receipt), agent),
            )

    def recent(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM purchases ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "receipt": json.loads(r["receipt"])} for r in rows]

    def earnings(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT pay_to, COUNT(*) AS reads, SUM(price_drops) AS drops "
                "FROM purchases GROUP BY pay_to ORDER BY drops DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # --- dashboard ---

    def dashboard(self, writer_id: str) -> dict:
        with self._conn() as c:
            mine = "FROM purchases p JOIN articles a ON a.id = p.article_id WHERE a.writer_id = ?"
            totals = c.execute(
                "SELECT COUNT(*) AS reads, COALESCE(SUM(p.price_drops), 0) AS earned_drops, "
                "COALESCE(SUM(CASE WHEN strftime('%Y-%m', p.created_at) = strftime('%Y-%m', 'now') "
                f"THEN p.price_drops END), 0) AS month_drops {mine}",
                (writer_id,),
            ).fetchone()
            latest = c.execute(
                "SELECT p.tx_hash, p.price_drops, p.agent, p.created_at, a.title "
                f"{mine} ORDER BY p.id DESC LIMIT 1",
                (writer_id,),
            ).fetchone()
            by_agent = c.execute(
                "SELECT p.agent AS name, COUNT(*) AS reads, SUM(p.price_drops) AS earned_drops "
                f"{mine} GROUP BY p.agent ORDER BY earned_drops DESC, name",
                (writer_id,),
            ).fetchall()
            agents_per_piece = c.execute(
                "SELECT p.article_id, p.agent, SUM(p.price_drops) AS earned "
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
