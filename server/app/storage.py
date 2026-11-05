"""Keeps each writer's original file in Supabase Storage. Demo mode has no storage."""

import logging

import httpx

log = logging.getLogger("tollgate")

BUCKET = "uploads"


def service_headers(key: str) -> dict[str, str]:
    """New sb_secret_ keys aren't JWTs, so they go in apikey only. Legacy service_role keys need both."""
    return {"apikey": key} if key.startswith("sb_") else {"apikey": key, "Authorization": f"Bearer {key}"}


class SupabaseStorage:
    def __init__(self, url: str, service_key: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self.base = f"{url.rstrip('/')}/storage/v1"
        self.headers = service_headers(service_key)
        self.transport = transport

    async def save(self, path: str, data: bytes, content_type: str) -> bool:
        """Best effort: the text is already in the database, so a failure must not stop publishing."""
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
                response = await client.post(
                    f"{self.base}/object/{BUCKET}/{path}",
                    content=data,
                    headers={**self.headers, "Content-Type": content_type},
                )
        except httpx.HTTPError as exc:
            log.warning("could not store the original file: %s", type(exc).__name__)
            return False
        if response.status_code >= 300:
            log.warning("could not store the original file: HTTP %s", response.status_code)
            return False
        return True
