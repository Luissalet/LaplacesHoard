"""Browser-attack guard middleware: DNS-rebinding and cross-site writes.

Applied to every route. Rejects a request whose `Host` header does not
match this app's own `127.0.0.1:<port>` / `localhost:<port>` (blocks DNS
rebinding from a malicious page), and for any non-GET/HEAD/OPTIONS request
rejects one that carries a cross-origin `Origin` header or
`Sec-Fetch-Site: cross-site` (blocks a page elsewhere from POSTing here).
Plain GET navigation from any browser tab keeps working — this is not CORS,
there is no `Access-Control-Allow-Origin` anywhere.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class BrowserGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, port: int):
        super().__init__(app)
        self._allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self._allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "")
        if host not in self._allowed_hosts:
            return JSONResponse(
                {"error": "forbidden_host", "message": f"Host header {host!r} is not this app's own address."},
                status_code=403,
            )
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            sec_fetch_site = request.headers.get("sec-fetch-site")
            if origin is not None and origin not in self._allowed_origins:
                return JSONResponse(
                    {"error": "forbidden_origin", "message": "Cross-origin requests are not allowed."},
                    status_code=403,
                )
            if sec_fetch_site == "cross-site":
                return JSONResponse(
                    {"error": "forbidden_origin", "message": "Cross-site requests are not allowed."},
                    status_code=403,
                )
        return await call_next(request)
