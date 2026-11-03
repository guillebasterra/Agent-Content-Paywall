"""SQLite purchase log. One row per settled purchase."""

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS purchases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash     TEXT UNIQUE NOT NULL,
    article_id  TEXT NOT NULL,
    payer       TEXT,
    pay_to      TEXT NOT NULL,
    price_drops INTEGER NOT NULL,
    network     TEXT NOT NULL,
    receipt     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
"""


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, *, tx_hash, article_id, payer, pay_to, price_drops, network, receipt) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO purchases "
                "(tx_hash, article_id, payer, pay_to, price_drops, network, receipt) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tx_hash, article_id, payer, pay_to, price_drops, network, json.dumps(receipt)),
            )

    def recent(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM purchases ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{**dict(r), "receipt": json.loads(r["receipt"])} for r in rows]

    def earnings(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT pay_to, COUNT(*) AS reads, SUM(price_drops) AS drops "
                "FROM purchases GROUP BY pay_to ORDER BY drops DESC"
            ).fetchall()
        return [dict(r) for r in rows]
