from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    database_url: str
    frontend_origin: str
    public_api_url: str
    writer_address: str
    signing_key: str
    encryption_key: str
    rpc_url: str = "https://s.altnet.rippletest.net:51234"
    secure: bool = True
    content_dir: Path = Path(__file__).resolve().parents[1] / "content"

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        required = [
            "DATABASE_URL",
            "FRONTEND_ORIGIN",
            "PUBLIC_API_URL",
            "WRITER_ADDRESS",
            "RECEIPT_SIGNING_KEY",
            "WALLET_ENCRYPTION_KEY",
        ]
        if missing := [name for name in required if not os.getenv(name)]:
            raise RuntimeError("Missing server configuration: " + ", ".join(missing))
        origin = os.environ["FRONTEND_ORIGIN"].rstrip("/")
        api = os.environ["PUBLIC_API_URL"].rstrip("/")
        secure = urlparse(origin).scheme == "https"
        hosted = bool(os.getenv("VERCEL"))
        if hosted and (
            not secure
            or not api.startswith("https://")
            or not os.environ["DATABASE_URL"].startswith(
                ("postgres://", "postgresql://")
            )
        ):
            raise RuntimeError("Hosted deployments require HTTPS and PostgreSQL")
        rpc = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234")
        if urlparse(rpc).hostname != "s.altnet.rippletest.net":
            raise RuntimeError("Only the configured XRPL testnet is supported")
        return cls(
            os.environ["DATABASE_URL"],
            origin,
            api,
            os.environ["WRITER_ADDRESS"],
            os.environ["RECEIPT_SIGNING_KEY"],
            os.environ["WALLET_ENCRYPTION_KEY"],
            rpc,
            secure,
        )
