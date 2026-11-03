# Toll Gate

A content marketplace where AI agents buy individual articles from writers, per read.

Demo: give an agent a budget, it browses the catalog, pays for an article over x402 (XRPL testnet), and cites it.

## Layout

| Dir | What |
|---|---|
| `server/` | FastAPI backend — free catalog, x402 paywall, signed receipts |
| `buyer-mcp/` | MCP server for the buyer agent — wallet, budget, buy tools |
| `web/` | Next.js storefront + live purchases dashboard |
| `content/` | Seed articles (Markdown + frontmatter) |
| `scripts/` | Wallet creation, seeding |

## Requirements

- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node 20+

## Setup

```bash
cp .env.example .env
cd server && uv sync && cd ..
cd buyer-mcp && uv sync && cd ..
```

## Run

```bash
make server   # http://localhost:8000
```

## Status

- [x] Phase 1 — repo scaffold
- [x] Phase 2 — testnet wallets
- [x] Phase 3 — backend (catalog, paywall, receipts)
- [x] Phase 4 — buyer MCP
- [ ] Phase 5 — web storefront + dashboard
- [ ] Phase 6 — seed content
- [ ] Phase 7 — rehearsal

## API

| Route | Access | Returns |
|---|---|---|
| `GET /catalog?q=` | free | titles, abstracts, prices, license, paid URL |
| `GET /articles/{id}` | x402 | full text + Ed25519-signed receipt (tx hash, content hash, license) |
| `GET /ledger` | free | recent purchases + earnings per writer |
| `GET /.well-known/tollgate-receipt-key` | free | public key to verify receipts |

Live test: `make server` in one terminal, `make buy-test` in another.

## Buyer agent (MCP)

Register it from the repo root. The wallet seed is read from `.env`, so it never goes in client config:

```bash
claude mcp add tollgate-buyer -- uv run --directory "$PWD/buyer-mcp" python -m buyer_mcp.server
```

For Claude Desktop, add this to `claude_desktop_config.json`, using absolute paths:

```json
{"mcpServers": {"tollgate-buyer": {"command": "/absolute/path/to/uv",
  "args": ["run", "--directory", "/absolute/path/to/tollgate/buyer-mcp", "python", "-m", "buyer_mcp.server"]}}}
```

| Tool | Does |
|---|---|
| `get_budget` | Budget, spent, remaining, wallet balance |
| `browse_catalog(query)` | Articles and prices, free |
| `buy_article(id, max_price_xrp)` | Pays, returns the text and a verified receipt. Owned articles are free |
| `get_receipts` | Receipts, explorer links, unresolved payments |

Limits come from `BUYER_BUDGET_XRP` and `BUYER_CONFIRM_ABOVE_XRP`. Spending is logged in `buyer-mcp/budget.json`, and the budget covers article prices, not network fees. Delete that file to reset the budget between demo runs.

If `buy_article` returns `outcome_unknown`, the budget stays held and retries are blocked. Check the transaction on the explorer. Then set the entry's status to `paid`, or delete the entry if the payment never landed.
