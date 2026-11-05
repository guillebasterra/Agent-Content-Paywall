"""x402 "exact" on the XRP Ledger, settled by the t54 facilitator.

Money goes straight to the writer. A writer with no address is paid through the platform
treasury and credited in the ledger instead. The SDK's middleware does the protocol work,
including SourceTag injection and facilitator verify/settle.
"""

import base64
import json
import time
from collections.abc import Sequence

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from x402_xrpl.clients.base import decode_payment_response
from x402_xrpl.facilitator import AsyncFacilitatorClient
from x402_xrpl.server import RequireX402Options, require_x402
from x402_xrpl.types import PaymentPayload, PaymentRequirements

from .. import config
from ..content import usd_to_drops
from .base import Sale
from .settle import Settlements, response_json, with_json


def pay_to_address(article: dict) -> str | None:
    return article["pay_to"] or config.TREASURY_ADDRESS or None


class ScopedInvoices:
    """Invoices keyed by article.

    The SDK checks a payment against its invoice, not against the URL. With one shared
    store, an invoice issued for a cheap article could pay for an expensive one.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], tuple[Sequence[PaymentRequirements], float]] = {}

    def for_article(self, article_id: str) -> "ArticleInvoices":
        return ArticleInvoices(self, article_id)

    def put(self, key: tuple[str, str], reqs: Sequence[PaymentRequirements], ttl_seconds: int) -> None:
        now = time.monotonic()
        self._data = {k: v for k, v in self._data.items() if v[1] > now}
        self._data[key] = (reqs, now + ttl_seconds)

    def get(self, key: tuple[str, str]) -> Sequence[PaymentRequirements] | None:
        entry = self._data.get(key)
        return entry[0] if entry and entry[1] > time.monotonic() else None

    def consume(self, key: tuple[str, str]) -> None:
        self._data.pop(key, None)


class ArticleInvoices:
    """The SDK's InvoiceStore interface, limited to one article."""

    def __init__(self, store: ScopedInvoices, article_id: str) -> None:
        self._store = store
        self._article_id = article_id

    async def put(self, invoice_id: str, reqs: Sequence[PaymentRequirements], *, ttl_seconds: int) -> None:
        self._store.put((self._article_id, invoice_id), reqs, ttl_seconds)

    async def get(self, invoice_id: str) -> Sequence[PaymentRequirements] | None:
        return self._store.get((self._article_id, invoice_id))

    async def consume(self, invoice_id: str) -> None:
        self._store.consume((self._article_id, invoice_id))


class XrplRail:
    name = "xrpl"

    def __init__(self, facilitator: AsyncFacilitatorClient, settlements: Settlements, agent_name):
        self.facilitator = facilitator
        self.settlements = settlements
        self.agent_name = agent_name
        self.invoices = ScopedInvoices()

    def handles(self, request: Request) -> bool:
        return True  # The default: anyone without another way to pay gets the x402 challenge.

    def advertise(self, article: dict) -> dict | None:
        return None  # x402 clients read this rail from `accepts`.

    async def charge(self, request: Request, article: dict, call_next) -> Response:
        pay_to = pay_to_address(article)
        if not pay_to:
            # Never fall through to the handler: that would serve the article for free.
            return JSONResponse(status_code=503, content={"error": "writer_has_no_payout_address"})

        options = RequireX402Options(
            pay_to=pay_to,
            amount=str(usd_to_drops(article["price_usd_micros"], config.XRP_USD_RATE)),
            network=config.NETWORK,
            asset="XRP",
            facilitator=self.facilitator,
            resource=f"{config.PUBLIC_URL}/articles/{article['id']}",
            description=f"{article['title']} — {article['author']} (license: {article['license']})",
            source_tag=config.SOURCE_TAG,
            invoice_store=self.invoices.for_article(article["id"]),
        )
        response = await require_x402(options)(request, call_next)
        settled = response.headers.get("PAYMENT-RESPONSE")
        if response.status_code != 200 or not settled:
            return response
        return await self._deliver(request, article, response, settled)

    async def _deliver(self, request: Request, article: dict, response: Response, settled: str) -> Response:
        """Runs after settlement, the first moment the transaction hash exists."""
        settlement = decode_payment_response(settled)
        # What the buyer actually signed. The writer may have changed payout address
        # since the invoice was issued, so the database can't say where the money went.
        signed = json.loads(base64.b64decode(request.headers["PAYMENT-SIGNATURE"]))
        accepted = PaymentPayload.from_dict(signed).accepted
        tx_hash = settlement.get("transaction")
        sale = Sale(
            rail=self.name,
            article=article,
            ref=tx_hash,
            amount_usd_micros=article["price_usd_micros"],
            amount_native=int(accepted.amount),
            payer=settlement.get("payer"),
            pay_to=accepted.pay_to,
            network=settlement.get("network") or config.NETWORK,
            agent=self.agent_name(request),
            credit_writer=accepted.pay_to == config.TREASURY_ADDRESS,
            receipt_fields={
                "price_drops": int(accepted.amount),
                "tx_hash": tx_hash,
                "explorer": config.EXPLORER_TX + str(tx_hash),
            },
        )
        receipt = self.settlements.receipt(sale)
        self.settlements.record(sale, receipt)
        return with_json(response, {**await response_json(response), "receipt": receipt})
