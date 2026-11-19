"""Runtime settings. Future LLM values are reserved and unused in mock mode."""
from dataclasses import dataclass
import os
from urllib.parse import urlsplit
from app.content import format_usd, to_micros
from app.discord_import import snowflake

@dataclass(frozen=True)
class Settings:
    guild_id: int
    channel_id: int
    api_url: str
    price_usd: str

    @classmethod
    def from_environment(cls):
        api = os.getenv('TOLLGATE_API_URL', 'https://tollgate-production-55166a8d.up.railway.app').rstrip('/')
        url = urlsplit(api)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path:
            raise ValueError('TOLLGATE_API_URL must be an HTTPS origin.')
        if os.getenv('RESEARCH_PROVIDER', 'mock') != 'mock' or os.getenv('SUMMARY_PROVIDER', 'manual') != 'manual':
            raise ValueError('Only mock research and manual summaries are implemented. Add an adapter before enabling an LLM.')
        return cls(int(snowflake(os.environ['DISCORD_GUILD_ID'])),
                   int(snowflake(os.environ['DISCORD_CHANNEL_ID'])), api,
                   format_usd(to_micros(os.getenv('DISCORD_PRICE_USD', '0.01'))))
