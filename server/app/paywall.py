"""One paywall for every article, priced from the database on each request.

New articles are for sale as soon as they are saved. The first rail that recognises a request
takes it, and a 402 also lists the other ways to pay.
"""

import re
from collections.abc import Sequence

from fastapi.responses import JSONResponse
from starlette.requests import Request

from .db import Database
from .rails.base import PaymentRail
from .rails.settle import response_json, with_json

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


def paywall(db: Database, rails: Sequence[PaymentRail]):
    async def middleware(request: Request, call_next):
        article_id = article_id_from(request)
        # Only GET can return article text. Others fall through to a 405 with no charge.
        article = db.article(article_id) if article_id and request.method == "GET" else None
        if article is None:
            return await call_next(request)

        rail = next(r for r in rails if r.handles(request))
        identity = getattr(rail, "authenticated_agent", None)
        agent = identity(request) if identity else agent_name(request)
        if agent is not None and not agent_allowed(article, agent):
            return JSONResponse(
                status_code=403,
                content={"error": "agent_not_allowed", "allowed_agents": article["allowed_agents"]},
            )

        response = await rail.charge(request, article, call_next)
        others = [offer for r in rails if r is not rail and (offer := r.advertise(article))]
        if response.status_code == 402 and others:
            # Beside `accepts`, not in it: x402 clients read every entry there as x402.
            return with_json(response, {**await response_json(response), "alternatives": others})
        return response

    return middleware
