import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)

NETWORK = os.getenv("XRPL_NETWORK", "xrpl:1")
RPC_URL = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234")
FACILITATOR_URL = os.getenv("XRPL_FACILITATOR_URL", "https://xrpl-facilitator-testnet.t54.ai")
WRITER_ADDRESS = os.getenv("WRITER_ADDRESS", "")
TREASURY_ADDRESS = os.getenv("TREASURY_ADDRESS", "")
CONTENT_DIR = Path(os.getenv("CONTENT_DIR", ROOT / "content"))
DB_PATH = Path(os.getenv("DATABASE_URL", "sqlite:///./tollgate.db").removeprefix("sqlite:///"))

# Testnet XRP has no real value, so this rate is a placeholder. Prices are USD; drops are derived from it.
try:
    XRP_USD_RATE = Decimal(os.getenv("XRP_USD_RATE", "2"))
except InvalidOperation:
    raise RuntimeError("XRP_USD_RATE must be a number") from None
if not XRP_USD_RATE.is_finite() or XRP_USD_RATE <= 0:
    raise RuntimeError("XRP_USD_RATE must be positive")

AUTH_MODE = os.getenv("AUTH_MODE", "demo")
if AUTH_MODE not in {"demo", "supabase"}:
    raise RuntimeError("AUTH_MODE must be demo or supabase")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", "")


STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
WEB_URL = os.getenv("TOLLGATE_WEB_URL", "http://localhost:3000").rstrip("/")


def database_target() -> Path | str:
    """Postgres in Supabase mode, SQLite in demo mode."""
    if AUTH_MODE != "supabase":
        return DB_PATH
    if not SUPABASE_DB_URL:
        raise RuntimeError("SUPABASE_DB_URL missing, and AUTH_MODE is supabase")
    return SUPABASE_DB_URL
PUBLIC_URL = os.getenv("TOLLGATE_API_URL", "http://localhost:8000").rstrip("/")

# t54's facilitator enforces this SourceTag on XRPL payments it settles.
SOURCE_TAG = 804681468
EXPLORER_TX = "https://testnet.xrpl.org/transactions/"
