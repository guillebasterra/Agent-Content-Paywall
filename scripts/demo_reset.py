"""Put the demo back at its starting line: no writers, articles or purchases, and a full budget.

Wallets and keys in .env are kept. Sign out in the browser separately.

    make demo-reset
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402

BUDGET_FILES = ["budget.json", "budget.json.lock", "budget.tmp"]
TABLES = ["purchases", "articles", "writers"]


def main() -> None:
    db_path = config.DB_PATH if config.DB_PATH.is_absolute() else ROOT / "server" / config.DB_PATH
    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")
        print(f"cleared {', '.join(TABLES)} in {db_path.name}")
    for name in BUDGET_FILES:
        (ROOT / "buyer-mcp" / name).unlink(missing_ok=True)
    print("buyer budget reset")
    print("restart `make server` if it is running in demo mode, so the demo writer is recreated")


if __name__ == "__main__":
    main()
