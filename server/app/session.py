"""Who is making this request. Placeholder until Supabase Auth replaces it.

Everything runs as one demo writer. Writer endpoints depend on current_writer(), so
this is the only backend code that changes when real auth arrives.
"""

from fastapi import HTTPException, Request

DEMO_WRITER_ID = "demo"
DEMO_WRITER_NAME = "Guillermo Basterra"
DEMO_WRITER_EMAIL = "demo@tollgate.local"


def current_writer(request: Request) -> dict:
    writer = request.app.state.db.writer(DEMO_WRITER_ID)
    if writer is None:
        raise HTTPException(401, "not signed in")
    return writer
