"""Toll Gate API.

Free:   GET /catalog, GET /catalog/{id}, GET /ledger, GET /llms.txt, GET /.well-known/tollgate-receipt-key
MCP:    /mcp  (streamable HTTP, read-only discovery: search_catalog, get_article. No auth)
Paid:   GET /articles/{id}  (PAYMENT_RAIL=base: x402 v2, USDC on Base, to the treasury.
                             PAYMENT_RAIL=xrpl: x402 on XRPL testnet, or prepaid Stripe credit)
Writer: GET/PUT /me/payout, PUT /me/profile, GET /me/dashboard, POST /articles, POST /me/stripe/*
Agent:  POST /agents, GET /agents/me, POST /agents/me/topups
Stripe: POST /webhooks/stripe, GET /agents/topup/done
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import frontmatter
import stripe
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from x402_xrpl.facilitator import AsyncFacilitatorClient, FacilitatorClientOptions
from xrpl.core.addresscodec import is_valid_classic_address

from . import community_routes
from . import config
from .agent_mcp import build_mcp
from .content import content_hash, format_usd, preview_text, seed_articles, slugify, to_micros, to_xrp, usd_to_drops
from .db import Database
from .paywall import agent_name, paywall
from .rails.base_usdc import BaseUsdcRail
from .rails.settle import Settlements
from .rails.stripe_credit import StripeCreditRail, bearer_key, hash_key, new_api_key
from .rails.xrpl import XrplRail, pay_to_address
from .receipts import ReceiptSigner
from .session import DEMO_WRITER_EMAIL, DEMO_WRITER_ID, DEMO_WRITER_NAME, DemoAuth, SupabaseAuth, current_writer
from .storage import SupabaseStorage
from .stripe_gateway import StripeGateway

log = logging.getLogger("tollgate")

MAX_UPLOAD_BYTES = 2_000_000
MIN_TOPUP_MICROS = 1_000_000
MAX_TOPUP_MICROS = 500_000_000
MICROS_PER_CENT = 10_000
TEXT_UPLOADS = {".md", ".txt"}
UNSUPPORTED_UPLOADS = "Only .md and .txt files can be uploaded for now."
LICENSES = {
    "ai-input": "Read and cite in answers. No training.",
    "ai-train": "Read, cite and train. Training is priced separately (train_price_usd).",
}

PreviewMode = Literal["none", "w50", "w100", "p10"]
License = Literal["ai-input", "ai-train"]
Writer = Annotated[dict, Depends(current_writer)]


class ProfileUpdate(BaseModel):
    name: str


class AgentCreate(BaseModel):
    name: str


class TopUp(BaseModel):
    amount_usd: str


class PayoutUpdate(BaseModel):
    payout_method: Literal["xrpl"]  # Stripe is not available yet.
    xrpl_address: str


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


def pay_to_for(article: dict) -> str | None:
    """Where an agent's money goes: the treasury on Base, or the writer (or XRPL treasury) on XRPL."""
    return config.TREASURY_BASE_ADDRESS if config.PAYMENT_RAIL == "base" else pay_to_address(article)


def listing(article: dict) -> dict:
    """The free view of an article. The body must never be added here."""
    train = article["train_price_usd_micros"]
    drops = usd_to_drops(article["price_usd_micros"], config.XRP_USD_RATE)
    return {
        "id": article["id"],
        "title": article["title"],
        "author": article["author"],
        "abstract": article["abstract"],
        "preview": preview_text(article["body"], article["preview_mode"]),
        "preview_mode": article["preview_mode"],
        "keywords": article["keywords"],
        "tags": article["keywords"],
        "word_count": len(article["body"].split()),
        "price_usd": format_usd(article["price_usd_micros"]),
        "price_usd_micros": article["price_usd_micros"],
        "price_xrp": to_xrp(drops),
        "price_drops": drops,
        "license": article["license"],
        "train_price_usd": format_usd(train) if train else None,
        "allowed_agents": article["allowed_agents"],
        "pay_to": pay_to_for(article),
        "reads": article["reads"],
        "earned_usd": format_usd(article["earned_usd_micros"]),
        "earned_usd_micros": article["earned_usd_micros"],
        "created_at": article["created_at"],
        "url": f"{config.PUBLIC_URL}/articles/{article['id']}",
    }


def _stripe_status(writer: dict, gateway: StripeGateway | None) -> dict:
    return {
        "available": gateway is not None,
        "connected": bool(writer["stripe_details_submitted"]),
        "payouts_enabled": bool(writer["stripe_payouts_enabled"]),
    }


def _score(item: dict, query: str) -> int:
    """How many distinct query words the article contains. Any one is a match, so natural phrasing still finds it."""
    text = " ".join([item["title"], item["abstract"], item["author"], *item["keywords"]]).casefold()
    return sum(word in text for word in set(query.casefold().split()))


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _unique_id(db: Database, title: str) -> str:
    slug = slugify(title)
    candidate, n = slug, 2
    while db.article_exists(candidate):
        candidate, n = f"{slug}-{n}", n + 1
    return candidate


def _usd_field(name: str, value: str) -> int:
    try:
        return to_micros(value)
    except ValueError as exc:
        raise HTTPException(422, f"{name}: {exc}") from None


def _licenses() -> str:
    return "\n".join(f"- {name}: {meaning}" for name, meaning in LICENSES.items())


def _llms_txt() -> str:
    return _llms_txt_base() if config.PAYMENT_RAIL == "base" else _llms_txt_xrpl()


def _llms_txt_base() -> str:
    base = config.PUBLIC_URL
    return f"""# Toll Gate

Articles sold to AI agents per read. Prices are in US dollars and paid in USDC on Base.
Writers are paid by Toll Gate: your payment goes to Toll Gate's treasury, and the writer is credited in Toll Gate's ledger.

## Search (free)

GET {base}/catalog?q=<text>&sort=reads|earned|new
Returns title, author, abstract, free preview, keywords, price_usd, license and url for each article.
The preview is free to quote. The full text is paid.

## MCP (free, read-only)

{base}/mcp is a remote MCP server (streamable HTTP, no sign-in) with search_catalog(query) and get_article(id).
Each result has the paid url and the arguments for Coinbase payments-mcp's make_http_request_with_x402.

## Buy one read (x402 v2)

Network: {config.BASE_NETWORK} (Base mainnet). Asset: USDC. Scheme: exact. Pay to: {config.TREASURY_BASE_ADDRESS}.
The amount is the article's price_usd in USDC atomic units (6 decimals): $0.40 is 400000.

1. GET {base}/articles/<id> with an X-Agent-Name header naming your agent (for example "Claude").
2. The response is 402. The PAYMENT-REQUIRED header holds the x402 v2 challenge (base64 JSON): accepts[0] has scheme, network, amount, asset and payTo.
3. Sign the USDC authorization and repeat the GET with it in a PAYMENT-SIGNATURE header. Any x402 v2 client does steps 2 and 3, for example Coinbase's payments-mcp (make_http_request_with_x402) or the x402 SDKs.
4. The response is 200 with the article body and a signed receipt. The PAYMENT-RESPONSE header carries the settlement and transaction hash.

A 403 means the writer does not sell this article to your agent: check allowed_agents in the catalog first. A 404 means no such article. Neither costs anything.
Each read is charged, so keep your copy.

## Licenses

{_licenses()}

Each article's license field says which one applies.

## Receipts

Each purchase returns an Ed25519-signed receipt: article id, title, content hash, license, amount in USD, payer, agent, the Base transaction hash and its BaseScan link.
Cite the title, author and receipt when you use the text.
Verify the receipt with the public key at {base}/.well-known/tollgate-receipt-key.
The signature covers the payload as JSON with sorted keys and no whitespace.
"""


def _llms_txt_xrpl() -> str:
    base = config.PUBLIC_URL
    licenses = _licenses()
    return f"""# Toll Gate

Articles sold to AI agents per read. Prices are in US dollars.

## Search

GET {base}/catalog?q=<text>&sort=reads|earned|new
Free. Returns title, author, abstract, free preview, keywords, price, license and url for each article.

## Buy with x402

Network: {config.NETWORK} (XRP Ledger testnet). Asset: XRP, invoiced in drops at 1 XRP = ${config.XRP_USD_RATE} (placeholder rate).
The payment goes directly to the writer, or to a platform treasury that credits the writer if they have no XRPL address.

1. GET {base}/articles/<id>. Send an X-Agent-Name header with your name.
2. The response is 402 with the amount, recipient and invoice in accepts[0].
3. Sign an XRPL Payment for exactly that amount to that recipient. Copy SourceTag and InvoiceID from accepts[0].extra.
4. Repeat the GET with the signed payment in a PAYMENT-SIGNATURE header.
5. The response is 200 with the article body and a signed receipt, and the payment has settled.

The x402-xrpl Python SDK does steps 2 to 4: x402_xrpl.clients.x402_purchase(url, wallet=..., max_value=<drops>).
A 403 means the writer does not sell this article to your agent. Check allowed_agents in the catalog first.

## Buy with prepaid credit (stripe-credit, test mode)

For agents that don't hold crypto. The 402 response also lists this under `alternatives`.

1. POST {base}/agents with {{"name": "<your name>"}}. The response has your API key, shown once.
2. POST {base}/agents/me/topups with {{"amount_usd": "10"}} and Authorization: Bearer <key>. A human opens checkout_url and pays by card.
3. GET {base}/articles/<id> with Authorization: Bearer <key>. The response is 200 with the article body and a signed receipt, and the price is debited from your credit.

Send X-Max-Price-Usd to refuse any price above your limit (409). A 402 here means your credit is too low. GET {base}/agents/me shows your balance.
Each read is charged, so keep your copy. Writers accrue the same amount and are paid out through Stripe Connect.

## Licenses

{licenses}

Each article's license field says which one applies.

## Receipts

Each purchase returns an Ed25519-signed receipt with the rail, article id, content hash, license and amount, plus the transaction hash on XRPL or the credit reference on Stripe.
Verify it with the public key at {base}/.well-known/tollgate-receipt-key.
The signature covers the payload as JSON with sorted keys and no whitespace.
"""


def _default_auth():
    if config.AUTH_MODE == "demo":
        return DemoAuth()
    if not (config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY):
        raise RuntimeError("SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are required when AUTH_MODE is supabase")
    return SupabaseAuth(config.SUPABASE_URL, config.SUPABASE_PUBLISHABLE_KEY)


def _default_base_facilitator():
    """The CDP facilitator, authenticated with the CDP API key. Needed for Base mainnet."""
    if not (config.CDP_API_KEY_ID and config.CDP_API_KEY_SECRET):
        raise RuntimeError("CDP_API_KEY_ID and CDP_API_KEY_SECRET are required when PAYMENT_RAIL is base")
    from cdp.x402 import create_facilitator_config
    from x402.http import HTTPFacilitatorClient

    return HTTPFacilitatorClient(create_facilitator_config(config.CDP_API_KEY_ID, config.CDP_API_KEY_SECRET))


def _payment_info() -> dict:
    if config.PAYMENT_RAIL == "base":
        return {"rail": "base", "protocol": "x402 v2", "scheme": "exact", "network": config.BASE_NETWORK,
                "asset": "USDC", "pay_to": config.TREASURY_BASE_ADDRESS, "explorer_tx": config.BASESCAN_TX,
                "fee_bps": config.PLATFORM_FEE_BPS}
    return {"rail": "xrpl", "protocol": "x402", "scheme": "exact", "network": config.NETWORK, "asset": "XRP",
            "explorer_tx": config.EXPLORER_TX}


def _default_stripe() -> StripeGateway | None:
    if config.STRIPE_SECRET_KEY:
        return StripeGateway(config.STRIPE_SECRET_KEY, config.STRIPE_WEBHOOK_SECRET)
    return None


def _default_storage() -> SupabaseStorage | None:
    if config.AUTH_MODE == "supabase" and config.SUPABASE_SERVICE_ROLE_KEY:
        return SupabaseStorage(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return None


def create_app(
    facilitator: AsyncFacilitatorClient | None = None,
    *,
    database: Path | str | None = None,
    content_dir: Path | None = None,
    auth=None,
    storage: SupabaseStorage | None = None,
    stripe_gateway: StripeGateway | None = None,
    base_facilitator=None,
) -> FastAPI:
    auth = auth or _default_auth()
    on_base = config.PAYMENT_RAIL == "base"
    if isinstance(auth, DemoAuth) and not on_base and not config.WRITER_ADDRESS:
        raise RuntimeError("WRITER_ADDRESS missing — run `make wallets` first")

    db = Database(database or config.database_target())
    storage = storage or _default_storage()
    gateway = stripe_gateway or _default_stripe()
    seeds = seed_articles(content_dir or config.CONTENT_DIR, DEMO_WRITER_ID, config.XRP_USD_RATE)
    # Demo mode needs its writer to sign in as. Otherwise it only exists to own seeded articles.
    if isinstance(auth, DemoAuth) or seeds:
        db.ensure_writer(
            id=DEMO_WRITER_ID, name=DEMO_WRITER_NAME, email=DEMO_WRITER_EMAIL, xrpl_address=config.WRITER_ADDRESS or None
        )
    for row in seeds:
        if not db.article_exists(row["id"]):
            db.add_article(row)

    signer = ReceiptSigner(_signing_key())

    def catalog_items(q: str | None = None, sort: str = "reads") -> list[dict]:
        items = [listing(a) for a in db.articles(sort)]
        if not q:
            return items
        # Best match first; ties keep the requested sort. The MCP shows only the top results.
        scored = [(score, i) for i in items if (score := _score(i, q))]
        return [i for _, i in sorted(scored, key=lambda pair: -pair[0])]

    def catalog_entry(article_id: str) -> dict | None:
        a = db.article(article_id)
        return listing(a) if a else None

    # The Toll Gate MCP for remote clients (e.g. a Claude custom connector), on the same catalog.
    # Read-only and public, so no auth. Stateless with JSON replies: any instance can answer, nothing to resume.
    # DNS-rebinding protection is for servers on a user's own machine; this one is public by design.
    agent_mcp = build_mcp(
        lambda q: run_in_threadpool(catalog_items, q),
        lambda article_id: run_in_threadpool(catalog_entry, article_id),
    )
    mcp_http = agent_mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with agent_mcp.session_manager.run():
            yield

    app = FastAPI(title="Toll Gate", lifespan=lifespan)
    app.include_router(community_routes.routes(db))
    app.state.db, app.state.signer, app.state.auth = db, signer, auth
    app.router.routes.extend(mcp_http.routes)

    settlements = Settlements(db, signer)
    if on_base:
        # The demo path: one rail, no Stripe. XRPL stays in the code as the fallback.
        rails = [BaseUsdcRail(
            base_facilitator or _default_base_facilitator(), settlements, agent_name,
            pay_to=config.TREASURY_BASE_ADDRESS, network=config.BASE_NETWORK, fee_bps=config.PLATFORM_FEE_BPS,
        )]
    else:
        facilitator = facilitator or AsyncFacilitatorClient(
            FacilitatorClientOptions(base_url=config.FACILITATOR_URL, timeout_seconds=60)
        )
        # First match wins, and the XRPL rail takes anything, so it goes last.
        rails = [XrplRail(facilitator, settlements, agent_name)]
        if gateway:
            rails.insert(0, StripeCreditRail(db, settlements))
    app.state.rails = rails
    app.middleware("http")(paywall(db, rails))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.WEB_URL],  # TOLLGATE_WEB_URL, http://localhost:3000 by default.
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["PAYMENT-REQUIRED", "PAYMENT-RESPONSE"],
    )

    # --- public routes ---
    @app.get("/health")
    def health():
        payment = _payment_info()
        return {"ok": True, "articles": len(db.articles()), "network": payment["network"], "payment": payment}

    @app.get("/catalog")
    def catalog(q: str | None = None, sort: Literal["reads", "earned", "new"] = "reads"):
        return {"articles": catalog_items(q, sort)}

    @app.get("/catalog/{article_id}")
    def catalog_item(article_id: str):
        """One article's free view. Never paid."""
        item = catalog_entry(article_id)
        if not item:
            raise HTTPException(404, "unknown article")
        return item

    @app.get("/articles/{article_id}")
    def read_article(article_id: str):
        a = db.article(article_id)
        if not a:
            raise HTTPException(404, "unknown article")
        return {
            "id": a["id"],
            "title": a["title"],
            "author": a["author"],
            "license": a["license"],
            "content_hash": content_hash(a["body"]),
            "body": a["body"],
        }

    @app.get("/ledger")
    def get_ledger(limit: int = 50):
        return {"purchases": db.recent(limit), "earnings": db.earnings()}

    @app.get("/.well-known/tollgate-receipt-key")
    def receipt_key():
        return {"alg": "ed25519", "public_key": signer.public_key_hex}

    @app.get("/llms.txt", response_class=PlainTextResponse)
    def llms_txt():
        return _llms_txt()

    # --- agent accounts ---
    def _require_stripe() -> StripeGateway:
        if not gateway:
            raise HTTPException(503, "Stripe is not configured on this server.")
        return gateway

    def _current_agent(request: Request) -> dict:
        key = bearer_key(request)
        agent = db.agent_by_key_hash(hash_key(key)) if key else None
        if not agent:
            raise HTTPException(401, "A valid agent key is required.")
        return agent

    def _apply_checkout(session: dict) -> None:
        """Credit a paid session, once. The amount comes from Stripe, never from the request."""
        agent_id = session["metadata"].get("agent_id")
        if session["livemode"]:
            log.warning("ignored a live-mode checkout session")
        elif session["payment_status"] == "paid" and agent_id and db.agent(agent_id):
            db.add_credit(agent_id, session["amount_total"] * MICROS_PER_CENT, session["id"])

    @app.post("/agents", status_code=201)
    def create_agent(body: AgentCreate):
        name = body.name.strip()[:64]
        if not name:
            raise HTTPException(422, "A name is required.")
        key = new_api_key()
        agent = db.create_agent(name=name, api_key_hash=hash_key(key))
        return {**agent, "api_key": key, "note": "Shown once. Store it now."}

    @app.get("/agents/me")
    def get_agent(request: Request):
        agent = _current_agent(request)
        return {
            "name": agent["name"],
            "credit_usd": format_usd(agent["credit_usd_micros"]),
            "credit_usd_micros": agent["credit_usd_micros"],
        }

    @app.post("/agents/me/topups")
    def create_topup(body: TopUp, request: Request):
        agent = _current_agent(request)
        stripe_api = _require_stripe()
        micros = _usd_field("amount_usd", body.amount_usd)
        if not MIN_TOPUP_MICROS <= micros <= MAX_TOPUP_MICROS or micros % MICROS_PER_CENT:
            raise HTTPException(422, "Top up between $1 and $500, in whole cents.")
        url = stripe_api.create_checkout(
            agent_id=agent["id"],
            cents=micros // MICROS_PER_CENT,
            success_url=f"{config.PUBLIC_URL}/agents/topup/done?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{config.PUBLIC_URL}/agents/topup/cancelled",
        )
        return {"checkout_url": url}

    @app.get("/agents/topup/done", response_class=PlainTextResponse)
    def topup_done(session_id: str):
        """Also credits, so a top-up still lands if the webhook listener isn't running."""
        try:
            _apply_checkout(_require_stripe().retrieve_checkout(session_id))
        except stripe.StripeError:
            raise HTTPException(404, "Unknown checkout session.") from None
        return "Payment received. Credit added. You can close this page."

    @app.get("/agents/topup/cancelled", response_class=PlainTextResponse)
    def topup_cancelled():
        return "Top-up cancelled. Nothing was charged."

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request):
        stripe_api = _require_stripe()
        if not stripe_api.webhook_secret:
            raise HTTPException(503, "STRIPE_WEBHOOK_SECRET is not set.")
        payload = await request.body()
        try:
            session = await run_in_threadpool(
                stripe_api.checkout_from_webhook, payload, request.headers.get("Stripe-Signature")
            )
        except (stripe.SignatureVerificationError, ValueError):
            raise HTTPException(400, "Invalid signature.") from None
        if session:
            await run_in_threadpool(_apply_checkout, session)
        return {"received": True}

    # --- writer routes ---
    @app.get("/me/payout")
    def get_payout(writer: Writer):
        return {
            **{k: writer[k] for k in ("name", "email", "payout_method", "xrpl_address")},
            "stripe": _stripe_status(writer, gateway),
            "payment": _payment_info(),
            "balance_usd_micros": db.writer_balance(writer["id"]),
        }

    @app.put("/me/profile")
    def put_profile(update: ProfileUpdate, writer: Writer):
        name = update.name.strip()
        if not name or len(name) > 100:
            raise HTTPException(422, "Enter a name of up to 100 characters.")
        db.set_name(writer["id"], name)
        return {"name": name}

    @app.put("/me/payout")
    def put_payout(update: PayoutUpdate, writer: Writer):
        address = update.xrpl_address.strip()
        if not is_valid_classic_address(address):
            raise HTTPException(422, "That is not a valid XRP Ledger address.")
        db.set_payout(writer["id"], payout_method=update.payout_method, xrpl_address=address)
        return {"payout_method": update.payout_method, "xrpl_address": address}

    @app.post("/me/stripe/onboarding")
    def stripe_onboarding(writer: Writer):
        stripe_api = _require_stripe()
        account = writer["stripe_account_id"]
        if not account:
            account = stripe_api.create_connected_account(writer["email"] or f"writer-{writer['id']}@tollgate.local")
            db.set_stripe_account(writer["id"], account)
        back = f"{config.WEB_URL}/onboarding/payout"
        url = stripe_api.onboarding_link(account, refresh_url=f"{back}?stripe=refresh", return_url=f"{back}?stripe=return")
        return {"url": url}

    @app.post("/me/stripe/refresh")
    def stripe_refresh(writer: Writer):
        """Called on return from Stripe. Reading it here avoids needing Connect webhooks locally."""
        stripe_api = _require_stripe()
        if not writer["stripe_account_id"]:
            return _stripe_status(writer, gateway)
        status = stripe_api.account_status(writer["stripe_account_id"])
        db.set_stripe_status(writer["id"], **status)
        return _stripe_status(db.writer(writer["id"]), gateway)

    @app.get("/me/dashboard")
    def dashboard(writer: Writer):
        return {
            "writer": {"name": writer["name"]},
            "payout": {
                "method": writer["payout_method"],
                "xrpl_address": writer["xrpl_address"],
                "stripe": _stripe_status(writer, gateway),
            },
            "xrp_usd_rate": str(config.XRP_USD_RATE),
            "payment": _payment_info(),
            **db.dashboard(writer["id"]),
        }

    @app.post("/articles", status_code=201)
    async def create_article(
        writer: Writer,
        file: Annotated[UploadFile, File()],
        price_usd: Annotated[str, Form()],
        title: Annotated[str, Form()] = "",
        abstract: Annotated[str, Form()] = "",
        preview_mode: Annotated[PreviewMode, Form()] = "w50",
        keywords: Annotated[str, Form()] = "",
        license: Annotated[License, Form()] = "ai-input",
        train_price_usd: Annotated[str, Form()] = "",
        allowed_agents: Annotated[str, Form()] = "*",
    ):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in TEXT_UPLOADS:
            raise HTTPException(415, UNSUPPORTED_UPLOADS)
        raw = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "The file is larger than 2 MB.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "The file must be UTF-8 text.") from None

        meta: dict = {}
        body = text
        if suffix == ".md":
            try:
                post = frontmatter.loads(text)
            except Exception:
                raise HTTPException(422, "The file's frontmatter could not be read.") from None
            meta, body = post.metadata, post.content
        body = body.strip()
        if not body:
            raise HTTPException(422, "The file has no text.")

        final_title = title.strip() or str(meta.get("title", "")).strip()
        if not final_title:
            raise HTTPException(422, "A title is required.")
        agents = _split_list(allowed_agents)
        if not agents:
            raise HTTPException(422, "Choose at least one agent.")
        train_micros = None
        if license == "ai-train":
            train_micros = _usd_field("train_price_usd", train_price_usd)

        article_id = _unique_id(db, final_title)
        db.add_article({
            "id": article_id,
            "writer_id": writer["id"],
            "title": final_title[:200],
            "abstract": abstract.strip() or str(meta.get("abstract", "")).strip(),
            "body": body,
            "preview_mode": preview_mode,
            "keywords": _split_list(keywords),
            "price_usd_micros": _usd_field("price_usd", price_usd),
            "license": license,
            "train_price_usd_micros": train_micros,
            "allowed_agents": ["*"] if "*" in agents else agents,
        })
        if storage:
            path = f"{writer['id']}/{article_id}/original{suffix}"
            if await storage.save(path, raw, file.content_type or "text/plain"):
                db.set_storage_path(article_id, path)
        return listing(db.article(article_id))

    return app


app = create_app() if os.getenv("TOLLGATE_NO_AUTOAPP") != "1" else None
