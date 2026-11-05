"""Every call Toll Gate makes to Stripe, in one place tests can replace. Test mode only."""

import stripe

TEST_KEY_PREFIXES = ("sk_test_", "rk_test_")
# Express dashboards with Stripe-managed risk are in public preview on Accounts v2.
ACCOUNTS_PREVIEW = {"stripe_version": "2026-10-28.preview"}


def require_test_key(key: str) -> str:
    if not key.startswith(TEST_KEY_PREFIXES):
        raise RuntimeError("STRIPE_SECRET_KEY must be a test key (sk_test_...). Live keys are refused.")
    return key


class StripeGateway:
    def __init__(self, secret_key: str, webhook_secret: str = ""):
        self.client = stripe.StripeClient(require_test_key(secret_key))
        self.webhook_secret = webhook_secret

    def create_checkout(self, *, agent_id: str, cents: int, success_url: str, cancel_url: str) -> str:
        session = self.client.v1.checkout.sessions.create(params={
            "mode": "payment",
            "line_items": [{
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": cents,
                    "product_data": {"name": "Toll Gate agent credit"},
                },
            }],
            "metadata": {"agent_id": agent_id},
            "success_url": success_url,
            "cancel_url": cancel_url,
        })
        return session.url

    def retrieve_checkout(self, session_id: str) -> dict:
        session = self.client.v1.checkout.sessions.retrieve(session_id)
        return {
            "id": session.id,
            "payment_status": session.payment_status,
            "amount_total": session.amount_total,
            "metadata": session.metadata.to_dict() if session.metadata else {},
            "livemode": session.livemode,
        }

    def checkout_from_webhook(self, payload: bytes, signature: str | None) -> dict | None:
        """The session in a verified checkout.session.completed event. Raises on a bad signature."""
        event = stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
        if event.type != "checkout.session.completed":
            return None
        return self.retrieve_checkout(event.data.object["id"])

    def create_connected_account(self, email: str) -> str:
        """Accounts v2. Stripe refuses v1 `type=express` for new platforms, and refuses a recipient-only
        account unless the platform takes on losses, so this is merchant + recipient with Stripe managing risk."""
        return self.client.v2.core.accounts.create(
            params={
                "contact_email": email,
                "identity": {"country": "US"},
                "dashboard": "express",
                "defaults": {"responsibilities": {"fees_collector": "stripe", "losses_collector": "stripe"}},
                "configuration": {
                    "merchant": {"capabilities": {"card_payments": {"requested": True}}},
                    "recipient": {"capabilities": {"stripe_balance": {"stripe_transfers": {"requested": True}}}},
                },
            },
            options=ACCOUNTS_PREVIEW,
        ).id

    def onboarding_link(self, account_id: str, *, refresh_url: str, return_url: str) -> str:
        return self.client.v1.account_links.create(params={
            "account": account_id,
            "type": "account_onboarding",
            "refresh_url": refresh_url,
            "return_url": return_url,
        }).url

    def account_status(self, account_id: str) -> dict:
        details = self.client.v1.accounts.retrieve(account_id).details_submitted
        account = self.client.v2.core.accounts.retrieve(account_id, params={"include": ["configuration.recipient"]})
        transfers = account.configuration.recipient.capabilities.stripe_balance.stripe_transfers.status
        return {"details_submitted": bool(details), "payouts_enabled": transfers == "active"}

    def create_transfer(self, *, cents: int, destination: str, idempotency_key: str) -> str:
        return self.client.v1.transfers.create(
            params={"amount": cents, "currency": "usd", "destination": destination},
            options={"idempotency_key": idempotency_key},
        ).id
