"""Who is making this request. Writer endpoints depend on current_writer().

Demo mode runs everything as one demo writer. Supabase mode verifies the access token
and maps its user to a writer, created on first login.
"""

import hashlib
import logging
import time

import httpx
import jwt
from fastapi import HTTPException, Request

log = logging.getLogger("tollgate")

DEMO_WRITER_ID = "demo"
DEMO_WRITER_NAME = "Guillermo Basterra"
DEMO_WRITER_EMAIL = "demo@tollgate.local"

ASYMMETRIC_ALGS = ["ES256", "RS256"]
AUDIENCE = "authenticated"
AUTH_SERVER_CACHE_SECONDS = 60

NOT_SIGNED_IN = HTTPException(401, "not signed in")


class DemoAuth:
    def writer(self, request: Request) -> dict:
        writer = request.app.state.db.writer(DEMO_WRITER_ID)
        if writer is None:
            raise NOT_SIGNED_IN
        return writer


class SupabaseAuth:
    """Asymmetric tokens are checked locally against the project's JWKS.

    Tokens from a project still on the legacy HS256 secret go to the Auth server instead, as
    Supabase recommends. No shared secret is ever held here, so a token can't choose its way
    into a weaker check.
    """

    def __init__(self, url: str, publishable_key: str, *, jwks: jwt.PyJWKClient | None = None, http=None):
        base = url.rstrip("/")
        self.issuer = f"{base}/auth/v1"
        self.publishable_key = publishable_key
        self.jwks = jwks or jwt.PyJWKClient(f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=600)
        self.http = http or httpx.Client(timeout=10)
        self._verified: dict[str, tuple[dict, float]] = {}

    def _from_auth_server(self, token: str) -> dict:
        key = hashlib.sha256(token.encode()).hexdigest()
        cached = self._verified.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        try:
            response = self.http.get(
                f"{self.issuer}/user",
                headers={"apikey": self.publishable_key, "Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            raise HTTPException(503, "The sign-in service can't be reached.") from None
        if response.status_code != 200:
            raise NOT_SIGNED_IN
        user = response.json()
        claims = {"sub": user["id"], "email": user.get("email"), "is_anonymous": user.get("is_anonymous", False)}
        now = time.monotonic()
        self._verified = {k: v for k, v in self._verified.items() if v[1] > now}
        self._verified[key] = (claims, now + AUTH_SERVER_CACHE_SECONDS)
        return claims

    def claims(self, token: str) -> dict:
        try:
            alg = jwt.get_unverified_header(token).get("alg")
            if alg == "HS256":
                return self._from_auth_server(token)
            if alg not in ASYMMETRIC_ALGS:
                raise NOT_SIGNED_IN
            key = self.jwks.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token, key, algorithms=ASYMMETRIC_ALGS, audience=AUDIENCE, issuer=self.issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWKClientConnectionError:
            log.warning("could not fetch the Supabase JWKS")
            raise HTTPException(503, "The sign-in service can't be reached.") from None
        except jwt.PyJWTError:
            raise NOT_SIGNED_IN from None

    def writer(self, request: Request) -> dict:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise NOT_SIGNED_IN
        claims = self.claims(token.strip())
        if claims.get("is_anonymous"):
            raise NOT_SIGNED_IN
        return request.app.state.db.writer_for_auth_user(claims["sub"], claims.get("email"))


def current_writer(request: Request) -> dict:
    return request.app.state.auth.writer(request)
