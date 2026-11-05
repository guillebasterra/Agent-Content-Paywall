"""Create the buyer's agent account and save its API key to .env. The key is never printed.

    make agent
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "scripts"))

from create_wallets import write_env  # noqa: E402

from app import config  # noqa: E402
from app.db import Database  # noqa: E402
from app.rails.stripe_credit import hash_key, new_api_key  # noqa: E402


def main() -> None:
    db = Database(config.database_target())
    existing = os.getenv("BUYER_STRIPE_API_KEY", "")
    if existing and db.agent_by_key_hash(hash_key(existing)):
        print("agent account already set up")
    else:
        key = new_api_key()
        name = os.getenv("BUYER_AGENT_NAME", "Claude")
        db.create_agent(name=name, api_key_hash=hash_key(key))
        write_env(ROOT / ".env", {"BUYER_STRIPE_API_KEY": key})
        print(f"created agent account {name}, key saved to .env as BUYER_STRIPE_API_KEY")
    db.close()


if __name__ == "__main__":
    main()
