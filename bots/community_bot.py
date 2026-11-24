"""Channel-based AMA workflow. Run from server/ so the API and worker share the same DB."""
import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from app import config
from app.community import CommunityStore, DRAFT_MARKERS
from app.content import format_usd
from app.db import Database

MAX_BYTES = 2_000_000
log = logging.getLogger(__name__)


def role_ids(member):
    return {str(role.id) for role in member.roles} if isinstance(member, discord.Member) else set()


async def message_draft(message):
    marker = next(prefix for prefix in DRAFT_MARKERS if message.content.startswith(prefix))
    title, _, body = message.content.removeprefix(marker).partition("\n")
    if message.attachments:
        if len(message.attachments) != 1 or body.strip():
            raise ValueError("Use the title and one file, or put the full text on the following lines.")
        file = message.attachments[0]
        if Path(file.filename).suffix.lower() not in {".md", ".txt"} or file.size > MAX_BYTES:
            raise ValueError("Use a UTF-8 .md or .txt file up to 2 MB.")
        body = (await file.read()).decode("utf-8-sig")
    return title.strip(), body.strip()


def build_client(store):
    intents = discord.Intents.default()
    intents.message_content = True

    class Client(discord.Client):
        async def setup_hook(self):
            await tree.sync()
            recover.start()

    client = Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())
    tree = app_commands.CommandTree(client)

    @tree.command(name="connect_ama", description="Connect this AMA channel to your signed-in writer dashboard")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def connect(interaction: discord.Interaction, code: str, review_channel: discord.TextChannel):
        if not interaction.permissions.manage_guild or not isinstance(interaction.channel, discord.TextChannel):
            raise ValueError("Manage Server in a text channel is required.")
        if review_channel.guild.id != interaction.guild_id or review_channel.permissions_for(
                interaction.guild.default_role).view_channel:
            raise ValueError("Select a private reviewer channel in this server.")
        if not review_channel.permissions_for(interaction.guild.me).send_messages:
            raise ValueError("Give the app permission to send review reminders in the private channel.")
        visible_roles = {str(role.id) for role in interaction.guild.roles if not role.is_default()}
        if not interaction.channel.permissions_for(interaction.guild.me).read_message_history:
            raise ValueError("Give the app Read Message History in the AMA channel.")
        await asyncio.to_thread(store.pair, code, str(interaction.guild_id), str(interaction.channel_id),
                                str(review_channel.id), str(interaction.id), visible_roles)
        await interaction.response.send_message("Connected. Send [AMA FINAL] Title followed by the approved text or file.",
                                                ephemeral=True)

    async def capture(message, settings):
        if message.author.bot or not message.content.startswith(DRAFT_MARKERS):
            return
        author = message.author
        if not isinstance(author, discord.Member):
            try:
                author = await message.guild.fetch_member(author.id)
            except discord.NotFound:
                return
        if not role_ids(author).intersection((settings["editor"], settings["reviewer"])):
            return
        title, body = await message_draft(message)
        await asyncio.to_thread(store.capture, settings["id"], str(message.id), title, body)

    @client.event
    async def on_message(message):
        if message.guild and message.content.startswith(DRAFT_MARKERS):
            settings = await asyncio.to_thread(store.channel, str(message.guild.id), str(message.channel.id))
            if settings:
                try:
                    await capture(message, settings)
                except ValueError:
                    log.warning("Invalid AMA source %s; check title, encoding and size", message.id)

    @tasks.loop(seconds=45)
    async def recover():
        # A durable cursor recovers events missed while offline. Only advance after processing.
        for settings in await asyncio.to_thread(store.channels):
            channel = client.get_channel(int(settings["id"]))
            if not channel:
                continue
            cursor = settings["cursor"]
            latest = cursor
            try:
                async for message in channel.history(after=discord.Object(id=int(cursor)), limit=200, oldest_first=True):
                    try:
                        await capture(message, settings)
                    except ValueError:
                        log.warning("Invalid AMA source %s", message.id)
                    latest = str(message.id)
                if latest != cursor:
                    await asyncio.to_thread(store.advance, settings["id"], cursor, latest)
            except discord.HTTPException:
                log.warning("Could not recover AMA history for channel %s", settings["id"])
        for draft in await asyncio.to_thread(store.reminders):
            target = client.get_channel(int(draft["review_channel"]))
            if not target or target.permissions_for(target.guild.default_role).view_channel:
                continue
            source = "/".join([draft["guild"], draft["channel"], draft["id"]])
            try:
                await target.send(f"AMA ready for review: <{config.WEB_URL}/community/review/{source}>"
                                  f" · <https://discord.com/channels/{source}>")
                await asyncio.to_thread(store.mark_notified, draft["id"])
            except discord.HTTPException:
                log.warning("Could not send AMA reminder for %s", draft["id"])

    @recover.before_loop
    async def ready():
        await client.wait_until_ready()

    async def lookup(interaction, message):
        settings = await asyncio.to_thread(store.channel, str(interaction.guild_id), str(message.channel.id))
        if not settings or settings["reviewer"] not in role_ids(interaction.user):
            raise ValueError("The configured reviewer role is required.")
        return await asyncio.to_thread(store.draft, settings["id"], str(message.id))

    @tree.context_menu(name="Review AMA")
    @app_commands.guild_only()
    async def review(interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True, thinking=True)
        draft = await lookup(interaction, message)
        if draft["article_id"]:
            await interaction.followup.send("Already published. Use Apps → AMA sales.", ephemeral=True)
            return
        source = f"{interaction.guild_id}/{message.channel.id}/{message.id}"
        await interaction.followup.send(f"Review and confirm: <{config.WEB_URL}/community/review/{source}>",
                                        ephemeral=True)

    @tree.context_menu(name="AMA sales")
    @app_commands.guild_only()
    async def sales(interaction: discord.Interaction, message: discord.Message):
        draft = await lookup(interaction, message)
        if not draft["article_id"]:
            raise ValueError("This draft has not been published.")
        article = await asyncio.to_thread(store.database.article, draft["article_id"])
        await interaction.response.send_message(
            f"{article['reads']} paid reads · net ${format_usd(article['earned_usd_micros'])}\n"
            f"Writer details: <{config.WEB_URL}/dashboard/sales/{article['id']}>", ephemeral=True)

    @tree.error
    async def error(interaction, exc):
        cause = getattr(exc, "original", exc)
        text = str(cause) if isinstance(cause, ValueError) else "Request failed. Open the source message to retry."
        respond = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await respond(text, ephemeral=True)

    return client


if __name__ == "__main__":
    db = Database(config.database_target())
    try:
        build_client(CommunityStore(db)).run(os.environ["DISCORD_PUBLISHER_BOT_TOKEN"])
    finally:
        db.close()
