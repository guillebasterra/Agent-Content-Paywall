import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)

NETWORK = os.getenv("XRPL_NETWORK", "xrpl:1")
RPC_URL = os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234")
FACILITATOR_URL = os.getenv("XRPL_FACILITATOR_URL", "https://xrpl-facilitator-testnet.t54.ai")
WRITER_ADDRESS = os.getenv("WRITER_ADDRESS", "")
CONTENT_DIR = Path(os.getenv("CONTENT_DIR", ROOT / "content"))
DB_PATH = Path(os.getenv("DATABASE_URL", "sqlite:///./tollgate.db").removeprefix("sqlite:///"))
PUBLIC_URL = os.getenv("TOLLGATE_API_URL", "http://localhost:8000").rstrip("/")

# t54's facilitator enforces this SourceTag on XRPL payments it settles.
SOURCE_TAG = 804681468
EXPLORER_TX = "https://testnet.xrpl.org/transactions/"
