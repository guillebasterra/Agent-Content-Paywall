"""Pricing help on /upload: exact integer math, and the endpoint the form calls."""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.estimate import monthly_earnings, suggested_price
from app.main import create_app
from tests.test_base import FakeFacilitator


def test_one_paid_agent_read_per_reader():
    assert monthly_earnings(20_000, 10_000, 0) == (10_000, 200_000_000)  # $0.02 × 10,000 = $200


def test_fee_is_taken_per_read_like_the_ledger():
    # 10% of $0.000015 is 1.5 micro-dollars, rounded down to 1 on each read.
    assert monthly_earnings(15, 100, 1_000) == (100, 1_400)


def test_no_readers_earns_nothing():
    assert monthly_earnings(20_000, 0, 0) == (0, 0)


@pytest.mark.parametrize("readers, price", [(0, 100_000), (1_000, 100_000), (4_000, 50_000), (10_000, 32_000),
                                            (40_000, 16_000), (100_000, 10_000), (50_000_000, 10_000)])
def test_suggested_price_falls_as_the_audience_grows(readers, price):
    assert suggested_price(readers) == price


def test_suggested_earnings_still_grow_with_the_audience():
    tiers = [0, 500, 999, 1_000, 1_001, 2_500, 9_999, 10_000, 10_001, 37_000, 99_999, 100_000, 100_001, 10**6, 10**8]
    earned = [monthly_earnings(suggested_price(r), r, 0)[1] for r in tiers]
    assert earned == sorted(earned)


@pytest.mark.parametrize("price, readers", [(0, 10), (-1, 10), (1, -1), (1, 100_000_001)])
def test_rejects_bad_input(price, readers):
    with pytest.raises(ValueError):
        monthly_earnings(price, readers, 0)


@pytest.fixture
def client(tmp_path, database, monkeypatch):
    monkeypatch.setattr(config, "PAYMENT_RAIL", "base")
    (tmp_path / "c").mkdir()
    app = create_app(base_facilitator=FakeFacilitator(), database=database, content_dir=tmp_path / "c")
    yield TestClient(app)
    app.state.db.close()


def test_endpoint_prices_this_price_and_suggests_one(client):
    data = client.get("/estimate", params={"price_usd": "0.40", "monthly_readers": 2_000}).json()
    assert data["price_usd"] == "0.40" and data["agent_reads"] == 2_000
    assert data["earned_usd_micros"] == 800_000_000  # $800
    assert data["suggested"] == {"price_usd": "0.071", "earned_usd_micros": 142_000_000}  # $142
    assert len(data["how"]) == 3 and "Cloudflare" in data["how"][0]


def test_endpoint_defaults_to_ten_thousand_readers(client):
    assert client.get("/estimate", params={"price_usd": "0.02"}).json()["monthly_readers"] == 10_000


@pytest.mark.parametrize("params", [{"price_usd": "abc"}, {"price_usd": "0"}, {"price_usd": "0.02", "monthly_readers": -5}])
def test_endpoint_rejects_bad_input(client, params):
    assert client.get("/estimate", params=params).status_code == 422
