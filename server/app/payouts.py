"""Pays writers what the ledger says they are owed, as Stripe test-mode Transfers."""

import logging

import stripe

from .db import Database
from .stripe_gateway import StripeGateway

log = logging.getLogger("tollgate")

MICROS_PER_CENT = 10_000


def pay_writers(db: Database, gateway: StripeGateway) -> list[dict]:
    """One result per writer with a balance. A failure for one writer doesn't stop the others.

    The idempotency key is tied to the writer's latest ledger entry. If a run dies after
    Stripe accepts a transfer but before it is recorded, the next run gets the same transfer
    back instead of paying twice. Sub-cent remainders stay in the balance.
    """
    results = []
    for writer in db.writers_with_balance():
        cents = writer["balance"] // MICROS_PER_CENT
        result = {"writer_id": writer["id"], "name": writer["name"], "cents": cents}
        results.append(result)
        if not writer["stripe_account_id"]:
            result["status"] = "no_stripe_account"
        elif cents < 1:
            result["status"] = "below_one_cent"
        else:
            try:
                transfer = gateway.create_transfer(
                    cents=cents,
                    destination=writer["stripe_account_id"],
                    idempotency_key=f"payout-{writer['id']}-{writer['last_entry']}",
                )
            except stripe.StripeError as exc:
                log.warning("transfer failed for writer %s: %s", writer["id"], exc.code)
                result.update(status="failed", reason=exc.user_message or exc.code or type(exc).__name__)
                continue
            db.record_transfer(writer["id"], cents * MICROS_PER_CENT, transfer)
            result.update(status="paid", transfer=transfer)
    return results
