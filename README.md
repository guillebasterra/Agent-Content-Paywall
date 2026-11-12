# Toll Gate

A content marketplace where AI agents buy individual articles from writers, per read.

Demo: Claude finds an article through the Toll Gate MCP, pays for it with Coinbase's payments-mcp over x402 (USDC on Base, to Toll Gate's treasury), and cites it with a signed receipt. The writer's dashboard is credited live. XRPL testnet is the fallback rail. Runbook: `docs/DEMO.md`.

## Layout

| Dir | What |
|---|---|
| `server/` | FastAPI backend — SQLite content, free catalog, x402 paywall, signed receipts, writer dashboard |
| `buyer-mcp/` | Toll Gate MCP — discovery only (`search_catalog`, `get_article`). No wallet |
| `web/` | Next.js writer dashboard, upload, catalog and article pages |
| `content/` | Seed articles (Markdown + frontmatter), imported into SQLite on startup |
| `scripts/` | Treasury (CDP) and XRPL wallets, pre-flight, tunnel, demo reset |

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

The backend allows one browser origin, `TOLLGATE_WEB_URL` (default `http://localhost:3000`). Set `NEXT_PUBLIC_TOLLGATE_API_URL` to use a backend other than `http://localhost:8000`.

Tests: `make test` (or `make server-test` and `make buyer-test`).

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
| `GET /catalog/{id}` | free | one article's free view |
| `GET /articles/{id}` | x402 | full text + Ed25519-signed receipt (tx hash, explorer link, content hash, license, amount, payer, agent). `PAYMENT_RAIL=base`: x402 v2, USDC on Base to the treasury. `xrpl`: XRPL testnet |
| `GET /llms.txt` | free | how agents search, pay and verify receipts |
| `/mcp` | free | remote MCP (streamable HTTP): `search_catalog`, `get_article` |
| `GET /ledger` | free | recent purchases + earnings per writer |
| `GET /.well-known/tollgate-receipt-key` | free | public key to verify receipts |
| `POST /articles` | writer | publish from a multipart `.md` or `.txt` file. For sale immediately |
| `GET /me/dashboard` | writer | totals, pieces with reads, earned and agents, earnings by agent |
| `GET`, `PUT /me/payout` | writer | name, Toll Gate balance, payout method (XRPL address on the fallback rail) |

With `AUTH_MODE=demo`, writer routes run unauthenticated as one demo writer, so don't expose the backend publicly. With `AUTH_MODE=supabase` they need a Supabase access token. Buyers can send an `X-Agent-Name` header (else the User-Agent is used), which is recorded with each purchase.

Live XRPL test (`PAYMENT_RAIL=xrpl`): `make server` in one terminal, `make buy-test` in another.

## Toll Gate MCP

Discovery only: it holds no wallet and can't pay. Claude pays the returned URL with Coinbase's payments-mcp (`make_http_request_with_x402`). Defined once in `server/app/agent_mcp.py`, served two ways:
- **Remote** (what users add): `https://tollgate-production-55166a8d.up.railway.app/mcp`, streamable HTTP, read-only, no sign-in. Setup for any Claude user: `docs/AGENT_SETUP.md`.
- **Local stdio** (development): `make buyer`, or `claude mcp add tollgate -- uv run --directory "$PWD/buyer-mcp" python -m buyer_mcp.server`. Reads the catalog from `TOLLGATE_API_URL`.

| Tool | Does |
|---|---|
| `search_catalog(query)` | Title, author, free preview, price, license, paid URL and payments-mcp arguments, best match first |
| `get_article(id)` | The same for one article |

The old paying buyer MCP (XRPL wallet, budget, Stripe credit) is at git tag `buyer-mcp-xrpl-v1`.
