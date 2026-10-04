"""One deployable app: MCP at /mcp (Streamable HTTP) + REST at /api + /health.

    uvicorn server.app:app --host 0.0.0.0 --port 8000

If LAWHACK_TOKEN is set, /mcp and /api require it, either as `Authorization: Bearer <token>`
(Le Chat, Legora, scripts) or as `?key=<token>` in the URL (Claude / ChatGPT connectors
configured without OAuth). OAuth 2.1 is the next step for public directory listings.
"""

import hmac
import os
from urllib.parse import parse_qs

from fastapi import FastAPI
from starlette.responses import JSONResponse

from server.api import router
from server.mcp_server import mcp

mcp_app = mcp.http_app(path="/mcp")


class TokenGuard:
    def __init__(self, app, token: str | None):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if self.token and scope["type"] == "http" and scope["path"].startswith(("/mcp", "/api")) and not scope["path"].startswith("/api/docs"):
            headers = dict(scope.get("headers") or [])
            bearer = headers.get(b"authorization", b"").decode().removeprefix("Bearer ").strip()
            key = parse_qs(scope.get("query_string", b"").decode()).get("key", [""])[0]
            if not any(v and hmac.compare_digest(v, self.token) for v in (bearer, key)):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


api = FastAPI(title="LawHack", version="0.1.0", lifespan=mcp_app.lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
api.include_router(router)


@api.get("/health")
def health() -> dict:
    return {"status": "ok", "attribution": "jev" if os.environ.get("TYPESAFE_API_KEY") else "heuristic"}


api.mount("/", mcp_app)
app = TokenGuard(api, os.environ.get("LAWHACK_TOKEN") or None)
