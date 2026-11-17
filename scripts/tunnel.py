"""Give the local API a public https URL, because payments-mcp fetches paid URLs from Coinbase's servers.

    make tunnel     # needs cloudflared (brew install cloudflared). Leave it running.

Starts a Cloudflare quick tunnel to localhost:8000, saves its URL to .env as TOLLGATE_API_URL,
and keeps the tunnel open until Ctrl-C. The URL changes on every run, so restart `make server`
after this prints it. Anyone with the URL can reach the API, so use AUTH_MODE=supabase.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from create_wallets import write_env  # noqa: E402

URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def main() -> None:
    binary = shutil.which("cloudflared")
    if not binary:
        sys.exit("cloudflared not found. Install it with `brew install cloudflared`, or set TOLLGATE_API_URL to another tunnel.")
    process = subprocess.Popen(
        [binary, "tunnel", "--no-autoupdate", "--url", "http://localhost:8000"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    try:
        found = False
        # Keep reading after the URL appears, so cloudflared never blocks on a full pipe.
        for line in process.stderr:
            if not found and (match := URL.search(line)):
                found = True
                write_env(ROOT / ".env", {"TOLLGATE_API_URL": match[0]})
                print(f"public API: {match[0]}  (saved to .env as TOLLGATE_API_URL)")
                print("now restart `make server`, then run `make preflight`. Ctrl-C here closes the tunnel.")
        process.wait()
    except KeyboardInterrupt:
        process.terminate()


if __name__ == "__main__":
    main()
