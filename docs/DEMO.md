# Demo runbook

Flow and goals are in `BRIEF.md`. This is how to run it. Sections marked *(later milestone)* fill in as those land.

## Start
From the repo root, in this order. Reset runs once and each service stays open in its own terminal:
```bash
make demo-reset
make server     # :8000
make web-demo   # :3000, production build. Rebuild after changing .env
make stripe-listen   # a fourth terminal, see Stripe below
```

For the real demo, set `AUTH_MODE=supabase` in `.env` and run `make supabase-setup` once. `AUTH_MODE=demo` is the fallback: one placeholder writer, no sign-in, SQLite.

## Sign-in
The default Supabase email holds only a link, and changing its template needs custom SMTP. It also allows only a few sends per hour. So rehearse and demo with a code, which sends nothing:
1. On `/signin`, enter your email and choose **I have a code**.
2. Run `make demo-otp EMAIL=you@example.com` and type the code it prints.

Run it right before step 1. **Continue** still emails a magic link, which works if opened in the same browser that requested it.

## Showing the agent buy
**Undecided, and untested with a real model:** see "Open decision" in `PLAN.md`. Whichever agent is used, keep the two windows side by side, agent and dashboard, and start a new chat for each purchase. Ask for the citation in the prompt, or the model decides what to include.

Step 4, on the XRPL rail:
> Why do Halden Valley orchards start their frost fans at 2.4 degrees? Use Toll Gate: check your budget, search the catalog, and buy only what you need. Answer with the article's title, the author, a direct quote, and the receipt with its explorer link.

Step 6, after uploading the second piece and running `make rail RAIL=stripe`:
> How did the 1987 Tidewater ferry strike end? Use Toll Gate and buy only what you need. Answer with the title, author, a direct quote and the receipt.

The Stripe answer has no explorer link. Its receipt shows a `stripe_ref`.

Buying an owned piece again returns the saved copy for free and the dashboard won't tick, so run `make demo-reset` after rehearsing.

Claude Code already has `tollgate-buyer` registered, so a new `claude` session in a terminal can run the same prompts.

## Claude Desktop (optional, currently skipped)
`~/Library/Application Support/Claude/claude_desktop_config.json`, then restart Desktop:
```json
{"mcpServers": {"tollgate-buyer": {"command": "/Users/guillebasterra/.local/bin/uv",
  "args": ["run", "--directory", "/Users/guillebasterra/me/cornell/dev/tollgate/buyer-mcp", "python", "-m", "buyer_mcp.server"]}}}
```
Seeds and limits are read from `.env`. Keep them out of this file. Switch rails for step 6 with `make rail RAIL=stripe`; no restart needed.

## Stripe
**Step 2 is yours to click.** Stripe's hosted onboarding shows a CAPTCHA, so it can't be automated. Choose **Use test phone number** and the other test shortcuts. Each `make demo-reset` means a new writer, so onboarding happens again. It takes a couple of minutes: consider doing it on camera only in the recording.

One-time: `make agent` creates the buyer's account and saves its key to `.env`.

Each run, in its own terminal: `make stripe-listen`. Restart `make server` the first time, so it reads the webhook secret.

Top up before step 6: `make topup ARGS="--usd 10"`. On the Checkout page choose **Card** (the delayed methods it also lists don't credit at once) and pay with **4000 0000 0000 0077**, any future date, any CVC. Untick "Save my information with Link", or it asks for a phone number. That card makes funds available at once; a normal test card leaves them pending and `make payout` fails with insufficient funds. If the listener is down, the page Checkout returns to still adds the credit.

After step 6, `make payout` sends the accrued balance to the writer's connected account as a test Transfer.

## Files to upload
`content/demo/` has two invented draft pieces, one per rail. The form prefills from their frontmatter. Replace them with real writing.
- `orchard-frost-fans.md`. Ask: "Why do Halden Valley orchards start frost fans at 2.4 degrees?"
- `tidewater-ferry-fares.md`. Ask: "How did the 1987 Tidewater ferry strike end?"

Upload both, one in step 3 and one just before step 6: step 6 needs a second piece of yours, or your Stripe balance can't accrue.

## Pre-flight
- [ ] `make server-test` and `make buyer-test` pass
- [ ] `curl -s https://xrpl-facilitator-testnet.t54.ai/supported` responds
- [ ] `make demo-reset` run
- [ ] `make topup` done with the test card (reset zeroes credit), and `make rail RAIL=xrpl`
- [ ] `make stripe-listen` running
- [ ] Signed out in the browser
- [ ] Buyer wallet has testnet XRP (`get_budget` shows the balance). If the testnet was reset: `make wallets ARGS=--force`

## If t54 is down
Purchases return a payment failure or stay `outcome_unknown`. Nothing else in the flow depends on it.
- Show steps 1–3, then the backup recording for steps 4–5.
- If a purchase is held as `outcome_unknown`, `make demo-reset` clears the spend log (testnet only).
