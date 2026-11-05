import hashlib
import json
import secrets
import time
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from nacl.secret import SecretBox
from pydantic import BaseModel, Field, StrictInt
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet, generate_faucet_wallet
from x402_xrpl.clients import x402_purchase
from x402_xrpl.clients.base import decode_payment_response
from x402_xrpl.facilitator import AsyncFacilitatorClient, FacilitatorClientOptions
from x402_xrpl.server import require_payment

from .content import load_articles
from .receipts import ReceiptSigner, verify
from .storage import Store
from .observability import event, install_request_logging

COOKIE = "tg_session"
BUDGET = 5_000_000
CAP = 1_000_000
SESSION_TTL = 30 * 86400


class PurchaseRequest(BaseModel):
    article_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z0-9_-]+$")
    max_price_drops: StrictInt = Field(gt=0, le=CAP)
    request_id: UUID


class Service:
    def __init__(self, settings, store=None):
        self.settings = settings
        self.store = store or Store(settings.database_url)
        self.box = SecretBox(bytes.fromhex(settings.encryption_key))
        self.signer = ReceiptSigner(settings.signing_key)
        self.articles = load_articles(settings.content_dir, settings.writer_address)

    def session(self, token):
        if not token or len(token) > 200:
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM tg_sessions WHERE id=? AND created_at>?",
                (key, int(time.time()) - SESSION_TTL),
            ).fetchone()
        return dict(row) if row else None

    def create_session(self, ip):
        now = int(time.time())
        # Atomically rate-limit provisioning, including failed faucet attempts.
        buckets = [
            (f"global:{now // 86400}", 100),
            (f"ip:{hashlib.sha256(ip.encode()).hexdigest()}:{now // 86400}", 3),
        ]
        with self.store.transaction() as db:
            for bucket, limit in buckets:
                db.execute(
                    "INSERT INTO tg_rates(id,count) VALUES (?,1) ON CONFLICT(id) DO UPDATE SET count=tg_rates.count+1",
                    (bucket,),
                )
                count = db.execute(
                    "SELECT count FROM tg_rates WHERE id=?", (bucket,)
                ).fetchone()["count"]
                if count > limit:
                    raise HTTPException(
                        429, "Daily preview limit reached. Please try again tomorrow."
                    )
        try:
            wallet = generate_faucet_wallet(JsonRpcClient(self.settings.rpc_url))
        except Exception:
            raise HTTPException(
                503, "Testnet is busy. Please try starting your wallet again later."
            ) from None
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode()).hexdigest()
        encrypted = self.box.encrypt(wallet.seed.encode()).hex()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO tg_sessions(id,seed,address,created_at) VALUES (?,?,?,?)",
                (key, encrypted, wallet.address, now),
            )
        return token

    def remaining(self, session):
        if not session:
            return 0
        with self.store.transaction() as db:
            total = db.execute(
                "SELECT COALESCE(SUM(cap),0) AS spent FROM tg_requests WHERE session_id=?",
                (session["id"],),
            ).fetchone()["spent"]
        return max(0, BUDGET - total)

    def validate_result(self, data, article, address, cap):
        receipt = data["receipt"]
        payload = receipt["payload"]
        digest = "sha256:" + hashlib.sha256(data["body"].encode()).hexdigest()
        if not (
            verify(receipt, self.signer.public_key_hex)
            and payload["article_id"] == data["id"] == article.id
            and payload["payer"] == address
            and payload["pay_to"] == article.pay_to
            and payload["content_hash"] == data["content_hash"] == digest
            and payload["price_drops"] == article.price_drops <= cap
            and payload["network"] == "xrpl:1"
            and payload.get("tx_hash")
        ):
            raise ValueError("Invalid receipt")
        return {**data, "receipt_verified": True}

    def library(self, session):
        if not session:
            return []
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT * FROM tg_requests WHERE session_id=? ORDER BY created_at DESC",
                (session["id"],),
            ).fetchall()
        for row in rows:
            if row["status"] != "pending":
                continue
            # If settlement finished but the buyer request timed out, recover the
            # paid response from the writer's durable settlement ledger.
            with self.store.transaction() as db:
                settled = db.execute(
                    "SELECT result FROM tg_ledger WHERE payer=? AND article_id=? AND created_at>=? ORDER BY created_at DESC LIMIT 1",
                    (session["address"], row["article_id"], row["created_at"]),
                ).fetchone()
            if settled:
                try:
                    result = self.validate_result(
                        json.loads(settled["result"]),
                        self.articles[row["article_id"]],
                        session["address"],
                        row["cap"],
                    )
                except (KeyError, ValueError):
                    continue
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE tg_requests SET status='complete',result=? WHERE id=? AND session_id=?",
                        (json.dumps(result), row["id"], session["id"]),
                    )
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT id,article_id,status,result FROM tg_requests WHERE session_id=? ORDER BY created_at DESC",
                (session["id"],),
            ).fetchall()
        return [
            {
                "request_id": r["id"],
                "article_id": r["article_id"],
                "status": r["status"],
                "purchase": json.loads(r["result"]) if r["result"] else None,
            }
            for r in rows
        ]

    def purchase(self, session, request):
        article = self.articles.get(request.article_id)
        if not article:
            raise HTTPException(404, "Article not found.")
        request_id = str(request.request_id)
        now = int(time.time())
        with self.store.transaction() as db:
            db.lock_session(session["id"])
            prior = db.execute(
                "SELECT * FROM tg_requests WHERE id=?", (request_id,)
            ).fetchone()
            if prior:
                if (
                    prior["session_id"] != session["id"]
                    or prior["article_id"] != request.article_id
                    or prior["cap"] != request.max_price_drops
                ):
                    raise HTTPException(409, "This request ID has already been used.")
                if prior["result"]:
                    return json.loads(prior["result"])
                raise HTTPException(
                    409, "Payment is still being confirmed. Check your library."
                )
            owned = db.execute(
                "SELECT result FROM tg_requests WHERE session_id=? AND article_id=? AND status='complete' LIMIT 1",
                (session["id"], article.id),
            ).fetchone()
            if owned:
                return json.loads(owned["result"])
            pending = db.execute(
                "SELECT id FROM tg_requests WHERE session_id=? AND status='pending' LIMIT 1",
                (session["id"],),
            ).fetchone()
            if pending:
                raise HTTPException(
                    409, "Another payment is still being confirmed. Check your library."
                )
            used = db.execute(
                "SELECT COALESCE(SUM(cap),0) AS spent FROM tg_requests WHERE session_id=?",
                (session["id"],),
            ).fetchone()["spent"]
            if (
                article.price_drops > request.max_price_drops
                or request.max_price_drops + used > BUDGET
            ):
                raise HTTPException(
                    409, "The article exceeds your price limit or remaining budget."
                )
            db.execute(
                "INSERT INTO tg_requests(id,session_id,article_id,cap,status,created_at) VALUES (?,?,?,?,'pending',?)",
                (request_id, session["id"], article.id, request.max_price_drops, now),
            )
        started = time.monotonic()
        stage = "payment"
        event("purchase_started", request_id=request_id, article_id=article.id)
        try:
            wallet = Wallet.from_seed(
                self.box.decrypt(bytes.fromhex(session["seed"])).decode()
            )
            result = x402_purchase(
                self.settings.public_api_url + "/articles/" + article.id,
                wallet=wallet,
                rpc_url=self.settings.rpc_url,
                network_filter="xrpl:1",
                max_value=str(request.max_price_drops),
                timeout=180,
            )
            if result.status != "success" or result.response is None:
                raise ValueError("Payment not confirmed")
            stage = "receipt_verification"
            data = self.validate_result(
                result.response.json(),
                article,
                session["address"],
                request.max_price_drops,
            )
            stage = "storage"
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE tg_requests SET status='complete',result=? WHERE id=? AND session_id=?",
                    (json.dumps(data), request_id, session["id"]),
                )
            event(
                "purchase_confirmed",
                request_id=request_id,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            return data
        except Exception as exc:
            event(
                "purchase_pending",
                request_id=request_id,
                stage=stage,
                error_type=type(exc).__name__,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            raise HTTPException(
                502,
                "Payment confirmation is delayed. Check your library before trying again.",
            ) from None


def create_app(settings, service=None, facilitator=None):
    service = service or Service(settings)
    app = FastAPI(title="AI Toll Gate API")
    app.state.service = service
    facilitator = facilitator or AsyncFacilitatorClient(
        FacilitatorClientOptions(
            base_url="https://xrpl-facilitator-testnet.t54.ai", timeout_seconds=60
        )
    )
    for article in service.articles.values():
        app.middleware("http")(
            require_payment(
                path="/articles/" + article.id,
                price=str(article.price_drops),
                pay_to_address=article.pay_to,
                network="xrpl:1",
                asset="XRP",
                facilitator=facilitator,
                resource=settings.public_api_url + "/articles/" + article.id,
                description=article.title,
                source_tag=804681468,
            )
        )

    @app.middleware("http")
    async def receipt_and_browser_guard(request, call_next):
        # Vercel's static frontend keeps trailing slashes. Normalize before the
        # router and exact-path x402 middleware, without a redirect loop.
        path = request.scope["path"]
        if path != "/" and path.endswith("/"):
            request.scope["path"] = path.rstrip("/")
            request.scope["raw_path"] = request.scope.get("raw_path", b"").rstrip(b"/")
        if request.method == "POST" and request.url.path.startswith("/api/tollgate/"):
            if (
                request.headers.get("origin") != settings.frontend_origin
                or request.headers.get("content-type", "").split(";", 1)[0]
                != "application/json"
            ):
                return JSONResponse(
                    {"detail": "Same-origin JSON requests required."}, status_code=403
                )
        response = await call_next(request)
        settlement_header = response.headers.get("PAYMENT-RESPONSE")
        article = service.articles.get(request.url.path.removeprefix("/articles/"))
        if response.status_code == 200 and settlement_header and article:
            settled = decode_payment_response(settlement_header)
            receipt = service.signer.sign(
                {
                    "article_id": article.id,
                    "title": article.title,
                    "content_hash": article.content_hash,
                    "license": article.license,
                    "price_drops": article.price_drops,
                    "pay_to": article.pay_to,
                    "payer": settled.get("payer"),
                    "network": settled.get("network"),
                    "tx_hash": settled.get("transaction"),
                }
            )
            body = b"".join([part async for part in response.body_iterator])
            data = {**json.loads(body), "receipt": receipt}
            with service.store.transaction() as db:
                db.execute(
                    "INSERT INTO tg_ledger(tx_hash,article_id,payer,result,created_at) VALUES (?,?,?,?,?) ON CONFLICT(tx_hash) DO NOTHING",
                    (
                        settled["transaction"],
                        article.id,
                        settled["payer"],
                        json.dumps(data),
                        int(time.time()),
                    ),
                )
            response = JSONResponse(
                data,
                headers={
                    k: v
                    for k, v in response.headers.items()
                    if k.lower() not in {"content-length", "content-type"}
                },
            )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "PAYMENT-SIGNATURE"],
        expose_headers=["PAYMENT-REQUIRED", "PAYMENT-RESPONSE"],
    )

    def current(request):
        return service.session(request.cookies.get(COOKIE))

    @app.get("/health")
    @app.get("/api/tollgate/health")
    def health(request: Request):
        session = current(request)
        return {
            "ok": True,
            "network": "xrpl:1",
            "mode": "hosted-testnet",
            "purchases_enabled": bool(session),
            "session_required": not bool(session),
            "library_enabled": True,
            "remaining_drops": service.remaining(session),
            "max_purchase_drops": CAP,
        }

    @app.post("/api/tollgate/session")
    def start_session(request: Request, response: Response):
        if not current(request):
            ip = request.client.host if request.client else "unknown"
            if request.headers.get("x-vercel-forwarded-for"):
                ip = request.headers["x-vercel-forwarded-for"].split(",")[0].strip()
            token = service.create_session(ip)
            response.set_cookie(
                COOKIE,
                token,
                httponly=True,
                secure=settings.secure,
                samesite="lax",
                path="/api/tollgate",
                max_age=SESSION_TTL,
            )
        return {"ok": True}

    @app.get("/catalog")
    @app.get("/api/tollgate/catalog")
    def catalog(q: str = ""):
        query = q.lower()
        return {
            "articles": [
                article.listing(settings.public_api_url)
                for article in service.articles.values()
                if query
                in (
                    article.title
                    + " "
                    + article.abstract
                    + " "
                    + " ".join(article.tags)
                ).lower()
            ]
        }

    @app.get("/articles/{article_id}")
    def article_body(article_id: str):
        a = service.articles.get(article_id)
        if not a:
            raise HTTPException(404, "Article not found")
        return {
            "id": a.id,
            "title": a.title,
            "author": a.author,
            "license": a.license,
            "content_hash": a.content_hash,
            "body": a.body,
        }

    @app.get("/.well-known/tollgate-receipt-key")
    def receipt_key():
        return {"alg": "ed25519", "public_key": service.signer.public_key_hex}

    @app.get("/api/tollgate/library")
    def library(request: Request):
        return {"items": service.library(current(request))}

    @app.get("/api/tollgate/ledger")
    def ledger(request: Request):
        items = service.library(current(request))
        receipts = [i["purchase"]["receipt"] for i in items if i["purchase"]]
        return {
            "purchases": [
                {
                    "article_id": r["payload"]["article_id"],
                    "price_drops": r["payload"]["price_drops"],
                    "tx_hash": r["payload"]["tx_hash"],
                    "receipt": r,
                }
                for r in receipts
            ],
            "earnings": [
                {
                    "reads": len(receipts),
                    "drops": sum(r["payload"]["price_drops"] for r in receipts),
                }
            ],
        }

    @app.post("/api/tollgate/purchases")
    def purchase(body: PurchaseRequest, request: Request):
        session = current(request)
        if not session:
            raise HTTPException(401, "Start a reading session first.")
        return service.purchase(session, body)

    install_request_logging(app)
    return app
