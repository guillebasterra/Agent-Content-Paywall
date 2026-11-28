"""The earnings estimate: exact integer math, and the endpoint the upload page calls."""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.estimate import SCENARIOS, monthly
from app.main import create_app
from tests.test_base import FakeFacilitator


def rows(price, readers, fee=0):
    return {r["id"]: r for r in monthly(price, readers, fee)}


def test_scenarios_scale_human_readers_by_agent_reads():
    r = rows(20_000, 10_000)  # $0.02, 10,000 readers a month
    assert r["today"]["agent_reads"] == 158  # 10,000 × 1/31 × 49%, rounded down
    assert r["parity"]["agent_reads"] == 10_000
    assert r["agent_first"]["agent_reads"] == 100_000
    assert r["parity"]["earned_usd_micros"] == 200_000_000  # $200
    assert r["agent_first"]["earned_usd_micros"] == 2_000_000_000  # $2,000


def test_scenarios_grow_and_every_one_cites_a_source():
    reads = [s.agent_reads_per_human_read for s in SCENARIOS]
    assert reads == sorted(reads)
    assert all(s.source and s.basis for s in SCENARIOS)


def test_fee_is_taken_per_read_like_the_ledger():
    # 10% of $0.000015 is 1.5 micro-dollars, rounded down to 1 per read, as each sale is.
    r = rows(15, 100, fee=1_000)["parity"]
    assert r["gross_usd_micros"] == 1_500 and r["earned_usd_micros"] == 1_400


def test_no_readers_earns_nothing():
    assert all(r["earned_usd_micros"] == 0 for r in monthly(20_000, 0, 0))


@pytest.mark.parametrize("price, readers", [(0, 10), (-1, 10), (1, -1), (1, 100_000_001)])
def test_rejects_bad_input(price, readers):
    with pytest.raises(ValueError):
        monthly(price, readers, 0)


@pytest.fixture
def client(tmp_path, database, monkeypatch):
    monkeypatch.setattr(config, "PAYMENT_RAIL", "base")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "a.md").write_text("---\nid: a\ntitle: A\nabstract: x\nprice_usd: 0.10\n---\nbody")
    (tmp_path / "c" / "b.md").write_text("---\nid: b\ntitle: B\nabstract: x\nprice_usd: 0.02\n---\nbody")
    app = create_app(base_facilitator=FakeFacilitator(), database=database, content_dir=tmp_path / "c")
    yield TestClient(app)
    app.state.db.close()


def test_endpoint_returns_scenarios_guidance_and_the_assumption(client):
    data = client.get("/estimate", params={"price_usd": "0.25", "monthly_readers": 2_000}).json()
    assert data["price_usd"] == "0.25" and data["monthly_readers"] == 2_000
    by_id = {s["id"]: s for s in data["scenarios"]}
    assert by_id["parity"]["earned_usd_micros"] == 500_000_000  # 2,000 × $0.25
    assert data["price_guidance"]["catalog_median_usd"] == "0.10"
    assert data["price_guidance"]["source"] and "pays" in data["assumes"]


def test_endpoint_defaults_to_ten_thousand_readers(client):
    assert client.get("/estimate", params={"price_usd": "0.02"}).json()["monthly_readers"] == 10_000


@pytest.mark.parametrize("params", [{"price_usd": "abc"}, {"price_usd": "0"}, {"price_usd": "0.02", "monthly_readers": -5}])
def test_endpoint_rejects_bad_input(client, params):
    assert client.get("/estimate", params=params).status_code == 422
