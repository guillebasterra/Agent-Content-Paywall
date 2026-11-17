"""Print a sign-in code without sending an email.

The default Supabase email holds only a link, and changing its template needs custom SMTP, so
this is the way to get a code. On /signin, enter your email, choose "I have a code", enter it.

    make demo-otp EMAIL=you@example.com
"""

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402
from app.storage import service_headers  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    args = parser.parse_args()
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY):
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")

    response = httpx.post(
        f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/generate_link",
        headers=service_headers(config.SUPABASE_SERVICE_ROLE_KEY),
        json={"type": "magiclink", "email": args.email},
        timeout=20,
    )
    if response.status_code >= 300:
        sys.exit(f"Supabase refused: HTTP {response.status_code}")
    data = response.json()
    code = data.get("email_otp") or data.get("properties", {}).get("email_otp")
    if not code:
        sys.exit("Supabase did not return a code")
    print(code)


if __name__ == "__main__":
    main()
