# Stripe MPP sandbox test (Nov 9)

Proved Stripe's Machine Payments Protocol works in our sandbox before touching the app. Guides: `docs.stripe.com/payments/machine/mpp.md` and `/mpp/sessions.md`. The Toll Gate app is unchanged; the test server was throwaway (`mppx` 0.17.6, `stripe`, Hono).

## Setup
- `STRIPE_PROFILE_ID`: `GET /v2/network/business_profiles/me` with `Stripe-Version: 2026-07-29.preview`. Returns 404 until a profile exists, and profiles can only be created in the Dashboard (`dashboard.stripe.com/profiles`, in the sandbox). Must start `profile_test_`.
- `TEMPO_DEPOSIT_ADDRESS`: `GET /v1/crypto/deposit_addresses?network=tempo`, `POST` with `network=tempo` if none. Creation worked, so the New York stablecoin exclusion didn't apply. The sandbox returned the same address as the docs' example, so it may be fixed per sandbox.
- `MPP_SESSION_OPERATOR_KEY`: `generatePrivateKey()` from `viem/accounts`. Signs session settlements and holds no funds.
- mppx 0.17.6 differs from the guide: `stripe.create` requires `store` (`Store.memory()` for one process). Sessions plug in through `defaultMethods().additional({ tempo: { session: {...} } })`.

## Results
| Test | Result |
|---|---|
| `npx mppx@latest validate`, 0.50 charge route (SPT + Tempo) | 28 passed, 0 failed. The Tempo payment settled |
| `npx mppx@latest validate`, session route (0.02 per unit, settle every 0.02) | 19 passed, 0 failed |
| `link-cli mpp pay ... --test` on the 0.50 route | Succeeded. Charged Stripe's test Visa 4242, `livemode=false` |
| `tempo request` on the session route | Hangs after the first unit (see below) |

The Payments page showed two 0.50 payments: one `crypto` (Tempo), one `card`/`link` (SPT). No session payments.

## Open issues
- **Session settlements under $0.50 aren't recorded.** Each 0.02 settlement goes through on Tempo, but recording it in Stripe fails with `amount_too_small`, "Amount must be no less than $0.50 usd". The sessions guide says the minimum is 0.01 USDC. Unknown whether enabling "Stablecoins and Crypto" (Dashboard → Settings → Payment methods) fixes it. Asked Stripe. Per-read pricing over sessions depends on the answer.
- **`tempo request` (CLI 1.18.2, tempo-request 0.15.1) stalls on session streams.** It opens the session, gets the first event, sends the mid-stream voucher, then waits until timeout and exits `E_PAYMENT_OUTCOME_UNKNOWN`. mppx's own client completes the same route in `validate`, so this looks like a CLI/mppx mismatch.

## Gotchas
- **Cornell's DNS blocks `tempo.xyz`.** Every hostname resolves to a Cornell address (`128.253.129.105`) and times out. Public DNS works. Use a hotspot or set DNS to `1.1.1.1`. This also affects a demo on Cornell Wi-Fi.
- `tempo wallet fund` only opens a browser page. On testnet, the faucet RPC funds directly: `tempo_fundAddress` on `https://rpc.moderato.tempo.xyz`.
- `link-cli mpp pay --test` shows your real Link wallet and card on the approval screen, but the token is minted from test card data and only works with a `profile_test_` seller. Nothing reaches the real card.
- Link's account-setup page froze ("Page Unresponsive: js.stripe.com") in one browser. The device login still completed. Chrome or Safari is the safer choice.
- The Tempo installer edits `~/.zshenv`, installs `libusb` with Homebrew, and installs a `tempo-request` skill into Claude Code, Cursor, Codex and Gemini CLI without asking.
