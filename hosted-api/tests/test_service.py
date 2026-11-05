import json
import os
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from pathlib import Path
import secrets
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from xrpl.wallet import Wallet
from tollgate_api.service import COOKIE, Service, create_app, PurchaseRequest
from tollgate_api.settings import Settings


class HostedApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database_url = "sqlite:///" + str(Path(self.tmp.name) / "test.sqlite")
        self.schema = None
        if os.getenv("TOLLGATE_TEST_DATABASE_URL"):
            import psycopg
            from psycopg import sql

            self.schema = "test_" + uuid4().hex
            with psycopg.connect(os.environ["TOLLGATE_TEST_DATABASE_URL"]) as db:
                db.execute(
                    sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema))
                )
            parsed = urlsplit(os.environ["TOLLGATE_TEST_DATABASE_URL"])
            query = dict(parse_qsl(parsed.query))
            query["options"] = "-csearch_path=" + self.schema
            database_url = urlunsplit(parsed._replace(query=urlencode(query)))
        self.settings = Settings(
            database_url=database_url,
            frontend_origin="http://localhost:8788",
            public_api_url="http://127.0.0.1:8001",
            writer_address="rJKbEpqxPts7PgJyZL5BPNFGuaYie9rAeY",
            signing_key=secrets.token_hex(32),
            encryption_key=secrets.token_hex(32),
            secure=False,
        )
        self.service = Service(self.settings)
        self.client = TestClient(create_app(self.settings, self.service))
        self.headers = {"Origin": self.settings.frontend_origin}
        self.article = next(iter(self.service.articles.values()))
        self.payload = {
            "article_id": self.article.id,
            "max_price_drops": self.article.price_drops,
            "request_id": str(uuid4()),
        }
        self.wallet = Wallet.create()
        with patch(
            "tollgate_api.service.generate_faucet_wallet", return_value=self.wallet
        ):
            response = self.client.post(
                "/api/tollgate/session", json={}, headers=self.headers
            )
        self.assertEqual(response.status_code, 200)
        self.session = self.service.session(self.client.cookies.get(COOKIE))

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()
        if self.schema:
            import psycopg
            from psycopg import sql

            with psycopg.connect(os.environ["TOLLGATE_TEST_DATABASE_URL"]) as db:
                db.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(
                        sql.Identifier(self.schema)
                    )
                )

    def data(self):
        a = self.article
        return {
            "id": a.id,
            "title": a.title,
            "body": a.body,
            "content_hash": a.content_hash,
            "receipt": self.service.signer.sign(
                {
                    "article_id": a.id,
                    "title": a.title,
                    "price_drops": a.price_drops,
                    "pay_to": a.pay_to,
                    "payer": self.wallet.address,
                    "network": "xrpl:1",
                    "tx_hash": "A" * 64,
                    "content_hash": a.content_hash,
                    "license": a.license,
                }
            ),
        }

    def result(self, data=None):
        value = data or self.data()
        return SimpleNamespace(
            status="success", response=SimpleNamespace(json=lambda: value)
        )

    def post(self, payload=None):
        return self.client.post(
            "/api/tollgate/purchases",
            json=payload or self.payload,
            headers=self.headers,
        )

    def test_wallet_encrypted_and_cookie_private(self):
        self.assertNotIn(self.wallet.seed, self.session["seed"])
        self.assertEqual(
            self.service.box.decrypt(bytes.fromhex(self.session["seed"])).decode(),
            self.wallet.seed,
        )
        self.assertNotIn(self.wallet.seed, self.client.get("/api/tollgate/health").text)
        self.client.cookies.clear()
        with patch(
            "tollgate_api.service.generate_faucet_wallet", return_value=Wallet.create()
        ):
            response = self.client.post(
                "/api/tollgate/session", json={}, headers=self.headers
            )
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertIn("Path=/api/tollgate", cookie)

    def test_proxy_trailing_slashes_do_not_redirect(self):
        self.assertEqual(
            self.client.get(
                "/api/tollgate/catalog/", follow_redirects=False
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/api/tollgate/health/", follow_redirects=False
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/tollgate/session/",
                json={},
                headers=self.headers,
                follow_redirects=False,
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                "/articles/" + self.article.id + "/", follow_redirects=False
            ).status_code,
            402,
        )

    def test_public_catalog_and_paywall(self):
        self.assertEqual(self.client.get("/catalog").status_code, 200)
        self.assertEqual(
            self.client.get("/catalog?q=not-a-topic").json()["articles"], []
        )
        response = self.client.get("/articles/" + self.article.id)
        self.assertEqual(response.status_code, 402)
        self.assertIn("payment-required", response.headers)
        self.assertNotIn(self.article.body, response.text)

    def test_session_required_and_csrf(self):
        self.assertEqual(
            self.client.post("/api/tollgate/purchases", json=self.payload).status_code,
            403,
        )
        self.client.cookies.clear()
        self.assertEqual(self.post().status_code, 401)
        self.assertEqual(self.client.get("/api/tollgate/library").json(), {"items": []})

    def test_caps_and_price_changes(self):
        with patch("tollgate_api.service.x402_purchase") as buy:
            for cap in [0, -1, True, "500000", 500000.5, 1000001]:
                self.assertEqual(
                    self.post({**self.payload, "max_price_drops": cap}).status_code, 422
                )
            self.assertEqual(
                self.post({**self.payload, "max_price_drops": 1}).status_code, 409
            )
            buy.assert_not_called()

    def test_purchase_persists_and_re_read_does_not_charge(self):
        with patch(
            "tollgate_api.service.x402_purchase", return_value=self.result()
        ) as buy:
            first = self.post()
            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.json()["receipt_verified"])
            self.assertEqual(self.post().json(), first.json())
            self.assertEqual(
                self.post({**self.payload, "request_id": str(uuid4())}).json(),
                first.json(),
            )
            buy.assert_called_once()
            self.assertEqual(
                buy.call_args.kwargs["max_value"], str(self.article.price_drops)
            )
        restarted = Service(self.settings)
        self.assertEqual(restarted.library(self.session)[0]["purchase"], first.json())
        self.assertEqual(
            restarted.remaining(self.session), 5000000 - self.article.price_drops
        )

    def test_other_session_cannot_read_or_replay_purchase(self):
        with patch("tollgate_api.service.x402_purchase", return_value=self.result()):
            self.assertEqual(self.post().status_code, 200)
        self.client.cookies.clear()
        with patch(
            "tollgate_api.service.generate_faucet_wallet", return_value=Wallet.create()
        ):
            self.client.post("/api/tollgate/session", json={}, headers=self.headers)
        self.assertEqual(self.client.get("/api/tollgate/library").json(), {"items": []})
        self.assertEqual(
            self.client.get("/api/tollgate/ledger").json()["purchases"], []
        )
        with patch("tollgate_api.service.x402_purchase") as buy:
            self.assertEqual(self.post().status_code, 409)
            buy.assert_not_called()

    def test_tampered_content_never_delivered(self):
        data = self.data()
        data["body"] = "tampered"
        with patch(
            "tollgate_api.service.x402_purchase", return_value=self.result(data)
        ):
            response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("tampered", response.text)

    def test_timeout_reserves_budget_and_blocks_duplicate(self):
        with patch(
            "tollgate_api.service.x402_purchase", side_effect=TimeoutError
        ) as buy:
            self.assertEqual(self.post().status_code, 502)
            self.assertEqual(self.post().status_code, 409)
            self.assertEqual(
                self.post({**self.payload, "request_id": str(uuid4())}).status_code, 409
            )
            buy.assert_called_once()
        self.assertEqual(
            self.service.remaining(self.session), 5000000 - self.article.price_drops
        )

    def test_payment_diagnostics_include_timing_without_secrets(self):
        with self.assertLogs("tollgate", level="INFO") as logs:
            with patch(
                "tollgate_api.service.x402_purchase",
                side_effect=TimeoutError("sensitive upstream detail"),
            ):
                response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertTrue(response.headers["x-request-id"])
        events = [json.loads(record.message) for record in logs.records]
        pending = next(
            event for event in events if event["event"] == "purchase_pending"
        )
        self.assertEqual(pending["stage"], "payment")
        self.assertEqual(pending["request_id"], self.payload["request_id"])
        self.assertEqual(pending["error_type"], "TimeoutError")
        self.assertGreaterEqual(pending["duration_ms"], 0)
        text = " ".join(logs.output)
        for secret in [
            self.wallet.seed,
            self.client.cookies.get(COOKIE),
            "sensitive upstream detail",
        ]:
            self.assertNotIn(secret, text)

    def test_library_recovers_settled_payment_after_timeout(self):
        with patch("tollgate_api.service.x402_purchase", side_effect=TimeoutError):
            self.post()
        with self.service.store.transaction() as db:
            db.execute(
                "INSERT INTO tg_ledger(tx_hash,article_id,payer,result,created_at) VALUES (?,?,?,?,?)",
                (
                    "A" * 64,
                    self.article.id,
                    self.wallet.address,
                    json.dumps(self.data()),
                    int(time.time()),
                ),
            )
        items = self.client.get("/api/tollgate/library").json()["items"]
        self.assertEqual(items[0]["status"], "complete")
        self.assertTrue(items[0]["purchase"]["receipt_verified"])

    def test_faucet_rate_limit(self):
        with patch(
            "tollgate_api.service.generate_faucet_wallet", return_value=Wallet.create()
        ) as faucet:
            for i in range(3):
                self.client.cookies.clear()
                result = self.client.post(
                    "/api/tollgate/session", json={}, headers=self.headers
                )
                self.assertEqual(result.status_code, 200 if i < 2 else 429)
            self.assertEqual(faucet.call_count, 2)

    def test_expired_session_not_accepted(self):
        with self.service.store.transaction() as db:
            db.execute(
                "UPDATE tg_sessions SET created_at=0 WHERE id=?", (self.session["id"],)
            )
        self.assertFalse(
            self.client.get("/api/tollgate/health").json()["purchases_enabled"]
        )
        self.assertEqual(self.post().status_code, 401)

    def test_parallel_requests_only_submit_one_payment(self):
        started, finish = threading.Event(), threading.Event()
        results = []

        def delayed(*args, **kwargs):
            started.set()
            finish.wait(5)
            return self.result()

        req = PurchaseRequest(**self.payload)
        with patch("tollgate_api.service.x402_purchase", side_effect=delayed) as buy:
            thread = threading.Thread(
                target=lambda: results.append(self.service.purchase(self.session, req))
            )
            thread.start()
            self.assertTrue(started.wait(5))
            self.assertEqual(
                self.post({**self.payload, "request_id": str(uuid4())}).status_code, 409
            )
            finish.set()
            thread.join(5)
            self.assertEqual(len(results), 1)
            buy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
