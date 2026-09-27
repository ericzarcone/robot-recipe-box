"""App factory. Run with: uvicorn --factory app.main:create_app"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route

from app import web, web_plans
from app.access import AccessMiddleware, AccessVerifier
from app.config import MCP_PATH, Settings
from app.db import Database
from app.mcp_server import build_mcp
from app.plans import PlanNotFound, PlanRepo
from app.repo import RecipeNotFound, RecipeRepo
from app.templating import templates

log = logging.getLogger("uvicorn.error")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    # Only this site's own files may run. No inline script, so injected markup cannot execute.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
}


def create_app(settings: Settings | None = None, verifier: AccessVerifier | None = None) -> FastAPI:
    """verifier: override the Cloudflare key source in tests. Ignored with DEV_NO_AUTH."""
    settings = settings or Settings.from_env()
    if settings.dev_no_auth:
        verifier = None
        log.warning("DEV_NO_AUTH is on: every request is allowed. Never expose this app like this.")
    else:
        verifier = verifier or AccessVerifier(settings)
    db = Database(settings.db_path)
    repo = RecipeRepo(db)
    plans = PlanRepo(db, repo)
    mcp = build_mcp(repo, plans, settings)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=settings.allowed_origins,
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.migrate()
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Robot Recipe Box", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.repo = repo
    app.state.plans = plans

    app.add_middleware(AccessMiddleware, verifier=verifier)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.exception_handler(RecipeNotFound)
    @app.exception_handler(PlanNotFound)
    async def not_found(request: Request, exc: LookupError):
        kind = "Meal plan" if isinstance(exc, PlanNotFound) else "Recipe"
        return templates.TemplateResponse(request, "404.html", {"kind": kind}, status_code=404)

    # Mount the MCP route directly (not with Mount) so /mcp works without a trailing-slash redirect.
    mcp_endpoint = next(r.endpoint for r in mcp_app.routes if isinstance(r, Route))
    app.router.routes.append(Route(MCP_PATH, endpoint=mcp_endpoint))
    app.router.routes.append(Route(MCP_PATH + "/", endpoint=mcp_endpoint))

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.include_router(web_plans.router)
    app.include_router(web.router)
    return app
