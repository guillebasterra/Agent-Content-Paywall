"""Put the demo back at its starting line: no writers, articles or purchases, and a full budget.

Works on whichever database AUTH_MODE selects. Wallets and keys in .env are kept, and so are
Supabase sign-ins: the next login simply creates a new writer. Sign out in the browser separately.

    make demo-reset
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402
from app.db import Database  # noqa: E402

BUDGET_FILES = ["budget.json", "budget.json.lock", "budget.tmp"]


def main() -> None:
    db = Database(config.database_target())
    db.reset()
    db.close()
    print(f"database cleared ({'Postgres' if db.is_postgres else 'SQLite'})")
    for name in BUDGET_FILES:
        (ROOT / "buyer-mcp" / name).unlink(missing_ok=True)
    print("buyer budget reset")
    if config.AUTH_MODE == "demo":
        print("restart `make server` so the demo writer is recreated")


if __name__ == "__main__":
    main()
