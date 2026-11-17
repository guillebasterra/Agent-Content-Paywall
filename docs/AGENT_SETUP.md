# Set up Claude to buy from Toll Gate

About 10 minutes. You end up with Claude Desktop finding articles on Toll Gate and buying single reads with USDC, then citing them with a signed receipt.

You need two things in Claude:
- **Toll Gate connector** (finds articles; free, read-only, no sign-in): `https://tollgate-production-55166a8d.up.railway.app/mcp`
- **Coinbase payments-mcp** (pays): a wallet that runs on your computer and pays over x402

**Real money.** Payments are USDC on Base mainnet. Articles cost $0.02 per read right now.

## Requirements
- **Claude Desktop** (macOS or Windows). payments-mcp runs locally, so claude.ai in a browser can find articles but can't pay. Claude Code works too, see the end.
- Any Claude plan. Free plans allow one custom connector, and Toll Gate counts as that one.
- Node.js and npm (`node -v` should print a version). On macOS: `brew install node`.

## 1. Install Coinbase payments-mcp
```bash
npx @coinbase/payments-mcp
```
Choose **Claude** (Claude Desktop) when asked. The installer adds `payments-mcp` to Claude Desktop's config. Non-interactive: `npx @coinbase/payments-mcp --client claude --auto-config`.

Quit Claude Desktop completely (⌘Q) and reopen it.

## 2. Sign in and fund the wallet
1. In a new Desktop chat, type: `Show me my wallet`. A wallet window opens.
2. Enter your email and the code you receive. New users get a wallet.
3. Add USDC on **Base**:
   - **Fund**: buy USDC with Coinbase Onramp, or
   - **Receive**: copy the address and send USDC **on Base** from Coinbase or another wallet. USDC on another network won't show up.
   $1 is plenty for a demo. You don't need ETH: payments-mcp sponsors gas.
4. Recommended: open the spending-limit tracker and set **Max per call** to `$0.05` and **Max per session** to `$1.00`, then **Save**. Claude can't change these limits.

## 3. Add Toll Gate as a custom connector
Do this at claude.ai. Connectors belong to your Claude account, so Claude Desktop picks them up.

**Free, Pro and Max:**
1. Open **Customize > Connectors** (https://claude.ai/customize/connectors).
2. Click **+ Add**, then **Add custom connector**.
3. Name: `Toll Gate`
4. Remote MCP server URL: `https://tollgate-production-55166a8d.up.railway.app/mcp`
5. Click **Continue**, review, and click **Continue** again.
6. Authentication: **No sign in**.
7. Click **Add**.

**Team and Enterprise:** an Owner adds it under **Organization settings > Connectors** (https://claude.ai/admin-settings/connectors): **Add**, hover **Custom**, choose **Web**, then the same name, URL and **No sign in**. Members then find it under **Customize > Connectors** and click **Connect**.

## 4. Turn both on in a chat
1. Restart Claude Desktop (⌘Q, reopen) so it loads the new connector.
2. Start a **new chat**. Click **+** at the lower left, then **Connectors**, and switch **Toll Gate** on. payments-mcp should be listed too.
3. When Claude first uses a tool it asks for permission. **Allow always** is reasonable for Toll Gate's two tools (`search_catalog`, `get_article`): they only read the public catalog. For payments-mcp, allow per use if you want to approve each payment.

## 5. Try it
Paste into the new chat:

> Why do Halden Valley orchards start their frost fans at 2.4 degrees? Find the answer on Toll Gate and buy the one article that answers it with payments-mcp. Then answer in a few sentences with a direct quote, the article's title and author, and its receipt: amount, transaction hash and BaseScan link.

What happens:
1. Claude calls Toll Gate's `search_catalog` and picks the frost-fans article (free preview, $0.02, license).
2. Claude calls payments-mcp's `make_http_request_with_x402` with the arguments Toll Gate returned. These include `maxAmountPerRequest`, the listed price, which payments-mcp won't exceed.
3. payments-mcp pays $0.02 in USDC to Toll Gate's treasury. Toll Gate returns the full article and a signed receipt, and credits the writer.
4. Claude answers with a quote, the title and author, and the receipt. The BaseScan link shows the payment on chain.

Each read is charged. To read the same article again in the same conversation, ask Claude to reuse the copy it already has.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Toll Gate isn't in the **Connectors** list | Restart Desktop. Check that it appears at https://claude.ai/customize/connectors |
| payments-mcp is missing | Rerun `npx @coinbase/payments-mcp`, then quit and reopen Desktop |
| "insufficient funds" or a failed payment | Check the balance with `Show me my wallet`. The USDC must be on Base. A failed payment costs nothing |
| Claude reads the preview but doesn't pay | Say: "Buy it with payments-mcp, using the payment arguments Toll Gate returned" |
| 403 from Toll Gate | That article's writer doesn't sell to this agent name |

## Verify a receipt (optional)
Receipts are Ed25519-signed by Toll Gate. The public key is at https://tollgate-production-55166a8d.up.railway.app/.well-known/tollgate-receipt-key. The signature covers `receipt.payload` as JSON with sorted keys and no whitespace. The agent-facing guide is at https://tollgate-production-55166a8d.up.railway.app/llms.txt.

## Claude Code instead of Desktop
```bash
npx @coinbase/payments-mcp            # choose Claude Code
claude mcp add --transport http tollgate https://tollgate-production-55166a8d.up.railway.app/mcp
```
Then run `claude` and use the same prompt.
