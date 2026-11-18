"""Discord boundary and existing MCP -> x402 purchase flow. No real Discord or money."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config
from app.content import content_hash
from app.discord_import import ImportFailure, fetch_snapshot
from app.main import create_app
from app.receipts import verify
from tests.test_base import FakeFacilitator, buy
from tests.test_mcp import session, text

GUILD = "100000000000000001"
CHANNEL = "100000000000000002"
SECRET = "Private orchard discussion: the frost fan threshold is 2.4 degrees."


def message(number=3, **changes):
    return {"id": f"10000000000000000{number}", "channel_id": CHANNEL,
            "type": 0, "author": {"username": "member", "bot": False},
            "content": SECRET, "timestamp": "2026-11-17T10:00:00+00:00", **changes}


def snapshot(messages=None, channel=None, status=200):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bot fake-token"
        if request.url.path.endswith("/messages"):
            return httpx.Response(status, json=messages if messages is not None else [message()])
        return httpx.Response(200, json=channel or {"id": CHANNEL, "guild_id": GUILD, "type": 0})

    with httpx.Client(base_url="https://discord.com/api/v10/", headers={"Authorization": "Bot fake-token"},
                      transport=httpx.MockTransport(handle)) as http:
        body = fetch_snapshot(http, GUILD, CHANNEL, 10)
    return body, requests


def test_only_configured_channel_is_read_and_messages_are_chronological():
    body, requests = snapshot([message(4, content="Later text"), message()])
    assert len(requests) == 2 and requests[1].url.params["limit"] == "10"
    assert body.index(SECRET) < body.index("Later text")
    assert f"https://discord.com/channels/{GUILD}/{CHANNEL}/100000000000000003" in body
    assert "fake-token" not in body


@pytest.mark.parametrize("channel", [
    {"id": CHANNEL, "guild_id": "100000000000000099", "type": 0},
    {"id": CHANNEL, "guild_id": GUILD, "type": 1},
    {"id": CHANNEL, "guild_id": GUILD, "type": 11},
])
def test_wrong_server_and_unsupported_channels_are_rejected(channel):
    with pytest.raises(ImportFailure):
        snapshot(channel=channel)


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_upstream_errors_do_not_expose_response_text(status):
    with pytest.raises(ImportFailure) as error:
        snapshot(status=status)
    assert SECRET not in str(error.value) and "fake-token" not in str(error.value)


def test_empty_content_fails_with_intent_hint():
    with pytest.raises(ImportFailure, match="Message Content Intent"):
        snapshot([message(content="")])


def test_bot_system_and_attachment_only_messages_are_not_imported():
    body, _ = snapshot([message(), message(4, author={"bot": True}, content="BOT_TEXT"),
                        message(5, type=7, content="SYSTEM_TEXT"), message(6, content="", attachments=[{"url": "secret"}])])
    assert SECRET in body and "BOT_TEXT" not in body and "SYSTEM_TEXT" not in body
    assert "Included human text messages: 1" in body


def test_foreign_message_is_rejected():
    with pytest.raises(ImportFailure, match="different channel"):
        snapshot([message(channel_id="100000000000000099")])


@pytest.mark.parametrize("guild,limit", [("../other", 10), (GUILD, 0), (GUILD, 101)])
def test_invalid_scope_rejected_before_network(guild, limit):
    with httpx.Client() as http, pytest.raises(ImportFailure):
        fetch_snapshot(http, guild, CHANNEL, limit)


def test_discord_snapshot_uses_existing_mcp_payment_receipt_and_writer_credit(monkeypatch, tmp_path, database):
    monkeypatch.setattr(config, "PAYMENT_RAIL", "base")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://tollgate.example")
    folder = tmp_path / "empty"
    folder.mkdir()
    facilitator = FakeFacilitator()
    app = create_app(base_facilitator=facilitator, database=database, content_dir=folder)
    try:
        client = TestClient(app)
        body, _ = snapshot()
        uploaded = client.post("/articles", data={"title": "Discord orchard snapshot", "abstract": "Community discussion about frost fans.",
                               "keywords": "discord,orchard", "price_usd": "0.01", "preview_mode": "none", "license": "ai-input"},
                               files={"file": ("discord.md", body.encode(), "text/markdown")})
        assert uploaded.status_code == 201
        article_id = uploaded.json()["id"]

        async def discover(mcp):
            found = text(await mcp.call_tool("search_catalog", {"query": "discord orchard"}))
            details = text(await mcp.call_tool("get_article", {"id": article_id}))
            return found, details

        found, details = session(app, discover)
        assert found["count"] == 1
        assert details["article"]["payment"]["maxAmountPerRequest"] == 10_000
        assert details["article"]["preview"] == ""
        for public in (found, details, client.get("/catalog").json(), uploaded.json()):
            assert SECRET not in json.dumps(public)
        unpaid = client.get(f"/articles/{article_id}")
        assert unpaid.status_code == 402 and SECRET not in unpaid.text
        paid = buy(app, f"/articles/{article_id}")
        assert paid.status_code == 200
        data = paid.json()
        assert data["body"] == body
        assert verify(data["receipt"], client.get("/.well-known/tollgate-receipt-key").json()["public_key"])
        assert data["receipt"]["payload"]["content_hash"] == content_hash(body)
        assert data["receipt"]["payload"]["amount_usd"] == "0.01"
        assert app.state.db.writer_balance("demo") == 10_000
        assert len(facilitator.settled) == 1
    finally:
        app.state.db.close()
