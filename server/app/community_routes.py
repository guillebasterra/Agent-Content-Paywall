from typing import Annotated

import httpx

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .community import CommunityStore
from .content import format_usd
from .session import current_writer

RoleId = Annotated[str, Field(pattern=r"^[0-9]{17,20}$")]


class PairRequest(BaseModel):
    editor: RoleId
    reviewer: RoleId
    price_usd: str


class Approval(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    price_usd: str
    confirm_rights: bool


async def discord_membership(guild: RoleId, authorization: Annotated[str, Header()]):
    """Discord validates the reviewer identity and current guild roles on every review or publish."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in with Discord.")
    async with httpx.AsyncClient(timeout=8) as client:
        try:
            response = await client.get(f"https://discord.com/api/v10/users/@me/guilds/{guild}/member",
                                        headers={"Authorization": authorization})
        except httpx.HTTPError:
            raise HTTPException(503, "Discord is temporarily unavailable.") from None
    if response.status_code != 200:
        status = {401: 401, 403: 403, 404: 403}.get(response.status_code, 503)
        raise HTTPException(status, "Could not verify Discord membership.")
    return response.json()


def routes(database):
    router = APIRouter()
    store = CommunityStore(database)

    @router.post("/me/discord/pair")
    def pair(settings: PairRequest, writer: dict = Depends(current_writer)):
        try:
            return {"code": store.pairing_code(writer["id"], settings.editor, settings.reviewer, settings.price_usd)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get("/me/discord/sales/{article_id}")
    def sales(article_id: str, writer: dict = Depends(current_writer)):
        article = database.article(article_id)
        if not article or article["writer_id"] != writer["id"]:
            raise HTTPException(404, "Article not found.")
        with database.transaction() as c:
            rows = c.execute(
                "SELECT tx_hash, rail, network, amount_usd_micros, fee_usd_micros, created_at, receipt "
                "FROM purchases WHERE article_id=? AND writer_id=? ORDER BY id DESC LIMIT 50",
                (article_id, writer["id"]),
            ).fetchall()
        return {"title": article["title"], "reads": article["reads"], "earned_usd_micros": article["earned_usd_micros"],
                "recent": [dict(row) for row in rows]}

    def reviewer(guild: RoleId, channel: RoleId, member: dict = Depends(discord_membership)):
        settings = store.channel(guild, channel)
        if not settings or settings["reviewer"] not in member["roles"]:
            raise HTTPException(403, "Reviewer role required.")
        return member

    path = "/discord/review/{guild}/{channel}/{message}"

    @router.get(path)
    def preview(channel: RoleId, message: RoleId, member: dict = Depends(reviewer)):
        try:
            draft = store.draft(channel, message)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None
        return {**draft, "price_usd": format_usd(draft["price"])}

    @router.post(path)
    def publish(channel: RoleId, message: RoleId, approval: Approval, member: dict = Depends(reviewer)):
        if not approval.confirm_rights:
            raise HTTPException(422, "Confirm the rights to this version.")
        try:
            article_id = store.publish(channel, message, member["user"]["id"], member["roles"],
                                       approval.summary, approval.price_usd)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"article_id": article_id}

    return router
