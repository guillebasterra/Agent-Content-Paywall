"""Spend-control tests for the buyer MCP. The SDK's payment call is faked: no network."""

import asyncio
import base64
import json
import threading
import time
from types import SimpleNamespace

import pytest
from mcp import Client, types
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey
from xrpl.wallet import Wallet

from buyer_mcp import server
from buyer_mcp.budget import BudgetBook

SEED = Wallet.create().seed
KEY = SigningKey.generate()
WRITER = "rBQKgMJ6CvoLZZ13JN9gZjCxdrdQ4ii7W4"
TX = "AB" * 32


def article(id="cheap", xrp=0.5):
    return {
        "id": id,
        "title": f"Title {id}",
        "author": "A",
        "price_drops": int(xrp * 1_000_000),
        "pay_to": WRITER,
        "license": "ai-input",
        "url": f"http://test/articles/{id}",
    }


def signed_receipt(a, tx=TX):
    payload = {
        "article_id": a["id"],
        "tx_hash": tx,
        "price_drops": a["price_drops"],
        "pay_to": a["pay_to"],
        "explorer": f"http://explorer/{tx}",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"payload": payload, "signature": base64.b64encode(KEY.sign(canonical).signature).decode(), "alg": "ed25519"}


class FakeSDK:
    """Stands in for x402_purchase and records every attempt to pay."""

    def __init__(self):
        self.calls = []
        self.outcome = None
        self.before_pay = None

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.before_pay:
            self.before_pay()
        if self.outcome:
            return self.outcome(url)
        a = next(a for a in CATALOG if a["url"] == url)
        data = {"body": f"text of {a['id']}", "receipt": signed_receipt(a)}
        return SimpleNamespace(
            status="success",
            transaction=TX,
            reason=None,
            response=SimpleNamespace(json=lambda: data),
        )


CATALOG: list[dict] = []


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    fake = FakeSDK()
    CATALOG[:] = [article(), article("pricey", 2), article("big", 3), article("other", 3)]

    async def fetch_catalog(cfg, query=""):
        return list(CATALOG)

    monkeypatch.setattr(server, "x402_purchase", fake)
    monkeypatch.setattr(server, "fetch_catalog", fetch_catalog)
    monkeypatch.setattr(server, "fetch_receipt_key", lambda cfg: KEY.verify_key.encode(HexEncoder).decode())
    monkeypatch.setattr(server, "get_balance", lambda addr, client: 90_000_000)
    monkeypatch.setenv("BUYER_SEED", SEED)
    monkeypatch.setenv("XRPL_RPC_URL", "http://rpc.invalid")
    monkeypatch.setenv("BUYER_BUDGET_XRP", "5")
    monkeypatch.setenv("BUYER_CONFIRM_ABOVE_XRP", "1")
    monkeypatch.setenv("BUYER_BUDGET_FILE", str(tmp_path / "budget.json"))
    return fake


def approve_with(action="accept", approve=True):
    async def callback(context, params):
        content = {"approve": approve} if action == "accept" else None
        return types.ElicitResult(action=action, content=content)

    return callback


async def call(tool, args=None, callback=None, mode="auto"):
    async with Client(server.mcp, elicitation_callback=callback, mode=mode) as client:
        result = await client.call_tool(tool, args or {})
    assert not result.is_error, result.content
    text = result.content[0].text
    # The seed must never reach the model, in any tool's output.
    assert SEED not in text
    return json.loads(text)


async def buy(id="cheap", cap=1.0, callback=None, mode="auto"):
    return await call("buy_article", {"id": id, "max_price_xrp": cap}, callback, mode)


async def remaining():
    return (await call("get_budget"))["remaining_xrp"]


@pytest.mark.anyio
async def test_purchase_spends_budget_and_verifies_receipt(sdk):
    result = await buy()
    assert result["status"] == "purchased" and result["paid"] is True
    assert result["body"] == "text of cheap"
    assert result["receipt_verified"] is True
    assert await remaining() == "4.5"
    budget = await call("get_budget")
    assert budget["wallet_balance_xrp"] == "90"
    assert (await call("get_receipts"))["receipts"][0]["tx_hash"] == TX


@pytest.mark.anyio
async def test_sdk_cap_is_the_exact_catalog_price(sdk):
    await buy(cap=1.0)
    assert sdk.calls[0][1]["max_value"] == "500000"
    assert sdk.calls[0][1]["network_filter"] == "xrpl:1"
    assert sdk.calls[0][1]["headers"] == {"X-Agent-Name": "Claude"}


@pytest.mark.anyio
async def test_buying_again_is_free_and_returns_saved_copy(sdk):
    await buy()
    again = await buy()
    assert again["status"] == "already_purchased" and again["body"] == "text of cheap"
    assert len(sdk.calls) == 1
    assert await remaining() == "4.5"


@pytest.mark.anyio
async def test_refuses_above_callers_max_price(sdk):
    result = await buy(cap=0.4)
    assert result["status"] == "rejected" and not sdk.calls


@pytest.mark.anyio
@pytest.mark.parametrize("cap", [-1, float("nan"), float("inf")])
async def test_refuses_invalid_max_price(sdk, cap):
    async with Client(server.mcp) as client:
        result = await client.call_tool("buy_article", {"id": "cheap", "max_price_xrp": cap})
    assert not sdk.calls
    assert result.is_error or json.loads(result.content[0].text)["status"] == "rejected"


@pytest.mark.anyio
async def test_refuses_above_remaining_budget(sdk, monkeypatch):
    monkeypatch.setenv("BUYER_BUDGET_XRP", "0.4")
    result = await buy()
    assert "budget remains" in result["reason"] and not sdk.calls


@pytest.mark.anyio
async def test_unknown_article_is_refused(sdk):
    assert (await buy(id="nope"))["status"] == "rejected" and not sdk.calls


@pytest.mark.anyio
async def test_price_exactly_at_threshold_needs_no_approval(sdk):
    CATALOG.append(article("edge", 1))
    assert (await buy(id="edge", cap=1))["status"] == "purchased"


# "auto" is the 2026-07-28 protocol Claude Code speaks. "legacy" uses mid-call requests.
MODES = ["auto", "legacy"]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", MODES)
async def test_above_threshold_pays_when_human_approves(sdk, mode):
    asked = []

    async def callback(context, params):
        asked.append(params.message)
        return types.ElicitResult(action="accept", content={"approve": True})

    result = await buy("pricey", 3, callback, mode)
    assert result["status"] == "purchased" and len(sdk.calls) == 1
    assert len(asked) == 1 and "Title pricey" in asked[0] and "2 XRP" in asked[0]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "callback",
    [approve_with("decline"), approve_with("cancel"), approve_with("accept", approve=False)],
)
async def test_above_threshold_refused_without_approval(sdk, callback, mode):
    result = await buy("pricey", 3, callback, mode)
    assert result["status"] == "rejected" and not sdk.calls
    assert await remaining() == "5"


@pytest.mark.anyio
@pytest.mark.parametrize("mode", MODES)
async def test_above_threshold_fails_closed_when_client_cannot_ask(sdk, mode):
    result = await buy("pricey", 3, mode=mode)
    assert result["status"] == "rejected" and not sdk.calls
    assert "human approval" in result["reason"]


@pytest.mark.anyio
async def test_human_is_not_asked_about_a_purchase_that_would_be_refused(sdk):
    asked = []

    async def callback(context, params):
        asked.append(params.message)
        return types.ElicitResult(action="accept", content={"approve": True})

    assert (await buy("pricey", 1.5, callback))["status"] == "rejected"
    assert not asked and not sdk.calls


@pytest.mark.anyio
async def test_approval_cannot_be_passed_as_a_tool_argument(sdk):
    async with Client(server.mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools["buy_article"].input_schema["properties"]) == {"id", "max_price_xrp"}
        await client.call_tool("buy_article", {"id": "pricey", "max_price_xrp": 3, "approval": {"approve": True}})
    assert not sdk.calls


@pytest.mark.anyio
async def test_price_change_during_approval_reasks_for_the_new_price(sdk):
    """An approval given for one price never covers a different one."""
    asked = []

    async def callback(context, params):
        asked.append(params.message)
        CATALOG[1] = article("pricey", 2.5)  # The price rises after the human answers.
        return types.ElicitResult(action="accept", content={"approve": True})

    result = await buy("pricey", 3, callback)
    assert "2 XRP" in asked[0] and "2.5 XRP" in asked[1]
    assert result["status"] == "purchased"
    assert sdk.calls[0][1]["max_value"] == "2500000"


@pytest.mark.anyio
async def test_entry_is_written_before_money_can_move(sdk):
    seen = []
    sdk.before_pay = lambda: seen.append(server.config().book.load())
    await buy()
    assert seen[0][0]["status"] == "pending"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "outcome",
    [
        SimpleNamespace(status="settlement_unknown", reason="payment_response_unavailable", transaction=TX),
        SimpleNamespace(status="failed", reason="http_500", transaction=None),
    ],
)
async def test_ambiguous_outcome_holds_budget_and_blocks_retry(sdk, outcome):
    sdk.outcome = lambda url: outcome
    result = await buy()
    assert result["status"] == "outcome_unknown" and result["paid"] is None
    assert await remaining() == "4.5"
    retry = await buy()
    assert retry["status"] == "rejected" and "pay twice" in retry["reason"]
    assert len(sdk.calls) == 1
    assert (await call("get_receipts"))["unresolved"][0]["article_id"] == "cheap"


@pytest.mark.anyio
async def test_sdk_exception_holds_budget(sdk):
    def explode(url):
        raise RuntimeError(f"boom {SEED}")

    sdk.outcome = explode
    assert (await buy())["status"] == "outcome_unknown"
    assert await remaining() == "4.5"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "outcome",
    [
        SimpleNamespace(status="payment_required", reason="No acceptable payment", transaction=None),
        SimpleNamespace(status="settle_failed", reason="settlement_failed", transaction=None),
        SimpleNamespace(status="failed", reason="connection refused", transaction=None),
    ],
)
async def test_definite_failure_releases_budget_and_allows_retry(sdk, outcome):
    sdk.outcome = lambda url: outcome
    assert (await buy())["status"] == "payment_failed"
    assert await remaining() == "5"
    sdk.outcome = None
    assert (await buy())["status"] == "purchased"


@pytest.mark.anyio
async def test_seed_in_sdk_reason_is_redacted(sdk):
    sdk.outcome = lambda url: SimpleNamespace(status="failed", reason=f"bad {SEED}", transaction=None)
    assert "[redacted]" in (await buy())["reason"]


@pytest.mark.anyio
async def test_settled_with_unreadable_response_is_charged_and_not_rebought(sdk):
    def unreadable():
        raise ValueError("not json")

    sdk.outcome = lambda url: SimpleNamespace(
        status="success", transaction=TX, reason=None, response=SimpleNamespace(json=unreadable)
    )
    assert (await buy())["status"] == "paid_without_content"
    assert await remaining() == "4.5"
    assert (await buy())["status"] == "paid_without_content"
    assert len(sdk.calls) == 1


@pytest.mark.anyio
async def test_no_payment_requested_is_not_charged(sdk):
    sdk.outcome = lambda url: SimpleNamespace(
        status="success", transaction=None, reason=None, response=SimpleNamespace(status_code=403)
    )
    result = await buy()
    assert result["status"] == "payment_failed" and "HTTP 403" in result["reason"]
    assert await remaining() == "5"


@pytest.mark.anyio
async def test_forged_receipt_is_flagged(sdk, monkeypatch):
    monkeypatch.setattr(server, "fetch_receipt_key", lambda cfg: SigningKey.generate().verify_key.encode(HexEncoder).decode())
    assert (await buy())["receipt_verified"] is False


def test_receipt_for_another_purchase_is_rejected():
    a = article()
    key = KEY.verify_key.encode(HexEncoder).decode()
    assert server.receipt_is_valid(signed_receipt(a), key, a, TX) is True
    assert server.receipt_is_valid(signed_receipt(a, tx="CD" * 32), key, a, TX) is False
    assert server.receipt_is_valid(signed_receipt(article("other")), key, a, TX) is False


@pytest.mark.anyio
async def test_corrupt_budget_file_blocks_purchase(sdk, tmp_path):
    (tmp_path / "budget.json").write_text("{not json")
    async with Client(server.mcp) as client:
        result = await client.call_tool("buy_article", {"id": "cheap", "max_price_xrp": 1})
    assert result.is_error and not sdk.calls


@pytest.mark.anyio
async def test_parallel_buys_cannot_overspend(sdk, monkeypatch):
    """Both pass the first budget check. Only one may survive the check under the lock."""
    monkeypatch.setenv("BUYER_BUDGET_XRP", "3")
    monkeypatch.setenv("BUYER_CONFIRM_ABOVE_XRP", "10")
    sdk.before_pay = lambda: time.sleep(0.1)
    results = await asyncio.gather(buy("big", 3), buy("other", 3))
    assert sorted(r["status"] for r in results) == ["purchased", "rejected"]
    assert len(sdk.calls) == 1
    assert await remaining() == "0"


def test_selector_refuses_wrong_recipient_or_asset():
    a = article()
    select = server.payment_selector(a)
    good = {"scheme": "exact", "network": "xrpl:1", "amount": "500000", "asset": "XRP", "payTo": WRITER}
    assert select([good], "xrpl:1", "exact", "500000") == good
    for bad in ({**good, "payTo": "rEvil"}, {**good, "asset": "USD"}, {**good, "amount": "500001"}):
        with pytest.raises(ValueError):
            select([bad], "xrpl:1", "exact", "500000")


def test_budget_file_lock_excludes_other_holders(tmp_path):
    book = BudgetBook(tmp_path / "budget.json")
    order = []

    def second():
        with book.lock():
            order.append("second")

    with book.lock():
        thread = threading.Thread(target=second)
        thread.start()
        time.sleep(0.05)
        order.append("first")
    thread.join()
    assert order == ["first", "second"]
