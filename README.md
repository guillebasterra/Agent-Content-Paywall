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
- [ ] Phase 4 — buyer MCP
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
