"""Toll Gate API.

Free:  GET /catalog, GET /ledger, GET /.well-known/tollgate-receipt-key
Paid:  GET /articles/{id}  (x402 over XRPL; payment goes straight to the writer)
"""

import json
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from x402_xrpl.clients.base import decode_payment_response
from x402_xrpl.facilitator import AsyncFacilitatorClient, FacilitatorClientOptions
from x402_xrpl.server import require_payment

from . import config
from .content import load_articles
from .db import Ledger
from .receipts import ReceiptSigner

log = logging.getLogger("tollgate")


def _signing_key() -> str:
    key = os.getenv("RECEIPT_SIGNING_KEY", "")
    if key:
        return key
    key = ReceiptSigner.generate_hex()
    if config.ENV_PATH.exists():
        text = config.ENV_PATH.read_text()
        if "RECEIPT_SIGNING_KEY=" in text:
            text = text.replace("RECEIPT_SIGNING_KEY=\n", f"RECEIPT_SIGNING_KEY={key}\n", 1)
        else:
            text += f"\nRECEIPT_SIGNING_KEY={key}\n"
        config.ENV_PATH.write_text(text)
        log.warning("generated RECEIPT_SIGNING_KEY and saved it to .env")
    os.environ["RECEIPT_SIGNING_KEY"] = key
    return key


def create_app(facilitator: AsyncFacilitatorClient | None = None) -> FastAPI:
    if not config.WRITER_ADDRESS:
        raise RuntimeError("WRITER_ADDRESS missing — run `make wallets` first")

    articles = load_articles(config.CONTENT_DIR, config.WRITER_ADDRESS)
    ledger = Ledger(config.DB_PATH)
    signer = ReceiptSigner(_signing_key())
    facilitator = facilitator or AsyncFacilitatorClient(
        FacilitatorClientOptions(base_url=config.FACILITATOR_URL, timeout_seconds=60)
    )

    app = FastAPI(title="Toll Gate")
    app.state.articles, app.state.ledger, app.state.signer = articles, ledger, signer

    # --- paywall: one x402 middleware per article (the SDK matches exact paths) ---
    for a in articles.values():
        app.middleware("http")(
            require_payment(
                path=f"/articles/{a.id}",
                price=str(a.price_drops),
                pay_to_address=a.pay_to,
                network=config.NETWORK,
                asset="XRP",
                facilitator=facilitator,
                resource=f"{config.PUBLIC_URL}/articles/{a.id}",
                description=f"{a.title} — {a.author} (license: {a.license})",
                source_tag=config.SOURCE_TAG,
            )
        )

    # --- receipts: runs outside the paywall, after settlement succeeded ---
    @app.middleware("http")
    async def attach_receipt(request: Request, call_next):
        response = await call_next(request)
        settled = response.headers.get("PAYMENT-RESPONSE")
        article_id = request.url.path.removeprefix("/articles/")
        if response.status_code != 200 or not settled or article_id not in articles:
            return response

        settlement = decode_payment_response(settled)
        a = articles[article_id]
        receipt = signer.sign({
            "article_id": a.id,
            "title": a.title,
            "content_hash": a.content_hash,
            "license": a.license,
            "price_drops": a.price_drops,
            "pay_to": a.pay_to,
            "payer": settlement.get("payer"),
            "network": settlement.get("network"),
            "tx_hash": settlement.get("transaction"),
            "explorer": config.EXPLORER_TX + str(settlement.get("transaction")),
        })
        ledger.record(
            tx_hash=settlement.get("transaction"),
            article_id=a.id,
            payer=settlement.get("payer"),
            pay_to=a.pay_to,
            price_drops=a.price_drops,
            network=settlement.get("network") or config.NETWORK,
            receipt=receipt,
        )

        body = b"".join([chunk async for chunk in response.body_iterator])
        data = {**json.loads(body), "receipt": receipt}
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(json.dumps(data), status_code=200, headers=headers, media_type="application/json")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["PAYMENT-REQUIRED", "PAYMENT-RESPONSE"],
    )

    # --- routes ---
    @app.get("/health")
    def health():
        return {"ok": True, "articles": len(articles), "network": config.NETWORK}

    @app.get("/catalog")
    def catalog(q: str | None = None):
        items = [a.listing(config.PUBLIC_URL) for a in articles.values()]
        if q:
            ql = q.lower()
            items = [
                i for i in items
                if ql in (i["title"] + " " + i["abstract"] + " " + " ".join(i["tags"])).lower()
            ]
        return {"articles": items}

    @app.get("/articles/{article_id}")
    def read_article(article_id: str):
        a = articles.get(article_id)
        if not a:
            raise HTTPException(404, "unknown article")
        return {
            "id": a.id,
            "title": a.title,
            "author": a.author,
            "license": a.license,
            "content_hash": a.content_hash,
            "body": a.body,
        }

    @app.get("/ledger")
    def get_ledger(limit: int = 50):
        return {"purchases": ledger.recent(limit), "earnings": ledger.earnings()}

    @app.get("/.well-known/tollgate-receipt-key")
    def receipt_key():
        return {"alg": "ed25519", "public_key": signer.public_key_hex}

    return app


app = create_app() if os.getenv("TOLLGATE_NO_AUTOAPP") != "1" else None
