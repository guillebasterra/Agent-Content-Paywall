# Toll Gate — project context

Content marketplace where AI agents buy individual articles from writers, per read, over x402 on XRPL or from Stripe-funded credit.
Demo goal: give an agent a budget → it browses `/catalog` → pays for an article → cites it, with a live dashboard of purchases.

Owner: Guillermo (Cornell Tech Product Studio + XRPL hackathon). Keep explanations brief, bullets over prose.

## Layout
- `server/` FastAPI backend (`app/main.py` builds the app via `create_app(facilitator=None, database=, content_dir=, auth=, storage=)`)
  - `db.py` one store on SQLite (demo, `server/tollgate.db`, gitignored) or Postgres (Supabase): `writers`, `articles`, `purchases`
  - `storage.py` original files in the private `uploads` bucket
  - `content.py` previews, slugs, USD/drops conversion, and seeding from `content/*.md` (frontmatter: id, title, abstract, price_usd, license, tags or keywords, optional preview_mode, train_price_usd, allowed_agents)
  - `paywall.py` the one middleware, priced from the DB per request; picks a rail
  - `rails/` `base.py` `PaymentRail` and `Sale`, `xrpl.py` the x402 rail, `stripe_credit.py` the prepaid rail, `settle.py` the shared receipt and record step
  - `stripe_gateway.py` every call to Stripe, faked in tests. `payouts.py` ledger balances to test Transfers
  - `session.py` `current_writer()`: `DemoAuth` or `SupabaseAuth`
  - `receipts.py` Ed25519-signed receipts (pynacl); public key at `/.well-known/tollgate-receipt-key`
- `buyer-mcp/` MCP server for the buyer agent
  - `buyer_mcp/server.py` tools: `get_budget`, `browse_catalog(query)`, `buy_article(id, max_price_usd)`, `get_receipts`
  - `buyer_mcp/budget.py` spend log (`buyer-mcp/budget.json`, gitignored; delete it to reset the demo budget)
- `web/` Next.js App Router: `/signin`, `/onboarding/payout`, `/dashboard` (polls every 3s), `/upload`, `/catalog`, `/articles/[id]`. Built from the "Toll Gate site mockup" artifact. `lib/session.ts` holds `getSession()`; `proxy.ts` refreshes Supabase sessions and guards writer pages; `lib/api-client.ts` `writerFetch` adds the bearer token. Public Supabase values come from the root `.env` through `next.config.ts`
- `scripts/create_wallets.py` faucet-funded testnet wallets → `.env`
- `scripts/buy_test.py` live end-to-end purchase with the buyer wallet

## Commands
- `make server` → uvicorn on :8000. Uploads are for sale immediately. Restart to import a new `content/*.md`
- `make server-test` → API tests with a mocked facilitator (no network)
- `make wallets` (`ARGS=--force` to replace after a testnet reset)
- `make buy-test` (`ARGS="--id <id> --max-xrp 1"`)
- `make buyer` → run buyer MCP over stdio
- `make web` → Next.js on :3000 (backend CORS only allows `http://localhost:3000`)
- `make buyer-test` → buyer MCP spend-control tests (payment faked, no network)
- `make supabase-setup` → schema, private bucket, checks the browser key reads nothing. `make migrate-db` copies SQLite rows to Postgres
- `make agent` buyer's agent account, key to `.env` · `make topup ARGS="--usd 10"` Checkout link · `make stripe-listen` webhook forwarding · `make payout` test Transfers
- `make rail RAIL=stripe|xrpl` → switches the buyer MCP live
- `make demo-otp EMAIL=` → prints a sign-in code without sending an email. On `/signin`: email, then "I have a code"
- `make demo-reset` → clear writers, articles, purchases and the buyer spend log. Keeps `.env`. Runbook in `docs/DEMO.md`

## Decisions (don't undo without asking)
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
- `buyer-mcp` uses `mcp>=2` (class is `MCPServer` from `mcp.server.mcpserver`, not FastMCP) plus `x402-xrpl`, with `override-dependencies = ["uvicorn>=0.31.1"]` because x402-xrpl pins uvicorn<0.31.
- XRPL purchases go through `x402_xrpl.clients.x402_purchase(..., max_value=<drops>)` — hard price cap.
- Python 3.12, uv-managed per subproject.
- `AUTH_MODE=demo|supabase`. Demo keeps one placeholder writer on SQLite with unauthenticated writer routes, so don't expose it publicly. Supabase uses email codes and Postgres.
- ES256/RS256 tokens are verified locally against JWKS. HS256 tokens go to `/auth/v1/user`, as Supabase recommends. No JWT secret is stored, so a token can't pick a weaker check.
- Every Postgres table has RLS on and no policies, because Supabase serves `public` to the browser key. Any new table must join `TABLES` in `db.py`. `make supabase-setup` checks this live.
- Original-file storage is best effort: the text is in the database, so a Storage outage must not stop publishing.
- Sign-in works by magic link (`/auth/callback`) or code. The default Supabase email holds only a link and its template can't change without custom SMTP, so codes come from `make demo-otp`. `SUPABASE_SERVICE_ROLE_KEY` is an `sb_secret_` key, sent in `apikey` only (`service_headers`), never as a bearer.
- Writers set their byline on onboarding. A new writer's name starts as the email's local part.
- Content lives in the database. On startup, `content/*.md` files with a new id are imported to the demo writer (in Supabase mode, a house account nobody signs in as). Editing an imported file changes nothing, and frontmatter `author` and `pay_to` are ignored. `content/demo/` is not imported: those are files to upload by hand, so the demo starts empty.
- The demo writer's address comes from `WRITER_ADDRESS` once. After `make wallets ARGS=--force`, update it on `/onboarding/payout`.
- `X-Agent-Name` is self-reported. It's recorded per purchase, and `allowed_agents` is checked against it (403 before any payment), so this is an honor system, not access control. Buyer MCP sends `BUYER_AGENT_NAME` (default `Claude`).
- Free previews are capped at half the article, so "first 100 words" can't give away a short piece. The rule is in `preview_text` and mirrored in `web/app/upload/form.tsx`.
- The blurred text on the site is filler (`BLURRED_FILLER`). Paid text must never be sent to the browser.
- `/llms.txt` is the agent-facing guide. Keep it in sync with the payment flow.
- The buyer's budget and caps are USD (`BUYER_BUDGET_USD`, `BUYER_CONFIRM_ABOVE_USD`), so one budget covers every rail.
- Human approval above `BUYER_CONFIRM_ABOVE_USD` uses `Resolve`/`Elicit`, never `ctx.elicit` (fails on protocol 2026-07-28, which Claude Code speaks) and never a tool argument (the model could self-approve). It fails closed.
- `max_value` passed to the SDK is the exact catalog price the budget and approval covered, and the selector also pins asset and `pay_to`.
- A budget entry is written before payment. Ambiguous outcomes (`settlement_unknown`, HTTP errors after paying) stay held and block retries until a human edits `budget.json`.
- Re-buying an owned article returns the saved copy for free, on either rail.
- `BUYER_RAIL` is read from `.env` on every call, and the file wins over the process env, so don't set it in the Claude Desktop config. On the Stripe rail, connection refused and HTTP refusals release the budget; timeouts and 5xx stay held.
- Catalog search matches any word of the query, so an agent's natural phrasing finds the piece.

## Rules
- Never commit `.env` (holds wallet seeds + RECEIPT_SIGNING_KEY). Never print seeds.
- Never source `.env` in a shell. Lines can have a space after `=`, and the shell then runs the value as a command and prints it. Read it with dotenv.
- Wallet seeds stay inside the MCP/server process — never put them in the model's context or tool outputs.
- Commit messages end with the Co-Authored-By / Claude-Session attribution lines the session provides.

## Pick up here (as of Nov 4, end of day)
- Everything is merged to `main`. No servers are running. Start them from `docs/DEMO.md`
- **Rotate first, if not done:** the Supabase `sb_secret_` key, the database password and the Stripe test key were printed into a Claude session transcript on Nov 4. They were not committed. Afterwards update `.env` and rebuild with `make web-demo`
- **Open decision, Guillermo's:** how to show the agent buying. He doesn't like forcing Claude Desktop and is considering deploying the site. Don't deploy until he says so. Options are in `docs/PLAN.md`
- Supabase holds rehearsal data: 1 writer with no payout method and 1 article, no purchases. `make demo-reset` clears it. Its Storage bucket also holds Claude's old test uploads in 2 folders, which reset doesn't touch and which are safe to delete
- `.env` has `AUTH_MODE=supabase` and `BUYER_RAIL=xrpl`
- Next for a human: finish Stripe onboarding, then run `make payout`

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
- [ ] A real model has never run the purchase. The tools were called directly over stdio, so the agent's choices and its citation are untested in Desktop and Claude Code. Desktop isn't configured and is skipped for now
- [ ] `next dev` sometimes shows a "1 Issue" badge, cause not found, nothing in the console. `make web-demo` has no overlay
- [ ] `.docx` and `.pdf` uploads (415 for now) · Xaman button (disabled, "Coming soon") · Training sales (the license and price are stored, there is no way to buy yet)
- [ ] Phase 6 real articles (Guillermo writes; `content/demo/` holds invented drafts) · [ ] Phase 7 rehearsal + backup recording
- Later list: `docs/BRIEF.md`.
