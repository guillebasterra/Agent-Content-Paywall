"""The Base rail: x402 v2 on eip155:8453, USDC to the treasury, with a fake facilitator.

No network and no funds. The buyer in the end-to-end tests is the official x402 Python client
with a throwaway key, so the challenge is checked by the same parser real agents use.
"""

import asyncio
import base64
import json

import httpx
import pytest
from eth_account import Account
from fastapi.testclient import TestClient
from x402 import x402Client
from x402.http import decode_payment_required_header, decode_payment_response_header
from x402.http.clients.httpx import x402AsyncTransport
from x402.mechanisms.evm.exact import register_exact_evm_client
from x402.schemas import SettleResponse, SupportedKind, SupportedResponse, VerifyResponse

from app import config
from app.main import create_app
from app.receipts import verify

TREASURY = config.TREASURY_BASE_ADDRESS
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE = "eip155:8453"
BODY = " ".join(f"word{i}" for i in range(200))


class FakeFacilitator:
    """Stands in for the CDP facilitator. Checks the authorization against the requirements, then settles."""

    def __init__(self, *, settle_ok=True):
        self.verified, self.settled = [], []
        self.settle_ok = settle_ok

    def get_supported(self):
        return SupportedResponse(kinds=[SupportedKind(x402_version=2, scheme="exact", network=BASE)])

    async def verify(self, payload, requirements, *args, **kwargs):
        self.verified.append((payload, requirements))
        auth = payload.payload["authorization"]
        ok = auth["to"].lower() == requirements.pay_to.lower() and str(auth["value"]) == requirements.amount
        return VerifyResponse(is_valid=ok, invalid_reason=None if ok else "mismatch", payer=auth["from"])

    async def settle(self, payload, requirements, *args, **kwargs):
        if not self.settle_ok:
            return SettleResponse(success=False, error_reason="insufficient_funds", transaction="", network=BASE)
        self.settled.append((payload, requirements))
        return SettleResponse(
            success=True,
            transaction=f"0x{len(self.settled):064x}",
            network=BASE,
            payer=payload.payload["authorization"]["from"],
        )


@pytest.fixture
def base_rail(monkeypatch):
    monkeypatch.setattr(config, "PAYMENT_RAIL", "base")
    monkeypatch.setattr(config, "PUBLIC_URL", "https://tollgate.example")


@pytest.fixture
def fake():
    return FakeFacilitator()


@pytest.fixture
def content(tmp_path):
    folder = tmp_path / "content"
    folder.mkdir()
    (folder / "seeded.md").write_text(
        f"---\nid: seeded\ntitle: Seeded piece\nabstract: Free.\nprice_usd: 0.40\nkeywords: [frost]\n---\n{BODY}"
    )
    return folder


@pytest.fixture
def app(base_rail, fake, content, database):
    app = create_app(base_facilitator=fake, database=database, content_dir=content)
    yield app
    app.state.db.close()


@pytest.fixture
def client(app):
    return TestClient(app)


def buyer():
    """The official x402 client with a fresh, unfunded key."""
    return register_exact_evm_client(x402Client(), Account.create())


def buy(app, path="/articles/seeded", headers=None):
    async def run():
        transport = x402AsyncTransport(buyer(), httpx.ASGITransport(app=app))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            return await http.get(path, headers=headers or {"X-Agent-Name": "Claude"})

    return asyncio.run(run())


def challenge(response):
    return decode_payment_required_header(response.headers["PAYMENT-REQUIRED"])


def test_unpaid_read_is_a_v2_challenge_for_base_usdc_to_the_treasury(client):
    response = client.get("/articles/seeded")
    assert response.status_code == 402
    required = challenge(response)
    assert required.x402_version == 2
    [option] = required.accepts
    assert option.scheme == "exact" and option.network == BASE
    assert option.pay_to == TREASURY and option.asset == USDC
    assert option.amount == "400000"  # $0.40 in USDC atomic units
    assert option.extra["name"] == "USD Coin" and option.extra["version"] == "2"
    assert required.resource.url == "https://tollgate.example/articles/seeded"
    body = response.json()
    assert body["article"]["title"] == "Seeded piece" and body["article"]["price_usd"] == "0.40"
    assert "word199" not in response.text


def test_challenge_is_the_wire_format_any_x402_client_reads(client):
    raw = json.loads(base64.b64decode(client.get("/articles/seeded").headers["PAYMENT-REQUIRED"]))
    assert raw["x402Version"] == 2
    option = raw["accepts"][0]
    assert {k: option[k] for k in ("scheme", "network", "amount", "asset", "payTo")} == {
        "scheme": "exact", "network": BASE, "amount": "400000", "asset": USDC, "payTo": TREASURY,
    }
    assert option["maxTimeoutSeconds"] == 300


def test_each_article_is_charged_its_own_price(client):
    client.post("/articles", data={"title": "Dear", "price_usd": "2.5"}, files={"file": ("a.md", BODY.encode())})
    client.post("/articles", data={"title": "Tiny", "price_usd": "0.000001"}, files={"file": ("a.md", BODY.encode())})
    assert challenge(client.get("/articles/dear")).accepts[0].amount == "2500000"
    assert challenge(client.get("/articles/tiny")).accepts[0].amount == "1"


def test_official_client_pays_and_gets_body_and_verifiable_receipt(app, client, fake):
    response = buy(app)
    assert response.status_code == 200
    data = response.json()
    assert data["body"] == BODY
    tx = f"0x{1:064x}"
    settlement = decode_payment_response_header(response.headers["PAYMENT-RESPONSE"])
    assert settlement.success and settlement.transaction == tx

    receipt = data["receipt"]
    assert verify(receipt, client.get("/.well-known/tollgate-receipt-key").json()["public_key"])
    payload = receipt["payload"]
    assert payload["rail"] == "base" and payload["network"] == BASE
    assert payload["tx_hash"] == tx and payload["explorer"] == f"https://basescan.org/tx/{tx}"
    assert payload["amount_usd"] == "0.40" and payload["amount_atomic"] == "400000" and payload["asset"] == "USDC"
    assert payload["pay_to"] == TREASURY and payload["agent"] == "Claude"
    assert payload["payer"] == fake.settled[0][0].payload["authorization"]["from"]
    assert payload["license"] == "ai-input" and payload["content_hash"].startswith("sha256:")
    assert len(fake.verified) == 1 and len(fake.settled) == 1


def test_purchase_credits_the_writer_in_the_ledger(app, client):
    buy(app)
    db = app.state.db
    assert db.writer_balance("demo") == 400_000
    dashboard = client.get("/me/dashboard").json()
    assert dashboard["balance_usd_micros"] == 400_000
    assert dashboard["totals"]["reads"] == 1 and dashboard["totals"]["earned_usd_micros"] == 400_000
    assert dashboard["latest"]["rail"] == "base" and dashboard["latest"]["agent"] == "Claude"
    assert dashboard["latest"]["tx_hash"] == f"0x{1:064x}"
    assert dashboard["payment"]["explorer_tx"] == "https://basescan.org/tx/"
    assert dashboard["by_agent"] == [{"name": "Claude", "reads": 1, "earned_usd_micros": 400_000}]
    purchase = client.get("/ledger").json()["purchases"][0]
    assert purchase["rail"] == "base" and purchase["amount_native"] == 400_000 and purchase["pay_to"] == TREASURY


def test_writer_needs_no_wallet(app, client):
    app.state.db.set_payout("demo", payout_method=None, xrpl_address=None)
    assert buy(app).status_code == 200
    assert client.get("/catalog").json()["articles"][0]["pay_to"] == TREASURY


def test_platform_fee_is_taken_from_the_writer_credit(base_rail, fake, content, database, monkeypatch):
    monkeypatch.setattr(config, "PLATFORM_FEE_BPS", 1_000)  # 10%
    app = create_app(base_facilitator=fake, database=database, content_dir=content)
    data = buy(app).json()
    assert data["receipt"]["payload"]["amount_usd"] == "0.40"
    assert data["receipt"]["payload"]["writer_credit_usd"] == "0.36"
    db = app.state.db
    assert db.writer_balance("demo") == 360_000
    dashboard = TestClient(app).get("/me/dashboard").json()
    assert dashboard["totals"]["earned_usd_micros"] == 360_000
    assert TestClient(app).get("/catalog").json()["articles"][0]["earned_usd"] == "0.36"
    db.close()


def test_agent_falls_back_to_user_agent(app):
    receipt = buy(app, headers={"User-Agent": "Claude-User/1.0"}).json()["receipt"]
    assert receipt["payload"]["agent"] == "Claude"


@pytest.mark.parametrize("path", ["/catalog", "/catalog/seeded", "/llms.txt", "/health", "/.well-known/tollgate-receipt-key", "/ledger"])
def test_everything_else_is_free(client, fake, path):
    assert client.get(path).status_code == 200
    assert not fake.verified


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_only_get_is_paid(client, fake, method):
    response = getattr(client, method)("/articles/seeded")
    assert response.status_code == 405 and "word199" not in response.text and not fake.verified


def test_unknown_article_is_404_and_costs_nothing(app, client, fake):
    assert client.get("/articles/nope").status_code == 404
    assert buy(app, "/articles/nope").status_code == 404
    assert not fake.verified and not fake.settled


def test_disallowed_agent_is_403_before_any_payment(app, client, fake):
    client.post(
        "/articles",
        data={"title": "Only Muse", "price_usd": "1", "allowed_agents": "Muse"},
        files={"file": ("a.md", BODY.encode())},
    )
    response = buy(app, "/articles/only-muse")
    assert response.status_code == 403 and not fake.verified


def test_failed_settlement_serves_nothing_and_records_nothing(base_rail, content, database):
    app = create_app(base_facilitator=FakeFacilitator(settle_ok=False), database=database, content_dir=content)
    response = buy(app)
    assert response.status_code == 402 and "word199" not in response.text
    assert app.state.db.recent() == [] and app.state.db.writer_balance("demo") == 0
    app.state.db.close()


def test_payment_for_a_cheap_article_cannot_buy_another(app, client, fake):
    client.post("/articles", data={"title": "Dear", "price_usd": "50"}, files={"file": ("a.md", BODY.encode())})

    async def run():
        http_client = x402Client()
        register_exact_evm_client(http_client, Account.create())
        from x402.http import x402HTTPClient

        wrapper = x402HTTPClient(http_client)
        cheap = client.get("/articles/seeded")
        required = wrapper.get_payment_required_response(lambda name: cheap.headers.get(name), cheap.json())
        payload = await http_client.create_payment_payload(required)
        return wrapper.encode_payment_signature_header(payload)

    headers = asyncio.run(run())
    response = client.get("/articles/dear", headers=headers)
    assert response.status_code == 402 and "word199" not in response.text
    assert not fake.settled


def test_llms_txt_describes_the_base_flow(client):
    text = client.get("/llms.txt").text
    for needle in (BASE, "USDC", TREASURY, "PAYMENT-REQUIRED", "PAYMENT-SIGNATURE", "make_http_request_with_x402",
                   "X-Agent-Name", "/.well-known/tollgate-receipt-key", "/catalog?q=", "ai-input", "/mcp"):
        assert needle in text


def test_health_and_payout_report_the_rail(client):
    assert client.get("/health").json()["payment"]["network"] == BASE
    payout = client.get("/me/payout").json()
    assert payout["payment"]["rail"] == "base" and payout["balance_usd_micros"] == 0


def test_demo_reset_keeps_writers_and_articles(app, client):
    buy(app)
    app.state.db.reset_sales()
    assert app.state.db.writer_balance("demo") == 0 and app.state.db.recent() == []
    article = client.get("/catalog").json()["articles"][0]
    assert article["id"] == "seeded" and article["reads"] == 0
    assert client.get("/me/payout").json()["name"]


def test_missing_treasury_refuses_to_start(base_rail, fake, content, database, monkeypatch):
    monkeypatch.setattr(config, "TREASURY_BASE_ADDRESS", "")
    with pytest.raises(RuntimeError, match="TREASURY_BASE_ADDRESS"):
        create_app(base_facilitator=fake, database=database, content_dir=content)


def test_repricing_changes_the_next_challenge(app, client):
    assert app.state.db.set_price(20_000) == 1
    assert challenge(client.get("/articles/seeded")).accepts[0].amount == "20000"
    assert app.state.db.set_price(30_000, "nope") == 0
