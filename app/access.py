"""Cloudflare Access authentication.

Cloudflare Access sits in front of the whole site. After a person logs in (browser) or an MCP client
finishes Access's managed OAuth flow (Claude's connector), Cloudflare forwards each request to this
app with a signed JWT in the Cf-Access-Jwt-Assertion header. This module checks that JWT on every
request, so a request that did not come through Access (for example, straight to port 8000) is refused.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import anyio.to_thread
import jwt
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import MCP_PATH, Settings

JWT_HEADER = "cf-access-jwt-assertion"
JWT_COOKIE = "CF_Authorization"
CLOCK_SKEW_SECONDS = 30
KEY_CACHE_SECONDS = 60 * 60
# The container health check calls /healthz without going through Cloudflare.
PUBLIC_PATHS = {"/healthz"}


class AccessDenied(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    email: str
    dev: bool = False


class SigningKeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class AccessVerifier:
    def __init__(self, settings: Settings, keys: SigningKeySource | None = None) -> None:
        self.issuer = settings.access_issuer
        self.audience = settings.access_aud
        self.allowed_emails = settings.allowed_emails
        # PyJWKClient caches the team's public keys and refetches when it sees a new key id.
        self.keys = keys or jwt.PyJWKClient(
            f"{self.issuer}/cdn-cgi/access/certs", cache_keys=True, lifespan=KEY_CACHE_SECONDS, timeout=10
        )

    async def verify(self, token: str | None) -> Identity:
        if not token:
            raise AccessDenied("No Cloudflare Access token. Open the app through its Cloudflare URL.")
        try:
            # Fetching keys is blocking network I/O the first time, so keep it off the event loop.
            key = await anyio.to_thread.run_sync(self.keys.get_signing_key_from_jwt, token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AccessDenied(f"Invalid Cloudflare Access token: {exc}") from exc
        email = str(claims.get("email") or "").lower()
        if self.allowed_emails and email not in self.allowed_emails:
            raise AccessDenied("This account is not allowed to use this app.")
        return Identity(email=email or str(claims.get("common_name") or claims.get("sub") or "unknown"))


class AccessMiddleware:
    """Pure ASGI middleware, so it also covers the MCP endpoint and static files."""

    def __init__(self, app: ASGIApp, verifier: AccessVerifier | None) -> None:
        self.app = app
        self.verifier = verifier  # None = DEV_NO_AUTH

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        if self.verifier is None:
            state["user"] = Identity(email="local development", dev=True)
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        token = headers.get(JWT_HEADER) or Request(scope).cookies.get(JWT_COOKIE)
        try:
            state["user"] = await self.verifier.verify(token)
        except AccessDenied as exc:
            await _denied(scope, str(exc))(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _denied(scope: Scope, reason: str):
    request = Request(scope)
    if scope["path"].startswith(MCP_PATH) or "text/html" not in request.headers.get("accept", ""):
        return JSONResponse({"error": "unauthorized", "detail": reason}, status_code=401)
    from app.templating import templates

    return templates.TemplateResponse(request, "denied.html", {"reason": reason}, status_code=403)
