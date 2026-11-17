"""Set the per-read price of every article, or one, in the database AUTH_MODE selects.

    make set-price ARGS="--usd 0.02"
    make set-price ARGS="--usd 0.40 --id why-halden-valley-orchards-run-their-frost-fans-at-2-4-degrees"

Takes effect on the next request: the paywall prices from the database each time.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402
from app.content import format_usd, to_micros  # noqa: E402
from app.db import Database  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usd", required=True, help="price per read in US dollars, e.g. 0.02")
    parser.add_argument("--id", help="one article id; every article if omitted")
    args = parser.parse_args()
    try:
        micros = to_micros(args.usd)
    except ValueError as exc:
        sys.exit(f"--usd: {exc}")

    db = Database(config.database_target())
    changed = db.set_price(micros, args.id)
    for article in db.articles("new"):
        print(f"${format_usd(article['price_usd_micros'])}  {article['id']}")
    db.close()
    where = "Postgres" if db.is_postgres else "SQLite"
    print(f"{changed} article(s) set to ${format_usd(micros)} ({where})")
    if args.id and not changed:
        sys.exit(f"no article with id {args.id!r}")


if __name__ == "__main__":
    main()
