# Toll Gate — build plan (demo: Nov 5, 2026)

Executes `docs/BRIEF.md`. One branch per milestone. All tests pass before each merge to `main`, then push. Demo steps 1–5 stay working at every merge.

## Milestones

### M1 — Baseline (`m1-baseline`)
- Fast-forward `phase-5-web` into `main`.
- `make demo-reset`: wipes writers, articles, purchases and the buyer spend log. Keeps wallets and keys.
- Move the placeholder article out of auto-import to `content/demo/`, so the dashboard and catalog start empty.
- Two demo pieces to upload (`content/demo/`), clearly marked as drafts for Guillermo to replace.
- Catalog search matches any word of the query, so natural agent queries find something.
- `docs/DEMO.md`: startup commands, Claude Desktop config, pre-flight checklist, t54 fallback.

### M2 — Supabase auth and Postgres (`m2-supabase`)
- `AUTH_MODE=demo|supabase`. Demo mode is unchanged and stays the fallback.
- Backend: `current_writer()` verifies the JWT and maps `sub` to a `writers` row, created on first login.
  - ES256/RS256: local check against JWKS, with issuer, audience and expiry.
  - HS256 (legacy project): ask the Auth server (`/auth/v1/user`), as Supabase recommends. No shared secret is stored, which also rules out algorithm confusion.
- Database: one `Database` class on SQLite or Postgres (psycopg + pool). Same schema. Tests run against both, using a local embedded Postgres.
- **RLS on every table with no policies.** Supabase exposes `public` through the anon key, so without this anyone could read article bodies and key hashes from the browser.
- `scripts/migrate_to_postgres.py` copies existing SQLite rows.
- Storage: originals go to the private `uploads` bucket, best-effort (the body is in the DB, so a Storage outage doesn't block publishing).
- Web: `@supabase/ssr`, `proxy.ts`, `/auth/callback`, code-entry step on `/signin`, sign-out. Remove Google, stub the XRPL wallet button. Bearer token on API calls.
- Author name field on onboarding, since the agent cites it and an email can't supply it.
- `make demo-otp`: generates a code through the admin API without sending an email. Used by automated runs and as the demo fallback if the email limit is hit.

### M3 — USD pricing and `PaymentRail` (`m3-rails`)
- USD is canonical, stored as integer micro-dollars (`price_usd_micros` etc.), matching how drops are stored. Floats never touch money, and SQLite has no decimal type. The API exposes `price_usd` strings.
- Drops are computed per invoice from `XRP_USD_RATE`, rounded up to a whole drop.
- `server/app/rails/`: `PaymentRail` interface, XRPL rail moved onto it. Both settle through one function: sign receipt, write purchase, write ledger.
- Treasury: a writer with no address gets `payTo` = treasury and is credited in the ledger. `make wallets` creates the treasury wallet.
- Migration for old rows, at the rate the UI already used (1 XRP = $2).
- Upload and all screens in USD, XRP as secondary text.
- Buyer MCP: budget and caps in USD (`buy_article(id, max_price_usd)`), still pinned to exact drops on the XRPL rail.

### M4 — Stripe rail (`m4-stripe`)
- Refuses anything but test keys at startup.
- Agent accounts: `POST /agents` returns a `tg_test_...` key once; only the hash is stored.
- Top-up: Checkout Session → webhook (`stripe listen`) credits the agent. The success page also reconciles from Stripe, using the same idempotent function, so the demo survives a dead listener.
- `GET /articles/{id}` with a bearer key: atomic debit in one transaction with purchase and ledger entries. Invalid key 401, low credit 402 with no body, `X-Max-Price-Usd` as a hard cap mirroring x402's `max_value`.
- The 402 body lists `stripe-credit` under `alternatives`, outside `accepts`, so x402 clients are unaffected. A test runs the SDK's parser against it.
- Connect Express onboarding, status on the payout screen and dashboard, `make payout` creating test Transfers (idempotent).
- Dashboard: both payout methods, Stripe balance, recent reads with rail. `/llms.txt`: both options.

### M5 — Buyer MCP on Stripe (`m5-buyer-stripe`)
- `BUYER_RAIL=xrpl|stripe`. Same budget book, approval and hold-on-ambiguity rules on both rails.
- Rail is read from `.env` on each call, so `make rail RAIL=stripe` switches without restarting Claude Desktop.
- Key stays in the process, never in tool output.

### M6 — Full demo run (`m6-demo-run`)
- Steps 1–7 in Supabase mode, live: real OTP, Stripe test onboarding, testnet purchase, Stripe test purchase, payout. Fix what breaks.
- The MCP is driven over stdio, as Desktop does. Claude Desktop itself needs a human pass (see Risks).

## What Guillermo must provide
Nothing else blocks on him. Mock-tested code merges without these; live checks wait for them.
- **Supabase**: project URL, publishable key, service role key, session pooler DB URL. Dashboard: `http://localhost:3000/auth/callback` in redirect URLs. The email template stays default (editing it needs custom SMTP), so `make demo-otp` supplies codes.
- **Stripe**: test secret key, Connect enabled on the account. `make stripe-listen` uses the key, so `stripe login` isn't needed.

## Decisions the brief leaves open
- **Second piece for step 6**: the writer uploads two files. "My Stripe balance accrues" needs the piece to be theirs, and step 3 needs an empty dashboard, so nothing can be pre-seeded.
- **Writer balance sources**: Stripe-rail reads and treasury-routed XRPL reads both accrue. Payouts go only through Stripe Connect; without an account the balance waits.
- **Stripe-rail agent name** comes from the authenticated account, not `X-Agent-Name`.
- **`tx_hash` column** holds the chain hash or the Stripe-credit ref; `rail` says which (the brief's "tx_hash or stripe ref").
- **Server-side re-reads are charged again.** The buyer MCP's saved copy is what makes re-buying free, as on XRPL. Receipts as access tokens are on the Later list.

## Risks
| Risk | Plan |
|---|---|
| Supabase built-in email allows only a few sends per hour, and its template can't include a code | Rehearse and demo with `make demo-otp`, which sends nothing. The emailed magic link also works |
| Stripe balance is pending after a normal test card, so Transfers fail | Top up with `4000 0000 0000 0077` (funds available immediately). In DEMO.md |
| Stripe refused Express (`type` and `controller`) for this sandbox | Happened. Now Accounts v2 with an Express dashboard, Stripe collecting fees and losses |
| Stripe onboarding shows a CAPTCHA | Happened. Not automatable, so a human does it |
| Claude Desktop may not support elicitation | Approval fails closed. $0.40 is under the $1 threshold, so the core flow doesn't need it |
| Claude Desktop can't be driven from here | Stdio run covers the MCP. Guillermo does one Desktop pass before the demo |
| t54 facilitator down | Fallback in DEMO.md: Stripe rail, and a backup recording |
| Sync Postgres calls in async middleware | Fine for one demo user. Noted for production |
| Pooler connection limits or latency on the 3s dashboard poll | Small pool, prepared statements off |

## Stripe machine payments (checked Nov 4)
- x402 on Stripe: live acceptance is gated by review. A sandbox path exists using Base Sepolia and the public `x402.org` facilitator.
- MPP / Shared Payment Tokens: no sign-up form, `link-cli --test`, needs agent OAuth and per-spend approval.
- Neither replaces prepaid credit tonight. Both go in docs as the upgrade path.
