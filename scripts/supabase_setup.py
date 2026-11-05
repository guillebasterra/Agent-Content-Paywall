"""Prepare the Supabase project: schema, the private uploads bucket, and a check the tables are closed.

Safe to run repeatedly.

    make supabase-setup
"""

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from app import config  # noqa: E402
from app.db import TABLES, Database  # noqa: E402
from app.storage import BUCKET  # noqa: E402


def main() -> None:
    missing = [
        name
        for name, value in {
            "SUPABASE_URL": config.SUPABASE_URL,
            "SUPABASE_PUBLISHABLE_KEY": config.SUPABASE_PUBLISHABLE_KEY,
            "SUPABASE_SERVICE_ROLE_KEY": config.SUPABASE_SERVICE_ROLE_KEY,
            "SUPABASE_DB_URL": config.SUPABASE_DB_URL,
        }.items()
        if not value
    ]
    if missing:
        sys.exit(f"missing in .env: {', '.join(missing)}")

    base = config.SUPABASE_URL.rstrip("/")
    Database(config.SUPABASE_DB_URL).close()
    print("schema ready, row level security on")

    service = {"apikey": config.SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}"}
    bucket = httpx.get(f"{base}/storage/v1/bucket/{BUCKET}", headers=service, timeout=20)
    if bucket.status_code == 200:
        if bucket.json().get("public"):
            sys.exit(f"bucket {BUCKET} is public. Make it private in the dashboard.")
        print(f"bucket {BUCKET} exists, private")
    else:
        created = httpx.post(
            f"{base}/storage/v1/bucket", headers=service, json={"id": BUCKET, "name": BUCKET, "public": False}, timeout=20
        )
        if created.status_code >= 300:
            sys.exit(f"could not create bucket {BUCKET}: HTTP {created.status_code}")
        print(f"bucket {BUCKET} created, private")

    browser = {"apikey": config.SUPABASE_PUBLISHABLE_KEY}
    for table in TABLES:
        response = httpx.get(f"{base}/rest/v1/{table}?select=*&limit=1", headers=browser, timeout=20)
        if response.status_code == 200 and response.json():
            sys.exit(f"LEAK: the browser key can read {table}. Do not continue.")
    print("browser key reads nothing from the tables")

    jwks = httpx.get(f"{base}/auth/v1/.well-known/jwks.json", timeout=20)
    keys = jwks.json().get("keys", []) if jwks.status_code == 200 else []
    print("tokens: " + ("asymmetric, verified locally" if keys else "legacy HS256, verified through the Auth server"))


if __name__ == "__main__":
    main()
