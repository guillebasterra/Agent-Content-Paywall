# Demo runbook (payment design v2)

Claude Desktop finds an article through the Toll Gate MCP, pays for it with Coinbase's payments-mcp (x402 v2, USDC on Base mainnet, to Toll Gate's treasury), and answers with a quote and the signed receipt. The writer dashboard shows the money, reads +1 and a BaseScan link. Design: `PLAN.md`.

**Real money.** Base mainnet, real USDC from the payments-mcp wallet. Each read costs the article's price (e.g. $0.40). Nothing here ever spends from the treasury.

## One-time setup
1. Pull `main` in `~/me/cornell/dev/tollgate` (Claude Desktop runs the MCP from there).
2. Treasury: done (`0xdef6b98CD666aA0d43125FAF320Db60999D01913`, CDP account `tollgate-treasury`). `make treasury` reuses it by name and rewrites `TREASURY_BASE_ADDRESS` if needed.
3. A public URL tool: `brew install cloudflared`. payments-mcp sends the paid request from Coinbase's servers (`payments-mcp.coinbase.com/api/proxy`), so `localhost` can't work.
4. Claude Desktop: merge this into `mcpServers` in `~/Library/Application Support/Claude/claude_desktop_config.json`, next to `payments-mcp`, then quit and reopen Desktop:
   ```json
   "tollgate": {
     "command": "/Users/guillebasterra/.local/bin/uv",
     "args": ["run", "--directory", "/Users/guillebasterra/me/cornell/dev/tollgate/buyer-mcp", "python", "-m", "buyer_mcp.server"]
   }
   ```
   No keys go in this file. The MCP reads `TOLLGATE_API_URL` from `.env`.
5. payments-mcp wallet: signed in, with a few dollars of USDC on Base. No ETH needed: x402 USDC payments are gasless for the payer.

## Start (each run)
Repo root, one terminal each:
```bash
make tunnel      # writes the public https URL to .env as TOLLGATE_API_URL. Leave it open
make server      # :8000. Start (or restart) after the tunnel, so it reads the new URL
make web-demo    # :3000, production build. Rebuild after changing .env
make preflight   # API up, Base rail, treasury = CDP account, CDP keys + facilitator, catalog, public URL serves the 402
```
The quick-tunnel URL changes on every `make tunnel`: restart `make server` each time. Keep `AUTH_MODE=supabase`, since the API is public while the tunnel is open; pre-flight fails on `AUTH_MODE=demo`. Close the tunnel after the demo.

## Before the demo
- [ ] `make test` passes
- [ ] `make demo-reset`: clears purchases and balances, keeps writers and articles. `ARGS=--all` also deletes writers and articles
- [ ] The answering article is in the catalog (`content/demo/orchard-frost-fans.md`, uploaded on `/upload`)
- [ ] `make preflight` prints "all checks passed"
- [ ] Signed in on `http://localhost:3000/dashboard` (code via `make demo-otp EMAIL=...`)
- [ ] In Desktop, both MCPs are on (tools menu shows `tollgate` and `payments-mcp`), and a new chat is open

## The demo
1. Windows side by side: Claude Desktop and the dashboard.
2. Paste into a new chat:
   > Why do Halden Valley orchards start their frost fans at 2.4 degrees? Find the answer on Toll Gate and buy the one article that answers it with payments-mcp. Then answer in a few sentences with a direct quote, the article's title and author, and its receipt: amount, transaction hash and BaseScan link.
3. Claude calls `search_catalog`, picks the frost-fans piece, then `make_http_request_with_x402` with the `payment` arguments the MCP returned (`X-Agent-Name: Claude`, `maxAmountPerRequest` = the price). payments-mcp may ask you to approve in its window.
4. Claude answers with the quote and receipt.
5. Switch to the dashboard (it polls every 3s): balance +$0.40, reads +1, "from Claude", BaseScan link on the latest read and in Recent reads.

Buying the same article again charges again (the server charges every read). Ask a different question or run `make demo-reset` after rehearsing.

## If something fails
| Symptom | Fix |
|---|---|
| payments-mcp: request failed / can't reach URL | `make preflight`. Usually the tunnel URL changed: restart `make server` |
| 402 after paying, `settlement_failed` | CDP facilitator or chain issue. Check BaseScan for the payer, then the XRPL fallback |
| Agent shows as something other than Claude | Claude didn't pass `headers`. The prompt can say "send the payment arguments exactly as returned" |
| 403 | The article's `allowed_agents` excludes the name sent |

## Fallback: XRPL testnet (no real money)
1. In `.env`: `PAYMENT_RAIL=xrpl`. Restart `make server`. Rebuild `make web-demo` so the site's copy says XRP.
2. Pre-flight for XRPL: `curl -s https://xrpl-facilitator-testnet.t54.ai/supported` responds. Buyer wallet funded (`make wallets ARGS=--force` after a testnet reset).
3. Show the purchase: `make buy-test ARGS="--id why-halden-valley-orchards-run-their-frost-fans-at-2-4-degrees --max-xrp 1"`. It pays from the buyer wallet, prints the receipt and explorer link, and the dashboard ticks with an XRPL link.
4. Agent-driven instead: the old paying buyer MCP is at tag `buyer-mcp-xrpl-v1`. `git worktree add ../tollgate-xrpl buyer-mcp-xrpl-v1`, `ln -s ~/me/cornell/dev/tollgate/.env ../tollgate-xrpl/.env`, and point a Desktop entry at `../tollgate-xrpl/buyer-mcp`. It works against today's server in `xrpl` mode.

Stripe credit still works on the `xrpl` rail (`make agent`, `make topup`, `make stripe-listen`), but it's out of the demo.
