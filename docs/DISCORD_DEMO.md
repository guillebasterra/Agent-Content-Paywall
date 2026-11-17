# Proposal: Paid Discord Content for AI Agents

## Objective

Extend Tollgate so an AI agent can discover and purchase content from one authorized Discord channel, using the existing MCP discovery tools, x402 payment flow, and signed receipts from `main`.

## Demo experience

1. A server administrator installs a bot and grants it access to one selected text channel.
2. An operator imports up to 100 recent messages as one static snapshot.
3. The snapshot is uploaded as a paid article under the operator's existing writer account. Its public description explains the topic; message text stays behind the paywall.
4. An AI agent uses `search_catalog` and `get_article` to discover the snapshot and its price.
5. The agent pays through the existing payments-mcp flow and receives the full snapshot, original message links, and a signed receipt. The existing ledger credits the publishing writer.

## Scope and acceptance

One server, one regular text channel, one manually imported snapshot, and a suggested price of $0.02 per read. Existing articles, payment rails, API routes, database schema, and MCP tools remain compatible.

Success means the snapshot appears in MCP discovery, an unpaid read returns 402 without the messages, and a paid read returns the snapshot with a verifiable receipt and writer credit.

Not included: live synchronization, threads, attachments, embeds, subscription management, automated payouts to individual message authors, or AI training. A snapshot is a copy at import time; later message edits/deletions are not synchronized. Source links still require Discord access when opened. MCP treats message text as untrusted source material.

## Discord setup

Use a server/channel whose contributors have authorized this use. For the first demonstration, a dedicated test channel with contributed sample discussion is sufficient.

1. Create an application and bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Message Content Intent** on the Bot page. Without it, message text may be empty.
3. Install the bot in the chosen server using the `bot` OAuth2 scope. Grant **View Channel** and **Read Message History** for the selected channel. No Administrator, Send Messages, or Manage Roles permission is needed.
4. In Discord's Developer Mode, copy the server ID and channel ID.
5. Configure these locally in the repository-root `.env` (never commit it):

```dotenv
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_GUILD_ID=your-server-id
DISCORD_CHANNEL_ID=your-channel-id
```

The importer checks that the channel belongs to this server and is a regular text channel. It makes only two Discord reads: channel metadata and one bounded message-history request. It skips bots, system events and empty messages, and orders included messages oldest first.

References: [Discord message API](https://docs.discord.com/developers/resources/message#get-channel-messages), [channel API](https://docs.discord.com/developers/resources/channel#get-channel).

## Import and publish

Run from `server/` with the existing uv environment:

```bash
uv sync --locked
uv run python ../scripts/import_discord.py --title "Discord frost fan discussion" --abstract "A community discussion about orchard frost fan thresholds." --keywords "discord,orchard,frost" --limit 50 --price-usd 0.02
```

This writes a private Markdown file under the gitignored `.discord-snapshots/` directory and does not publish it. Review it locally, then upload it through the existing writer website. Set the title, description, keywords, price, **preview = none**, and **license = ai-input**. The public description acts as the preview; no message excerpts are exposed.

For a single-command import and publish, add `--publish --api-url https://YOUR-TOLLGATE-API`. Set `TOLLGATE_WRITER_TOKEN` locally to the access token from your existing signed-in writer session. A remote API must use HTTPS. This token is sent only to Tollgate; the bot token is sent only to Discord. For a local demo-mode server at `http://localhost:8000`, no writer token is required. Do not expose demo-mode writer routes publicly.

Publishing uses the existing authenticated `POST /articles`; the publishing writer receives the revenue. Each invocation imports a fresh snapshot and each upload creates an article. If an upload times out, check the writer dashboard before retrying to avoid duplicates. Saved Markdown has no frontmatter and is intended for the writer upload flow, not startup seeding.

## Run the agent demonstration

Use the latest `main` server (`server/`), **not** the older XRPL-only `hosted-api/` snapshot preserved on `ruolan`. Follow [AGENT_SETUP.md](AGENT_SETUP.md) to configure the existing MCP and wallet. For your own deployed demo, point the Tollgate connector at **your API's `/mcp`**, not the upstream production URL in that guide. Configure `TOLLGATE_API_URL` to the same public origin.

Ask the agent:

> Find the Discord discussion about orchard frost fan thresholds in Tollgate. Show me the price, then use the existing payment tool within my authorized budget to buy it. Answer using the discussion, include a source message link, and cite the signed receipt.

The buyer path stays unchanged: MCP discovery -> payments-mcp -> `GET /articles/{id}` -> 402 -> payment -> full body and receipt. The importer CLI is an operator tool, not a new buyer/payment interface. Base mainnet purchases spend real USDC; automated tests use fake settlement and no funds.

## Verification

```bash
cd server
uv run pytest -q
cd ../buyer-mcp
uv run pytest -q
```

`server/tests/test_discord_import.py` covers channel scoping, unsupported channel types, missing content, Discord failures, excluded message types, and MCP discovery through a paid x402 read with receipt verification and writer credit. HTTP and settlement are faked; a real Discord import and real purchase require separately configured credentials.

The `hosted-api/` files remain for the earlier frontend integration. Pushing `ruolan` does not automatically connect or deploy this demo; the selected Tollgate API must run this branch's `server/` code and receive the uploaded snapshot.
