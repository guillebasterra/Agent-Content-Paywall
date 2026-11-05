"""Where every rail ends: sign the receipt, then record the purchase and any ledger entries."""

import json

from starlette.responses import Response

from ..content import content_hash, format_usd
from ..db import Database
from ..receipts import ReceiptSigner
from .base import Sale


class Settlements:
    def __init__(self, db: Database, signer: ReceiptSigner):
        self.db = db
        self.signer = signer

    def receipt(self, sale: Sale) -> dict:
        article = sale.article
        return self.signer.sign({
            "rail": sale.rail,
            "article_id": article["id"],
            "title": article["title"],
            "content_hash": content_hash(article["body"]),
            "license": article["license"],
            "amount_usd": format_usd(sale.amount_usd_micros),
            "pay_to": sale.pay_to,
            "payer": sale.payer,
            "network": sale.network,
            **sale.receipt_fields,
        })

    def record(self, sale: Sale, receipt: dict, *, debit_agent_id: str | None = None) -> bool:
        """False only when a debit was asked for and the agent's credit can't cover it."""
        return self.db.record_purchase(
            ref=sale.ref,
            rail=sale.rail,
            article_id=sale.article["id"],
            writer_id=sale.article["writer_id"],
            payer=sale.payer,
            pay_to=sale.pay_to,
            amount_usd_micros=sale.amount_usd_micros,
            amount_native=sale.amount_native,
            network=sale.network,
            receipt=receipt,
            agent=sale.agent,
            credit_writer=sale.credit_writer,
            debit_agent_id=debit_agent_id,
        )


async def response_json(response: Response) -> dict:
    """Read a JSON response, whether it was built whole or came streaming from the app."""
    body = getattr(response, "body", None)
    if body is None:
        body = b"".join([chunk async for chunk in response.body_iterator])
    return json.loads(body)


def with_json(response: Response, data: dict) -> Response:
    """The same response with a new JSON body, keeping status and headers."""
    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
    return Response(json.dumps(data), status_code=response.status_code, headers=headers, media_type="application/json")
