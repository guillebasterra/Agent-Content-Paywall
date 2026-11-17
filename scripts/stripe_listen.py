"""Save the webhook secret to .env, then forward Stripe events to the local server.

Reads .env with dotenv, never by sourcing it in a shell: a line like `KEY= value` would make the
shell run the value as a command and print it. The key goes in the child's environment, not its
arguments, so it can't show up in process listings. Restart `make server` if the secret was new.

    make stripe-listen
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "scripts"))

from create_wallets import write_env  # noqa: E402

from app import config  # noqa: E402
from app.stripe_gateway import require_test_key  # noqa: E402

EVENTS = ["--events", "checkout.session.completed"]


def main() -> None:
    env = {**os.environ, "STRIPE_API_KEY": require_test_key(config.STRIPE_SECRET_KEY)}
    done = subprocess.run(["stripe", "listen", *EVENTS, "--print-secret"], env=env, capture_output=True, text=True)
    secret = done.stdout.strip()
    if done.returncode or not secret.startswith("whsec_"):
        sys.exit("stripe listen could not get a webhook secret. Check STRIPE_SECRET_KEY.")
    if secret != config.STRIPE_WEBHOOK_SECRET:
        write_env(ROOT / ".env", {"STRIPE_WEBHOOK_SECRET": secret})
        print("webhook secret saved to .env. Restart `make server` to use it.", flush=True)
    os.execvpe("stripe", ["stripe", "listen", *EVENTS, "--forward-to", "localhost:8000/webhooks/stripe"], env)


if __name__ == "__main__":
    main()
