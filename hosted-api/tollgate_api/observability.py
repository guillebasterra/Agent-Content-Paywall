"""Small, structured operational events. Never log bodies, cookies or wallet data."""

import json
import logging
import time
from uuid import uuid4

logger = logging.getLogger("tollgate")
logger.setLevel(logging.INFO)


def event(name, **fields):
    logger.info(json.dumps({"event": name, **fields}, separators=(",", ":")))


def install_request_logging(app):
    @app.middleware("http")
    async def request_log(request, call_next):
        reference = str(uuid4())
        started = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = reference
            return response
        finally:
            if request.method == "POST" or status >= 400:
                event(
                    "request_finished",
                    reference=reference,
                    method=request.method,
                    path=request.url.path,
                    status=status,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
