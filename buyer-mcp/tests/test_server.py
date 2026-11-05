"""Spend-control tests for the buyer MCP. The SDK's payment call is faked: no network."""

import asyncio
import base64
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from mcp import Client, types
from nacl.encoding import HexEncoder
from nacl.signing import SigningKey
from xrpl.wallet import Wallet

from buyer_mcp import server
from buyer_mcp.budget import BudgetBook

SEED = Wallet.create().seed
API_KEY = "tg_test_secretsecretsecret"
KEY = SigningKey.generate()
WRITER = "rBQKgMJ6CvoLZZ13JN9gZjCxdrdQ4ii7W4"
TX = "AB" * 32


def article(id="cheap", usd=0.5):
    return {
        "id": id,
        "title": f"Title {id}",
        "author": "A",
        "price_usd_micros": int(usd * 1_000_000),
        "price_drops": int(usd * 500_000),  # At 1 XRP = $2.
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
    monkeypatch.setenv("BUYER_BUDGET_USD", "5")
    monkeypatch.setenv("BUYER_CONFIRM_ABOVE_USD", "1")
    monkeypatch.setenv("BUYER_BUDGET_FILE", str(tmp_path / "budget.json"))
    monkeypatch.setenv("BUYER_ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.setenv("BUYER_RAIL", "xrpl")
    monkeypatch.setenv("BUYER_STRIPE_API_KEY", API_KEY)
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
    assert SEED not in text and API_KEY not in text
    return json.loads(text)


async def buy(id="cheap", cap=1.0, callback=None, mode="auto"):
    return await call("buy_article", {"id": id, "max_price_usd": cap}, callback, mode)


async def remaining():
    return (await call("get_budget"))["remaining_usd"]


@pytest.mark.anyio
async def test_purchase_spends_budget_and_verifies_receipt(sdk):
    result = await buy()
    assert result["status"] == "purchased" and result["paid"] is True
    assert result["body"] == "text of cheap"
    assert result["receipt_verified"] is True
    assert await remaining() == "4.50"
    budget = await call("get_budget")
    assert budget["wallet_balance_xrp"] == "90"
    assert (await call("get_receipts"))["receipts"][0]["tx_hash"] == TX


@pytest.mark.anyio
async def test_sdk_cap_is_the_exact_catalog_price(sdk):
    await buy(cap=1.0)
    assert sdk.calls[0][1]["max_value"] == "250000"
    assert sdk.calls[0][1]["network_filter"] == "xrpl:1"
    assert sdk.calls[0][1]["headers"] == {"X-Agent-Name": "Claude"}


@pytest.mark.anyio
async def test_buying_again_is_free_and_returns_saved_copy(sdk):
    await buy()
    again = await buy()
    assert again["status"] == "already_purchased" and again["body"] == "text of cheap"
    assert len(sdk.calls) == 1
    assert await remaining() == "4.50"


@pytest.mark.anyio
async def test_refuses_above_callers_max_price(sdk):
    result = await buy(cap=0.4)
    assert result["status"] == "rejected" and not sdk.calls


@pytest.mark.anyio
@pytest.mark.parametrize("cap", [-1, float("nan"), float("inf")])
async def test_refuses_invalid_max_price(sdk, cap):
    async with Client(server.mcp) as client:
        result = await client.call_tool("buy_article", {"id": "cheap", "max_price_usd": cap})
    assert not sdk.calls
    assert result.is_error or json.loads(result.content[0].text)["status"] == "rejected"


@pytest.mark.anyio
async def test_refuses_above_remaining_budget(sdk, monkeypatch):
    monkeypatch.setenv("BUYER_BUDGET_USD", "0.4")
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
    assert len(asked) == 1 and "Title pricey" in asked[0] and "$2.00" in asked[0]


@pytest.mark.anyio
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "callback",
    [approve_with("decline"), approve_with("cancel"), approve_with("accept", approve=False)],
)
async def test_above_threshold_refused_without_approval(sdk, callback, mode):
    result = await buy("pricey", 3, callback, mode)
    assert result["status"] == "rejected" and not sdk.calls
    assert await remaining() == "5.00"


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
        assert set(tools["buy_article"].input_schema["properties"]) == {"id", "max_price_usd"}
        await client.call_tool("buy_article", {"id": "pricey", "max_price_usd": 3, "approval": {"approve": True}})
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
    assert "$2.00" in asked[0] and "$2.50" in asked[1]
    assert result["status"] == "purchased"
    assert sdk.calls[0][1]["max_value"] == "1250000"


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
    assert await remaining() == "4.50"
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
    assert await remaining() == "4.50"


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
    assert await remaining() == "5.00"
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
    assert await remaining() == "4.50"
    assert (await buy())["status"] == "paid_without_content"
    assert len(sdk.calls) == 1


@pytest.mark.anyio
async def test_no_payment_requested_is_not_charged(sdk):
    sdk.outcome = lambda url: SimpleNamespace(
        status="success", transaction=None, reason=None, response=SimpleNamespace(status_code=403)
    )
    result = await buy()
    assert result["status"] == "payment_failed" and "HTTP 403" in result["reason"]
    assert await remaining() == "5.00"


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
        result = await client.call_tool("buy_article", {"id": "cheap", "max_price_usd": 1})
    assert result.is_error and not sdk.calls


@pytest.mark.anyio
async def test_parallel_buys_cannot_overspend(sdk, monkeypatch):
    """Both pass the first budget check. Only one may survive the check under the lock."""
    monkeypatch.setenv("BUYER_BUDGET_USD", "3")
    monkeypatch.setenv("BUYER_CONFIRM_ABOVE_USD", "10")
    sdk.before_pay = lambda: time.sleep(0.1)
    results = await asyncio.gather(buy("big", 3), buy("other", 3))
    assert sorted(r["status"] for r in results) == ["purchased", "rejected"]
    assert len(sdk.calls) == 1
    assert await remaining() == "0.00"


def test_selector_refuses_wrong_recipient_or_asset():
    a = article()
    select = server.payment_selector(a)
    good = {"scheme": "exact", "network": "xrpl:1", "amount": "500000", "asset": "XRP", "payTo": WRITER}
    assert select([good], "xrpl:1", "exact", "500000") == good
    for bad in ({**good, "payTo": "rEvil"}, {**good, "asset": "USD"}, {**good, "amount": "500001"}):
        with pytest.raises(ValueError):
            select([bad], "xrpl:1", "exact", "500000")


def stripe_receipt(a, ref="credit_1", amount=None):
    payload = {"rail": "stripe", "article_id": a["id"], "stripe_ref": ref, "amount_usd": amount or server.to_usd(a["price_usd_micros"])}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"payload": payload, "signature": base64.b64encode(KEY.sign(canonical).signature).decode(), "alg": "ed25519"}


@pytest.fixture
def stripe_api(sdk, monkeypatch):
    """Stands in for GET /articles/{id} with an agent key. sdk is there to catch any XRPL payment."""
    monkeypatch.setenv("BUYER_RAIL", "stripe")
    fake = SimpleNamespace(calls=[], answer=None)

    def read(url, headers):
        fake.calls.append((url, headers))
        if fake.answer:
            return fake.answer(url)
        a = next(a for a in CATALOG if a["url"] == url)
        return httpx.Response(200, json={"body": f"text of {a['id']}", "receipt": stripe_receipt(a)})

    monkeypatch.setattr(server, "stripe_read", read)
    monkeypatch.setattr(server, "fetch_credit", lambda cfg, key: "9.60")
    return fake


@pytest.mark.anyio
async def test_stripe_rail_buys_from_credit_and_never_touches_the_wallet(sdk, stripe_api):
    result = await buy()
    assert result["status"] == "purchased" and result["rail"] == "stripe"
    assert result["body"] == "text of cheap" and result["receipt_verified"] is True
    assert result["stripe_ref"] == "credit_1" and result["explorer"] is None and "tx_hash" not in result
    assert not sdk.calls
    assert await remaining() == "4.50"
    _, headers = stripe_api.calls[0]
    assert headers["Authorization"] == f"Bearer {API_KEY}" and headers["X-Max-Price-Usd"] == "0.50"
    assert headers["X-Agent-Name"] == "Claude"


@pytest.mark.anyio
async def test_stripe_budget_shows_credit_not_the_wallet(stripe_api):
    budget = await call("get_budget")
    assert budget["rail"] == "stripe" and budget["prepaid_credit_usd"] == "9.60" and "wallet_address" not in budget


@pytest.mark.anyio
async def test_one_budget_covers_both_rails(sdk, stripe_api, monkeypatch):
    await buy()
    monkeypatch.setenv("BUYER_RAIL", "xrpl")
    CATALOG.append(article("second", 1))
    assert (await buy("second", 1))["rail"] == "xrpl"
    assert await remaining() == "3.50"
    assert len(stripe_api.calls) == 1 and len(sdk.calls) == 1


@pytest.mark.anyio
async def test_article_owned_on_one_rail_is_free_on_the_other(sdk, stripe_api, monkeypatch):
    await buy()
    monkeypatch.setenv("BUYER_RAIL", "xrpl")
    assert (await buy())["status"] == "already_purchased" and not sdk.calls


@pytest.mark.anyio
@pytest.mark.parametrize("mode", MODES)
async def test_stripe_rail_also_needs_approval_above_the_threshold(stripe_api, mode):
    result = await buy("pricey", 3, mode=mode)
    assert result["status"] == "rejected" and "human approval" in result["reason"] and not stripe_api.calls
    approved = await buy("pricey", 3, approve_with(), mode)
    assert approved["status"] == "purchased" and len(stripe_api.calls) == 1


@pytest.mark.anyio
async def test_stripe_rail_refuses_above_budget_and_cap(stripe_api, monkeypatch):
    assert (await buy(cap=0.4))["status"] == "rejected"
    monkeypatch.setenv("BUYER_BUDGET_USD", "0.4")
    assert "budget remains" in (await buy())["reason"]
    assert not stripe_api.calls


@pytest.mark.anyio
async def test_low_credit_releases_the_budget_and_says_to_top_up(stripe_api):
    stripe_api.answer = lambda url: httpx.Response(
        402, json={"error": "insufficient_credit", "credit_usd": "0.10", "price_usd": "0.50"}
    )
    result = await buy()
    assert result["status"] == "payment_failed" and result["paid"] is False and "make topup" in result["reason"]
    assert await remaining() == "5.00"


@pytest.mark.anyio
@pytest.mark.parametrize("code", [401, 403, 404, 409])
async def test_stripe_refusals_release_the_budget_and_allow_retry(stripe_api, code):
    stripe_api.answer = lambda url: httpx.Response(code, json={"error": "refused"})
    assert (await buy())["status"] == "payment_failed"
    assert await remaining() == "5.00"
    stripe_api.answer = None
    assert (await buy())["status"] == "purchased"


@pytest.mark.anyio
async def test_stripe_server_error_holds_budget_and_blocks_retry(stripe_api):
    stripe_api.answer = lambda url: httpx.Response(500)
    assert (await buy())["status"] == "outcome_unknown"
    assert await remaining() == "4.50"
    assert (await buy())["status"] == "rejected" and len(stripe_api.calls) == 1


@pytest.mark.anyio
async def test_stripe_timeout_holds_budget_because_the_debit_may_have_happened(stripe_api):
    def slow(url):
        raise httpx.ReadTimeout("slow")

    stripe_api.answer = slow
    assert (await buy())["status"] == "outcome_unknown"
    assert await remaining() == "4.50"


@pytest.mark.anyio
async def test_stripe_connection_refused_releases_budget(stripe_api):
    def down(url):
        raise httpx.ConnectError("refused")

    stripe_api.answer = down
    assert (await buy())["status"] == "payment_failed"
    assert await remaining() == "5.00"


@pytest.mark.anyio
async def test_stripe_unreadable_success_is_charged_and_not_rebought(stripe_api):
    stripe_api.answer = lambda url: httpx.Response(200, content=b"not json")
    assert (await buy())["status"] == "paid_without_content"
    assert await remaining() == "4.50"
    assert (await buy())["status"] == "paid_without_content" and len(stripe_api.calls) == 1


@pytest.mark.anyio
async def test_stripe_forged_receipt_is_flagged(stripe_api, monkeypatch):
    monkeypatch.setattr(server, "fetch_receipt_key", lambda cfg: SigningKey.generate().verify_key.encode(HexEncoder).decode())
    assert (await buy())["receipt_verified"] is False


def test_stripe_receipt_for_another_read_or_price_is_rejected():
    a = article()
    key = KEY.verify_key.encode(HexEncoder).decode()
    assert server.receipt_is_valid(stripe_receipt(a), key, a, "credit_1", "stripe") is True
    assert server.receipt_is_valid(stripe_receipt(a, ref="credit_2"), key, a, "credit_1", "stripe") is False
    assert server.receipt_is_valid(stripe_receipt(a, amount="9.99"), key, a, "credit_1", "stripe") is False
    assert server.receipt_is_valid(signed_receipt(a), key, a, TX, "stripe") is False


@pytest.mark.anyio
async def test_missing_agent_key_is_refused_without_a_request(stripe_api, monkeypatch):
    monkeypatch.setenv("BUYER_STRIPE_API_KEY", "")
    assert "make agent" in (await buy())["reason"] and not stripe_api.calls


def test_rail_file_wins_over_the_process_and_switches_live(tmp_path, monkeypatch):
    env_file = tmp_path / "x.env"
    monkeypatch.setenv("BUYER_ENV_FILE", str(env_file))
    monkeypatch.setenv("BUYER_RAIL", "xrpl")
    assert server.current_rail() == "xrpl"
    env_file.write_text("BUYER_RAIL=stripe\n")
    assert server.current_rail() == "stripe"
    env_file.write_text("BUYER_RAIL=paypal\n")
    with pytest.raises(ValueError):
        server.current_rail()


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
