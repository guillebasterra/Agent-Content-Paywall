"""Toll Gate's treasury on Base: a CDP server wallet that agents pay over x402.

    make treasury             # create it once (or reuse it by name), save TREASURY_BASE_ADDRESS
    make treasury ARGS=--check   # read-only: is the saved address the CDP account, and do the keys work

Reads CDP_API_KEY_ID, CDP_API_KEY_SECRET and CDP_WALLET_SECRET from .env. Prints the address only.
This script never signs or sends anything: the treasury only receives.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from create_wallets import write_env  # noqa: E402

ENV = ROOT / ".env"
ACCOUNT_NAME = "tollgate-treasury"
KEYS = ("CDP_API_KEY_ID", "CDP_API_KEY_SECRET", "CDP_WALLET_SECRET")


def short_error(exc: Exception) -> str:
    """The class and first line only: SDK errors can echo request details."""
    return f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}"


async def account_address(env: dict, *, create: bool) -> str:
    from cdp import CdpClient

    async with CdpClient(
        api_key_id=env["CDP_API_KEY_ID"],
        api_key_secret=env["CDP_API_KEY_SECRET"],
        wallet_secret=env["CDP_WALLET_SECRET"],
    ) as cdp:
        if create:
            account = await cdp.evm.get_or_create_account(name=ACCOUNT_NAME)
        else:
            account = await cdp.evm.get_account(name=ACCOUNT_NAME)
        return account.address


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify only, change nothing")
    args = parser.parse_args()

    env = dotenv_values(ENV)
    missing = [k for k in KEYS if not (env.get(k) or "").strip()]
    if missing:
        sys.exit(f"missing in .env: {', '.join(missing)}")
    env = {k: env[k].strip() for k in KEYS} | {"TREASURY_BASE_ADDRESS": (env.get("TREASURY_BASE_ADDRESS") or "").strip()}

    try:
        address = asyncio.run(account_address(env, create=not args.check))
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"CDP request failed ({short_error(exc)}). Check the CDP keys in .env.")

    saved = env["TREASURY_BASE_ADDRESS"]
    if args.check:
        if saved.lower() != address.lower():
            sys.exit(f"TREASURY_BASE_ADDRESS ({saved or 'unset'}) is not the CDP account {address}. Run `make treasury`.")
        print(f"treasury ok: {address} (CDP account '{ACCOUNT_NAME}', keys valid)")
        return

    if saved and saved.lower() != address.lower():
        print(f"replacing TREASURY_BASE_ADDRESS {saved} with the CDP account's address")
    write_env(ENV, {"TREASURY_BASE_ADDRESS": address})
    print(f"treasury: {address} (CDP account '{ACCOUNT_NAME}') saved to .env as TREASURY_BASE_ADDRESS")
    print(f"https://basescan.org/address/{address}")


if __name__ == "__main__":
    main()
