# Demo runbook

Flow and goals are in `BRIEF.md`. This is how to run it. Sections marked *(later milestone)* fill in as those land.

## Start
Three terminals from the repo root, in this order:
```bash
make demo-reset
make server     # :8000
make web        # :3000
```

## Claude Desktop
`~/Library/Application Support/Claude/claude_desktop_config.json`, then restart Desktop:
```json
{"mcpServers": {"tollgate-buyer": {"command": "/Users/guillebasterra/.local/bin/uv",
  "args": ["run", "--directory", "/Users/guillebasterra/me/cornell/dev/tollgate/buyer-mcp", "python", "-m", "buyer_mcp.server"]}}}
```
Seeds and limits are read from `.env`. Keep them out of this file.

## Files to upload
`content/demo/` has two invented draft pieces, one per rail. Replace them with real writing.
- `orchard-frost-fans.md`. Ask: "Why do Halden Valley orchards start frost fans at 2.4 degrees?"
- `tidewater-ferry-fares.md`. Ask: "How did the 1987 Tidewater ferry strike end?"

Upload both: step 6 needs a second piece of yours, or your Stripe balance can't accrue.

## Pre-flight
- [ ] `make server-test` and `make buyer-test` pass
- [ ] `curl -s https://xrpl-facilitator-testnet.t54.ai/supported` responds
- [ ] `make demo-reset` run, server restarted
- [ ] Signed out in the browser
- [ ] Buyer wallet has testnet XRP (`get_budget` shows the balance). If the testnet was reset: `make wallets ARGS=--force`

## If t54 is down
Purchases return a payment failure or stay `outcome_unknown`. Nothing else in the flow depends on it.
- Show steps 1–3, then the backup recording for steps 4–5.
- If a purchase is held as `outcome_unknown`, `make demo-reset` clears the spend log (testnet only).
