"""Pre-flight for the Base demo. Read-only: nothing is signed, paid or written.

    make preflight

Checks, in order: the API is up on the Base rail, the treasury address is set and is the CDP
account, the CDP keys work with the facilitator, the catalog has articles, and the public URL
(which payments-mcp fetches from Coinbase's servers) serves the same 402 challenge.
Prints addresses and URLs only, never keys.
"""

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from treasury import ACCOUNT_NAME, account_address, short_error  # noqa: E402

LOCAL = os.getenv("TOLLGATE_LOCAL_URL", "http://localhost:8000").rstrip("/")
BASE = "eip155:8453"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append(ok)
    print(f"{'ok  ' if ok else 'FAIL'}  {name}{f' — {detail}' if detail else ''}")
    return ok


def get(url: str) -> httpx.Response | None:
    try:
        return httpx.get(url, timeout=20, headers={"X-Agent-Name": "preflight"})
    except httpx.HTTPError:
        return None


def main() -> None:
    env = {k: (v or "").strip() for k, v in dotenv_values(ROOT / ".env").items()}
    treasury = env.get("TREASURY_BASE_ADDRESS", "")
    public = env.get("TOLLGATE_API_URL", "http://localhost:8000").rstrip("/")

    # 1. API up, on the Base rail
    health = get(f"{LOCAL}/health")
    payment = health.json().get("payment", {}) if health is not None and health.status_code == 200 else {}
    if not check("API up", bool(payment), LOCAL if payment else f"nothing at {LOCAL}. Start `make server`"):
        return finish()
    check("Base rail active", payment.get("rail") == "base" and payment.get("network") == BASE,
          f"{payment.get('rail')} on {payment.get('network')}" + ("" if payment.get("rail") == "base" else ". Set PAYMENT_RAIL=base and restart"))

    # 2. Treasury set, and it is the CDP account the server charges to
    check("TREASURY_BASE_ADDRESS set", bool(treasury), treasury or "run `make treasury`")
    check("server pays to the treasury", payment.get("pay_to", "").lower() == treasury.lower() != "",
          payment.get("pay_to") or "restart `make server` after `make treasury`")

    # 3. CDP keys valid: the account resolves, and the facilitator answers with our key
    keys = {k: env.get(k, "") for k in ("CDP_API_KEY_ID", "CDP_API_KEY_SECRET", "CDP_WALLET_SECRET")}
    if check("CDP keys present", all(keys.values()), "" if all(keys.values()) else "missing in .env"):
        try:
            address = asyncio.run(account_address(keys, create=False))
            check(f"CDP account '{ACCOUNT_NAME}' matches", address.lower() == treasury.lower(), address)
        except Exception as exc:  # noqa: BLE001
            check(f"CDP account '{ACCOUNT_NAME}'", False, short_error(exc))
        try:
            from cdp.x402 import create_facilitator_config
            from x402.http import HTTPFacilitatorClientSync

            supported = HTTPFacilitatorClientSync(
                create_facilitator_config(keys["CDP_API_KEY_ID"], keys["CDP_API_KEY_SECRET"])
            ).get_supported()
            ok = any(k.x402_version == 2 and k.scheme == "exact" and k.network == BASE for k in supported.kinds)
            check("CDP facilitator supports x402 v2 exact on Base", ok)
        except Exception as exc:  # noqa: BLE001
            check("CDP facilitator", False, short_error(exc))

    # 4. Catalog non-empty
    catalog = get(f"{LOCAL}/catalog")
    articles = catalog.json()["articles"] if catalog is not None and catalog.status_code == 200 else []
    check("catalog non-empty", bool(articles), f"{len(articles)} article(s)" if articles else "upload a piece on /upload")

    # 5. Public URL: payments-mcp fetches it from Coinbase's servers, so localhost can't work
    host = urlsplit(public).hostname or ""
    is_public = public.startswith("https://") and host not in {"localhost", "127.0.0.1", "0.0.0.0"}
    check("TOLLGATE_API_URL is a public https URL", is_public,
          public + ("" if is_public else ". payments-mcp can't reach localhost: run `make tunnel`, then restart `make server`"))
    if is_public:
        remote = get(f"{public}/health")
        same = remote is not None and remote.status_code == 200 and remote.json().get("payment", {}).get("pay_to") == payment.get("pay_to")
        check("public URL reaches this server", same, public if same else f"{public}/health didn't answer as this server")
        if same and articles:
            first = articles[0]
            challenge = get(f"{public}/articles/{first['id']}")
            ok = challenge is not None and challenge.status_code == 402 and "payment-required" in challenge.headers
            if ok:
                from x402.http import decode_payment_required_header

                option = decode_payment_required_header(challenge.headers["payment-required"]).accepts[0]
                ok = (option.network == BASE and option.asset == USDC and option.pay_to.lower() == treasury.lower()
                      and option.amount == str(first["price_usd_micros"]))
            check("public 402 challenge: Base USDC to the treasury at the listed price", ok, first["title"])
    if is_public and env.get("AUTH_MODE", "demo") == "demo":
        check("writer routes are authenticated", False, "AUTH_MODE=demo exposes unauthenticated writer routes on the public URL")

    print("\nNot checked here: the payments-mcp wallet's USDC balance. Ask Claude Desktop to run get_wallet_balance.")
    finish()


def finish() -> None:
    failed = results.count(False)
    print(f"\n{'all checks passed' if not failed else f'{failed} check(s) failed'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
