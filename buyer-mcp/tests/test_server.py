"""Toll Gate MCP: discovery only. The API is faked with an httpx mock transport: no network."""

import json

import httpx
import pytest
from mcp import Client

from buyer_mcp import server

API = "http://api.test"


def listing(id="frost", usd="0.40", micros=400_000):
    return {
        "id": id,
        "title": f"Title {id}",
        "author": "Guillermo Basterra",
        "abstract": "Why the fans start at 2.4 degrees.",
        "preview": "The first words, free.",
        "price_usd": usd,
        "price_usd_micros": micros,
        "license": "ai-input",
        "allowed_agents": ["*"],
        "reads": 3,
        "url": f"https://tollgate.example/articles/{id}",
        "keywords": ["frost"],
        "pay_to": "0xdef6b98CD666aA0d43125FAF320Db60999D01913",
    }


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def api(monkeypatch):
    seen = []
    catalog = [listing(), listing("ferry", "2.50", 2_500_000)]

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/catalog":
            words = request.url.params.get("q", "").split()
            hits = [a for a in catalog if any(w in a["id"] for w in words)]
            return httpx.Response(200, json={"articles": hits})
        if request.url.path.startswith("/catalog/"):
            item = next((a for a in catalog if a["id"] == request.url.path.removeprefix("/catalog/")), None)
            return httpx.Response(200, json=item) if item else httpx.Response(404, json={"detail": "unknown article"})
        return httpx.Response(500)

    real = httpx.AsyncClient

    def client(**kwargs):
        return real(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(server.httpx, "AsyncClient", client)
    monkeypatch.setenv("TOLLGATE_API_URL", API)
    monkeypatch.delenv("BUYER_AGENT_NAME", raising=False)
    return seen


async def call(tool, args):
    async with Client(server.mcp) as client:
        result = await client.call_tool(tool, args)
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


async def tool_names():
    async with Client(server.mcp) as client:
        return {t.name for t in (await client.list_tools()).tools}


@pytest.mark.anyio
async def test_only_discovery_tools_exist():
    assert await tool_names() == {"search_catalog", "get_article"}


@pytest.mark.anyio
async def test_search_returns_what_the_agent_needs_to_choose_and_pay(api):
    result = await call("search_catalog", {"query": "why frost fans"})
    assert result["status"] == "ok" and result["count"] == 1
    [article] = result["articles"]
    assert {k: article[k] for k in ("title", "author", "preview", "price_usd", "license", "paid_url")} == {
        "title": "Title frost",
        "author": "Guillermo Basterra",
        "preview": "The first words, free.",
        "price_usd": "0.40",
        "license": "ai-input",
        "paid_url": "https://tollgate.example/articles/frost",
    }
    assert "body" not in article
    assert api[0].url.params["q"] == "why frost fans"


@pytest.mark.anyio
async def test_payment_arguments_match_payments_mcp(api):
    payment = (await call("get_article", {"id": "ferry"}))["article"]["payment"]
    assert payment == {
        "tool": "make_http_request_with_x402",
        "baseURL": "https://tollgate.example",
        "path": "/articles/ferry",
        "method": "GET",
        "headers": {"X-Agent-Name": "Claude"},
        "maxAmountPerRequest": 2_500_000,
    }


@pytest.mark.anyio
async def test_agent_name_is_configurable(api, monkeypatch):
    monkeypatch.setenv("BUYER_AGENT_NAME", "Muse")
    article = (await call("get_article", {"id": "frost"}))["article"]
    assert article["payment"]["headers"] == {"X-Agent-Name": "Muse"}


@pytest.mark.anyio
async def test_unknown_article(api):
    result = await call("get_article", {"id": "nope"})
    assert result["status"] == "error" and "search_catalog" in result["reason"]


@pytest.mark.anyio
async def test_id_cannot_reach_another_route(api):
    await call("get_article", {"id": "../me/dashboard"})
    assert api[-1].url.raw_path == b"/catalog/..%2Fme%2Fdashboard"


@pytest.mark.anyio
async def test_unreachable_api_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("TOLLGATE_API_URL", "http://127.0.0.1:9")
    result = await call("search_catalog", {"query": "frost"})
    assert result["status"] == "error" and "unreachable" in result["reason"]


@pytest.mark.anyio
async def test_instructions_send_claude_to_payments_mcp_and_the_receipt():
    async with Client(server.mcp) as client:
        instructions = client.instructions
    for text in ("make_http_request_with_x402", "payments-mcp", "receipt", "explorer", "USDC", "untrusted"):
        assert text in instructions
