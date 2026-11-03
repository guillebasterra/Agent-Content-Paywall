"""API tests with a mocked facilitator: no network, no real payments."""

import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from x402_xrpl.facilitator import AsyncFacilitatorClient, FacilitatorClientOptions

from app import config
from app.main import create_app
from app.receipts import verify

WRITER = config.WRITER_ADDRESS
OTHER_ADDRESS = "rUfsN4hHr9w9mhcqiZAwzFfR4aBKU4KrYg"
PAYER = "rPayerPayerPayerPayerPayerPayerPay"
BODY = " ".join(f"word{i}" for i in range(200))


class MockFacilitator:
    def __init__(self):
        self.verified, self.settled = [], []
        self.count = 0
        self.client = AsyncFacilitatorClient(FacilitatorClientOptions(base_url="http://facilitator.test"))
        self.client._client = httpx.AsyncClient(
            base_url="http://facilitator.test", transport=httpx.MockTransport(self.handle)
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/verify":
            self.verified.append(body)
            return httpx.Response(200, json={"isValid": True, "payer": PAYER})
        self.settled.append(body)
        self.count += 1
        return httpx.Response(200, json={
            "success": True,
            "transaction": f"{self.count:064X}",
            "network": "xrpl:1",
            "payer": PAYER,
        })


@pytest.fixture
def facilitator():
    return MockFacilitator()


@pytest.fixture
def content(tmp_path):
    folder = tmp_path / "content"
    folder.mkdir()
    (folder / "README.md").write_text("not an article")
    (folder / "_template.md").write_text("---\ntitle: skip\n---\nskip")
    (folder / "seeded.md").write_text(
        f"---\nid: seeded\ntitle: Seeded piece\nabstract: Free abstract.\nprice_xrp: 0.5\ntags: [xrpl, reserves]\n---\n{BODY}"
    )
    return folder


@pytest.fixture
def client(facilitator, content, tmp_path):
    app = create_app(facilitator.client, db_path=tmp_path / "test.db", content_dir=content)
    return TestClient(app)


def pay(client, article_id, *, challenge=None, agent=None):
    """Answer a 402 the way a buyer would, with a mocked signature."""
    headers = {"X-Agent-Name": agent} if agent else {}
    challenge = challenge or client.get(f"/articles/{article_id}", headers=headers).json()
    accepted = challenge["accepts"][0]
    signature = base64.b64encode(json.dumps({
        "x402Version": 2,
        "accepted": accepted,
        "payload": {"signedTxBlob": "00", "invoiceId": accepted["extra"]["invoiceId"]},
    }).encode()).decode()
    return client.get(f"/articles/{article_id}", headers={**headers, "PAYMENT-SIGNATURE": signature})


def upload(client, *, name="piece.md", body=BODY, **fields):
    data = {"title": "A new piece", "price_xrp": "1.25", **fields}
    return client.post("/articles", data=data, files={"file": (name, body.encode())})


def test_seeds_from_content_and_assigns_demo_writer(client):
    items = client.get("/catalog").json()["articles"]
    assert [a["id"] for a in items] == ["seeded"]
    assert items[0]["author"] == "Guillermo Basterra"
    assert items[0]["pay_to"] == WRITER
    assert items[0]["keywords"] == ["xrpl", "reserves"]


def test_restart_keeps_data_and_does_not_reseed_over_it(facilitator, content, tmp_path):
    path = tmp_path / "test.db"
    first = TestClient(create_app(facilitator.client, db_path=path, content_dir=content))
    first.put("/me/payout", json={"payout_method": "xrpl", "xrpl_address": OTHER_ADDRESS})
    upload(first)
    second = TestClient(create_app(facilitator.client, db_path=path, content_dir=content))
    assert second.get("/me/payout").json()["xrpl_address"] == OTHER_ADDRESS
    assert len(second.get("/catalog").json()["articles"]) == 2


def test_catalog_never_exposes_the_body(client):
    assert "word199" not in client.get("/catalog").text


def test_unpaid_request_gets_402_with_price_recipient_and_source_tag(client):
    response = client.get("/articles/seeded")
    assert response.status_code == 402
    accepted = response.json()["accepts"][0]
    assert accepted["amount"] == "500000"
    assert accepted["payTo"] == WRITER
    assert accepted["extra"]["sourceTag"] == 804681468
    assert "word199" not in response.text


def test_paid_request_returns_body_and_verifiable_receipt(client, facilitator):
    response = pay(client, "seeded")
    assert response.status_code == 200
    data = response.json()
    assert data["body"] == BODY
    payload = data["receipt"]["payload"]
    assert payload["tx_hash"] == f"{1:064X}" and payload["price_drops"] == 500000 and payload["pay_to"] == WRITER
    key = client.get("/.well-known/tollgate-receipt-key").json()["public_key"]
    assert verify(data["receipt"], key)
    assert len(facilitator.settled) == 1
    assert client.get("/ledger").json()["purchases"][0]["article_id"] == "seeded"


def test_uploaded_article_is_paywalled_without_restart(client):
    created = upload(client)
    assert created.status_code == 201
    article_id = created.json()["id"]
    assert article_id == "a-new-piece"
    challenge = client.get(f"/articles/{article_id}")
    assert challenge.status_code == 402
    assert challenge.json()["accepts"][0]["amount"] == "1250000"
    paid = pay(client, article_id, challenge=challenge.json())
    assert paid.status_code == 200 and paid.json()["body"] == BODY


def test_invoice_for_a_cheap_article_cannot_buy_another(client, facilitator):
    upload(client, title="Expensive", price_xrp="50")
    cheap = client.get("/articles/seeded").json()
    response = pay(client, "expensive", challenge=cheap)
    assert response.status_code != 200
    assert "word199" not in response.text
    assert not facilitator.settled


def test_invoice_cannot_be_used_twice(client, facilitator):
    challenge = client.get("/articles/seeded").json()
    assert pay(client, "seeded", challenge=challenge).status_code == 200
    second = pay(client, "seeded", challenge=challenge)
    assert second.status_code != 200 and "word199" not in second.text
    assert len(facilitator.settled) == 1


def test_changed_amount_in_the_signed_payment_is_refused(client, facilitator):
    challenge = client.get("/articles/seeded").json()
    challenge["accepts"][0]["amount"] = "1"
    response = pay(client, "seeded", challenge=challenge)
    assert response.status_code == 402 and not facilitator.settled


def test_receipt_records_the_address_the_buyer_paid(client):
    challenge = client.get("/articles/seeded").json()
    client.put("/me/payout", json={"payout_method": "xrpl", "xrpl_address": OTHER_ADDRESS})
    paid = pay(client, "seeded", challenge=challenge)
    assert paid.json()["receipt"]["payload"]["pay_to"] == WRITER
    assert client.get("/articles/seeded").json()["accepts"][0]["payTo"] == OTHER_ADDRESS


@pytest.mark.parametrize("method", ["post", "put", "delete", "head"])
def test_other_methods_neither_charge_nor_return_the_body(client, facilitator, method):
    response = getattr(client, method)("/articles/seeded")
    assert response.status_code == 405 and "word199" not in response.text and not facilitator.settled


def test_unknown_article_is_404_without_a_charge(client):
    assert client.get("/articles/nope").status_code == 404


def test_writer_without_address_is_not_served_free(client):
    client.app.state.db.set_payout("demo", payout_method="xrpl", xrpl_address=None)
    response = client.get("/articles/seeded")
    assert response.status_code == 503 and "word199" not in response.text


def test_agent_name_is_recorded_and_defaults_to_unknown(client):
    pay(client, "seeded", agent="Claude")
    pay(client, "seeded")
    agents = [p["agent"] for p in client.get("/ledger").json()["purchases"]]
    assert agents == ["unknown", "Claude"]


def test_old_database_gains_agent_column_and_keeps_purchases(facilitator, content, tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, tx_hash TEXT UNIQUE NOT NULL, "
        "article_id TEXT NOT NULL, payer TEXT, pay_to TEXT NOT NULL, price_drops INTEGER NOT NULL, "
        "network TEXT NOT NULL, receipt TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z')"
    )
    old.execute("INSERT INTO purchases (tx_hash, article_id, pay_to, price_drops, network, receipt) "
                "VALUES ('T', 'seeded', ?, 500000, 'xrpl:1', '{}')", (WRITER,))
    old.commit()
    old.close()
    app = TestClient(create_app(facilitator.client, db_path=path, content_dir=content))
    assert app.get("/ledger").json()["purchases"][0]["agent"] == "unknown"
    assert app.get("/catalog").json()["articles"][0]["reads"] == 1


def test_allowed_agents_blocks_before_any_payment(client, facilitator):
    created = upload(client, allowed_agents="Claude, Muse").json()
    assert created["allowed_agents"] == ["Claude", "Muse"]
    blocked = client.get(f"/articles/{created['id']}", headers={"X-Agent-Name": "ChatGPT"})
    assert blocked.status_code == 403 and not facilitator.settled
    assert client.get(f"/articles/{created['id']}", headers={"X-Agent-Name": "claude"}).status_code == 402


@pytest.mark.parametrize(
    ("mode", "words"), [("none", 0), ("w50", 50), ("w100", 100), ("p10", 20)]
)
def test_preview_modes(client, mode, words):
    preview = upload(client, preview_mode=mode).json()["preview"]
    assert len(preview.split()) == words


def test_preview_never_gives_away_a_short_article(client):
    short = " ".join(f"w{i}" for i in range(60))
    preview = upload(client, preview_mode="w100", body=short).json()["preview"]
    assert len(preview.split()) == 30


def test_catalog_search_sort_and_counts(client):
    upload(client, title="Second piece", keywords="carburetors", price_xrp="3")
    upload(client, title="Third piece", price_xrp="1")
    for _ in range(2):
        pay(client, "third-piece")
    pay(client, "second-piece")
    ids = lambda **p: [a["id"] for a in client.get("/catalog", params=p).json()["articles"]]
    assert ids(sort="reads")[0] == "third-piece"
    assert ids(sort="earned")[0] == "second-piece"
    assert ids(sort="new")[-1] in {"seeded", "second-piece", "third-piece"}
    assert ids(q="CARBURETOR") == ["second-piece"]
    third = next(a for a in client.get("/catalog").json()["articles"] if a["id"] == "third-piece")
    assert third["reads"] == 2 and third["earned_xrp"] == "2"
    assert client.get("/catalog", params={"sort": "bad"}).status_code == 422


def test_dashboard_totals_pieces_and_agents(client):
    upload(client, title="Other", price_xrp="2")
    pay(client, "seeded", agent="Claude")
    pay(client, "other", agent="Muse")
    pay(client, "other", agent="Claude")
    data = client.get("/me/dashboard").json()
    assert data["totals"] == {"reads": 3, "earned_drops": 4_500_000, "month_drops": 4_500_000}
    assert data["payout"] == {"method": "xrpl", "xrpl_address": WRITER}
    assert data["latest"]["agent"] == "Claude" and data["latest"]["title"] == "Other"
    pieces = {p["id"]: p for p in data["pieces"]}
    assert pieces["other"]["reads"] == 2 and pieces["other"]["earned_drops"] == 4_000_000
    assert sorted(pieces["other"]["agents"]) == ["Claude", "Muse"]
    assert data["by_agent"][0] == {"name": "Claude", "reads": 2, "earned_drops": 2_500_000}


def test_empty_dashboard(tmp_path, facilitator):
    empty = tmp_path / "empty"
    empty.mkdir()
    data = TestClient(create_app(facilitator.client, db_path=tmp_path / "e.db", content_dir=empty)).get("/me/dashboard").json()
    assert data["totals"]["reads"] == 0 and data["latest"] is None and data["pieces"] == []


def test_payout_validates_address_and_rejects_stripe(client):
    assert client.put("/me/payout", json={"payout_method": "xrpl", "xrpl_address": "nope"}).status_code == 422
    assert client.put("/me/payout", json={"payout_method": "stripe", "xrpl_address": OTHER_ADDRESS}).status_code == 422
    assert client.put("/me/payout", json={"payout_method": "xrpl", "xrpl_address": OTHER_ADDRESS}).status_code == 200
    assert client.get("/me/payout").json()["xrpl_address"] == OTHER_ADDRESS
    assert client.get("/catalog").json()["articles"][0]["pay_to"] == OTHER_ADDRESS


def test_payout_does_not_leak_stripe_fields(client):
    assert "stripe_account_id" not in client.get("/me/payout").json()


@pytest.mark.parametrize("name", ["a.docx", "a.pdf", "a.exe", "noext"])
def test_upload_refuses_other_file_types(client, name):
    assert upload(client, name=name).status_code == 415


def test_upload_accepts_txt_and_uppercase_suffix(client):
    assert upload(client, name="a.TXT").status_code == 201


def test_upload_strips_frontmatter_and_uses_it_as_fallback(client):
    created = upload(client, title="", body="---\ntitle: From file\nabstract: From meta\n---\nThe text").json()
    assert created["title"] == "From file" and created["abstract"] == "From meta"
    assert created["word_count"] == 2


@pytest.mark.parametrize(
    "fields",
    [
        {"price_xrp": "0"}, {"price_xrp": "-1"}, {"price_xrp": "abc"}, {"price_xrp": "NaN"},
        {"price_xrp": "0.0000001"}, {"preview_mode": "all"}, {"license": "free"},
        {"license": "ai-train"}, {"license": "ai-train", "train_price_xrp": "0"},
        {"allowed_agents": " , "}, {"title": "   "},
    ],
)
def test_upload_rejects_bad_fields(client, fields):
    assert upload(client, **fields).status_code == 422


@pytest.mark.parametrize("body", ["   ", "---\ntitle: only meta\n---\n"])
def test_upload_rejects_empty_text(client, body):
    assert upload(client, body=body).status_code == 422


def test_upload_rejects_non_utf8_and_oversize(client):
    response = client.post("/articles", data={"title": "x", "price_xrp": "1"}, files={"file": ("a.txt", b"\xff\xfe\xff")})
    assert response.status_code == 422
    assert upload(client, body="x" * 2_000_001).status_code == 413


def test_training_license_keeps_its_price(client):
    created = upload(client, license="ai-train", train_price_xrp="25").json()
    assert created["train_price_xrp"] == "25" and created["train_price_drops"] == 25_000_000
    assert upload(client, train_price_xrp="25").json()["train_price_drops"] is None


def test_same_title_gets_a_new_id(client):
    assert upload(client).json()["id"] == "a-new-piece"
    assert upload(client).json()["id"] == "a-new-piece-2"


def test_llms_txt_covers_search_payment_license_and_receipts(client):
    response = client.get("/llms.txt")
    assert response.headers["content-type"].startswith("text/plain")
    for text in ("/catalog?q=", "402", "PAYMENT-SIGNATURE", "ai-input", "ai-train",
                 "/.well-known/tollgate-receipt-key", "X-Agent-Name"):
        assert text in response.text
