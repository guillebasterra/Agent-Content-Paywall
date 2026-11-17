"""Put the demo back at its starting line: no purchases and no balances. Writers and articles stay.

    make demo-reset              # clear purchases, writer balances, fees and agent credit
    make demo-reset ARGS=--all   # also delete writers and articles (the old full wipe)

Works on whichever database AUTH_MODE selects. Wallets and keys in .env are kept, and so are
Supabase sign-ins. Nothing on chain changes: USDC already paid stays in the treasury.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402
from app.db import Database  # noqa: E402

# The old paying buyer MCP kept a spend log here. Harmless to remove if present.
BUDGET_FILES = ["budget.json", "budget.json.lock", "budget.tmp"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="also delete writers and articles")
    args = parser.parse_args()

    db = Database(config.database_target())
    kind = "Postgres" if db.is_postgres else "SQLite"
    if args.all:
        db.reset()
        print(f"database wiped: writers, articles, purchases, balances ({kind})")
    else:
        db.reset_sales()
        print(f"purchases and balances cleared; writers and articles kept ({kind})")
    db.close()
    for name in BUDGET_FILES:
        (ROOT / "buyer-mcp" / name).unlink(missing_ok=True)
    if args.all and config.AUTH_MODE == "demo":
        print("restart `make server` so the demo writer is recreated")


if __name__ == "__main__":
    main()
