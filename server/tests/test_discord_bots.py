"""Time-window completeness and publisher state/permission boundaries."""
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

import httpx
import pytest
from app.discord_import import fetch_snapshot, ImportFailure

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bots'))
import drafts

GUILD = '100000000000000001'
CHANNEL = '100000000000000002'
BOT = '100000000000000003'
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = START + timedelta(hours=1)


def msg(when, text, bot=False, identity=BOT, kind=0):
    key = str((int(when.timestamp() * 1000) - 1420070400000) << 22)
    return {'id':key, 'channel_id':CHANNEL, 'type':kind, 'timestamp':when.isoformat(),
            'content':text, 'author':{'id':identity, 'username':'Research', 'bot':bot}}


def capture(pages, **kwargs):
    queue = iter(pages)
    def handle(request):
        if request.url.path.endswith('/messages'):
            return httpx.Response(200,json=next(queue))
        return httpx.Response(200,json={'id':CHANNEL,'guild_id':GUILD,'type':0})
    with httpx.Client(base_url='https://discord.com/api/v10/',transport=httpx.MockTransport(handle)) as http:
        return fetch_snapshot(http,GUILD,CHANNEL,start=START,end=END,allowed_bot_ids=(BOT,),**kwargs)


def test_range_boundaries_and_only_allowlisted_bot_slash_response():
    body = capture([[msg(START-timedelta(seconds=1),'TOO_EARLY'),msg(START,'INCLUDED'),
                     msg(START+timedelta(minutes=1),'MOCK_ANSWER',True,kind=20),
                     msg(START+timedelta(minutes=2),'OTHER_BOT',True,'100000000000000004'),
                     msg(END,'TOO_LATE')]])
    assert 'INCLUDED' in body and 'MOCK_ANSWER' in body and '[Bot-generated]' in body
    assert all(x not in body for x in ('TOO_EARLY','TOO_LATE','OTHER_BOT'))
    assert 'Included text messages: 2' in body


def test_full_page_is_followed_to_collect_older_context():
    page=[msg(START+timedelta(minutes=30,seconds=i),f'new-{i}') for i in range(100)]
    body=capture([page,[msg(START,'OLDER_CONTEXT')]])
    assert 'OLDER_CONTEXT' in body and 'Included text messages: 101' in body


def test_over_limit_window_is_not_silently_truncated():
    page=[msg(START+timedelta(minutes=30,seconds=i),'text') for i in range(100)]
    with pytest.raises(ImportFailure,match='no partial snapshot'):
        capture([page],max_pages=1)


def test_naive_dates_are_rejected_before_network():
    with httpx.Client() as http, pytest.raises(ImportFailure,match='time zones'):
        fetch_snapshot(http,GUILD,CHANNEL,start=START.replace(tzinfo=None),end=END)


def test_draft_owner_rejected_state_and_double_approval(monkeypatch,tmp_path):
    monkeypatch.setattr(drafts,'ROOT',tmp_path)
    key=drafts.create_draft('owner',{'body':'PRIVATE','price_usd':'0.01'})
    with pytest.raises(ImportFailure): drafts.get_draft(key,'other')
    drafts.transition(key,'owner','draft','reviewed')
    drafts.transition(key,'owner','reviewed','publishing')
    with pytest.raises(ImportFailure): drafts.transition(key,'owner','reviewed','publishing')
    assert drafts.get_draft(key,'owner')[0]=='publishing'
    other=drafts.create_draft('owner',{'body':'PRIVATE'})
    drafts.transition(other,'owner','draft','rejected')
    with pytest.raises(ImportFailure): drafts.transition(other,'owner','reviewed','publishing')


def test_commands_have_runtime_admin_checks_and_build_without_login(monkeypatch):
    monkeypatch.setenv('DISCORD_GUILD_ID',GUILD)
    monkeypatch.setenv('DISCORD_CHANNEL_ID',CHANNEL)
    discord = pytest.importorskip('discord', reason='Install bots/requirements.txt to test command registration.')
    import discord_demo
    client=discord_demo.build_client('publisher')
    commands=client.tree.get_commands(guild=discord.Object(id=int(GUILD)))
    assert {c.name for c in commands}=={'snapshot','review','approve','reject'}
    assert all(c.checks and c.default_permissions.manage_guild for c in commands)
    from types import SimpleNamespace
    assert not discord_demo.admin_allowed(SimpleNamespace(guild_id=0,channel_id=int(CHANNEL),user=None))
    assert not discord_demo.admin_allowed(SimpleNamespace(guild_id=int(GUILD),channel_id=0,user=None))
    assert not discord_demo.admin_allowed(SimpleNamespace(guild_id=int(GUILD),channel_id=int(CHANNEL),user=None))
    asyncio.run(client.close())

def test_approval_export_requires_review_and_owner(monkeypatch, tmp_path):
    pytest.importorskip('discord')
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import discord_demo as demo
    import discord
    monkeypatch.setattr(drafts, 'ROOT', tmp_path)
    monkeypatch.setattr(demo, 'dotenv_values', lambda *a, **k: {'DISCORD_PUBLISHER_OWNER_ID':'42'})
    monkeypatch.delenv('TOLLGATE_WRITER_TOKEN', raising=False)
    async def run():
        client=demo.build_client('publisher')
        approve=client.tree.get_command('approve',guild=discord.Object(id=demo.GUILD))
        response=SimpleNamespace(send_message=AsyncMock())
        interaction=SimpleNamespace(user=SimpleNamespace(id=42),response=response)
        key=drafts.create_draft('42',{'body':'private','title':'Title','summary':'Public','price_usd':'0.01'})
        with pytest.raises(ImportFailure,match='reviewed'):
            await approve.callback(interaction,key,True)
        drafts.transition(key,'42','draft','reviewed')
        with pytest.raises(ImportFailure,match='not confirmed'):
            await approve.callback(interaction,key,False)
        monkeypatch.setattr(demo,'dotenv_values',lambda *a, **k: {'DISCORD_PUBLISHER_OWNER_ID':'99'})
        with pytest.raises(ImportFailure,match='owner'):
            await approve.callback(interaction,key,True)
        monkeypatch.setattr(demo,'dotenv_values',lambda *a, **k: {'DISCORD_PUBLISHER_OWNER_ID':'42'})
        await approve.callback(interaction,key,True)
        assert drafts.get_draft(key,'42')[0]=='approved_for_upload'
        sent=response.send_message.call_args
        assert 'Not published yet' in sent.args[0] and sent.kwargs['ephemeral'] is True
        with pytest.raises(ImportFailure,match='reviewed'):
            await approve.callback(interaction,key,True)
        await client.close()
    asyncio.run(run())
