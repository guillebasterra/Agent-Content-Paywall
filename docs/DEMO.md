# Demo runbook

Flow and goals are in `BRIEF.md`. This is how to run it. Sections marked *(later milestone)* fill in as those land.

## Start
Three terminals from the repo root, in this order:
```bash
make demo-reset
make server     # :8000
make web        # :3000
```

For the real demo, set `AUTH_MODE=supabase` in `.env` and run `make supabase-setup` once. `AUTH_MODE=demo` is the fallback: one placeholder writer, no sign-in, SQLite.

## Sign-in codes
Supabase's built-in email allows only a few sends per hour, so a rehearsal can use up the demo's send. Rehearse with `make demo-otp EMAIL=you@example.com`, which prints a code and sends nothing. If the live email is rate limited, the same command rescues the demo.

The Magic Link email template must contain `{{ .Token }}`, or no code arrives.

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
