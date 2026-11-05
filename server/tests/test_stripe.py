"""The Stripe rail, with Stripe itself faked. No network, no real charges."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import stripe
from fastapi.testclient import TestClient
from test_api import BODY, MockFacilitator, pay, upload

from app.main import create_app
from app.payouts import pay_writers
from app.receipts import verify
from app.stripe_gateway import StripeGateway, require_test_key


class FakeStripe:
    webhook_secret = "whsec_test"

    def __init__(self):
        self.sessions = {}
        self.transfers = []
        self.fail_transfer = None
        self.accounts = {}

    def create_checkout(self, *, agent_id, cents, success_url, cancel_url):
        session_id = f"cs_test_{len(self.sessions)}"
        self.sessions[session_id] = {
            "id": session_id, "payment_status": "unpaid", "amount_total": cents,
            "metadata": {"agent_id": agent_id}, "livemode": False,
        }
        self.success_url = success_url
        return f"https://checkout.test/{session_id}"

    def retrieve_checkout(self, session_id):
        if session_id not in self.sessions:
            raise stripe.InvalidRequestError("no such session", "id")
        return self.sessions[session_id]

    def checkout_from_webhook(self, payload, signature):
        event = stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
        if event.type != "checkout.session.completed":
            return None
        return self.retrieve_checkout(event.data.object["id"])

    def create_connected_account(self, email):
        account = f"acct_{len(self.accounts)}"
        self.accounts[account] = {"email": email, "details_submitted": False, "payouts_enabled": False}
        return account

    def onboarding_link(self, account_id, *, refresh_url, return_url):
        return f"https://connect.test/{account_id}?return={return_url}"

    def account_status(self, account_id):
        a = self.accounts[account_id]
        return {"details_submitted": a["details_submitted"], "payouts_enabled": a["payouts_enabled"]}

    def create_transfer(self, *, cents, destination, idempotency_key):
        if self.fail_transfer:
            raise self.fail_transfer
        for t in self.transfers:
            if t["key"] == idempotency_key:
                return t["id"]
        transfer = {"id": f"tr_{len(self.transfers)}", "cents": cents, "destination": destination, "key": idempotency_key}
        self.transfers.append(transfer)
        return transfer["id"]


@pytest.fixture
def gateway():
    return FakeStripe()


@pytest.fixture
def facilitator():
    return MockFacilitator()


@pytest.fixture
def client(database, tmp_path, gateway, facilitator):
    empty = tmp_path / "empty"
    empty.mkdir()
    app = create_app(facilitator.client, database=database, content_dir=empty, stripe_gateway=gateway)
    yield TestClient(app)
    app.state.db.close()


def signed(payload: bytes, secret="whsec_test"):
    stamp = int(time.time())
    signature = stripe.WebhookSignature._compute_signature(f"{stamp}.{payload.decode()}", secret)
    return f"t={stamp},v1={signature}"


def webhook_body(session_id, type="checkout.session.completed"):
    return json.dumps({"id": "evt_1", "object": "event", "type": type, "data": {"object": {"id": session_id, "object": "checkout.session"}}}).encode()


def new_agent(client, name="Claude", credit="10"):
    created = client.post("/agents", json={"name": name}).json()
    headers = {"Authorization": f"Bearer {created['api_key']}"}
    if credit:
        client.app.state.db.add_credit(created["id"], int(float(credit) * 1_000_000), f"seed-{created['id']}")
    return created, headers


def piece(client, **fields):
    return upload(client, price_usd="0.40", **fields).json()["id"]


def test_live_keys_are_refused():
    for key in ("sk_live_abc", "rk_live_abc", "", "pk_test_abc"):
        with pytest.raises(RuntimeError):
            require_test_key(key)
    assert require_test_key("sk_test_abc") == "sk_test_abc"


def test_agent_key_is_shown_once_and_only_its_hash_is_stored(client):
    created = client.post("/agents", json={"name": "Claude"}).json()
    assert created["api_key"].startswith("tg_test_")
    with client.app.state.db._conn() as c:
        row = dict(c.execute("SELECT * FROM agents").fetchone())
    assert created["api_key"] not in json.dumps(row)
    me = client.get("/agents/me", headers={"Authorization": f"Bearer {created['api_key']}"}).json()
    assert me == {"name": "Claude", "credit_usd": "0.00", "credit_usd_micros": 0}
    assert "api_key" not in me


def test_read_debits_credit_and_accrues_to_the_writer(client):
    article = piece(client)
    _, headers = new_agent(client)
    response = client.get(f"/articles/{article}", headers=headers)
    assert response.status_code == 200 and response.json()["body"] == BODY
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "9.60"
    dash = client.get("/me/dashboard").json()
    assert dash["balance_usd_micros"] == 400_000 and dash["totals"]["earned_usd_micros"] == 400_000
    assert dash["latest"]["rail"] == "stripe" and dash["latest"]["agent"] == "Claude"
    assert client.get("/catalog").json()["articles"][0]["reads"] == 1


def test_stripe_receipt_verifies_and_names_the_rail(client):
    article = piece(client)
    _, headers = new_agent(client)
    receipt = client.get(f"/articles/{article}", headers=headers).json()["receipt"]
    payload = receipt["payload"]
    assert payload["rail"] == "stripe" and payload["amount_usd"] == "0.40"
    assert payload["stripe_ref"].startswith("credit_") and "tx_hash" not in payload and "explorer" not in payload
    assert verify(receipt, client.get("/.well-known/tollgate-receipt-key").json()["public_key"])


def test_no_key_still_gets_x402_and_learns_about_credit(client):
    article = piece(client)
    response = client.get(f"/articles/{article}")
    assert response.status_code == 402 and BODY not in response.text
    data = response.json()
    assert all(a["scheme"] == "exact" for a in data["accepts"])
    assert data["alternatives"][0]["scheme"] == "stripe-credit" and data["alternatives"][0]["price_usd"] == "0.40"
    assert response.headers.get("PAYMENT-REQUIRED")


def test_alternatives_do_not_disturb_paying_with_xrpl(client, facilitator):
    article = piece(client)
    challenge = client.get(f"/articles/{article}").json()
    paid = pay(client, article, challenge=challenge)
    assert paid.status_code == 200 and paid.json()["receipt"]["payload"]["rail"] == "xrpl"
    assert client.get("/me/dashboard").json()["balance_usd_micros"] == 0


def test_without_stripe_configured_402_lists_only_x402(database, tmp_path, facilitator):
    empty = tmp_path / "e"
    empty.mkdir()
    app = create_app(facilitator.client, database=database, content_dir=empty)
    client = TestClient(app)
    assert "alternatives" not in client.get(f"/articles/{piece(client)}").json()
    app.state.db.close()


def test_bad_key_is_401_with_no_text(client):
    article = piece(client)
    response = client.get(f"/articles/{article}", headers={"Authorization": "Bearer tg_test_wrong"})
    assert response.status_code == 401 and BODY not in response.text


def test_low_credit_is_402_with_no_text_and_no_debit(client):
    article = piece(client)
    _, headers = new_agent(client, credit="0.39")
    response = client.get(f"/articles/{article}", headers=headers)
    assert response.status_code == 402 and BODY not in response.text
    assert response.json()["error"] == "insufficient_credit" and response.json()["credit_usd"] == "0.39"
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "0.39"
    assert client.get("/ledger").json()["purchases"] == []


def test_price_cap_header_refuses_a_higher_price(client):
    article = piece(client)
    _, headers = new_agent(client)
    above = client.get(f"/articles/{article}", headers={**headers, "X-Max-Price-Usd": "0.39"})
    assert above.status_code == 409 and BODY not in above.text
    assert client.get(f"/articles/{article}", headers={**headers, "X-Max-Price-Usd": "bad"}).status_code == 400
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "10.00"
    assert client.get(f"/articles/{article}", headers={**headers, "X-Max-Price-Usd": "0.40"}).status_code == 200


def test_allowed_agents_uses_the_account_name_not_the_header(client):
    article = upload(client, price_usd="0.40", allowed_agents="Claude").json()["id"]
    _, muse = new_agent(client, name="Muse")
    spoofed = client.get(f"/articles/{article}", headers={**muse, "X-Agent-Name": "Claude"})
    assert spoofed.status_code == 403 and BODY not in spoofed.text
    assert client.get("/agents/me", headers=muse).json()["credit_usd"] == "10.00"
    _, claude = new_agent(client, name="Claude")
    assert client.get(f"/articles/{article}", headers=claude).status_code == 200


def test_unknown_article_is_404_without_a_debit(client):
    _, headers = new_agent(client)
    assert client.get("/articles/nope", headers=headers).status_code == 404
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "10.00"


def test_parallel_reads_cannot_overdraw(client):
    article = piece(client)
    _, headers = new_agent(client, credit="0.40")
    with ThreadPoolExecutor(4) as pool:
        codes = list(pool.map(lambda _: client.get(f"/articles/{article}", headers=headers).status_code, range(4)))
    assert sorted(codes) == [200, 402, 402, 402]
    assert client.get("/agents/me", headers=headers).json()["credit_usd_micros"] == 0


def test_debit_loss_at_the_last_moment_returns_no_text(client):
    """The balance check passes, then another read takes the credit before the debit."""
    article = piece(client)
    created, headers = new_agent(client, credit="0.40")
    db = client.app.state.db
    original = db.record_purchase

    def race(**kwargs):
        with db._conn() as c:
            c.execute("UPDATE agents SET credit_usd_micros = 0 WHERE id = ?", (created["id"],))
        return original(**kwargs)

    db.record_purchase = race
    response = client.get(f"/articles/{article}", headers=headers)
    assert response.status_code == 402 and BODY not in response.text
    assert client.get("/ledger").json()["purchases"] == []


@pytest.mark.parametrize("amount", ["0.50", "501", "abc", "10.001"])
def test_topup_limits(client, amount):
    _, headers = new_agent(client, credit=None)
    assert client.post("/agents/me/topups", headers=headers, json={"amount_usd": amount}).status_code == 422


def test_topup_needs_an_agent_key(client):
    assert client.post("/agents/me/topups", json={"amount_usd": "10"}).status_code == 401


def checkout(client, gateway, headers, amount="10"):
    url = client.post("/agents/me/topups", headers=headers, json={"amount_usd": amount}).json()["checkout_url"]
    return url.rsplit("/", 1)[1]


def test_webhook_credits_a_paid_session_once(client, gateway):
    _, headers = new_agent(client, credit=None)
    session = checkout(client, gateway, headers)
    gateway.sessions[session]["payment_status"] = "paid"
    body = webhook_body(session)
    for _ in range(2):
        assert client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": signed(body)}).status_code == 200
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "10.00"


def test_webhook_and_success_page_together_credit_once(client, gateway):
    _, headers = new_agent(client, credit=None)
    session = checkout(client, gateway, headers)
    gateway.sessions[session]["payment_status"] = "paid"
    assert client.get("/agents/topup/done", params={"session_id": session}).status_code == 200
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "10.00"
    body = webhook_body(session)
    client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": signed(body)})
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "10.00"


def test_success_url_carries_stripes_session_placeholder(client, gateway):
    _, headers = new_agent(client, credit=None)
    checkout(client, gateway, headers)
    assert gateway.success_url.endswith("/agents/topup/done?session_id={CHECKOUT_SESSION_ID}")


def test_unpaid_session_adds_nothing(client, gateway):
    _, headers = new_agent(client, credit=None)
    session = checkout(client, gateway, headers)
    client.get("/agents/topup/done", params={"session_id": session})
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "0.00"


def test_live_mode_session_adds_nothing(client, gateway):
    _, headers = new_agent(client, credit=None)
    session = checkout(client, gateway, headers)
    gateway.sessions[session].update(payment_status="paid", livemode=True)
    client.get("/agents/topup/done", params={"session_id": session})
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "0.00"


def test_unknown_session_is_404(client):
    assert client.get("/agents/topup/done", params={"session_id": "cs_test_nope"}).status_code == 404


@pytest.mark.parametrize("signature", ["t=1,v1=bad", None])
def test_webhook_refuses_a_bad_signature(client, gateway, signature):
    _, headers = new_agent(client, credit=None)
    session = checkout(client, gateway, headers)
    gateway.sessions[session]["payment_status"] = "paid"
    sent = {"Stripe-Signature": signature} if signature else {}
    assert client.post("/webhooks/stripe", content=webhook_body(session), headers=sent).status_code == 400
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "0.00"


def test_webhook_ignores_other_events(client, gateway):
    body = webhook_body("cs_test_x", type="payment_intent.created")
    assert client.post("/webhooks/stripe", content=body, headers={"Stripe-Signature": signed(body)}).status_code == 200


def test_gateway_verifies_real_signatures():
    gateway = StripeGateway("sk_test_x", "whsec_test")
    with pytest.raises(stripe.SignatureVerificationError):
        gateway.checkout_from_webhook(webhook_body("cs"), "t=1,v1=bad")
    assert gateway.checkout_from_webhook(*(lambda b: (b, signed(b)))(webhook_body("cs", type="other"))) is None


def test_connect_onboarding_reuses_one_account_and_reports_status(client, gateway):
    assert client.get("/me/payout").json()["stripe"] == {"available": True, "connected": False, "payouts_enabled": False}
    first = client.post("/me/stripe/onboarding").json()["url"]
    client.post("/me/stripe/onboarding")
    assert len(gateway.accounts) == 1 and "/onboarding/payout?stripe=return" in first
    assert client.post("/me/stripe/refresh").json()["connected"] is False
    gateway.accounts["acct_0"].update(details_submitted=True, payouts_enabled=True)
    assert client.post("/me/stripe/refresh").json() == {"available": True, "connected": True, "payouts_enabled": True}
    assert client.get("/me/dashboard").json()["payout"]["stripe"]["connected"] is True
    assert "stripe_account_id" not in client.get("/me/payout").json()


def test_stripe_routes_say_so_when_not_configured(database, tmp_path, facilitator):
    empty = tmp_path / "e"
    empty.mkdir()
    app = create_app(facilitator.client, database=database, content_dir=empty)
    client = TestClient(app)
    assert client.post("/me/stripe/onboarding").status_code == 503
    assert client.get("/me/payout").json()["stripe"]["available"] is False
    app.state.db.close()


def accrue(client, reads=1):
    article = piece(client)
    _, headers = new_agent(client)
    for _ in range(reads):
        client.get(f"/articles/{article}", headers=headers)


def test_payout_transfers_the_balance_once(client, gateway):
    accrue(client, 2)
    client.post("/me/stripe/onboarding")
    db = client.app.state.db
    first = pay_writers(db, gateway)
    assert first[0]["status"] == "paid" and first[0]["cents"] == 80
    assert gateway.transfers[0]["destination"] == "acct_0" and gateway.transfers[0]["cents"] == 80
    assert client.get("/me/dashboard").json()["balance_usd_micros"] == 0
    assert pay_writers(db, gateway) == []
    assert len(gateway.transfers) == 1


def test_payout_keeps_the_sub_cent_remainder(client, gateway):
    article = upload(client, price_usd="0.405").json()["id"]
    _, headers = new_agent(client)
    client.get(f"/articles/{article}", headers=headers)
    client.post("/me/stripe/onboarding")
    assert pay_writers(client.app.state.db, gateway)[0]["cents"] == 40
    assert client.get("/me/dashboard").json()["balance_usd_micros"] == 5_000


def test_payout_waits_for_a_connected_account(client, gateway):
    accrue(client)
    assert pay_writers(client.app.state.db, gateway)[0]["status"] == "no_stripe_account"
    assert not gateway.transfers and client.get("/me/dashboard").json()["balance_usd_micros"] == 400_000


def test_failed_transfer_keeps_the_balance(client, gateway):
    accrue(client)
    client.post("/me/stripe/onboarding")
    gateway.fail_transfer = stripe.InvalidRequestError("insufficient funds", None, code="balance_insufficient")
    assert pay_writers(client.app.state.db, gateway)[0]["status"] == "failed"
    assert client.get("/me/dashboard").json()["balance_usd_micros"] == 400_000


def test_crash_before_recording_reuses_the_same_transfer(client, gateway):
    accrue(client)
    client.post("/me/stripe/onboarding")
    db = client.app.state.db
    original = db.record_transfer
    db.record_transfer = lambda *a: (_ for _ in ()).throw(RuntimeError("crash"))
    with pytest.raises(RuntimeError):
        pay_writers(db, gateway)
    db.record_transfer = original
    pay_writers(db, gateway)
    assert len(gateway.transfers) == 1
    assert client.get("/me/dashboard").json()["balance_usd_micros"] == 0


def test_treasury_xrpl_read_also_accrues_for_payout(client, gateway):
    article = piece(client)
    client.app.state.db.set_payout("demo", payout_method="xrpl", xrpl_address=None)
    pay(client, article)
    assert client.get("/me/dashboard").json()["balance_usd_micros"] == 400_000


def test_reset_keeps_agent_keys_and_zeroes_credit(client):
    _, headers = new_agent(client)
    client.app.state.db.reset()
    assert client.get("/agents/me", headers=headers).json()["credit_usd"] == "0.00"
    assert client.get("/ledger").json()["purchases"] == []


def test_llms_txt_covers_both_rails(client):
    text = client.get("/llms.txt").text
    for needle in ("stripe-credit", "Authorization: Bearer", "/agents/me/topups", "alternatives", "X-Max-Price-Usd", "PAYMENT-SIGNATURE"):
        assert needle in text
