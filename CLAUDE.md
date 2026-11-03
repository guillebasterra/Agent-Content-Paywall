# Toll Gate — project context

Content marketplace where AI agents buy individual articles from writers, per read, over x402 on XRPL.
Demo goal: give an agent a budget → it browses `/catalog` → pays for an article → cites it, with a live dashboard of purchases.

Owner: Guillermo (Cornell Tech Product Studio + XRPL hackathon). Keep explanations brief, bullets over prose.

## Layout
- `server/` FastAPI backend (`app/main.py` builds the app via `create_app(facilitator=None)`)
  - `content.py` loads `content/*.md` (frontmatter: id, title, author, abstract, price_xrp, license, tags, optional pay_to)
  - `db.py` SQLite purchase log (`server/tollgate.db`, gitignored)
  - `receipts.py` Ed25519-signed receipts (pynacl); public key at `/.well-known/tollgate-receipt-key`
- `buyer-mcp/` MCP server for the buyer agent (Phase 4 — currently only a `ping` tool)
- `web/` Next.js storefront + dashboard (Phase 5, not scaffolded)
- `scripts/create_wallets.py` faucet-funded testnet wallets → `.env`
- `scripts/buy_test.py` live end-to-end purchase with the buyer wallet

## Commands
- `make server` → uvicorn on :8000 (restart after adding/editing articles; prices are bound at startup)
- `make wallets` (`ARGS=--force` to replace after a testnet reset)
- `make buy-test` (`ARGS="--id <id> --max-xrp 1"`)
- `make buyer` → run buyer MCP over stdio

## Decisions (don't undo without asking)
- Rail: x402 "exact" scheme on XRPL testnet (`xrpl:1`), priced in XRP drops, settled by t54 facilitator `https://xrpl-facilitator-testnet.t54.ai`. Stripe/Base is the planned production rail behind the same interface.
- `x402-xrpl==0.3.4` pinned (early-stage SDK). Its `require_payment` middleware matches exact paths with a fixed price, so `create_app` registers one middleware per article.
- t54 enforces `SourceTag=804681468` → set via `source_tag` in `require_payment`.
- Settlement info (tx hash) only exists after the handler runs, so an outer `attach_receipt` middleware decodes `PAYMENT-RESPONSE`, signs the receipt, records it, and injects `receipt` into the JSON body.
- Payment goes straight to the writer's address (`pay_to`); the platform never holds funds.
- `buyer-mcp` uses `mcp>=2` (class is `MCPServer` from `mcp.server.mcpserver`, not FastMCP) plus `x402-xrpl`, with `override-dependencies = ["uvicorn>=0.31.1"]` because x402-xrpl pins uvicorn<0.31.
- Buyer purchases go through `x402_xrpl.clients.x402_purchase(..., max_value=<drops>)` — hard price cap.
- Python 3.12, uv-managed per subproject.

## Rules
- Never commit `.env` (holds wallet seeds + RECEIPT_SIGNING_KEY). Never print seeds.
- Wallet seeds stay inside the MCP/server process — never put them in the model's context or tool outputs.
- Commit messages end with the Co-Authored-By / Claude-Session attribution lines the session provides.

## Status
- [x] Phase 1 scaffold · [x] Phase 2 wallets · [x] Phase 3 backend (tested with a mocked facilitator)
- [ ] **Next:** run `make buy-test` against live testnet and fix any t54 rejections
- [ ] Phase 4 buyer MCP: tools `get_budget`, `browse_catalog(query)`, `buy_article(id, max_price_xrp)`, `get_receipts`; budget file + confirm-above threshold; register with `claude mcp add` / Claude Desktop
- [ ] Phase 5 web: Next.js storefront + live `/ledger` feed with testnet explorer links
- [ ] Phase 6 real articles (Guillermo writes) · [ ] Phase 7 rehearsal + backup recording
- Later: passage-level sales, training-vs-reference licensing (RSL `ai-input`), receipt-as-access-token for re-reads, Stripe rail.
