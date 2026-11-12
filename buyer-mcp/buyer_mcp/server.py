"""The Toll Gate MCP over stdio, for development. Discovery only: no wallet, no payments.

The tools and instructions are defined once in server/app/agent_mcp.py, which the API also
serves remotely at /mcp. Here they read the catalog over HTTP from TOLLGATE_API_URL.
"""

import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
# agent_mcp imports only the MCP SDK and the standard library, so this venv can load it as is.
sys.path.insert(0, str(ROOT / "server"))

from app.agent_mcp import INSTRUCTIONS, CatalogUnavailable, build_mcp  # noqa: E402

__all__ = ["INSTRUCTIONS", "mcp"]


def api_url() -> str:
    return os.getenv("TOLLGATE_API_URL", "http://localhost:8000").rstrip("/")


def agent_name() -> str:
    return os.getenv("BUYER_AGENT_NAME", "").strip() or "Claude"


async def fetch(path: str, params: dict | None = None) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            return await client.get(f"{api_url()}{path}", params=params)
    except httpx.HTTPError as exc:
        raise CatalogUnavailable(f"Toll Gate is unreachable at {api_url()} ({type(exc).__name__}).") from None


def failed(response: httpx.Response) -> CatalogUnavailable:
    return CatalogUnavailable(f"Toll Gate at {api_url()} answered HTTP {response.status_code}.")


async def search(query: str) -> list[dict]:
    response = await fetch("/catalog", {"q": query})
    if response.status_code != 200:
        raise failed(response)
    return response.json()["articles"]


async def lookup(article_id: str) -> dict | None:
    # Quoted whole, so an id can't walk to another route.
    response = await fetch(f"/catalog/{quote(article_id, safe='')}")
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise failed(response)
    return response.json()


mcp = build_mcp(search, lookup, agent_name)


if __name__ == "__main__":
    mcp.run()
