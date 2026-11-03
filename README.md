# Toll Gate

A content marketplace where AI agents buy individual articles from writers, per read.

Demo: give an agent a budget, it browses the catalog, pays for an article over x402 (XRPL testnet), and cites it.

## Layout

| Dir | What |
|---|---|
| `server/` | FastAPI backend — SQLite content, free catalog, x402 paywall, signed receipts, writer dashboard |
| `buyer-mcp/` | MCP server for the buyer agent — wallet, budget, buy tools |
| `web/` | Next.js writer dashboard, upload, catalog and article pages |
| `content/` | Seed articles (Markdown + frontmatter), imported into SQLite on startup |
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
make web      # http://localhost:3000
```

The backend only allows the origin `http://localhost:3000`, so keep that port and hostname. Set `NEXT_PUBLIC_TOLLGATE_API_URL` to use a backend other than `http://localhost:8000`.

Tests: `make server-test` and `make buyer-test`.

## Status

- [x] Phase 1 — repo scaffold
- [x] Phase 2 — testnet wallets
- [x] Phase 3 — backend (catalog, paywall, receipts)
- [x] Phase 4 — buyer MCP
- [x] Phase 5 — web storefront + dashboard
- [ ] Phase 6 — seed content
- [ ] Phase 7 — rehearsal

## API

| Route | Access | Returns |
|---|---|---|
| `GET /catalog?q=&sort=reads\|earned\|new` | free | titles, abstracts, free previews, prices, license, reads, earned, paid URL |
| `GET /articles/{id}` | x402 | full text + Ed25519-signed receipt (tx hash, content hash, license) |
| `GET /llms.txt` | free | how agents search, pay and verify receipts |
| `GET /ledger` | free | recent purchases + earnings per writer |
| `GET /.well-known/tollgate-receipt-key` | free | public key to verify receipts |
| `POST /articles` | writer | publish from a multipart `.md` or `.txt` file. For sale immediately |
| `GET /me/dashboard` | writer | totals, pieces with reads, earned and agents, earnings by agent |
| `GET`, `PUT /me/payout` | writer | payout method and XRPL address |

Writer routes run as one demo writer until Supabase Auth replaces `current_writer()` and `getSession()`, so don't expose the backend publicly. Buyers can send an `X-Agent-Name` header, which is recorded with each purchase.

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
