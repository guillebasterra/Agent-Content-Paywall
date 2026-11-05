"""Toll Gate API.

Free:   GET /catalog, GET /ledger, GET /llms.txt, GET /.well-known/tollgate-receipt-key
Paid:   GET /articles/{id}  (x402 over XRPL; payment goes straight to the writer)
Writer: GET/PUT /me/payout, PUT /me/profile, GET /me/dashboard, POST /articles
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Annotated, Literal

import frontmatter
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from x402_xrpl.clients.base import decode_payment_response
from x402_xrpl.facilitator import AsyncFacilitatorClient, FacilitatorClientOptions
from x402_xrpl.types import PaymentPayload
from xrpl.core.addresscodec import is_valid_classic_address

from . import config
from .content import content_hash, preview_text, seed_articles, slugify, to_drops, to_xrp
from .db import Database
from .paywall import agent_name, article_id_from, paywall
from .receipts import ReceiptSigner
from .session import DEMO_WRITER_EMAIL, DEMO_WRITER_ID, DEMO_WRITER_NAME, DemoAuth, SupabaseAuth, current_writer
from .storage import SupabaseStorage

log = logging.getLogger("tollgate")

MAX_UPLOAD_BYTES = 2_000_000
TEXT_UPLOADS = {".md", ".txt"}
UNSUPPORTED_UPLOADS = "Only .md and .txt files can be uploaded for now."
LICENSES = {
    "ai-input": "Read and cite in answers. No training.",
    "ai-train": "Read, cite and train. Training is priced separately (train_price_xrp).",
}

PreviewMode = Literal["none", "w50", "w100", "p10"]
License = Literal["ai-input", "ai-train"]
Writer = Annotated[dict, Depends(current_writer)]


class ProfileUpdate(BaseModel):
    name: str


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


def listing(article: dict) -> dict:
    """The free view of an article. The body must never be added here."""
    train = article["train_price_drops"]
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
        "price_xrp": to_xrp(article["price_drops"]),
        "price_drops": article["price_drops"],
        "license": article["license"],
        "train_price_xrp": to_xrp(train) if train else None,
        "train_price_drops": train,
        "allowed_agents": article["allowed_agents"],
        "pay_to": article["pay_to"],
        "reads": article["reads"],
        "earned_drops": article["earned_drops"],
        "earned_xrp": to_xrp(article["earned_drops"]) if article["earned_drops"] else "0",
        "created_at": article["created_at"],
        "url": f"{config.PUBLIC_URL}/articles/{article['id']}",
    }


def _matches(item: dict, query: str) -> bool:
    """Any word of the query counts, so an agent's natural phrasing still finds the piece."""
    text = " ".join([item["title"], item["abstract"], item["author"], *item["keywords"]]).casefold()
    return any(word in text for word in query.casefold().split())


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _unique_id(db: Database, title: str) -> str:
    slug = slugify(title)
    candidate, n = slug, 2
    while db.article_exists(candidate):
        candidate, n = f"{slug}-{n}", n + 1
    return candidate


def _drops_field(name: str, value: str) -> int:
    try:
        return to_drops(value)
    except ValueError as exc:
        raise HTTPException(422, f"{name}: {exc}") from None


def _llms_txt() -> str:
    base = config.PUBLIC_URL
    licenses = "\n".join(f"- {name}: {meaning}" for name, meaning in LICENSES.items())
    return f"""# Toll Gate

Articles sold to AI agents per read. Each payment goes directly to the writer.

## Search

GET {base}/catalog?q=<text>&sort=reads|earned|new
Free. Returns title, author, abstract, free preview, keywords, price, license and url for each article.

## Buy with x402

Network: {config.NETWORK} (XRP Ledger testnet). Asset: XRP, priced in drops.

1. GET {base}/articles/<id>. Send an X-Agent-Name header with your name.
2. The response is 402 with the amount, recipient and invoice in accepts[0].
3. Sign an XRPL Payment for exactly that amount to that recipient. Copy SourceTag and InvoiceID from accepts[0].extra.
4. Repeat the GET with the signed payment in a PAYMENT-SIGNATURE header.
5. The response is 200 with the article body and a signed receipt, and the payment has settled.

The x402-xrpl Python SDK does steps 2 to 4: x402_xrpl.clients.x402_purchase(url, wallet=..., max_value=<drops>).
A 403 means the writer does not sell this article to your agent. Check allowed_agents in the catalog first.

## Licenses

{licenses}

Each article's license field says which one applies.

## Receipts

Each purchase returns an Ed25519-signed receipt with the article id, content hash, license, price and transaction hash.
Verify it with the public key at {base}/.well-known/tollgate-receipt-key.
The signature covers the payload as JSON with sorted keys and no whitespace.
"""


def _default_auth():
    if config.AUTH_MODE == "demo":
        return DemoAuth()
    if not (config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY):
        raise RuntimeError("SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY are required when AUTH_MODE is supabase")
    return SupabaseAuth(config.SUPABASE_URL, config.SUPABASE_PUBLISHABLE_KEY)


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
) -> FastAPI:
    if not config.WRITER_ADDRESS:
        raise RuntimeError("WRITER_ADDRESS missing — run `make wallets` first")

    db = Database(database or config.database_target())
    auth = auth or _default_auth()
    storage = storage or _default_storage()
    seeds = seed_articles(content_dir or config.CONTENT_DIR, DEMO_WRITER_ID)
    # Demo mode needs its writer to sign in as. Otherwise it only exists to own seeded articles.
    if isinstance(auth, DemoAuth) or seeds:
        db.ensure_writer(
            id=DEMO_WRITER_ID, name=DEMO_WRITER_NAME, email=DEMO_WRITER_EMAIL, xrpl_address=config.WRITER_ADDRESS
        )
    for row in seeds:
        if not db.article_exists(row["id"]):
            db.add_article(row)

    signer = ReceiptSigner(_signing_key())
    facilitator = facilitator or AsyncFacilitatorClient(
        FacilitatorClientOptions(base_url=config.FACILITATOR_URL, timeout_seconds=60)
    )

    app = FastAPI(title="Toll Gate")
    app.state.db, app.state.signer, app.state.auth = db, signer, auth

    app.middleware("http")(paywall(db, facilitator))

    # --- receipts: runs outside the paywall, after settlement succeeded ---
    @app.middleware("http")
    async def attach_receipt(request: Request, call_next):
        response = await call_next(request)
        settled = response.headers.get("PAYMENT-RESPONSE")
        article_id = article_id_from(request)
        article = db.article(article_id) if article_id else None
        if response.status_code != 200 or not settled or article is None:
            return response

        settlement = decode_payment_response(settled)
        # What the buyer actually signed. The writer may have changed payout address
        # since the invoice was issued, so the database can't say where the money went.
        signed = json.loads(base64.b64decode(request.headers["PAYMENT-SIGNATURE"]))
        accepted = PaymentPayload.from_dict(signed).accepted
        price_drops = int(accepted.amount)

        receipt = signer.sign({
            "article_id": article["id"],
            "title": article["title"],
            "content_hash": content_hash(article["body"]),
            "license": article["license"],
            "price_drops": price_drops,
            "pay_to": accepted.pay_to,
            "payer": settlement.get("payer"),
            "network": settlement.get("network"),
            "tx_hash": settlement.get("transaction"),
            "explorer": config.EXPLORER_TX + str(settlement.get("transaction")),
        })
        db.record(
            tx_hash=settlement.get("transaction"),
            article_id=article["id"],
            payer=settlement.get("payer"),
            pay_to=accepted.pay_to,
            price_drops=price_drops,
            network=settlement.get("network") or config.NETWORK,
            receipt=receipt,
            agent=agent_name(request),
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

    # --- public routes ---
    @app.get("/health")
    def health():
        return {"ok": True, "articles": len(db.articles()), "network": config.NETWORK}

    @app.get("/catalog")
    def catalog(q: str | None = None, sort: Literal["reads", "earned", "new"] = "reads"):
        items = [listing(a) for a in db.articles(sort)]
        if q:
            items = [i for i in items if _matches(i, q)]
        return {"articles": items}

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

    # --- writer routes ---
    @app.get("/me/payout")
    def get_payout(writer: Writer):
        return {k: writer[k] for k in ("name", "email", "payout_method", "xrpl_address")}

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

    @app.get("/me/dashboard")
    def dashboard(writer: Writer):
        return {
            "writer": {"name": writer["name"]},
            "payout": {"method": writer["payout_method"], "xrpl_address": writer["xrpl_address"]},
            **db.dashboard(writer["id"]),
        }

    @app.post("/articles", status_code=201)
    async def create_article(
        writer: Writer,
        file: Annotated[UploadFile, File()],
        price_xrp: Annotated[str, Form()],
        title: Annotated[str, Form()] = "",
        abstract: Annotated[str, Form()] = "",
        preview_mode: Annotated[PreviewMode, Form()] = "w50",
        keywords: Annotated[str, Form()] = "",
        license: Annotated[License, Form()] = "ai-input",
        train_price_xrp: Annotated[str, Form()] = "",
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
        train_drops = None
        if license == "ai-train":
            train_drops = _drops_field("train_price_xrp", train_price_xrp)

        article_id = _unique_id(db, final_title)
        db.add_article({
            "id": article_id,
            "writer_id": writer["id"],
            "title": final_title[:200],
            "abstract": abstract.strip() or str(meta.get("abstract", "")).strip(),
            "body": body,
            "preview_mode": preview_mode,
            "keywords": _split_list(keywords),
            "price_drops": _drops_field("price_xrp", price_xrp),
            "license": license,
            "train_price_drops": train_drops,
            "allowed_agents": ["*"] if "*" in agents else agents,
        })
        if storage:
            path = f"{writer['id']}/{article_id}/original{suffix}"
            if await storage.save(path, raw, file.content_type or "text/plain"):
                db.set_storage_path(article_id, path)
        return listing(db.article(article_id))

    return app


app = create_app() if os.getenv("TOLLGATE_NO_AUTOAPP") != "1" else None
