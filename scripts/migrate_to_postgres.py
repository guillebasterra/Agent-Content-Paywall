"""Copy the SQLite demo database into Supabase Postgres. Safe to run twice: existing rows are kept.

    make migrate-db
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402
from app.db import TABLES, Database  # noqa: E402


def copy_rows(source: Database, target: Database) -> dict[str, int]:
    """Parents first, so references hold. Identity ids are left for Postgres to assign, in the same order."""
    copied = {}
    for table in TABLES:
        with source._conn() as c:
            rows = [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]
        with target._conn() as c:
            for row in rows:
                if table in Database.SERIAL_TABLES:
                    row.pop("id")
                columns = ", ".join(row)
                marks = ", ".join("?" for _ in row)
                c.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({marks}) ON CONFLICT DO NOTHING", tuple(row.values())
                )
        copied[table] = len(rows)
    return copied


def main() -> None:
    if not config.SUPABASE_DB_URL:
        sys.exit("SUPABASE_DB_URL is not set in .env")
    path = config.DB_PATH if config.DB_PATH.is_absolute() else ROOT / "server" / config.DB_PATH
    if not path.exists():
        sys.exit(f"nothing to migrate: {path} does not exist")
    source, target = Database(path), Database(config.SUPABASE_DB_URL)
    for table, count in copy_rows(source, target).items():
        print(f"{table}: {count} rows read")
    source.close()
    target.close()


if __name__ == "__main__":
    main()
