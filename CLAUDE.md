# Toll Gate — project context

Content marketplace where AI agents buy individual articles from writers, per read. Payment design v2: agents pay Toll Gate's treasury in USDC on Base over x402, and the ledger credits the writer.
Demo goal: Claude Desktop finds an article with the Toll Gate MCP → pays with Coinbase's payments-mcp → answers with a quote and the signed receipt, while the writer dashboard ticks live. Runbook: `docs/DEMO.md`.

Owner: Guillermo (Cornell Tech Product Studio + XRPL hackathon). Keep explanations brief, bullets over prose.

## Layout
- `server/` FastAPI backend (`app/main.py` builds the app via `create_app(facilitator=None, database=, content_dir=, auth=, storage=, stripe_gateway=, base_facilitator=)`)
  - `db.py` one store on SQLite (demo, `server/tollgate.db`, gitignored) or Postgres (Supabase): `writers`, `articles`, `purchases`
  - `storage.py` original files in the private `uploads` bucket
  - `content.py` previews, slugs, USD/drops conversion, and seeding from `content/*.md` (frontmatter: id, title, abstract, price_usd, license, tags or keywords, optional preview_mode, train_price_usd, allowed_agents)
  - `paywall.py` the one middleware, priced from the DB per request; picks a rail. `agent_name()`: `X-Agent-Name`, else User-Agent ("claude" → `Claude`), else `unknown`
  - `rails/` `base.py` `PaymentRail` and `Sale` (not Base the chain), `base_usdc.py` x402 v2 on Base (the demo), `xrpl.py` x402 on XRPL testnet, `stripe_credit.py` the prepaid rail, `settle.py` the shared receipt and record step
  - `stripe_gateway.py` every call to Stripe, faked in tests. `payouts.py` ledger balances to test Transfers
  - `session.py` `current_writer()`: `DemoAuth` or `SupabaseAuth`
  - `receipts.py` Ed25519-signed receipts (pynacl); public key at `/.well-known/tollgate-receipt-key`
  - `agent_mcp.py` the Toll Gate MCP (`build_mcp(search, lookup)`), mounted at `/mcp` (streamable HTTP) and reused by the stdio MCP. Imports only `mcp` and the stdlib
- `buyer-mcp/` the Toll Gate MCP over stdio, for development: imports `server/app/agent_mcp.py` and reads the catalog over HTTP. Discovery only: `search_catalog(query)`, `get_article(id)`. No wallet, no payments. Each result carries `paid_url` and a `payment` object of arguments for payments-mcp's `make_http_request_with_x402`. The old paying MCP (XRPL wallet, budget, approval, Stripe credit) is at git tag `buyer-mcp-xrpl-v1`
- `web/` Next.js App Router: `/signin`, `/onboarding/payout`, `/dashboard` (polls every 3s), `/upload`, `/catalog`, `/articles/[id]`. Built from the "Toll Gate site mockup" artifact. `lib/session.ts` holds `getSession()`; `proxy.ts` refreshes Supabase sessions and guards writer pages; `lib/api-client.ts` `writerFetch` adds the bearer token. Public Supabase values come from the root `.env` through `next.config.ts`
- `scripts/treasury.py` the Base treasury (CDP server account `tollgate-treasury`) → `TREASURY_BASE_ADDRESS`. `scripts/preflight.py`, `scripts/tunnel.py`
- `scripts/create_wallets.py` faucet-funded XRPL testnet wallets → `.env`
- `scripts/buy_test.py` live end-to-end XRPL purchase with the buyer wallet (`PAYMENT_RAIL=xrpl`)

## Commands
- `make server` → uvicorn on :8000. Uploads are for sale immediately. Restart to import a new `content/*.md`
- `make server-test` → API tests with fake facilitators (no network). `make test` runs server and MCP tests
- `make treasury` → create or reuse the CDP treasury, save `TREASURY_BASE_ADDRESS` (`ARGS=--check` read-only)
- `make tunnel` → Cloudflare quick tunnel to :8000, writes `TOLLGATE_API_URL`; restart `make server` after
- `make preflight` → read-only checks for the Base demo (API, rail, treasury, CDP keys, facilitator, catalog, public URL). `ARGS="--url https://…"` checks a deploy
- `make wallets` (`ARGS=--force` to replace after a testnet reset)
- `make buy-test` (`ARGS="--id <id> --max-xrp 1"`)
- `make buyer` → run the Toll Gate MCP over stdio
- `make web` → Next.js on :3000 (backend CORS allows only `TOLLGATE_WEB_URL`, default `http://localhost:3000`)
- `make buyer-test` → Toll Gate MCP tests (API faked, no network)
- `make supabase-setup` → schema, private bucket, checks the browser key reads nothing. `make migrate-db` copies SQLite rows to Postgres
- `make agent` buyer's agent account, key to `.env` · `make topup ARGS="--usd 10"` Checkout link · `make stripe-listen` webhook forwarding · `make payout` test Transfers
- `make rail RAIL=stripe|xrpl` → only for the old paying MCP. The server's rail is `PAYMENT_RAIL=base|xrpl` in `.env`, then restart
- `make demo-otp EMAIL=` → prints a sign-in code without sending an email. On `/signin`: email, then "I have a code"
- `make set-price ARGS="--usd 0.02"` (all) or `ARGS="--usd 0.40 --id <id>"` → reprices in the `.env` database (Supabase, shared with Railway)
- `make demo-reset` → clear purchases and balances, keep writers and articles (`ARGS=--all` also deletes writers and articles). Keeps `.env`

## Decisions (don't undo without asking)
### Payment design v2 (Nov 11)
- `PAYMENT_RAIL=base|xrpl`, default `base`. One rail per server. `base` has no Stripe; `xrpl` is the old XRPL + Stripe-credit setup, kept as the fallback.
- Base rail: official `x402[evm,fastapi]==2.27.0` middleware inside our paywall, x402 v2 `exact`, `eip155:8453`, USDC, CDP facilitator (`cdp-sdk` `create_facilitator_config` with `CDP_API_KEY_ID/SECRET`). Only `GET /articles/{id}` is paid; 404 and 403 happen before the SDK runs.
- Agents pay `TREASURY_BASE_ADDRESS`, a CDP server account named `tollgate-treasury` (`0xdef6b98CD666aA0d43125FAF320Db60999D01913`). Nothing in the repo signs from it. Never spend from or move treasury funds.
- Price: the SDK's price callback returns an `AssetAmount` of the article's `price_usd_micros`, since micro-dollars and USDC atomic units are the same integer. The article reaches the callback through a `ContextVar`.
- The challenge's resource URL is `TOLLGATE_API_URL` (`public_request()` rewrites scheme and host), so it's right behind a tunnel.
- Receipt and purchase amounts come from the signed payment (`payload.accepted`), like XRPL. The writer is credited `amount − fee` (`PLATFORM_FEE_BPS`, rounded down) in `ledger_entries`; a non-zero fee goes to account `platform/tollgate`. `purchases.fee_usd_micros`; "earned" everywhere a writer sees it is net.
- payments-mcp proxies paid requests through `payments-mcp.coinbase.com/api/proxy`, so the API needs a public https URL. It forwards the tool's `headers`, so the MCP tells Claude to send `X-Agent-Name: Claude`.
- The Toll Gate MCP builds payments-mcp arguments from the server's own `url`, with `maxAmountPerRequest` = the listed price as a hard cap. Ids are URL-quoted so they can't reach other routes.
- `x402-xrpl` pins `fastapi<0.116` and x402 needs Starlette ≥ 1.3, so `server/pyproject.toml` overrides `fastapi>=0.162.0`. All XRPL and Stripe tests pass on it.
- Remote MCP (Nov 12): `/mcp` on the API, stateless streamable HTTP with JSON replies, read-only, no auth (public catalog data only). DNS-rebinding protection off because the server is public by design. Paid URLs come from the server's `TOLLGATE_API_URL`. Users add it as a Claude custom connector (`docs/AGENT_SETUP.md`); payments-mcp stays local. The stdio MCP shares `agent_mcp.py`, so the two can't drift.
- `mcp>=2.3` in the server needs `uvicorn>=0.31.1`, also overridden (x402-xrpl pins `<0.31`).
- Bazaar listing (Nov 28): the Base route is `GET /articles/:id` (named, not `*`) with `declare_discovery_extension` (path param `id`, output example), `service_name`, ≤5 tags, and a description ≤500 chars that points agents to the free `/catalog?q=` search (startup refuses a longer one: the facilitator rejects verify and settle above it). CDP lists one entry per route template after the first settled purchase whose payload echoes the extension, and drops it after 30 days without one. No `/.well-known/x402` ownership proofs: they need a treasury signature. `make preflight` runs CDP's public validator and reports whether it's listed
- Catalog search: any word matches; results are ordered by how many distinct query words match, ties by the requested sort.
- Tests: `tests/test_base.py` uses a fake facilitator and the official x402 Python client (throwaway key, no funds) through `httpx.ASGITransport`. Keep `test_payment_for_a_cheap_article_cannot_buy_another`.

### XRPL, Stripe, auth and content (v1)
- XRPL rail: x402 "exact" scheme on XRPL testnet (`xrpl:1`), invoiced in XRP drops, settled by t54 facilitator `https://xrpl-facilitator-testnet.t54.ai`.
- Prices are USD, stored as integer micro-dollars (`*_usd_micros`), exposed as `price_usd` strings. Floats never touch money, and SQLite has no decimal type. Drops are computed per invoice from `XRP_USD_RATE` (placeholder), rounded up to a whole drop.
- Stripe rail is custodial and test mode only: live keys are refused at startup. Agents prepay credit through Checkout; a read is one transaction that debits credit (conditional update, so it can't go negative), writes the purchase and accrues to the writer.
- Webhook and Checkout's success page credit through one idempotent function, so a dead `stripe listen` doesn't lose a top-up.
- On the Stripe rail, the agent name comes from the authenticated account, not `X-Agent-Name`. `X-Max-Price-Usd` is a hard cap like x402's `max_value`. The server charges every read; the buyer's saved copy is what makes re-buying free.
- `stripe-credit` is listed under `alternatives` in the 402 body, not in `accepts`, because x402 clients read every `accepts` entry as x402.
- Connect status is pulled on return from onboarding (`/me/stripe/refresh`), so local dev needs no Connect webhooks. Stripe refuses v1 `type=express` for this sandbox, so `create_connected_account` uses Accounts v2: Express dashboard (preview version), merchant + recipient, Stripe collecting fees and losses.
- `purchases.tx_hash` holds the chain hash or the Stripe-credit ref, and `rail` says which. Old rows convert at the rate the UI used (1 XRP = $2).
- `x402-xrpl==0.3.4` pinned (early-stage SDK). `rails/xrpl.py` builds `RequireX402Options` per request for `require_x402`, with price and `pay_to` from the DB.
- Invoices are stored per article (`ScopedInvoices`). The SDK checks a payment against its invoice, not the URL, so a shared store would let a cheap article's invoice buy an expensive one. Keep `test_invoice_for_a_cheap_article_cannot_buy_another`.
- t54 enforces `SourceTag=804681468` → set via `source_tag` in `RequireX402Options`.
- Settlement info (tx hash) only exists after the handler runs, so `XrplRail` decodes `PAYMENT-RESPONSE` after the SDK returns, signs the receipt, records it, and injects `receipt` into the JSON body. Price and `pay_to` in the receipt come from the signed payment, not the DB, because a writer can change address between invoice and payment.
- XRPL payments go straight to the writer's address. A writer with no address is paid through `TREASURY_ADDRESS` and credited in `ledger_entries`. This is where the platform starts holding money, so custodial balances need legal review before real funds.
- `buyer-mcp` uses `mcp>=2` (class is `MCPServer` from `mcp.server.mcpserver`, not FastMCP).
- Python 3.12, uv-managed per subproject.
- `AUTH_MODE=demo|supabase`. Demo keeps one placeholder writer on SQLite with unauthenticated writer routes, so don't expose it publicly. Supabase uses email codes and Postgres.
- ES256/RS256 tokens are verified locally against JWKS. HS256 tokens go to `/auth/v1/user`, as Supabase recommends. No JWT secret is stored, so a token can't pick a weaker check.
- Every Postgres table has RLS on and no policies, because Supabase serves `public` to the browser key. Any new table must join `TABLES` in `db.py`. `make supabase-setup` checks this live.
- Original-file storage is best effort: the text is in the database, so a Storage outage must not stop publishing.
- Sign-in works by magic link (`/auth/callback`) or code. The default Supabase email holds only a link and its template can't change without custom SMTP, so codes come from `make demo-otp`. `SUPABASE_SERVICE_ROLE_KEY` is an `sb_secret_` key, sent in `apikey` only (`service_headers`), never as a bearer.
- Writers set their byline on onboarding. A new writer's name starts as the email's local part.
- Content lives in the database. On startup, `content/*.md` files with a new id are imported to the demo writer (in Supabase mode, a house account nobody signs in as). Editing an imported file changes nothing, and frontmatter `author` and `pay_to` are ignored. `content/demo/` is not imported: those are files to upload by hand, so the demo starts empty.
- The demo writer's address comes from `WRITER_ADDRESS` once. After `make wallets ARGS=--force`, update it on `/onboarding/payout`.
- The agent name is self-reported (`X-Agent-Name` or User-Agent). It's recorded per purchase and in the receipt, and `allowed_agents` is checked against it (403 before any payment), so this is an honor system, not access control. The Toll Gate MCP tells Claude to send `BUYER_AGENT_NAME` (default `Claude`).
- Free previews are capped at half the article, so "first 100 words" can't give away a short piece. The rule is in `preview_text` and mirrored in `web/app/upload/form.tsx`.
- The blurred text on the site is filler (`BLURRED_FILLER`). Paid text must never be sent to the browser.
- `/llms.txt` is the agent-facing guide. Keep it in sync with the payment flow.
- Old paying MCP (tag `buyer-mcp-xrpl-v1`): budget in USD, approval via `Resolve`/`Elicit` (never `ctx.elicit`, never a tool argument), `x402_purchase(..., max_value=<drops>)`, budget entry written before payment, ambiguous outcomes held. Spend limits now live in payments-mcp.
- Catalog search matches any word of the query, so an agent's natural phrasing finds the piece.

## Rules
- Never commit `.env` (holds wallet seeds + RECEIPT_SIGNING_KEY). Never print seeds.
- Never source `.env` in a shell. Lines can have a space after `=`, and the shell then runs the value as a command and prints it. Read it with dotenv.
- Wallet seeds stay inside the MCP/server process — never put them in the model's context or tool outputs. CDP keys and the wallet secret stay in `.env`; scripts print addresses only.
- Base is mainnet with real USDC. Never spend from the treasury or move funds. Live purchases are Guillermo's.
- Commit messages end with the Co-Authored-By / Claude-Session attribution lines the session provides.

## Pick up here (as of Nov 12)
- API on Railway: `https://tollgate-production-55166a8d.up.railway.app`, deploys on push to `main` (`server/Dockerfile`, build context `server/`). Same Supabase database as the local `.env`
- Remote MCP at `/mcp` (Toll Gate custom connector). Setup for any Claude user: `docs/AGENT_SETUP.md`
- All three articles are $0.02 (set with `make set-price`)
- **Next for Guillermo:** add the connector, then the first live purchase in Claude Desktop. The real-model flow is untested
- Guillermo's `claude_desktop_config.json` has only `payments-mcp` (node from a versioned Homebrew Cellar path). No stdio `tollgate` entry
- **Rotate, if not done:** the Supabase `sb_secret_` key, the database password and the Stripe test key (printed into a transcript on Nov 4)

## Status
- [x] Phase 1 scaffold · [x] Phase 2 wallets · [x] Phase 3 backend (tested with a mocked facilitator)
- [x] Live `make buy-test` settled on testnet · [x] Phase 4 buyer MCP (registered with `claude mcp add`)
- [ ] Try one above-threshold purchase in an interactive Claude Code session (approval prompt not yet seen by a human)
- [x] Phase 5 web: six mockup screens, SQLite content, per-request paywall, uploads, dashboard
- [x] M1 baseline · [x] M2 Supabase + Postgres · [x] M3 USD + `PaymentRail` · [x] M4 Stripe rail · [x] M5 buyer on Stripe. Plan in `docs/PLAN.md`
- [x] Live: XRPL purchase through the real MCP over stdio, with browser upload and dashboard tick, in demo mode
- [x] M6 live in Supabase mode, from `make demo-reset`: code sign-in, magic link (PKCE), upload to Postgres and Storage, XRPL buy, Checkout top-up, webhook, Stripe buy, dashboard, `/llms.txt`. The MCP was driven over stdio
- [x] Guillermo signed in himself on the live site
- [ ] Needs a human: Stripe hosted onboarding (CAPTCHA), so "dashboard shows both", `connected` status and a successful `make payout` are unverified live
- [x] v2: CDP treasury on Base · Base rail with the official x402 middleware + CDP facilitator · ledger credit net of fee · Toll Gate MCP (discovery) · dashboard (balance, reads, BaseScan, by agent, Withdraw stub) · payout screen without a wallet · `/llms.txt` · `make demo-reset` keeps content · `make preflight`. 293 server + 8 MCP tests
- [x] v2 checked live without paying: server started against the real CDP facilitator and served a correct v2 challenge (`400000` USDC atomic to the treasury); pre-flight green except the public URL
- [x] Railway deploy passes `make preflight --url` · [x] remote MCP at `/mcp`, tested with the MCP client locally and on Railway
- [ ] v2 live: connector added in Claude, first real purchase with payments-mcp (Guillermo)
- [ ] A real model has never run a purchase end to end
- [ ] `next dev` sometimes shows a "1 Issue" badge, cause not found, nothing in the console. `make web-demo` has no overlay
- [ ] `.docx` and `.pdf` uploads (415 for now) · Xaman button (disabled, "Coming soon") · Training sales (the license and price are stored, there is no way to buy yet)
- [ ] Phase 6 real articles (Guillermo writes; `content/demo/` holds invented drafts) · [ ] Phase 7 rehearsal + backup recording
- Later list: `docs/BRIEF.md`.
