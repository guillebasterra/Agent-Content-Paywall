"""Store for writers, articles, purchases and the custodial ledger: SQLite in demo mode, Postgres in Supabase mode.

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

TABLES = ["writers", "articles", "agents", "purchases", "ledger_entries"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS writers (
    id                TEXT PRIMARY KEY,
    auth_user_id      TEXT UNIQUE,
    name              TEXT NOT NULL,
    email             TEXT,
    payout_method     TEXT,
    xrpl_address      TEXT,
    stripe_account_id TEXT,
    stripe_details_submitted INTEGER NOT NULL DEFAULT 0,
    stripe_payouts_enabled   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS articles (
    id                TEXT PRIMARY KEY,
    writer_id         TEXT NOT NULL REFERENCES writers(id),
    title             TEXT NOT NULL,
    abstract          TEXT NOT NULL DEFAULT '',
    body              TEXT NOT NULL,
    preview_mode      TEXT NOT NULL DEFAULT 'w50',
    keywords          TEXT NOT NULL DEFAULT '[]',
    price_usd_micros  BIGINT NOT NULL,
    license           TEXT NOT NULL DEFAULT 'ai-input',
    train_price_usd_micros BIGINT,
    allowed_agents    TEXT NOT NULL DEFAULT '["*"]',
    storage_path      TEXT,
    created_at        TEXT NOT NULL DEFAULT {now}
);
CREATE TABLE IF NOT EXISTS agents (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    api_key_hash      TEXT UNIQUE NOT NULL,
    credit_usd_micros BIGINT NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT {now}
);
CREATE TABLE IF NOT EXISTS purchases (
    id                {serial},
    tx_hash           TEXT UNIQUE NOT NULL,
    rail              TEXT NOT NULL DEFAULT 'xrpl',
    article_id        TEXT NOT NULL,
    writer_id         TEXT,
    payer             TEXT,
    pay_to            TEXT NOT NULL,
    amount_usd_micros BIGINT NOT NULL,
    amount_native     BIGINT,
    network           TEXT NOT NULL,
    receipt           TEXT NOT NULL,
    agent             TEXT NOT NULL DEFAULT 'unknown',
    fee_usd_micros    BIGINT NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT {now}
);
CREATE TABLE IF NOT EXISTS ledger_entries (
    id                {serial},
    account_type      TEXT NOT NULL,
    account_id        TEXT NOT NULL,
    kind              TEXT NOT NULL,
    amount_usd_micros BIGINT NOT NULL,
    ref               TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT {now},
    UNIQUE (account_type, account_id, kind, ref)
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
    ("writers", "stripe_details_submitted", "INTEGER NOT NULL DEFAULT 0"),
    ("writers", "stripe_payouts_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("purchases", "fee_usd_micros", "BIGINT NOT NULL DEFAULT 0"),
]

# The rate the site displayed before prices moved to USD (1 XRP = $2). One drop is two micro-dollars.
LEGACY_MICROS_PER_DROP = 2

# Rows from before USD pricing, in order: add the new columns, fill them, drop the old ones.
USD_UPGRADES = {
    ("articles", "price_drops"): [
        "ALTER TABLE articles ADD COLUMN price_usd_micros BIGINT NOT NULL DEFAULT 0",
        "ALTER TABLE articles ADD COLUMN train_price_usd_micros BIGINT",
        f"UPDATE articles SET price_usd_micros = price_drops * {LEGACY_MICROS_PER_DROP}, "
        f"train_price_usd_micros = train_price_drops * {LEGACY_MICROS_PER_DROP}",
        "ALTER TABLE articles DROP COLUMN price_drops",
        "ALTER TABLE articles DROP COLUMN train_price_drops",
    ],
    ("purchases", "price_drops"): [
        "ALTER TABLE purchases ADD COLUMN rail TEXT NOT NULL DEFAULT 'xrpl'",
        "ALTER TABLE purchases ADD COLUMN writer_id TEXT",
        "ALTER TABLE purchases ADD COLUMN amount_usd_micros BIGINT NOT NULL DEFAULT 0",
        "ALTER TABLE purchases ADD COLUMN amount_native BIGINT",
        f"UPDATE purchases SET amount_native = price_drops, amount_usd_micros = price_drops * {LEGACY_MICROS_PER_DROP}, "
        "writer_id = (SELECT writer_id FROM articles WHERE articles.id = purchases.article_id)",
        "ALTER TABLE purchases DROP COLUMN price_drops",
    ],
}

ARTICLE_SELECT = """
SELECT a.*, w.name AS author, w.xrpl_address AS pay_to,
       COALESCE(p.reads, 0) AS reads, COALESCE(p.earned, 0) AS earned_usd_micros
FROM articles a
JOIN writers w ON w.id = a.writer_id
LEFT JOIN (
    SELECT article_id, COUNT(*) AS reads, CAST(SUM(amount_usd_micros - fee_usd_micros) AS BIGINT) AS earned
    FROM purchases GROUP BY article_id
) p ON p.article_id = a.id
"""

SORTS = {
    "reads": "reads DESC, a.created_at DESC, a.id",
    "earned": "earned_usd_micros DESC, a.created_at DESC, a.id",
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
            for (table, column), statements in USD_UPGRADES.items():
                if column in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                    for statement in statements:
                        c.execute(statement)

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
            for (table, column), statements in USD_UPGRADES.items():
                found = c.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ?", (table, column)
                ).fetchone()
                if found:
                    for statement in statements:
                        c.execute(statement)
            # Supabase serves the public schema to anyone holding the browser's key. RLS with no
            # policies shuts that door. The backend connects as the table owner, which RLS skips.
            for table in TABLES:
                c.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    def close(self) -> None:
        self.pool.close()


class Database:
    SERIAL_TABLES = {"purchases", "ledger_entries"}  # Tables whose id the database assigns.

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
        """Delete everything but agent accounts, whose keys live in .env. Their credit goes back to zero.

        Only `make demo-reset` calls this.
        """
        with self._conn() as c:
            for table in reversed(TABLES):
                if table != "agents":
                    c.execute(f"DELETE FROM {table}")
            c.execute("UPDATE agents SET credit_usd_micros = 0")

    def reset_sales(self) -> None:
        """Delete purchases and every balance (writer earnings, platform fees, agent credit).

        Writers and articles stay, so a rehearsed demo can run again without re-uploading.
        """
        with self._conn() as c:
            c.execute("DELETE FROM ledger_entries")
            c.execute("DELETE FROM purchases")
            c.execute("UPDATE agents SET credit_usd_micros = 0")

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

    def set_stripe_account(self, writer_id: str, account_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE writers SET stripe_account_id = ? WHERE id = ?", (account_id, writer_id))

    def set_stripe_status(self, writer_id: str, *, details_submitted: bool, payouts_enabled: bool) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE writers SET stripe_details_submitted = ?, stripe_payouts_enabled = ? WHERE id = ?",
                (int(details_submitted), int(payouts_enabled), writer_id),
            )

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
                "price_usd_micros, license, train_price_usd_micros, allowed_agents, storage_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article["id"], article["writer_id"], article["title"], article["abstract"], article["body"],
                    article["preview_mode"], json.dumps(article["keywords"]), article["price_usd_micros"],
                    article["license"], article["train_price_usd_micros"], json.dumps(article["allowed_agents"]),
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

    def record_purchase(
        self, *, ref, rail, article_id, writer_id, payer, pay_to, amount_usd_micros, amount_native,
        network, receipt, agent, credit_writer=False, fee_usd_micros=0, debit_agent_id=None,
    ) -> bool:
        """Write the purchase and its ledger entries in one transaction. A repeated ref changes nothing.

        A credited writer gets the amount minus the fee, and the fee goes to the platform's account.
        """
        with self._conn() as c:
            if debit_agent_id:
                # Conditional, so credit can never go below zero however requests interleave.
                debited = c.execute(
                    "UPDATE agents SET credit_usd_micros = credit_usd_micros - ? "
                    "WHERE id = ? AND credit_usd_micros >= ?",
                    (amount_usd_micros, debit_agent_id, amount_usd_micros),
                ).rowcount
                if not debited:
                    return False
                self._ledger(c, "agent", debit_agent_id, "read_debit", -amount_usd_micros, ref)
            inserted = c.execute(
                "INSERT INTO purchases (tx_hash, rail, article_id, writer_id, payer, pay_to, amount_usd_micros, "
                "amount_native, network, receipt, agent, fee_usd_micros) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT DO NOTHING",
                (ref, rail, article_id, writer_id, payer, pay_to, amount_usd_micros, amount_native,
                 network, json.dumps(receipt), agent, fee_usd_micros),
            ).rowcount
            if inserted and credit_writer:
                self._ledger(c, "writer", writer_id, "read_accrual", amount_usd_micros - fee_usd_micros, ref)
                if fee_usd_micros:
                    self._ledger(c, "platform", "tollgate", "read_fee", fee_usd_micros, ref)
        return True

    @staticmethod
    def _ledger(c, account_type, account_id, kind, amount_usd_micros, ref) -> bool:
        """False if this entry already exists, which is what makes crediting idempotent."""
        return bool(c.execute(
            "INSERT INTO ledger_entries (account_type, account_id, kind, amount_usd_micros, ref) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            (account_type, account_id, kind, amount_usd_micros, ref),
        ).rowcount)

    # --- agents ---

    def create_agent(self, *, name: str, api_key_hash: str) -> dict:
        agent_id = str(uuid.uuid4())
        with self._conn() as c:
            c.execute("INSERT INTO agents (id, name, api_key_hash) VALUES (?, ?, ?)", (agent_id, name, api_key_hash))
        return {"id": agent_id, "name": name}

    def agent(self, agent_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return dict(row) if row else None

    def agent_by_key_hash(self, api_key_hash: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM agents WHERE api_key_hash = ?", (api_key_hash,)).fetchone()
        return dict(row) if row else None

    def add_credit(self, agent_id: str, amount_usd_micros: int, ref: str) -> bool:
        """Add a top-up once. Stripe's webhook and the success page both land here, in either order."""
        with self._conn() as c:
            if not self._ledger(c, "agent", agent_id, "topup", amount_usd_micros, ref):
                return False
            c.execute(
                "UPDATE agents SET credit_usd_micros = credit_usd_micros + ? WHERE id = ?",
                (amount_usd_micros, agent_id),
            )
        return True

    # --- writer balances ---

    def writers_with_balance(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT w.id, w.name, w.stripe_account_id, b.balance, b.last_entry FROM writers w JOIN ("
                "SELECT account_id, CAST(SUM(amount_usd_micros) AS BIGINT) AS balance, MAX(id) AS last_entry "
                "FROM ledger_entries WHERE account_type = 'writer' GROUP BY account_id"
                ") b ON b.account_id = w.id WHERE b.balance > 0 ORDER BY w.id"
            ).fetchall()
        return [dict(r) for r in rows]

    def record_transfer(self, writer_id: str, amount_usd_micros: int, transfer_id: str) -> None:
        with self._conn() as c:
            self._ledger(c, "writer", writer_id, "transfer", -amount_usd_micros, transfer_id)

    def writer_balance(self, writer_id: str) -> int:
        with self._conn() as c:
            return c.execute(
                "SELECT CAST(COALESCE(SUM(amount_usd_micros), 0) AS BIGINT) AS balance FROM ledger_entries "
                "WHERE account_type = 'writer' AND account_id = ?",
                (writer_id,),
            ).fetchone()["balance"]

    def recent(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM purchases ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(r), "receipt": json.loads(r["receipt"])} for r in rows]

    def earnings(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT pay_to, COUNT(*) AS reads, CAST(SUM(amount_usd_micros) AS BIGINT) AS amount_usd_micros "
                "FROM purchases GROUP BY pay_to ORDER BY amount_usd_micros DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # --- dashboard ---

    def dashboard(self, writer_id: str) -> dict:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self._conn() as c:
            mine = "FROM purchases p JOIN articles a ON a.id = p.article_id WHERE a.writer_id = ?"
            totals = c.execute(
                "SELECT COUNT(*) AS reads, CAST(COALESCE(SUM(p.amount_usd_micros - p.fee_usd_micros), 0) AS BIGINT) "
                "AS earned_usd_micros, CAST(COALESCE(SUM(CASE WHEN substr(p.created_at, 1, 7) = ? "
                f"THEN p.amount_usd_micros - p.fee_usd_micros END), 0) AS BIGINT) AS month_usd_micros {mine}",
                (month, writer_id),
            ).fetchone()
            recent = c.execute(
                "SELECT p.tx_hash, p.rail, p.network, p.amount_usd_micros, p.fee_usd_micros, p.agent, p.created_at, a.title "
                f"{mine} ORDER BY p.id DESC LIMIT 10",
                (writer_id,),
            ).fetchall()
            by_agent = c.execute(
                "SELECT p.agent AS name, COUNT(*) AS reads, "
                "CAST(SUM(p.amount_usd_micros - p.fee_usd_micros) AS BIGINT) AS earned_usd_micros "
                f"{mine} GROUP BY p.agent ORDER BY earned_usd_micros DESC, name",
                (writer_id,),
            ).fetchall()
            agents_per_piece = c.execute(
                "SELECT p.article_id, p.agent, CAST(SUM(p.amount_usd_micros - p.fee_usd_micros) AS BIGINT) AS earned "
                f"{mine} GROUP BY p.article_id, p.agent ORDER BY earned DESC, p.agent",
                (writer_id,),
            ).fetchall()
            pieces = c.execute(
                f"{ARTICLE_SELECT} WHERE a.writer_id = ? ORDER BY earned_usd_micros DESC, a.created_at DESC, a.id",
                (writer_id,),
            ).fetchall()

        agents: dict[str, list[str]] = {}
        for row in agents_per_piece:
            agents.setdefault(row["article_id"], []).append(row["agent"])
        recent = [dict(r) for r in recent]
        return {
            "totals": dict(totals),
            "latest": recent[0] if recent else None,
            "recent": recent,
            "balance_usd_micros": self.writer_balance(writer_id),
            "pieces": [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "price_usd_micros": p["price_usd_micros"],
                    "reads": p["reads"],
                    "earned_usd_micros": p["earned_usd_micros"],
                    "agents": agents.get(p["id"], []),
                }
                for p in pieces
            ],
            "by_agent": [dict(a) for a in by_agent],
        }
