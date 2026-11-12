"""The Toll Gate MCP served at /mcp (streamable HTTP), driven by the official MCP client. No network."""

import asyncio
import json

import httpx2
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app import config
from app.main import create_app
from tests.test_base import BODY, FakeFacilitator

PUBLIC = "https://tollgate.example"


@pytest.fixture
def app(monkeypatch, tmp_path, database):
    monkeypatch.setattr(config, "PAYMENT_RAIL", "base")
    monkeypatch.setattr(config, "PUBLIC_URL", PUBLIC)
    content = tmp_path / "content"
    content.mkdir()
    (content / "seeded.md").write_text(
        f"---\nid: seeded\ntitle: Frost fans\nabstract: Why 2.4 degrees.\nprice_usd: 0.40\nkeywords: [frost]\n---\n{BODY}"
    )
    app = create_app(base_facilitator=FakeFacilitator(), database=database, content_dir=content)
    yield app
    app.state.db.close()


def session(app, run):
    """Run `run(client)` against the app over real streamable HTTP, in process."""

    async def main():
        async with app.router.lifespan_context(app):
            http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=PUBLIC)
            async with Client(streamable_http_client(f"{PUBLIC}/mcp", http_client=http)) as client:
                return await run(client)

    return asyncio.run(main())


def text(result):
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


def test_tools_are_the_two_read_only_discovery_tools(app):
    async def run(client):
        return (await client.list_tools()).tools, client.instructions

    tools, instructions = session(app, run)
    assert {t.name for t in tools} == {"search_catalog", "get_article"}
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)
    assert "make_http_request_with_x402" in instructions and "payments-mcp" in instructions


def test_search_returns_the_servers_own_paid_url_and_payment_arguments(app):
    async def run(client):
        return text(await client.call_tool("search_catalog", {"query": "why frost fans"}))

    result = session(app, run)
    assert result["status"] == "ok" and result["count"] == 1
    [article] = result["articles"]
    assert article["title"] == "Frost fans" and article["price_usd"] == "0.40"
    assert article["paid_url"] == f"{PUBLIC}/articles/seeded"
    assert article["payment"] == {
        "tool": "make_http_request_with_x402",
        "baseURL": PUBLIC,
        "path": "/articles/seeded",
        "method": "GET",
        "headers": {"X-Agent-Name": "Claude"},
        "maxAmountPerRequest": 400_000,
    }
    assert "word199" not in json.dumps(result)


def test_get_article_and_unknown_id(app):
    async def run(client):
        found = text(await client.call_tool("get_article", {"id": "seeded"}))
        missing = text(await client.call_tool("get_article", {"id": "../me/dashboard"}))
        return found, missing

    found, missing = session(app, run)
    assert found["article"]["id"] == "seeded" and "body" not in found["article"]
    assert missing["status"] == "error" and "search_catalog" in missing["reason"]


def test_mcp_is_free_and_accepts_a_public_host(app):
    """No payment, no auth, and the Host check that suits local servers is off for this public one."""
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    }
    with TestClient(app, base_url="https://tollgate-production.up.railway.app") as client:
        response = client.post("/mcp", json=initialize, headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "tollgate"
    assert "PAYMENT-REQUIRED" not in response.headers
