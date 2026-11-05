"""Prepaid credit, funded through Stripe Checkout. Custodial and test mode only.

Per-read card charges don't work because of Stripe's minimums and fees, so an agent tops up
in advance and each read is debited here. The writer accrues the same amount in the ledger.
"""

import hashlib
import secrets
import uuid

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .. import config
from ..content import format_usd, to_micros
from ..db import Database
from .base import Sale
from .settle import Settlements, response_json, with_json

KEY_PREFIX = "tg_test_"
BEARER = "bearer "


def new_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    """SHA-256 is enough here: the key is 32 random bytes, so there is nothing to brute force."""
    return hashlib.sha256(key.encode()).hexdigest()


def bearer_key(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header[: len(BEARER)].lower() != BEARER:
        return None
    token = header[len(BEARER) :].strip()
    return token if token.startswith("tg_") else None


class StripeCreditRail:
    name = "stripe"

    def __init__(self, db: Database, settlements: Settlements):
        self.db = db
        self.settlements = settlements

    def handles(self, request: Request) -> bool:
        return bearer_key(request) is not None

    def _agent(self, request: Request) -> dict | None:
        return self.db.agent_by_key_hash(hash_key(bearer_key(request)))

    def authenticated_agent(self, request: Request) -> str | None:
        """The account's name, which unlike X-Agent-Name is not self-reported. None if the key is bad."""
        agent = self._agent(request)
        return agent["name"] if agent else None

    def advertise(self, article: dict) -> dict:
        return {
            "scheme": "stripe-credit",
            "price_usd": format_usd(article["price_usd_micros"]),
            "description": "Prepaid credit, topped up with a card. Send your agent key as a bearer token.",
            "header": "Authorization: Bearer tg_test_...",
            "docs": f"{config.PUBLIC_URL}/llms.txt",
        }

    async def charge(self, request: Request, article: dict, call_next) -> Response:
        agent = self._agent(request)
        if agent is None:
            return JSONResponse(status_code=401, content={"error": "invalid_api_key"})

        price = article["price_usd_micros"]
        cap = request.headers.get("X-Max-Price-Usd")
        if cap is not None:
            # The same hard stop x402's max_value gives: a price rise can't spend more than was agreed.
            try:
                above = price > to_micros(cap)
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "invalid_max_price"})
            if above:
                return JSONResponse(status_code=409, content={"error": "price_above_limit", "price_usd": format_usd(price)})

        declined = JSONResponse(
            status_code=402,
            content={
                "error": "insufficient_credit",
                "price_usd": format_usd(price),
                "credit_usd": format_usd(agent["credit_usd_micros"]),
                "top_up": f"POST {config.PUBLIC_URL}/agents/me/topups",
            },
        )
        if agent["credit_usd_micros"] < price:
            return declined

        response = await call_next(request)
        if response.status_code != 200:
            return response
        ref = f"credit_{uuid.uuid4().hex}"
        sale = Sale(
            rail=self.name,
            article=article,
            ref=ref,
            amount_usd_micros=price,
            amount_native=None,
            payer=agent["name"],
            pay_to=f"ledger:{article['writer_id']}",
            network="stripe:test",
            agent=agent["name"],
            credit_writer=True,
            receipt_fields={"stripe_ref": ref, "funding": "prepaid-credit"},
        )
        receipt = self.settlements.receipt(sale)
        # The debit is what actually decides: two reads racing for the last of the credit can't both win.
        if not self.settlements.record(sale, receipt, debit_agent_id=agent["id"]):
            return declined
        data = await response_json(response)
        return with_json(response, {**data, "receipt": receipt})
