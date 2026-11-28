"""x402 v2 "exact" on Base mainnet: USDC to Toll Gate's treasury, settled by the CDP facilitator.

The official x402 middleware does the protocol work: the 402 challenge, verify, and settle
after the handler runs. Toll Gate decides which requests reach it (only known articles, only
allowed agents), sets each article's own price, and after settlement signs the receipt and
credits the writer in the ledger, minus the platform fee. Writers need no wallet.

Micro-dollars and USDC atomic units (6 decimals) are the same integer, so a price is never converted.
"""

from collections.abc import Callable
from contextvars import ContextVar

from starlette.requests import Request
from starlette.responses import Response
from x402 import x402ResourceServer
from x402.extensions.bazaar import OutputConfig, bazaar_resource_server_extension, declare_discovery_extension
from x402.http import (
    PAYMENT_RESPONSE_HEADER,
    HTTPRequestContext,
    HTTPResponseBody,
    PaymentOption,
    RouteConfig,
    decode_payment_response_header,
)
from x402.http.middleware.fastapi import payment_middleware
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.schemas import AssetAmount, PaymentPayload

from .. import config
from ..content import format_usd
from .base import Sale
from .settle import Settlements, response_json, with_json

# A named parameter, not "*", so the Bazaar lists one entry with a readable template.
ROUTE = "GET /articles/:id"
BPS = 10_000
# The article being sold on this request. Set before the SDK runs and read by its price callback.
_article: ContextVar[dict] = ContextVar("tollgate_article")


def usdc_asset(network: str) -> str:
    if network not in config.USDC_BY_NETWORK:
        raise RuntimeError(f"No USDC address known for {network}")
    return config.USDC_BY_NETWORK[network]


def fee_micros(amount: int, fee_bps: int) -> int:
    """Rounded down, so the writer is never credited less than their share."""
    return amount * fee_bps // BPS


def _price(_: HTTPRequestContext) -> AssetAmount:
    article = _article.get()
    return AssetAmount(amount=str(article["price_usd_micros"]), asset=usdc_asset(config.BASE_NETWORK))


def _unpaid_body(_: HTTPRequestContext) -> HTTPResponseBody:
    """Readable context for agents. The challenge itself is the PAYMENT-REQUIRED header."""
    article = _article.get()
    return HTTPResponseBody(
        content_type="application/json",
        body={
            "error": "payment_required",
            "article": {
                "id": article["id"],
                "title": article["title"],
                "author": article["author"],
                "license": article["license"],
                "price_usd": format_usd(article["price_usd_micros"]),
            },
            "pay_with": f"x402 v2, scheme exact, USDC on Base ({config.BASE_NETWORK}). Challenge in the PAYMENT-REQUIRED header.",
            "docs": f"{config.PUBLIC_URL}/llms.txt",
        },
    )


# Bazaar limits: description <= 500 chars, service name <= 32, at most 5 tags of <= 32.
SERVICE_NAME = "Toll Gate"
TAGS = ["articles", "research", "writing", "analysis", "pay-per-read"]
DESCRIPTION_LIMIT = 500


def bazaar_description(public_url: str) -> str:
    """Tells an agent when to use this, and how to find an id first. Facts only: listings are screened."""
    return (
        "Original articles by independent writers, sold to AI agents one read at a time. "
        "Use when a question needs a specific expert piece rather than free web results. "
        f"Find an article id with the free search GET {public_url}/catalog?q=<keywords>, which lists "
        "title, abstract, price and license. GET /articles/:id returns the full text, title, author "
        "and a receipt signed by Toll Gate. Each writer sets their own price."
    )


def bazaar_extension() -> dict:
    """Discovery metadata. The CDP facilitator lists the route after the first settled payment that carries it."""
    return declare_discovery_extension(
        path_params_schema={
            "properties": {"id": {"type": "string", "description": "Article id, from GET /catalog"}},
            "required": ["id"],
        },
        output=OutputConfig(
            example={
                "id": "example-article",
                "title": "Example article",
                "author": "Writer name",
                "license": "ai-input",
                "content_hash": "sha256:...",
                "body": "The full article text.",
                "receipt": {"payload": {"amount_usd": "0.02", "tx_hash": "0x...", "explorer": "https://basescan.org/tx/0x..."}, "signature": "..."},
            },
        ),
    )


def public_request(request: Request) -> Request:
    """The request as seen at TOLLGATE_API_URL, so the challenge names the public URL even behind a tunnel."""
    scheme, _, host = config.PUBLIC_URL.partition("://")
    host = host.split("/", 1)[0]
    headers = [(k, v) for k, v in request.scope["headers"] if k != b"host"] + [(b"host", host.encode())]
    return Request({**request.scope, "scheme": scheme, "headers": headers}, request.receive)


class BaseUsdcRail:
    name = "base"

    def __init__(
        self,
        facilitator,
        settlements: Settlements,
        agent_name: Callable[[Request], str],
        *,
        pay_to: str,
        network: str,
        fee_bps: int,
        sync_on_start: bool = True,
    ):
        if not pay_to:
            raise RuntimeError("TREASURY_BASE_ADDRESS missing — run `make treasury` first")
        if not 0 <= fee_bps <= BPS:
            raise RuntimeError("PLATFORM_FEE_BPS must be between 0 and 10000")
        usdc_asset(network)
        self.settlements = settlements
        self.agent_name = agent_name
        self.pay_to = pay_to
        self.network = network
        self.fee_bps = fee_bps

        server = x402ResourceServer(facilitator)
        server.register(network, ExactEvmServerScheme())
        server.register_extension(bazaar_resource_server_extension)
        description = bazaar_description(config.PUBLIC_URL)
        if len(description) > DESCRIPTION_LIMIT:  # the facilitator rejects verify and settle above this
            raise RuntimeError(f"Bazaar description is {len(description)} chars; the limit is {DESCRIPTION_LIMIT}")
        routes = {
            ROUTE: RouteConfig(
                accepts=PaymentOption(scheme="exact", pay_to=pay_to, price=_price, network=network, max_timeout_seconds=300),
                description=description,
                mime_type="application/json",
                service_name=SERVICE_NAME,
                tags=TAGS,
                unpaid_response_body=_unpaid_body,
                extensions=bazaar_extension(),
            )
        }
        # Fetches the facilitator's /supported once at startup. If that fails it retries on the first paid request.
        self._middleware = payment_middleware(routes, server, sync_facilitator_on_start=sync_on_start)

    def handles(self, request: Request) -> bool:
        return True

    def advertise(self, article: dict) -> dict | None:
        return None  # x402 clients read this rail from the PAYMENT-REQUIRED header.

    async def charge(self, request: Request, article: dict, call_next) -> Response:
        token = _article.set(article)
        try:
            public = public_request(request)
            response = await self._middleware(public, call_next)
        finally:
            _article.reset(token)
        settled = response.headers.get(PAYMENT_RESPONSE_HEADER)
        if response.status_code != 200 or not settled:
            return response
        return await self._deliver(public, article, response, settled)

    async def _deliver(self, request: Request, article: dict, response: Response, settled: str) -> Response:
        """Runs after settlement, the first moment the transaction hash exists."""
        settlement = decode_payment_response_header(settled)
        payload: PaymentPayload = request.state.payment_payload
        # What the buyer signed, not the database: the price may have changed since the challenge.
        accepted = payload.accepted
        amount = int(accepted.amount)
        fee = fee_micros(amount, self.fee_bps)
        tx_hash = settlement.transaction
        agent = self.agent_name(request)
        sale = Sale(
            rail=self.name,
            article=article,
            ref=tx_hash,
            amount_usd_micros=amount,
            amount_native=amount,
            payer=settlement.payer,
            pay_to=accepted.pay_to,
            network=settlement.network or accepted.network,
            agent=agent,
            credit_writer=True,
            fee_usd_micros=fee,
            receipt_fields={
                "asset": "USDC",
                "asset_address": accepted.asset,
                "amount_atomic": str(amount),
                "writer_credit_usd": format_usd(amount - fee),
                "tx_hash": tx_hash,
                "explorer": config.BASESCAN_TX + tx_hash,
            },
        )
        receipt = self.settlements.receipt(sale)
        self.settlements.record(sale, receipt)
        return with_json(response, {**await response_json(response), "receipt": receipt})
