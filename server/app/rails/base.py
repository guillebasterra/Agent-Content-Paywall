"""The interface every payment rail implements. All rails settle into the same tables."""

from dataclasses import dataclass, field
from typing import Protocol

from starlette.requests import Request
from starlette.responses import Response


@dataclass(frozen=True)
class Sale:
    """One settled read, as recorded in purchases and carried on the signed receipt."""

    rail: str
    article: dict
    ref: str  # Chain transaction hash, or the Stripe-credit reference.
    amount_usd_micros: int
    amount_native: int | None  # Drops on XRPL, USDC atomic units on Base. Nothing for Stripe credit.
    payer: str | None
    pay_to: str
    network: str
    agent: str
    credit_writer: bool  # True when the platform holds the money and owes it to the writer.
    receipt_fields: dict = field(default_factory=dict)
    fee_usd_micros: int = 0  # The platform's share. The writer is credited the rest.


class PaymentRail(Protocol):
    name: str

    def handles(self, request: Request) -> bool:
        """Whether this request is paying with this rail."""

    async def charge(self, request: Request, article: dict, call_next) -> Response:
        """Serve the article if paid. The response carries the receipt, or says how to pay."""

    def advertise(self, article: dict) -> dict | None:
        """How to pay this way, listed in other rails' 402 responses."""
