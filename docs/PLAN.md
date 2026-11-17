# Toll Gate — plan: payment design v2 (Nov 11, 2026)

The v1 plan (M1–M6: Supabase, USD pricing, `PaymentRail`, Stripe credit, buyer MCP on two rails) is done; see git history before `e3f1070`. This plan replaces it.

## The demo
1. Guillermo asks Claude Desktop a niche question.
2. Claude finds the article through the Toll Gate MCP (discovery only, no browser).
3. Claude pays through Coinbase's payments-mcp (`make_http_request_with_x402`), x402 v2 on Base mainnet, USDC.
4. Claude answers, quoting the article and its signed receipt.
5. The writer dashboard shows the money, reads +1 and a BaseScan link.

## Design
- **Agents pay Toll Gate's treasury** (a CDP server wallet on Base). The ledger credits the writer, minus `PLATFORM_FEE_BPS` (default 0). Writers need no wallet.
- **One active rail per server**, `PAYMENT_RAIL=base|xrpl` (default `base`).
  - `base`: official `x402[evm,fastapi]` middleware, CDP facilitator, `eip155:8453`, `exact`, payTo = `TREASURY_BASE_ADDRESS`, price = the article's USD price as USDC atomic units (micro-dollars and USDC units are the same integer, so no conversion).
  - `xrpl`: the existing XRPL rail (plus Stripe credit if configured), unchanged. This is the fallback demo.
- Only `GET /articles/{id}` is paid. Unknown ids are 404 and disallowed agents 403, both before any payment.
- After settlement, the existing step runs: Ed25519 receipt (tx hash, BaseScan link, content hash, license, amount, payer, agent), purchase row, ledger credit.
- Amounts in the receipt and purchase come from the signed payment (`accepted`), as on XRPL.
- Agent name: `X-Agent-Name`, else User-Agent (anything containing "claude" → `Claude`), else `unknown`.

## Milestones (branch `guillebasterra/base-x402`, merged to `main` when green)
1. **Treasury**: `scripts/treasury.py` (`make treasury`), CDP `get_or_create_account(name="tollgate-treasury")`, writes `TREASURY_BASE_ADDRESS`. `--check` is read-only for pre-flight. Done: `0xdef6b98CD666aA0d43125FAF320Db60999D01913`.
2. **Server rail**: `rails/base_usdc.py` wraps the SDK middleware inside our paywall. Dynamic price via a callable. Resource URL pinned to `TOLLGATE_API_URL`. 402 body repeats the challenge in JSON for agents that read bodies. Fee column on purchases; ledger credit net of fee.
3. **Tests**: a fake facilitator (no network). Assert the v2 `PAYMENT-REQUIRED` header decodes with the SDK, `eip155:8453`, payTo = treasury, amount = price in atomic USDC. Then the official x402 Python client (`x402Client` + `ExactEvmClientScheme`, throwaway key, no funds) parses the 402, signs, and gets the body and receipt back.
4. **Buyer MCP → Toll Gate MCP**: discovery only (`search_catalog`, `get_article`), no wallet, no payments. Instructions point Claude at payments-mcp with `X-Agent-Name: Claude`.
5. **Web**: dashboard (balance, reads, latest with BaseScan link, reads by agent, disabled Withdraw), payout screen without a wallet, rail-aware copy.
6. **Ops**: `make demo-reset` keeps writers and articles, clears purchases and balances. `make preflight`. `/llms.txt` describes the Base flow.
7. **Docs**: `DEMO.md`, `CLAUDE.md`, `BRIEF.md` ("Payment design v2").

## Risks
| Risk | Plan |
|---|---|
| **payments-mcp sends the paid request from Coinbase's servers** (`payments-mcp.coinbase.com/api/proxy`), so `localhost` is unreachable | The API needs a public HTTPS URL: a tunnel (cloudflared/ngrok) or a deploy. Guillermo's call. `TOLLGATE_API_URL` drives every paid URL. Pre-flight checks it from outside |
| x402-xrpl pins `fastapi<0.116`; x402 needs Starlette ≥ 1.3 | uv `override-dependencies`. All 237 XRPL/Stripe tests pass on FastAPI 0.162 / Starlette 1.10 |
| payments-mcp uses a smart wallet (ERC-1271/6492 signatures) | The CDP facilitator verifies them. Our server never checks signatures itself |
| Real USDC on mainnet | Tests use a fake facilitator. Nothing here signs from the treasury. The first live buy is Guillermo's |
| The proxy's User-Agent isn't Claude's | The MCP tells Claude to send `X-Agent-Name: Claude` in `headers` (payments-mcp forwards them) |
| CDP facilitator down | Fallback: `PAYMENT_RAIL=xrpl` and the XRPL testnet flow in `DEMO.md` |
