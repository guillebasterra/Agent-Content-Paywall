# Toll Gate — project context

Content marketplace where AI agents buy individual articles from writers, per read, over x402 on XRPL.
Demo goal: give an agent a budget → it browses `/catalog` → pays for an article → cites it, with a live dashboard of purchases.

Owner: Guillermo (Cornell Tech Product Studio + XRPL hackathon). Keep explanations brief, bullets over prose.

## Layout
- `server/` FastAPI backend (`app/main.py` builds the app via `create_app(facilitator=None, db_path=, content_dir=)`)
  - `db.py` SQLite store: `writers`, `articles`, `purchases` (`server/tollgate.db`, gitignored)
  - `content.py` previews, slugs, XRP/drops conversion, and seeding from `content/*.md` (frontmatter: id, title, abstract, price_xrp, license, tags or keywords, optional preview_mode, train_price_xrp, allowed_agents)
  - `paywall.py` the one x402 middleware, priced from the DB per request
  - `session.py` `current_writer()`, the auth placeholder
  - `receipts.py` Ed25519-signed receipts (pynacl); public key at `/.well-known/tollgate-receipt-key`
- `buyer-mcp/` MCP server for the buyer agent
  - `buyer_mcp/server.py` tools: `get_budget`, `browse_catalog(query)`, `buy_article(id, max_price_xrp)`, `get_receipts`
  - `buyer_mcp/budget.py` spend log (`buyer-mcp/budget.json`, gitignored; delete it to reset the demo budget)
- `web/` Next.js App Router: `/signin`, `/onboarding/payout`, `/dashboard` (polls every 3s), `/upload`, `/catalog`, `/articles/[id]`. Built from the "Toll Gate site mockup" artifact, with amounts in XRP. `lib/session.ts` holds `getSession()`, the auth placeholder
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

## Decisions (don't undo without asking)
- Rail: x402 "exact" scheme on XRPL testnet (`xrpl:1`), priced in XRP drops, settled by t54 facilitator `https://xrpl-facilitator-testnet.t54.ai`. Stripe/Base is the planned production rail behind the same interface.
- `x402-xrpl==0.3.4` pinned (early-stage SDK). `paywall.py` matches `/articles/{id}`, reads price and `pay_to` from the DB, and builds `RequireX402Options` per request for `require_x402`.
- Invoices are stored per article (`ScopedInvoices`). The SDK checks a payment against its invoice, not the URL, so a shared store would let a cheap article's invoice buy an expensive one. Keep `test_invoice_for_a_cheap_article_cannot_buy_another`.
- t54 enforces `SourceTag=804681468` → set via `source_tag` in `RequireX402Options`.
- Settlement info (tx hash) only exists after the handler runs, so an outer `attach_receipt` middleware decodes `PAYMENT-RESPONSE`, signs the receipt, records it, and injects `receipt` into the JSON body. Price and `pay_to` in the receipt come from the signed payment, not the DB, because a writer can change address between invoice and payment.
- Payment goes straight to the writer's address (`pay_to`); the platform never holds funds.
- `buyer-mcp` uses `mcp>=2` (class is `MCPServer` from `mcp.server.mcpserver`, not FastMCP) plus `x402-xrpl`, with `override-dependencies = ["uvicorn>=0.31.1"]` because x402-xrpl pins uvicorn<0.31.
- Buyer purchases go through `x402_xrpl.clients.x402_purchase(..., max_value=<drops>)` — hard price cap.
- Python 3.12, uv-managed per subproject.
- Auth is a placeholder: sign-in screens are UI only and every action runs as one demo writer. Supabase Auth replaces both seams later: backend `current_writer()` and frontend `getSession()`. Until then, writer endpoints are unauthenticated, so don't expose the backend publicly.
- Content lives in SQLite. On startup, `content/*.md` files with a new id are imported to the demo writer. Editing an imported file changes nothing, and frontmatter `author` and `pay_to` are ignored.
- The demo writer's address comes from `WRITER_ADDRESS` once. After `make wallets ARGS=--force`, update it on `/onboarding/payout`.
- `X-Agent-Name` is self-reported. It's recorded per purchase, and `allowed_agents` is checked against it (403 before any payment), so this is an honor system, not access control. Buyer MCP sends `BUYER_AGENT_NAME` (default `Claude`).
- Free previews are capped at half the article, so "first 100 words" can't give away a short piece. The rule is in `preview_text` and mirrored in `web/app/upload/form.tsx`.
- The blurred text on the site is filler (`BLURRED_FILLER`). Paid text must never be sent to the browser.
- `/llms.txt` is the agent-facing guide. Keep it in sync with the payment flow.
- Human approval above `BUYER_CONFIRM_ABOVE_XRP` uses `Resolve`/`Elicit`, never `ctx.elicit` (fails on protocol 2026-07-28, which Claude Code speaks) and never a tool argument (the model could self-approve). It fails closed.
- `max_value` passed to the SDK is the exact catalog price the budget and approval covered, and the selector also pins asset and `pay_to`.
- A budget entry is written before payment. Ambiguous outcomes (`settlement_unknown`, HTTP errors after paying) stay held and block retries until a human edits `budget.json`.
- Re-buying an owned article returns the saved copy for free.

## Rules
- Never commit `.env` (holds wallet seeds + RECEIPT_SIGNING_KEY). Never print seeds.
- Wallet seeds stay inside the MCP/server process — never put them in the model's context or tool outputs.
- Commit messages end with the Co-Authored-By / Claude-Session attribution lines the session provides.

## Status
- [x] Phase 1 scaffold · [x] Phase 2 wallets · [x] Phase 3 backend (tested with a mocked facilitator)
- [x] Live `make buy-test` settled on testnet · [x] Phase 4 buyer MCP (registered with `claude mcp add`)
- [ ] Try one above-threshold purchase in an interactive Claude Code session (approval prompt not yet seen by a human)
- [x] Phase 5 web: six mockup screens, SQLite content, per-request paywall, uploads, dashboard
- [ ] `.docx` and `.pdf` uploads (415 for now) · Stripe and Xaman buttons (disabled, "Coming soon") · Training sales (the license and price are stored, there is no way to buy yet)
- [ ] **Next:** Phase 6 real articles (Guillermo writes) · [ ] Phase 7 rehearsal + backup recording
- Later: passage-level sales, training-vs-reference licensing (RSL `ai-input`), receipt-as-access-token for re-reads, Stripe rail.
