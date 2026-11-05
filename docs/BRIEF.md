# Toll Gate — build brief (demo: Nov 5, 2026)

Read this with CLAUDE.md. You own planning and implementation. Only stop for me when you need something you can't get yourself (see "When to check in").

## Goal

A working end-to-end demo of a content marketplace where AI agents buy individual articles from writers, per read, and cite them, with two payment rails (XRPL and Stripe), real writer sign-in (email), and a writer site that matches the mockup.

## The demo (exact flow, ~3 minutes)

Before: server, web and buyer MCP running; `make demo-reset` run; I'm signed out.

1. Sign in: I open the site, enter my email, type the one-time code, and land on payout onboarding as a new writer.
2. Payout method: I paste my XRPL address (rail 1). I also click "Connect with Stripe" and finish Stripe Connect test-mode onboarding (rail 2). The dashboard shows both.
3. Upload: from the empty dashboard I drop a `.md` file. The form opens prefilled: title, abstract, free preview length, keywords, price per read ($0.40), training license (not for training), and which agents can buy. I publish, and it appears in the Catalog as a square tile with the clear preview, the blurred rest, author, earned and reads.
4. Agent buys over XRPL: in Claude Desktop, with the buyer MCP set to the XRPL rail and a $5 budget, I ask a question only my article answers. The agent:
   - searches the catalog
   - picks my piece
   - asks me to approve if the price is above the threshold
   - pays over x402 on XRPL testnet (~4s)
   - answers with the article's title, author and a quote, plus the receipt and explorer link
5. Writer sees it: the dashboard ticks up live (+$0.40, agent "Claude", explorer link), and the catalog tile's reads go up.
6. Agent buys over Stripe: I switch the buyer MCP to the Stripe rail (prepaid credit funded by a Stripe test card) and ask a second question. A different piece is bought and debited from credit. The dashboard shows the read as Stripe-funded, and my Stripe balance accrues.
7. For agents: I open `/llms.txt` to show how any agent discovers and pays.

Each step must work without manual fixes. Steps 1–5 are the core; never let a commit break them.

## Architecture

### Components (keep the current layout)
- `server/`: FastAPI. Source of truth for writers, articles, purchases, receipts, rails.
- `web/`: Next.js thin client over the API, matching the mockup screens (Sign in, Payout method, Dashboard, Upload, Catalog, Article). Look as already built.
- `buyer-mcp/`: the agent's tools (`get_budget`, `browse_catalog`, `buy_article`, `get_receipts`), with budget, approval threshold, `X-Agent-Name`, and a `BUYER_RAIL=xrpl|stripe` setting.
- Supabase: Auth (email one-time code), Postgres, Storage bucket `uploads` (private, original files).

### Auth
- `AUTH_MODE=demo|supabase`. Demo mode keeps the current placeholder writer and SQLite and must keep working as a fallback.
- Supabase mode: the frontend uses `@supabase/ssr` with a `/auth/callback` route. Backend `current_writer()` verifies the Supabase JWT (check current docs: JWKS vs legacy secret) and maps the auth user to a `writers` row, created on first login.
- Postgres via `SUPABASE_DB_URL` in Supabase mode; SQLite via `DATABASE_URL` in demo mode. Same schema. Migrate the existing rows.
- Email one-time code (OTP) only; show the code-entry step on /signin. Google sign-in and XRPL-wallet sign-in come later; remove the Google button and keep the XRPL-wallet button as a "coming soon" stub.
- Supabase's built-in email sender is rate-limited (a few emails per hour). Avoid sending real emails in automated tests, and tell me if I need custom SMTP.

### Pricing
- The canonical price is USD (`price_usd`) per article. The XRPL amount is computed per invoice from `XRP_USD_RATE` (placeholder env, since testnet XRP has no real value). The UI shows "≈ $X" with XRP as secondary text where relevant.

### Payment rails (one `PaymentRail` interface; both settle into the same purchases and receipts tables)

1. XRPL rail (non-custodial, built)
   - x402 "exact" on XRPL testnet, settled by the t54 facilitator; SourceTag 804681468.
   - `payTo` is the writer's XRPL address, so money goes straight to the writer. If a writer has no XRPL address, `payTo` is a platform treasury testnet address and the writer is credited in the ledger.
   - Receipt: the Ed25519-signed receipt as now, with `rail: "xrpl"` and the tx hash.

2. Stripe rail (custodial, test mode only)
   - Agent operators get an agent account plus API key (`Authorization: Bearer tg_test_...`). They top up prepaid credit through Stripe Checkout (test card). Per-read card charges don't work because of Stripe's ~$0.50 minimum and fees.
   - `GET /articles/{id}` with a valid agent key and sufficient credit returns 200 + article + receipt with `rail: "stripe"`; the read is debited from credit. Without a key the response is still the x402 402. Also list a `stripe-credit` option in the 402 body so agents learn it exists.
   - Writers: Stripe Connect Express onboarding in test mode. Earnings accrue in the internal ledger; a `make payout` (or admin endpoint) creates test-mode Transfers to connected accounts.
   - Check Stripe's current machine-payments docs (x402/MPP, Shared Payment Tokens). If test-mode access is available without gating, note it in docs as the upgrade path. The prepaid-credit design above is the baseline either way.
   - Webhooks for Checkout completion: use the Stripe CLI (`stripe listen`) locally.

### Data model (extend what exists)
- `writers`: auth_user_id, name, email, xrpl_address, stripe_account_id, payout flags
- `articles`: writer_id, title, abstract, body, preview_mode, keywords, price_usd, license, train_price_usd, allowed_agents, storage_path, created_at
- `agents`: name, api_key_hash, credit_usd
- `purchases`: article_id, writer_id, agent name, rail, amount_usd, amount_native, tx_hash or stripe ref, receipt, created_at
- `ledger_entries` for custodial balances (agent credit, writer accrued, transfers)

### Agent discovery
- `GET /llms.txt` covers what Toll Gate is, how to search, both payment options, license meaning, and the receipt key URL.

## Non-goals tonight
- No real money, no mainnet, no production deploy.
- Training restrictions are license metadata and receipts only; no enforcement tech.
- Google sign-in, XRPL-wallet sign-in and passage-level sales come later.

## Later (not tonight)

Keep this list current: add anything deferred while building, and don't build these tonight.

### Auth
- Google sign-in (Google Cloud OAuth client → Supabase provider)
- XRPL-wallet sign-in: the user signs a challenge with Xaman and the backend verifies the signature (needs a Xaman developer account and API keys)
- Custom SMTP (e.g. Resend) to lift Supabase's email rate limit
- Link one writer account to several sign-in methods

### Payments in (agents → Toll Gate)
- Stripe machine payments: x402 (USDC on Base/Solana/Tempo) and/or MPP with Shared Payment Tokens, once test-mode access is confirmed
- MPP sessions or XRPL payment channels for high-frequency agents (pre-authorized cap, off-ledger claims)
- RLUSD (stablecoin) pricing on XRPL instead of XRP
- x402 on Base/Solana (USDC), where most agent volume is today
- Card top-ups for AI companies that won't hold crypto (prepaid credit, invoicing)
- AP2 / Verifiable Intent mandates as proof a user approved a purchase
- Real FX rate (replace `XRP_USD_RATE`)

### Payouts (Toll Gate → writers)
- Stripe Connect in live mode: KYC, payout schedules, tax forms (1099s)
- Writer wallet options: bring your own, Toll Gate-created wallet, or Stripe only
- Legal review of custodial balances (money transmission) before handling real funds

### Licensing and access
- Passage-level sales (sell the relevant chunks instead of the whole piece)
- Training license as a separate, priced product
- RSL vocabulary in 402 responses and `llms.txt`
- Receipts as access tokens (re-read within N days without paying again)
- Per-buyer text fingerprinting to trace training leaks

### Agent identity and trust
- Web Bot Auth (signed agent requests) to replace `X-Agent-Name`
- XRPL Credentials for verified writers
- Reputation/quality signals (upvotes, third-party follower counts)

### Writers and content
- `.docx` / `.pdf` parsing on upload
- Substack import plus ownership verification (code on the about page); later a Substack plugin
- Human-reader lane with its own pricing and engagement metrics

### Discovery and distribution
- List paid endpoints on the x402 Bazaar and the XRPL AI Hub
- Public `llms.txt`, docs and success stories for AI-engine optimization
- Niche-creator recruiting

### Infrastructure
- Production deploy (hosting, domain, public resource URLs)
- XRPL mainnet and live Stripe
- Monitoring, rate limiting, abuse handling

## How to work
1. Write `docs/PLAN.md` first (milestones, order, risks), then execute without waiting for me.
2. Order, so the demo stays shippable at every step:
   1. Merge phase-5-web → main; `make demo-reset`; `docs/DEMO.md` (startup commands, Claude Desktop config, pre-flight checklist, fallback if t54 is down)
   2. Supabase auth + Postgres behind `AUTH_MODE`
   3. USD pricing + `PaymentRail` interface (XRPL rail refactored onto it)
   4. Stripe rail: agent accounts, Checkout top-up, credit debit, Connect onboarding, test payouts
   5. Buyer MCP `BUYER_RAIL=stripe`
   6. Full demo run of steps 1–7 in Supabase mode, with fixes
3. Use a branch per milestone. Run all tests before merging to main, and merge yourself when green. Push after each merge.
4. Keep tests passing and add tests for both auth modes and both rails (mock Stripe and the facilitator in tests). Do at least one live testnet purchase and one live Stripe test-mode purchase.
5. Update CLAUDE.md (status, decisions) and DEMO.md as you go.

## When to check in with me
- You need a key, password or dashboard action: Supabase, Stripe (test keys, Connect settings, CLI login).
- You'd have to break the core demo (steps 1–5) to proceed.
- A product decision this brief doesn't settle and that's expensive to reverse.

Everything else: decide, note it in CLAUDE.md, keep going.

## Rules
- Never commit `.env`, `web/.env.local`, seeds, or Stripe and Supabase secrets. Never print seeds or secret keys.
- Stripe in test mode only; refuse live keys.
- Wallet seeds and API keys stay inside server and MCP processes, never in tool outputs or model context.
- Commit messages end with the attribution lines the session provides.
