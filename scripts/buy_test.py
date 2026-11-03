"""Buy one article on XRPL testnet with the buyer wallet, end to end.

    make buy-test                      # first article in the catalog
    make buy-test ARGS="--id some-id --max-xrp 1"
"""

import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from xrpl.account import get_balance
from xrpl.clients import JsonRpcClient
from xrpl.utils import drops_to_xrp
from xrpl.wallet import Wallet
from x402_xrpl.clients import x402_purchase

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))
load_dotenv(ROOT / ".env")

from app.receipts import verify  # noqa: E402


def xrp(addr: str, client: JsonRpcClient) -> str:
    return str(drops_to_xrp(str(get_balance(addr, client))))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--id")
    p.add_argument("--max-xrp", type=float, default=1.0, help="refuse to pay more than this")
    args = p.parse_args()

    api = os.getenv("TOLLGATE_API_URL", "http://localhost:8000")
    rpc = os.environ["XRPL_RPC_URL"]
    client = JsonRpcClient(rpc)
    buyer = Wallet.from_seed(os.environ["BUYER_SEED"])

    catalog = httpx.get(f"{api}/catalog").json()["articles"]
    article = next(a for a in catalog if a["id"] == args.id) if args.id else catalog[0]
    writer = article["pay_to"]

    print(f"buying   {article['title']}  ({article['price_xrp']} XRP)")
    print(f"before   buyer {xrp(buyer.address, client)}  writer {xrp(writer, client)}")

    result = x402_purchase(
        article["url"],
        wallet=buyer,
        rpc_url=rpc,
        network_filter=os.getenv("XRPL_NETWORK", "xrpl:1"),
        max_value=str(int(args.max_xrp * 1_000_000)),
        headers={"X-Agent-Name": "buy-test"},
        timeout=180,
    )
    print(f"status   {result.status}" + (f"  ({result.reason})" if result.reason else ""))
    if result.status != "success":
        if result.response is not None:
            print(result.response.text[:800])
        sys.exit(1)

    data = result.response.json()
    receipt = data["receipt"]
    key = httpx.get(f"{api}/.well-known/tollgate-receipt-key").json()["public_key"]

    print(f"after    buyer {xrp(buyer.address, client)}  writer {xrp(writer, client)}")
    print(f"tx       {receipt['payload']['explorer']}")
    print(f"receipt  signature valid: {verify(receipt, key)}")
    print(f"\n--- {data['title']} ---\n{data['body'][:400]}{'...' if len(data['body']) > 400 else ''}")


if __name__ == "__main__":
    main()
