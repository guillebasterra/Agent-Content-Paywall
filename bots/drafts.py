"""Private durable drafts with compare-and-set publication states."""
import json
import sqlite3
from contextlib import contextmanager
from uuid import uuid4
from pathlib import Path
from app.discord_import import ImportFailure
ROOT = Path(__file__).resolve().parents[1]

@contextmanager
def database():
    folder = ROOT / '.discord-snapshots'
    folder.mkdir(exist_ok=True)
    db = sqlite3.connect(folder / 'publisher.sqlite')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, owner TEXT, state TEXT, payload TEXT)')
        with db:
            yield db
    finally:
        db.close()


def create_draft(owner, payload):
    key = uuid4().hex[:12]
    with database() as db:
        db.execute('INSERT INTO drafts VALUES (?, ?, ?, ?)', (key, str(owner), 'draft', json.dumps(payload)))
    return key


def get_draft(key, owner):
    with database() as db:
        row = db.execute('SELECT owner,state,payload FROM drafts WHERE id=?', (key,)).fetchone()
    if not row or row[0] != str(owner):
        raise ImportFailure('Draft not found or belongs to another administrator.')
    return row[1], json.loads(row[2])


def transition(key, owner, previous, state, payload=None):
    with database() as db:
        result = db.execute('UPDATE drafts SET state=?, payload=COALESCE(?,payload) WHERE id=? AND owner=? AND state=?',
                            (state, json.dumps(payload) if payload is not None else None, key, str(owner), previous))
        if result.rowcount != 1:
            raise ImportFailure('Draft state changed. Review its status; do not retry publishing blindly.')

