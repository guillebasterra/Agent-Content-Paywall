"""Both auth modes, and the Postgres protections Supabase mode relies on. No network."""

import time

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from test_api import BODY, MockFacilitator, upload

from app.db import Database
from app.main import create_app
from app.session import SupabaseAuth
from app.storage import SupabaseStorage

URL = "https://project.supabase.co"
ISSUER = f"{URL}/auth/v1"
USER = "6f1c1e36-0000-4000-8000-000000000001"
OTHER = "6f1c1e36-0000-4000-8000-000000000002"
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


class FakeJWKS:
    """Stands in for the project's JWKS endpoint."""

    def get_signing_key_from_jwt(self, token):
        return type("Key", (), {"key": SIGNING_KEY.public_key()})


def token(sub=USER, email="ada@example.com", key=SIGNING_KEY, alg="ES256", **overrides):
    claims = {"sub": sub, "email": email, "aud": "authenticated", "iss": ISSUER, "exp": time.time() + 300, **overrides}
    return jwt.encode(claims, key, algorithm=alg)


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


def auth_server(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def empty_content(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    return folder


@pytest.fixture
def client(database, empty_content):
    auth = SupabaseAuth(URL, "publishable", jwks=FakeJWKS(), http=auth_server(lambda r: httpx.Response(401)))
    app = create_app(MockFacilitator().client, database=database, content_dir=empty_content, auth=auth)
    yield TestClient(app)
    app.state.db.close()


def test_demo_mode_needs_no_token(database, empty_content):
    app = create_app(MockFacilitator().client, database=database, content_dir=empty_content)
    assert TestClient(app).get("/me/dashboard").status_code == 200
    app.state.db.close()


@pytest.mark.parametrize("route", ["/me/payout", "/me/dashboard"])
def test_writer_routes_refuse_a_missing_token(client, route):
    assert client.get(route).status_code == 401


def test_upload_refuses_a_missing_token(client):
    assert upload(client).status_code == 401
    assert client.get("/catalog").json()["articles"] == []


@pytest.mark.parametrize(
    "bad",
    [
        "garbage",
        token(key=ec.generate_private_key(ec.SECP256R1())),
        token(exp=time.time() - 10),
        token(aud="anon"),
        token(iss="https://evil.example/auth/v1"),
        token(is_anonymous=True),
        jwt.encode({"sub": USER, "aud": "authenticated", "iss": ISSUER, "exp": time.time() + 300}, "", algorithm="none"),
    ],
)
def test_bad_tokens_are_refused(client, bad):
    assert client.get("/me/dashboard", headers=bearer(bad)).status_code == 401


def test_catalog_stays_public(client):
    assert client.get("/catalog").status_code == 200


def test_first_login_creates_one_writer(client):
    first = client.get("/me/payout", headers=bearer(token())).json()
    assert first["name"] == "ada" and first["email"] == "ada@example.com" and first["xrpl_address"] is None
    client.get("/me/dashboard", headers=bearer(token()))
    with client.app.state.db._conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM writers").fetchone()["n"] == 1


def test_new_writer_starts_empty_and_writers_are_separate(client):
    ada, bob = bearer(token()), bearer(token(sub=OTHER, email="bob@example.com"))
    assert client.get("/me/dashboard", headers=ada).json()["pieces"] == []
    created = client.post(
        "/articles", headers=ada, data={"title": "Ada's", "price_usd": "2"}, files={"file": ("a.md", BODY.encode())}
    )
    assert created.status_code == 201 and created.json()["author"] == "ada"
    assert len(client.get("/me/dashboard", headers=ada).json()["pieces"]) == 1
    assert client.get("/me/dashboard", headers=bob).json()["pieces"] == []


def test_profile_name_becomes_the_byline(client):
    ada = bearer(token())
    assert client.put("/me/profile", headers=ada, json={"name": "  Ada Lovelace "}).json()["name"] == "Ada Lovelace"
    assert client.get("/me/payout", headers=ada).json()["name"] == "Ada Lovelace"
    assert client.put("/me/profile", headers=ada, json={"name": "  "}).status_code == 422
    assert client.put("/me/profile", json={"name": "x"}).status_code == 401


def test_legacy_hs256_token_is_checked_by_the_auth_server_and_cached(database, empty_content):
    calls = []

    def handler(request):
        calls.append(request.headers["apikey"])
        return httpx.Response(200, json={"id": USER, "email": "ada@example.com"})

    auth = SupabaseAuth(URL, "publishable", jwks=FakeJWKS(), http=auth_server(handler))
    app = create_app(MockFacilitator().client, database=database, content_dir=empty_content, auth=auth)
    client = TestClient(app)
    legacy = jwt.encode({"sub": "attacker-chosen", "exp": time.time() + 300}, "x" * 32, algorithm="HS256")
    for _ in range(2):
        assert client.get("/me/payout", headers=bearer(legacy)).json()["email"] == "ada@example.com"
    assert calls == ["publishable"]
    app.state.db.close()


def test_legacy_token_refused_by_the_auth_server_is_refused(client):
    legacy = jwt.encode({"sub": USER, "exp": time.time() + 300}, "x" * 32, algorithm="HS256")
    assert client.get("/me/payout", headers=bearer(legacy)).status_code == 401


def test_auth_server_outage_is_503_not_401(database, empty_content):
    def handler(request):
        raise httpx.ConnectError("down")

    auth = SupabaseAuth(URL, "publishable", jwks=FakeJWKS(), http=auth_server(handler))
    app = create_app(MockFacilitator().client, database=database, content_dir=empty_content, auth=auth)
    legacy = jwt.encode({"sub": USER, "exp": time.time() + 300}, "x" * 32, algorithm="HS256")
    assert TestClient(app).get("/me/payout", headers=bearer(legacy)).status_code == 503
    app.state.db.close()


def storage_app(database, content, handler):
    auth = SupabaseAuth(URL, "publishable", jwks=FakeJWKS())
    storage = SupabaseStorage(URL, "service", transport=httpx.MockTransport(handler))
    return create_app(MockFacilitator().client, database=database, content_dir=content, auth=auth, storage=storage)


def test_original_file_goes_to_the_private_bucket(database, empty_content):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    app = storage_app(database, empty_content, handler)
    client = TestClient(app)
    response = client.post(
        "/articles", headers=bearer(token()), data={"title": "Kept", "price_usd": "2"},
        files={"file": ("my piece.md", b"---\ntitle: x\n---\nThe text")},
    )
    assert response.status_code == 201
    stored = app.state.db.article("kept")["storage_path"]
    assert stored.endswith("/kept/original.md")
    assert seen[0].url.path == f"/storage/v1/object/uploads/{stored}"
    assert seen[0].content.startswith(b"---\ntitle")  # The original, frontmatter included.
    app.state.db.close()


@pytest.mark.parametrize("failure", [httpx.Response(500), httpx.ConnectError("down")])
def test_storage_failure_does_not_block_publishing(database, empty_content, failure):
    def handler(request):
        if isinstance(failure, Exception):
            raise failure
        return failure

    app = storage_app(database, empty_content, handler)
    response = TestClient(app).post(
        "/articles", headers=bearer(token()), data={"title": "Kept", "price_usd": "2"},
        files={"file": ("a.md", b"The text")},
    )
    assert response.status_code == 201 and app.state.db.article("kept")["storage_path"] is None
    app.state.db.close()


def test_postgres_tables_are_closed_to_the_browser_key(postgres_url):
    """RLS on, no policies: Supabase's anon and authenticated roles can read nothing."""
    db = Database(postgres_url)
    with db._conn() as c:
        rows = c.execute(
            "SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('writers', 'articles', 'agents', 'purchases', 'ledger_entries')"
        ).fetchall()
        policies = c.execute("SELECT COUNT(*) AS n FROM pg_policies").fetchone()["n"]
    db.close()
    assert {r["relname"] for r in rows} == {"writers", "articles", "agents", "purchases", "ledger_entries"}
    assert all(r["relrowsecurity"] for r in rows) and policies == 0
    with psycopg.connect(postgres_url, autocommit=True) as admin:
        admin.execute("CREATE ROLE anon_test NOLOGIN")
        admin.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO anon_test")
        admin.execute("INSERT INTO writers (id, name) VALUES ('w', 'W') ON CONFLICT DO NOTHING")
        admin.execute("SET ROLE anon_test")
        assert admin.execute("SELECT * FROM writers").fetchall() == []
        admin.execute("RESET ROLE")


def test_reset_clears_every_table(database, empty_content):
    app = create_app(MockFacilitator().client, database=database, content_dir=empty_content)
    client = TestClient(app)
    assert upload(client).status_code == 201
    app.state.db.reset()
    assert client.get("/catalog").json()["articles"] == []
    app.state.db.close()


def test_migration_keeps_rows_and_order(tmp_path, empty_content, postgres_url):
    import sys
    import uuid
    from pathlib import Path

    from test_api import pay

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from migrate_to_postgres import copy_rows

    app = create_app(MockFacilitator().client, database=tmp_path / "old.db", content_dir=empty_content)
    client = TestClient(app)
    upload(client)
    pay(client, "a-new-piece", agent="First")
    pay(client, "a-new-piece", agent="Second")

    name = f"t{uuid.uuid4().hex}"
    with psycopg.connect(postgres_url, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    target = Database(postgres_url.replace("/postgres?", f"/{name}?"))
    assert copy_rows(app.state.db, target) == {"writers": 1, "articles": 1, "agents": 0, "purchases": 2, "ledger_entries": 0}
    copy_rows(app.state.db, target)
    assert [p["agent"] for p in target.recent()] == ["Second", "First"]
    assert target.article("a-new-piece")["reads"] == 2
    app.state.db.close()
    target.close()
