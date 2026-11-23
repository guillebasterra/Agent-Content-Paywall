"""Persistence for Discord channel pairing, frozen drafts and their published articles."""
import hashlib
import secrets
import time
import uuid

from .content import to_micros

MARKER = "【纪要定稿】"
TABLES = ["discord_pairs", "discord_channels", "discord_drafts"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS discord_pairs (
    id TEXT PRIMARY KEY, writer_id TEXT NOT NULL UNIQUE REFERENCES writers(id),
    editor TEXT NOT NULL, reviewer TEXT NOT NULL, price BIGINT NOT NULL, expires BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS discord_channels (
    id TEXT PRIMARY KEY, guild TEXT NOT NULL, writer_id TEXT NOT NULL REFERENCES writers(id),
    editor TEXT NOT NULL, reviewer TEXT NOT NULL, price BIGINT NOT NULL, review_channel TEXT NOT NULL, cursor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discord_drafts (
    id TEXT PRIMARY KEY, channel TEXT NOT NULL REFERENCES discord_channels(id),
    title TEXT NOT NULL, body TEXT NOT NULL, summary TEXT NOT NULL, price BIGINT NOT NULL,
    article_id TEXT UNIQUE REFERENCES articles(id), approved_by TEXT, notified INTEGER NOT NULL DEFAULT 0
)
"""


class CommunityStore:
    def __init__(self, database):
        self.database = database

    def pairing_code(self, writer_id, editor, reviewer, price_usd):
        code = secrets.token_urlsafe(24)
        digest = hashlib.sha256(code.encode()).hexdigest()
        with self.database.transaction() as c:
            c.execute(
                "INSERT INTO discord_pairs(id,writer_id,editor,reviewer,price,expires) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(writer_id) DO UPDATE SET id=excluded.id, editor=excluded.editor, "
                "reviewer=excluded.reviewer, price=excluded.price, expires=excluded.expires",
                (digest, writer_id, editor, reviewer, to_micros(price_usd), int(time.time()) + 600),
            )
        return code

    def pair(self, code, guild, channel, review_channel, cursor, available_roles):
        with self.database.transaction() as c:
            row = c.execute("DELETE FROM discord_pairs WHERE id=? AND expires>? RETURNING *",
                            (hashlib.sha256(code.encode()).hexdigest(), int(time.time()))).fetchone()
            if not row:
                raise ValueError("Pairing code expired or already used.")
            if not {row["editor"], row["reviewer"]}.issubset(available_roles):
                raise ValueError("Select editor and reviewer role IDs from this server.")
            changed = c.execute(
                "INSERT INTO discord_channels(id,guild,writer_id,editor,reviewer,price,review_channel,cursor) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET editor=excluded.editor, "
                "reviewer=excluded.reviewer, price=excluded.price, review_channel=excluded.review_channel "
                "WHERE discord_channels.writer_id=excluded.writer_id AND discord_channels.guild=excluded.guild",
                (channel, guild, row["writer_id"], row["editor"], row["reviewer"], row["price"], review_channel, cursor),
            )
            if not changed.rowcount:
                raise ValueError("This channel is already linked to another writer.")

    def channel(self, guild, channel):
        with self.database.transaction() as c:
            row = c.execute("SELECT * FROM discord_channels WHERE guild=? AND id=?", (guild, channel)).fetchone()
            return dict(row) if row else None

    def channels(self):
        with self.database.transaction() as c:
            return [dict(row) for row in c.execute("SELECT * FROM discord_channels").fetchall()]

    def advance(self, channel, expected, cursor):
        with self.database.transaction() as c:
            c.execute("UPDATE discord_channels SET cursor=? WHERE id=? AND cursor=?", (cursor, channel, expected))

    def reminders(self):
        with self.database.transaction() as c:
            return [dict(row) for row in c.execute(
                "SELECT d.id,d.channel,c.guild,c.review_channel FROM discord_drafts d "
                "JOIN discord_channels c ON c.id=d.channel WHERE d.notified=0 AND d.article_id IS NULL"
            ).fetchall()]

    def mark_notified(self, message):
        with self.database.transaction() as c:
            c.execute("UPDATE discord_drafts SET notified=1 WHERE id=?", (message,))

    def capture(self, channel, message, title, body):
        title, body = title.strip(), body.strip()
        if not title or not body or len(title) > 200 or len(body.encode()) > 2_000_000:
            raise ValueError("Supply a title (up to 200 characters) and up to 2 MB of text.")
        with self.database.transaction() as c:
            return bool(c.execute(
                "INSERT INTO discord_drafts(id,channel,title,body,summary,price) "
                "SELECT ?,id,?,?,?,price FROM discord_channels WHERE id=? ON CONFLICT(id) DO NOTHING",
                (message, title, body, title, channel),
            ).rowcount)

    def draft(self, channel, message):
        with self.database.transaction() as c:
            row = c.execute("SELECT * FROM discord_drafts WHERE channel=? AND id=?", (channel, message)).fetchone()
            if not row:
                raise ValueError("No AMA draft for this message.")
            return dict(row)

    def publish(self, channel, message, reviewer_id, role_ids, summary, price_usd):
        summary = summary.strip()
        if not summary or len(summary) > 2000:
            raise ValueError("The public abstract must be 1–2000 characters.")
        price = to_micros(price_usd)
        with self.database.transaction() as c:
            # Serialize confirmations before reading the article mapping (SQLite and Postgres).
            if not c.execute("UPDATE discord_drafts SET id=id WHERE id=? AND channel=?", (message, channel)).rowcount:
                raise ValueError("No AMA draft for this message.")
            draft = c.execute(
                "SELECT d.*, c.writer_id,c.reviewer FROM discord_drafts d JOIN discord_channels c "
                "ON c.id=d.channel WHERE d.id=?", (message,),
            ).fetchone()
            if draft["reviewer"] not in role_ids:
                raise ValueError("The configured reviewer role is required.")
            if draft["article_id"]:
                return draft["article_id"]
            article_id = "ama-" + uuid.uuid4().hex
            self.database.insert_article(c, {
                "id": article_id, "writer_id": draft["writer_id"], "title": draft["title"],
                "body": draft["body"], "abstract": summary, "preview_mode": "none",
                "keywords": ["discord", "ama"], "price_usd_micros": price, "license": "ai-input",
                "allowed_agents": ["*"], "train_price_usd_micros": None,
            })
            c.execute("UPDATE discord_drafts SET article_id=?, approved_by=?, summary=?, price=? WHERE id=?",
                      (article_id, reviewer_id, summary, price, message))
        return article_id
