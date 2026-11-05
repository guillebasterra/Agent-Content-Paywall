import os

os.environ["TOLLGATE_NO_AUTOAPP"] = "1"
os.environ.setdefault("WRITER_ADDRESS", "rBQKgMJ6CvoLZZ13JN9gZjCxdrdQ4ii7W4")
os.environ["RECEIPT_SIGNING_KEY"] = "11" * 32
os.environ["XRP_USD_RATE"] = "2"
os.environ["TREASURY_ADDRESS"] = "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh"
os.environ["AUTH_MODE"] = "demo"  # Tests that need Supabase mode pass their own auth.

import uuid

import psycopg
import pytest


@pytest.fixture(scope="session")
def postgres_url(tmp_path_factory):
    """A real, local Postgres. No network, and never the Supabase project."""
    import pgserver

    server = pgserver.get_server(tmp_path_factory.mktemp("pg"))
    yield server.get_uri()
    server.cleanup()


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    """Every API test runs on both databases, each in a database of its own."""
    if request.param == "sqlite":
        yield tmp_path / "test.db"
        return
    url = request.getfixturevalue("postgres_url")
    name = f"t{uuid.uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    yield url.replace("/postgres?", f"/{name}?")
