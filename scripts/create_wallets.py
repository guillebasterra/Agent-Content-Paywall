"""Create and fund the writer, buyer and treasury wallets on XRPL testnet, then save them to .env.

Run from the repo root:  make wallets
Re-run with --force to replace existing wallets.
"""

import argparse
import shutil
from pathlib import Path

from xrpl.account import get_balance
from xrpl.clients import JsonRpcClient
from xrpl.utils import drops_to_xrp
from xrpl.wallet import generate_faucet_wallet

ROOT = Path(__file__).resolve().parent.parent
TESTNET_RPC = "https://s.altnet.rippletest.net:51234"
EXPLORER = "https://testnet.xrpl.org/accounts/"
ROLES = ["WRITER", "BUYER", "TREASURY"]


def read_env(path: Path) -> dict[str, str]:
    env = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def write_env(path: Path, updates: dict[str, str]) -> None:
    lines, seen = [], set()
    for line in path.read_text().splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in updates:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            lines.append(line)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="replace existing wallets")
    p.add_argument("--env", type=Path, default=ROOT / ".env")
    args = p.parse_args()

    if not args.env.exists():
        shutil.copy(ROOT / ".env.example", args.env)
        print(f"created {args.env} from .env.example")

    env = read_env(args.env)
    client = JsonRpcClient(env.get("XRPL_RPC_URL") or TESTNET_RPC)
    updates = {}

    for role in ROLES:
        if env.get(f"{role}_ADDRESS") and not args.force:
            print(f"{role.lower()}: already set ({env[f'{role}_ADDRESS']}), skipping. Use --force to replace.")
            continue
        print(f"{role.lower()}: requesting funded wallet from testnet faucet...")
        wallet = generate_faucet_wallet(client)
        updates[f"{role}_ADDRESS"] = wallet.address
        updates[f"{role}_SEED"] = wallet.seed

    if updates:
        write_env(args.env, updates)
        env.update(updates)

    print()
    for role in ROLES:
        addr = env.get(f"{role}_ADDRESS")
        if not addr:
            continue
        xrp = drops_to_xrp(str(get_balance(addr, client)))
        print(f"{role.lower():>8}  {addr}  {xrp} XRP")
        print(f"          {EXPLORER}{addr}")
    print(f"\nseeds saved to {args.env} (gitignored, never commit it)")


if __name__ == "__main__":
    main()
