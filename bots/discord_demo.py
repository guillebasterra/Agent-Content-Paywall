"""Local, single-community Discord demo. No wallet or LLM credentials required."""
import argparse
import asyncio
import io
import os
from pathlib import Path
import sys
from datetime import datetime

import discord
from discord import app_commands
import httpx
from dotenv import load_dotenv, dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from app.discord_import import fetch_snapshot, ImportFailure

load_dotenv(ROOT / '.env', encoding='utf-8-sig')
from config import Settings
from drafts import create_draft, get_draft, transition
from providers import MockResearchProvider
from publishing import publish_snapshot
SETTINGS = Settings.from_environment()
GUILD, CHANNEL, API = SETTINGS.guild_id, SETTINGS.channel_id, SETTINGS.api_url
research_provider = MockResearchProvider()

def admin_allowed(interaction):
    return (interaction.guild_id == GUILD and interaction.channel_id == CHANNEL
            and isinstance(interaction.user, discord.Member)
            and interaction.permissions.manage_guild)


class Client(discord.Client):
    def __init__(self, role):
        super().__init__(intents=discord.Intents.none(), allowed_mentions=discord.AllowedMentions.none())
        self.role = role
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync(guild=discord.Object(id=GUILD))
        print(f'{self.role}: commands registered for the configured server.', flush=True)


def build_client(role):
    client = Client(role)
    guild = discord.Object(id=GUILD)

    @client.tree.error
    async def error(interaction, exc):
        original = getattr(exc, 'original', exc)
        message = str(original) if isinstance(original, ImportFailure) else 'Request failed. Check configuration and permissions; no secrets are shown.'
        if interaction.response.is_done():
            await interaction.followup.send(message[:1800], ephemeral=True)
        else:
            await interaction.response.send_message(message[:1800], ephemeral=True)

    if role == 'research':
        @client.tree.command(name='research', description='Ask the mock research bot (fixed fictional response).', guild=guild)
        @app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)
        async def research(interaction: discord.Interaction, question: str):
            if interaction.guild_id != GUILD or interaction.channel_id != CHANNEL:
                raise ImportFailure('Use this command in the configured research channel.')
            await interaction.response.send_message(f'**Question from {interaction.user.display_name}:** {question[:500]}\n\n{await research_provider.answer(question)}',
                                                    allowed_mentions=discord.AllowedMentions.none())
        return client

    @client.tree.command(name='snapshot', description='Create a private draft for a time range; does not publish.', guild=guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(admin_allowed)
    async def snapshot(interaction: discord.Interaction, start: str, end: str, title: str, summary: str):
        if not 1 <= len(title.strip()) <= 200 or not 1 <= len(summary.strip()) <= 1000:
            raise ImportFailure('Provide a title (up to 200 characters) and a free summary (up to 1000).')
        try:
            start_dt, end_dt = [datetime.fromisoformat(t.replace('Z', '+00:00')) for t in (start, end)]
        except ValueError:
            raise ImportFailure('Use ISO dates with time zones, for example 2026-11-19T09:00:00-05:00.')
        await interaction.response.defer(ephemeral=True, thinking=True)
        def capture():
            with httpx.Client(base_url='https://discord.com/api/v10/', timeout=30,
                              headers={'Authorization': 'Bot ' + os.environ['DISCORD_PUBLISHER_BOT_TOKEN']}) as http:
                return fetch_snapshot(http, str(GUILD), str(CHANNEL), start=start_dt, end=end_dt,
                                      allowed_bot_ids=(os.environ['DISCORD_RESEARCH_BOT_ID'],))
        body = await asyncio.to_thread(capture)
        key = create_draft(interaction.user.id, {'title': title.strip(), 'summary': summary.strip(), 'body': body, 'price_usd': SETTINGS.price_usd})
        await interaction.followup.send(f'Draft `{key}` saved. Run `/review draft_id:{key}` to review the exact text. '
                                        f'Price: ${SETTINGS.price_usd} per retrieval. Summary is free. Future messages are excluded.', ephemeral=True)

    @client.tree.command(name='review', description='Privately review the exact draft that would be published.', guild=guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(admin_allowed)
    async def review(interaction: discord.Interaction, draft_id: str):
        state, payload = get_draft(draft_id, interaction.user.id)
        publication = f"\nPublished: {API}/articles/{payload['article_id']}" if payload.get('article_id') else ''
        await interaction.response.send_message(
            f"State: {state}{publication}\n**{payload['title']}**\nFree summary: {payload['summary']}\n"
            f"${payload['price_usd']} per retrieval of the attached snapshot. Future messages, attachments, and threads are excluded. "
            'Review the attachment before approving. You must be authorized to publish these messages.',
            file=discord.File(io.BytesIO(payload['body'].encode()), filename='snapshot.md'), ephemeral=True)
        if state == 'draft':
            transition(draft_id, interaction.user.id, 'draft', 'reviewed')

    @client.tree.command(name='approve', description='Publish a reviewed snapshot at its configured price.', guild=guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(admin_allowed)
    async def approve(interaction: discord.Interaction, draft_id: str, confirm_publish: bool):
        if not confirm_publish:
            raise ImportFailure('Publishing was not confirmed.')
        state, payload = get_draft(draft_id, interaction.user.id)
        if state != 'reviewed':
            raise ImportFailure('Only a reviewed draft can be published. Run /review first.')
        # Refresh short-lived credentials without restarting a running bot.
        local = dotenv_values(ROOT / '.env', encoding='utf-8-sig')
        writer = (local.get('TOLLGATE_WRITER_TOKEN') or os.getenv('TOLLGATE_WRITER_TOKEN', '')).strip()
        writer_admin = (local.get('DISCORD_PUBLISHER_OWNER_ID') or os.getenv('DISCORD_PUBLISHER_OWNER_ID', '')).strip()
        if str(interaction.user.id) != writer_admin:
            raise ImportFailure('Approval requires the configured publisher owner.')
        if not writer:
            await interaction.response.send_message(
                f"Approved for website upload at ${payload['price_usd']} per retrieval. Not published yet.\n"
                'Open https://tollgate-omega.vercel.app/upload with your writer account. '
                'Upload the reviewed snapshot, use the reviewed title and summary, set Free preview to Abstract only, '
                f"and set the price to ${payload['price_usd']}. A writer API token enables direct publication later.",
                file=discord.File(io.BytesIO(payload['body'].encode()), filename=f'{draft_id}.md'), ephemeral=True)
            transition(draft_id, interaction.user.id, 'reviewed', 'approved_for_upload')
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        transition(draft_id, interaction.user.id, 'reviewed', 'publishing')
        try:
            article_id = await publish_snapshot(API, writer, payload, payload['price_usd'])
        except Exception:
            transition(draft_id, interaction.user.id, 'publishing', 'needs_reconciliation')
            raise ImportFailure('Publication outcome needs reconciliation. Check the writer dashboard; automatic retry is disabled.') from None
        payload['article_id'] = article_id
        payload['publication_method'] = 'writer_api'
        transition(draft_id, interaction.user.id, 'publishing', 'published', payload)
        await interaction.followup.send(f"Published at ${payload['price_usd']} per retrieval: {API}/articles/{article_id}", ephemeral=True)

    @client.tree.command(name='reject', description='Reject an unpublished draft.', guild=guild)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.check(admin_allowed)
    async def reject(interaction: discord.Interaction, draft_id: str):
        state, _ = get_draft(draft_id, interaction.user.id)
        if state not in ('draft', 'reviewed'):
            raise ImportFailure('Only unpublished drafts can be rejected.')
        transition(draft_id, interaction.user.id, state, 'rejected')
        await interaction.response.send_message('Draft rejected. Nothing was published.', ephemeral=True)

    return client


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('research', 'publisher'))
    args = parser.parse_args()
    key = 'DISCORD_BOT_TOKEN' if args.role == 'research' else 'DISCORD_PUBLISHER_BOT_TOKEN'
    token = os.getenv(key, '').strip()
    if not token:
        parser.exit(1, f'Configure {key} in the local .env.\n')
    if args.role == 'publisher' and not os.getenv('DISCORD_RESEARCH_BOT_ID'):
        parser.exit(1, 'Configure DISCORD_RESEARCH_BOT_ID.\n')
    build_client(args.role).run(token, log_handler=None)
