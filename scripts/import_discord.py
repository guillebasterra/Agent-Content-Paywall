"""Import one Discord channel. Save locally by default; --publish uploads to Tollgate."""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.content import format_usd, to_micros
from app.discord_import import ImportFailure, fetch_snapshot


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Public catalog title")
    parser.add_argument("--abstract", required=True, help="Public preview description; no private message text")
    parser.add_argument("--keywords", default="discord,community")
    parser.add_argument("--price-usd", default="0.02")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--publish", action="store_true", help="Publish using existing POST /articles")
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()
    try:
        price = format_usd(to_micros(args.price_usd))
        if not args.title.strip() or not args.abstract.strip():
            raise ImportFailure("Title and abstract must not be blank.")
        token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        guild = os.getenv("DISCORD_GUILD_ID", "").strip()
        channel = os.getenv("DISCORD_CHANNEL_ID", "").strip()
        writer_token = os.getenv("TOLLGATE_WRITER_TOKEN", "").strip()
        if not token:
            raise ImportFailure("Configure DISCORD_BOT_TOKEN in the local environment or .env.")
        url = urlsplit(args.api_url)
        if args.publish:
            local = url.hostname in {"localhost", "127.0.0.1", "::1"}
            if url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
                raise ImportFailure("--api-url must be an origin without credentials, path, query or fragment.")
            if url.scheme != "https" and not (local and url.scheme == "http"):
                raise ImportFailure("Use HTTPS for a remote Tollgate API.")
            if not local and not writer_token:
                raise ImportFailure("Set TOLLGATE_WRITER_TOKEN to your signed-in writer's access token for remote publishing.")
        with httpx.Client(base_url="https://discord.com/api/v10/", timeout=30,
                          headers={"Authorization": f"Bot {token}"}, follow_redirects=False) as http:
            body = fetch_snapshot(http, guild, channel, args.limit)
        folder = ROOT / ".discord-snapshots"
        folder.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = folder / f"discord-{channel}-{stamp}.md"
        with path.open("x", encoding="utf-8") as output:
            output.write(body)
        print(f"Saved private snapshot: {path}")
        if not args.publish:
            print("Review locally, then upload this Markdown file through the writer website. Choose preview 'none'.")
            return
        headers = {"Authorization": f"Bearer {writer_token}"} if writer_token else {}
        with httpx.Client(timeout=30, follow_redirects=False) as http:
            response = http.post(args.api_url.rstrip("/") + "/articles", headers=headers,
                                 data={"title": args.title, "abstract": args.abstract,
                                       "keywords": args.keywords, "price_usd": price,
                                       "preview_mode": "none", "license": "ai-input"},
                                 files={"file": (path.name, body.encode("utf-8"), "text/markdown")})
        if response.status_code != 201:
            raise ImportFailure(f"Upload HTTP {response.status_code}. Snapshot is saved; check writer login/API configuration.")
        article = response.json()
        print(f"Published: {article['id']} (${article['price_usd']} per read). Find it through search_catalog.")
    except (ValueError, httpx.HTTPError, OSError) as exc:
        # HTTP errors may contain URLs/headers; never print them or upstream response bodies.
        message = str(exc) if isinstance(exc, ValueError) else "Request or file operation failed; check the saved snapshot and catalog before retrying."
        parser.exit(1, message + "\n")


if __name__ == "__main__":
    main()
