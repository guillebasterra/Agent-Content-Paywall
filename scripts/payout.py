"""Pay writers their accrued balance as Stripe test-mode Transfers.

    make payout
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402
from app.db import Database  # noqa: E402
from app.payouts import pay_writers  # noqa: E402
from app.stripe_gateway import StripeGateway  # noqa: E402


def main() -> None:
    if not config.STRIPE_SECRET_KEY:
        sys.exit("STRIPE_SECRET_KEY is not set in .env")
    db = Database(config.database_target())
    results = pay_writers(db, StripeGateway(config.STRIPE_SECRET_KEY))
    db.close()
    if not results:
        print("no writer has a balance")
    for r in results:
        detail = r.get("transfer") or r.get("reason") or ""
        print(f"{r['name']}: ${r['cents'] / 100:.2f} {r['status']} {detail}".rstrip())


if __name__ == "__main__":
    main()
