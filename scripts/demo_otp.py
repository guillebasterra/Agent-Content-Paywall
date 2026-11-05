"""Print a sign-in code without sending an email, for when Supabase's email limit is hit.

Enter the code on /signin after requesting one, or skip the request if email is rate limited.

    make demo-otp EMAIL=you@example.com
"""

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    args = parser.parse_args()
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY):
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")

    key = config.SUPABASE_SERVICE_ROLE_KEY
    response = httpx.post(
        f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/generate_link",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
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
