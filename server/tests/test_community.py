from concurrent.futures import ThreadPoolExecutor

import pytest
from app.community import CommunityStore
from app.community_routes import discord_membership
from app.receipts import verify
from test_api import client, content, facilitator, pay

GUILD, CHANNEL, SOURCE, EDITOR, CHIEF = [str(10**17 + i) for i in range(5)]


def test_source_to_paid_read_and_sales(client):
    store = CommunityStore(client.app.state.db)
    code = client.post("/me/discord/pair", json={"editor": EDITOR, "reviewer": CHIEF, "price_usd": "0.01"}).json()["code"]
    args = (code, GUILD, CHANNEL, "private", SOURCE, {EDITOR, CHIEF})
    store.pair(*args)
    with pytest.raises(ValueError):
        store.pair(*args)
    assert store.capture(CHANNEL, SOURCE, "Caching AMA", "Private answer")
    assert not store.capture(CHANNEL, SOURCE, "changed", "changed")
    assert [r["id"] for r in store.reminders()] == [SOURCE]
    store.mark_notified(SOURCE)
    assert not store.reminders()
    member = {"user": {"id": "chief"}, "roles": [CHIEF]}
    client.app.dependency_overrides[discord_membership] = lambda: member
    path = f"/discord/review/{GUILD}/{CHANNEL}/{SOURCE}"
    assert client.get(path).json()["body"] == "Private answer"
    approval = {"summary": "Public abstract", "price_usd": "0.02", "confirm_rights": True}
    member["roles"] = [EDITOR]
    assert client.post(path, json=approval).status_code == 403
    member["roles"] = [CHIEF]
    assert client.post(path, json={**approval, "confirm_rights": False}).status_code == 422
    def publish(_):
        return client.post(path, json=approval).json()["article_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(publish, range(2))
    assert first == second
    assert "Private answer" not in client.get("/catalog").text
    response = pay(client, first).json()
    assert response["body"] == "Private answer"
    key = client.get("/.well-known/tollgate-receipt-key").json()["public_key"]
    assert verify(response["receipt"], key)
    sales = client.get(f"/me/discord/sales/{first}").json()
    assert sales["reads"] == 1 and sales["earned_usd_micros"] == 20000
    assert sales["recent"][0]["tx_hash"] == response["receipt"]["payload"]["tx_hash"]
    assert store.draft(CHANNEL, SOURCE)["article_id"] == first


def test_pair_cannot_take_over_other_writer_and_sales_are_scoped(client):
    from app.session import current_writer
    db = client.app.state.db
    store = CommunityStore(db)
    roles = {EDITOR, CHIEF}
    db.ensure_writer(id="other", name="Other", email=None, xrpl_address=None)
    for writer in ("demo", "other"):
        code = store.pairing_code(writer, EDITOR, CHIEF, "1")
        if writer == "demo":
            store.pair(code, GUILD, CHANNEL, "private", SOURCE, roles)
        else:
            with pytest.raises(ValueError, match="another writer"):
                store.pair(code, GUILD, CHANNEL, "private", SOURCE, roles)
    store.capture(CHANNEL, SOURCE, "AMA", "Private")
    article = store.publish(CHANNEL, SOURCE, "reviewer", roles, "Public", "1")
    client.app.dependency_overrides[current_writer] = lambda: {"id": "other"}
    assert client.get(f"/me/discord/sales/{article}").status_code == 404


def test_worker_registers_and_parses_one_markdown_attachment():
    import asyncio
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    discord = pytest.importorskip("discord")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bots"))
    from community_bot import build_client, message_draft
    worker = build_client(None)
    assert worker.intents.message_content
    assert {cmd.name for cmd in worker._connection._command_tree.get_commands(type=discord.AppCommandType.message)} == {
        "Review AMA", "AMA sales"
    }
    file = SimpleNamespace(filename="notes.md", size=5, read=AsyncMock(return_value=b"hello"))
    msg = SimpleNamespace(content="【纪要定稿】 Caching", attachments=[file])
    assert asyncio.run(message_draft(msg)) == ("Caching", "hello")
    msg.content += "\nsecond source"
    with pytest.raises(ValueError):
        asyncio.run(message_draft(msg))
