"""One x402 paywall for every article, priced from the database on each request.

New articles are for sale as soon as they are saved. The SDK's middleware still does
the protocol work, including SourceTag injection and facilitator verify/settle.
"""

import re
import time
from collections.abc import Sequence

from fastapi.responses import JSONResponse
from starlette.requests import Request
from x402_xrpl.facilitator import AsyncFacilitatorClient
from x402_xrpl.server import RequireX402Options, require_x402
from x402_xrpl.types import PaymentRequirements

from . import config
from .db import Database

ARTICLE_PATH = re.compile(r"^/articles/([^/]+)$")
UNKNOWN_AGENT = "unknown"
MAX_AGENT_NAME = 64


def article_id_from(request: Request) -> str | None:
    match = ARTICLE_PATH.match(request.scope["path"])
    return match[1] if match else None


def agent_name(request: Request) -> str:
    raw = request.headers.get("X-Agent-Name", "")
    return "".join(ch for ch in raw if ch.isprintable()).strip()[:MAX_AGENT_NAME] or UNKNOWN_AGENT


def agent_allowed(article: dict, agent: str) -> bool:
    allowed = article["allowed_agents"]
    return "*" in allowed or agent.casefold() in {a.casefold() for a in allowed}


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


def paywall(db: Database, facilitator: AsyncFacilitatorClient):
    invoices = ScopedInvoices()

    async def middleware(request: Request, call_next):
        article_id = article_id_from(request)
        # Only GET can return article text. Others fall through to a 405 with no charge.
        article = db.article(article_id) if article_id and request.method == "GET" else None
        if article is None:
            return await call_next(request)

        if not agent_allowed(article, agent_name(request)):
            return JSONResponse(
                status_code=403,
                content={"error": "agent_not_allowed", "allowed_agents": article["allowed_agents"]},
            )
        if not article["pay_to"]:
            # Never fall through to the handler: that would serve the article for free.
            return JSONResponse(status_code=503, content={"error": "writer_has_no_payout_address"})

        options = RequireX402Options(
            pay_to=article["pay_to"],
            amount=str(article["price_drops"]),
            network=config.NETWORK,
            asset="XRP",
            facilitator=facilitator,
            resource=f"{config.PUBLIC_URL}/articles/{article['id']}",
            description=f"{article['title']} — {article['author']} (license: {article['license']})",
            source_tag=config.SOURCE_TAG,
            invoice_store=invoices.for_article(article["id"]),
        )
        return await require_x402(options)(request, call_next)

    return middleware
