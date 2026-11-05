"""Open a Stripe Checkout page to add credit to the buyer's agent account. Needs `make server` running.

    make topup ARGS="--usd 10"

Pay with test card 4000 0000 0000 0077, so the funds are available for `make payout` at once.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--usd", default="10")
    args = parser.parse_args()
    key = os.getenv("BUYER_STRIPE_API_KEY", "")
    if not key:
        sys.exit("BUYER_STRIPE_API_KEY is not set. Run `make agent` first.")
    response = httpx.post(
        f"{config.PUBLIC_URL}/agents/me/topups",
        headers={"Authorization": f"Bearer {key}"},
        json={"amount_usd": args.usd},
        timeout=30,
    )
    if response.status_code != 200:
        sys.exit(f"top-up refused: HTTP {response.status_code} {response.text[:200]}")
    url = response.json()["checkout_url"]
    print(url)
    print("Test card: 4000 0000 0000 0077, any future date, any CVC")
    subprocess.run(["open", url], check=False)


if __name__ == "__main__":
    main()
