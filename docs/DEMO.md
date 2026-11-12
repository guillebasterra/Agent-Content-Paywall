# Demo runbook (payment design v2)

Claude Desktop finds an article through the Toll Gate MCP, pays for it with Coinbase's payments-mcp (x402 v2, USDC on Base mainnet, to Toll Gate's treasury), and answers with a quote and the signed receipt. The writer dashboard shows the money, reads +1 and a BaseScan link. Design: `PLAN.md`.

**Real money.** Base mainnet, real USDC from the payments-mcp wallet. Each read costs the article's price (e.g. $0.40). Nothing here ever spends from the treasury.

## One-time setup
The API runs on Railway: `https://tollgate-production-55166a8d.up.railway.app` (deploys on push to `main`). Agent setup for any Claude user, including you: `AGENT_SETUP.md`. In short:
1. payments-mcp in Claude Desktop, signed in, with a little USDC on Base (articles are $0.02).
2. Toll Gate as a custom connector: **Customize > Connectors > + Add > Add custom connector**, URL `https://tollgate-production-55166a8d.up.railway.app/mcp`, **No sign in**. This replaces the local stdio entry in `claude_desktop_config.json`.
3. Treasury: done (`0xdef6b98CD666aA0d43125FAF320Db60999D01913`, CDP account `tollgate-treasury`).

Prices: `make set-price ARGS="--usd 0.02"` (all) or `ARGS="--usd 0.40 --id <id>"`. It writes the database in `.env`, which is the one Railway uses.

## Start (each run)
```bash
make preflight ARGS="--url https://tollgate-production-55166a8d.up.railway.app"
make web-demo    # the writer dashboard on :3000, against the API in NEXT_PUBLIC_TOLLGATE_API_URL (localhost by default)
```
The dashboard reads the same Supabase database as Railway, so a local `make server` also shows Railway's purchases. For local development without Railway, `make tunnel` + `make server` still work (see `make preflight` without `--url`), and the stdio MCP runs with `make buyer`.

## Before the demo
- [ ] `make test` passes
- [ ] `make demo-reset`: clears purchases and balances, keeps writers and articles. `ARGS=--all` also deletes writers and articles
- [ ] The answering article is in the catalog (`content/demo/orchard-frost-fans.md`, uploaded on `/upload`)
- [ ] `make preflight ARGS="--url https://tollgate-production-55166a8d.up.railway.app"` prints "all checks passed"
- [ ] Signed in on `http://localhost:3000/dashboard` (code via `make demo-otp EMAIL=...`)
- [ ] In Desktop, a new chat with **+ > Connectors > Toll Gate** on, and payments-mcp available

## The demo
1. Windows side by side: Claude Desktop and the dashboard.
2. Paste into a new chat:
   > Why do Halden Valley orchards start their frost fans at 2.4 degrees? Find the answer on Toll Gate and buy the one article that answers it with payments-mcp. Then answer in a few sentences with a direct quote, the article's title and author, and its receipt: amount, transaction hash and BaseScan link.
3. Claude calls the connector's `search_catalog`, picks the frost-fans piece, then `make_http_request_with_x402` with the `payment` arguments it returned (`X-Agent-Name: Claude`, `maxAmountPerRequest` = the price). Desktop may ask you to allow each tool.
4. Claude answers with the quote and receipt.
5. Switch to the dashboard (it polls every 3s): balance +$0.02, reads +1, "from Claude", BaseScan link on the latest read and in Recent reads.

Buying the same article again charges again (the server charges every read). Ask a different question or run `make demo-reset` after rehearsing.

## If something fails
| Symptom | Fix |
|---|---|
| payments-mcp: request failed / can't reach URL | `make preflight ARGS="--url …"`. Check the Railway deploy |
| Toll Gate tools missing in Desktop | Restart Desktop; check https://claude.ai/customize/connectors |
| 402 after paying, `settlement_failed` | CDP facilitator or chain issue. Check BaseScan for the payer, then the XRPL fallback |
| Agent shows as something other than Claude | Claude didn't pass `headers`. The prompt can say "send the payment arguments exactly as returned" |
| 403 | The article's `allowed_agents` excludes the name sent |

## Fallback: XRPL testnet (no real money)
1. In `.env`: `PAYMENT_RAIL=xrpl`. Restart `make server`. Rebuild `make web-demo` so the site's copy says XRP.
2. Pre-flight for XRPL: `curl -s https://xrpl-facilitator-testnet.t54.ai/supported` responds. Buyer wallet funded (`make wallets ARGS=--force` after a testnet reset).
3. Show the purchase: `make buy-test ARGS="--id why-halden-valley-orchards-run-their-frost-fans-at-2-4-degrees --max-xrp 1"`. It pays from the buyer wallet, prints the receipt and explorer link, and the dashboard ticks with an XRPL link.
4. Agent-driven instead: the old paying buyer MCP is at tag `buyer-mcp-xrpl-v1`. `git worktree add ../tollgate-xrpl buyer-mcp-xrpl-v1`, `ln -s ~/me/cornell/dev/tollgate/.env ../tollgate-xrpl/.env`, and point a Desktop entry at `../tollgate-xrpl/buyer-mcp`. It works against today's server in `xrpl` mode.

Stripe credit still works on the `xrpl` rail (`make agent`, `make topup`, `make stripe-listen`), but it's out of the demo.
