# Discord bots: single-channel, time-window demo

## Boundaries

- Research Bot: `/research question:...` posts a fixed, clearly marked fictional answer. It has no LLM or wallet access.
- Publisher Bot: `/snapshot`, `/review`, `/approve`, `/reject`. Commands run only in the configured server and channel. Responses and review attachments are ephemeral.
- A current member with **Manage Server** can draft and review their own snapshot. Publishing additionally requires `DISCORD_PUBLISHER_OWNER_ID` to match the operator whose writer token is configured. This is deliberately a single-writer demo, not multi-tenant account linking.
- Bots do not need Administrator or Manage Server themselves. Research needs View Channel and Send Messages; Publisher needs View Channel and Read Message History plus Message Content Intent. Both need the applications.commands installation scope.
- Grant access only to the intended channel in Discord permissions. The application also checks its configured guild/channel on every command.
- Nothing is published on a schedule or because another bot asks. `/approve confirm_publish:true` is the only publication path.

## Configuration

Copy missing keys from `.env.example` into the root `.env`; never commit secrets. Existing `DISCORD_BOT_TOKEN` is Research Bot. Create a separate Discord application for Publisher and set `DISCORD_PUBLISHER_BOT_TOKEN`.

`DISCORD_RESEARCH_BOT_ID` allows that bot's text into snapshots. Other bots and Publisher output are excluded. The root `.env` contains blank placeholders for `LLM_BASE_URL`, `LLM_API_KEY`, `RESEARCH_MODEL`, and `SUMMARY_MODEL`; these are intentionally unused. Keep `RESEARCH_PROVIDER=mock` and `SUMMARY_PROVIDER=manual`.

`DISCORD_PRICE_USD=0.01` is copied into each draft. Changing the environment later does not reprice a reviewed draft. `TOLLGATE_API_URL` is an HTTPS origin (defaults to the existing production API). `TOLLGATE_WRITER_TOKEN` is an ordinary signed-in author's short-lived token, never a Supabase service key. Expiry requires a fresh login.

## Run (PowerShell, repo root)

```powershell
uv pip install --python server/.venv/Scripts/python.exe -r bots/requirements.txt
.\server\.venv\Scripts\python.exe bots/discord_demo.py research
# A second terminal:
.\server\.venv\Scripts\python.exe bots/discord_demo.py publisher
```

Both processes must remain running. Commands register for one server only at startup. No public HTTP callback or new payment server is needed.

## Admin flow

1. Ask `/research` in `#stock-research`. Its fixed mock answer includes the question for snapshot context.
2. Run `/snapshot start:2026-11-19T09:00:00-05:00 end:2026-11-19T10:00:00-05:00 title:... summary:...`. Use past timestamps with explicit offsets. The interval includes start and excludes end.
3. `/review draft_id:...` returns the immutable Markdown attachment, public summary, and price privately. Check all included human/bot text before publication.
4. `/approve draft_id:... confirm_publish:true` publishes through main's existing `POST /articles`, with summary-only preview and AI-input license. `/reject` stops an unpublished draft. To revise title/summary/range, reject and create a fresh draft.
5. Agent discovery sees the summary for free. A paid retrieval returns the frozen snapshot, not membership or future messages. Main's x402/MCP flow is unchanged.

## Completeness and failure handling

The importer paginates the entire selected window up to 2,000 scanned messages. It refuses an over-limit window instead of silently selling a partial snapshot. Thread messages, attachments, embeds, deleted messages and context outside the window are not included; allowed research-bot text is labeled.

Drafts persist in gitignored `.discord-snapshots/publisher.sqlite`. State is `draft -> reviewed -> publishing -> published`; a rejected draft cannot publish. Atomic state transitions prevent duplicate approval from uploading twice. An interrupted/ambiguous upload stays `publishing` or `needs_reconciliation`; inspect the writer dashboard/catalog before manual recovery. There is no blind retry because the existing upload API has no idempotency key. Ephemeral visibility means other users cannot view the Discord response; local draft files still require ordinary machine access protection.

## Extension seams

- `config.py`: validated environment settings.
- `providers.py`: `ResearchProvider.answer` and `SummaryProvider.suggest` interfaces; currently mock/manual only.
- `drafts.py`: private durable state and ownership checks.
- `publishing.py`: the existing authenticated writer API adapter.
- `discord_demo.py`: Discord commands and permission checks.
- `server/app/discord_import.py`: deterministic history selection and rendering.

A future LLM adapter may propose research text or a summary, but must never approve a draft or publish. Summaries must still be reviewed by an administrator. Multi-writer OAuth linking, automatic token refresh, granular reviewer roles, automatic syncing, and hosted process supervision are separate future work.

## Website publication fallback

### Get a temporary writer token

On the updated writer dashboard, sign in with the publishing account and use
**Publisher Bot → Copy temporary writer token**. Paste it into
`TOLLGATE_WRITER_TOKEN` in the local, gitignored `.env`. Never post it in Discord
or chat. This is the existing Supabase session access token, not a new API key
and not a Supabase service-role key. It has the account's writer API access;
it is not scoped to a Discord channel. The UI displays its expiry. Copy a fresh
token after expiration; the running publisher reads the file on each approval.
The button is available only on deployments containing this branch's UI changes.

If `TOLLGATE_WRITER_TOKEN` is blank, `/approve` still requires the configured publisher owner and a reviewed draft. It returns the exact approved snapshot privately and transitions to `approved_for_upload`, explicitly **not published**. The administrator uploads it through the existing signed-in writer website, retaining the reviewed title, summary, price and Abstract only preview. No browser session secret is extracted. Direct API publishing remains available when a writer token is configured.

A website upload does not automatically notify the bot. After observing the successful writer-dashboard entry and checking the public catalog against the approved metadata, an operator can reconcile the local draft as `published_via_website`, recording the article ID and snapshot hash. Never mark an ambiguous API publication as successful merely because an article with a similar title exists.

## Verified live demo — November 19, 2026

- Publisher application: `1572991848849342584`; Research application: `1572498007805534218`.
- Research slash command returned its labeled fictional response.
- Draft `bd16a198222a` contains two text messages from Nov 18 00:00 EST (inclusive) through Nov 19 10:21:14 EST (exclusive).
- `/snapshot`, `/review` and `/approve confirm_publish:true` succeeded as FlyingC; review/export responses were ephemeral.
- Published through the signed-in RolaineC writer website; article ID `northstar-q3-growth-quality-and-customer-risk-discord-demo`, $0.01, preview mode none.
- Production MCP returns the article and x402 purchase arguments. Unpaid GET returns 402 with amount 10000 on Base mainnet and no snapshot body.
- Publisher can read stock-research (HTTP 200); general, market-news, earnings-analysis, trading-strategies, ai-trading-tutorials and Investor Lounge return 403. Category member denials restrict the synced channels; stock-research has an explicit member allow.
- No real paid purchase occurred in this run. Read count was zero when checked. Direct bot-to-writer API publication is not verified because its writer token remains blank.

## AMA channel publishing

Run the new channel worker from `server/` with the same database and web URL as the API:
`.venv/bin/python ../bots/community_bot.py` after installing `bots/requirements.txt` into that environment.
Use one worker instance per publisher application. The time-window CLI and original slash-command demo are still available separately.

1. Configure the publisher application's bot token, enable Message Content Intent and register the exact web OAuth redirect URL. Configure the web service with DISCORD_PUBLISHER_APPLICATION_ID, DISCORD_OAUTH_CLIENT_SECRET, DISCORD_REVIEW_CALLBACK_URL (https://your-web-host/api/discord-review/callback), and NEXT_PUBLIC_TOLLGATE_API_URL. Set TOLLGATE_WEB_URL for the worker. Use Supabase writer authentication on shared deployments. Only the backend/worker should receive database credentials.
2. On the writer Dashboard, install the application and generate a single-use pairing code with the editor/reviewer role IDs and default USD price. An operator with Manage Server runs /connect_ama in the source channel, specifying a private reminder channel. Grant the worker View Channel and Read Message History on the source, and View Channel and Send Messages in the reminder channel. Pair again to change the site's role/price settings for this channel.
3. An editor posts `[AMA FINAL] Title`, followed by the paid text on subsequent lines, or one UTF-8 .md/.txt attachment up to 2 MB. The first valid version is frozen per message. Post a fresh marked message for a replacement edition. For a hand-selected conversation excerpt, include speaker labels and reply context in the supplied text. Historic messages before pairing and unmarked conversation are excluded.
4. Follow the private reminder or open Apps → Review AMA on the original message. Sign in with Discord, review the frozen text, edit the public abstract and price, confirm rights, then publish. The site verifies guild membership and the reviewer role with Discord on each preview and approval. Abstract-only preview and the ai-input license are fixed for this workflow. The existing article table feeds MCP, x402 and the writer ledger.
5. Open Apps → AMA sales on the original message for reviewer-only totals. Sign in as the publishing writer for the article's latest 50 transactions and receipts. Pairing, drafts and delivery state share the backend's SQLite/Postgres store. A periodic history scan resumes from the channel checkpoint, and private reminders are retried until delivered. Reminders can repeat if the worker stops between delivery and acknowledgment; the draft and article stay unique.

### Verified AMA walkthrough — November 24, 2026

FlyingC paired the test server's stock-research channel with a private ama-review
channel. The same AMA Reviewer role filled both role fields for this one-person demo.
An original English recap titled *Inference Caching: A Rollout Checklist* triggered
a private reminder. In Discord's message menu, the observed path was **Apps →
Tollgate Publisher Bot → Review AMA**. Discord OAuth, rights confirmation, and
**Confirm publication** produced article `ama-8bd4f7eda72a4d4783dd63ae7353191e`
in the local test database. **Apps → Tollgate Publisher Bot → AMA sales** and
**View writer sales** both showed zero paid reads and zero net earnings.
A live Codex model called the local MCP search tool and returned the title, $0.01
price, and ai-input license. The unpaid article endpoint returned HTTP 402.
The web app and API ran locally with demo writer authentication and the XRPL test rail.

To repeat buyer discovery on macOS, start the local API with the database containing
the published recap, sign in to the Codex CLI, and run
[`Live AMA Buyer Demo.command`](../scripts/Live%20AMA%20Buyer%20Demo.command).
The launcher connects to the local MCP endpoint on port 8000 and asks the model
to report the public listing, price, and license. A fresh database needs its own
published recap before the same search will return a match.
