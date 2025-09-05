from __future__ import annotations
import json, hmac, hashlib, os, time
from typing import Optional, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Config
SHARED_SECRET = os.getenv("SHARED_SECRET", "")
V2_REQUIRED = os.getenv("REQUIRE_V2_SIGNATURE", "false").lower() in ("1","true","yes")
TS_SKEW_SECONDS = int(os.getenv("SIG_TS_SKEW", "90"))

# Allowlist: these paths must bypass all checks
PATH_ALLOWLIST = {"/", "/health", "/healthz", "/docs", "/openapi.json", "/bars", "/status", "/account", "/_routes"}

def _hmac_hex(key: str, data: bytes) -> str:
    return hmac.new(key.encode(), data, hashlib.sha256).hexdigest()

class BBBIntentGuard(BaseHTTPMiddleware):
    """
    Guard ONLY POST /intent:
      - optional V2 signature (x-signature-v2 + x-signature-ts)
      - otherwise allow V1 (x-signature) to be handled by route
    All other endpoints are passed through unchanged.
    """

    async def dispatch(self, request: Request, call_next):
        # Bypass for allowlisted read-only endpoints
        if request.url.path in PATH_ALLOWLIST:
            return await call_next(request)

        # We only guard POST /intent
        if request.method != "POST" or request.url.path.rstrip("/") != "/intent":
            return await call_next(request)

        # Read body once
        body = await request.body()

        # V2: validate (if present) and inject V1 for downstream
        sig_v2 = request.headers.get("x-signature-v2")
        ts_hdr = request.headers.get("x-signature-ts")

        if sig_v2 and ts_hdr:
            try:
                ts = int(ts_hdr)
            except ValueError:
                return JSONResponse({"detail": "invalid timestamp"}, status_code=403)

            now = int(time.time())
            if abs(now - ts) > TS_SKEW_SECONDS:
                return JSONResponse({"detail": "stale signature"}, status_code=403)
            if not SHARED_SECRET:
                return JSONResponse({"detail": "server missing secret"}, status_code=500)

            calc_v2 = _hmac_hex(SHARED_SECRET, f"{ts}.{body.decode('utf-8')}".encode())
            if not hmac.compare_digest(calc_v2, sig_v2):
                return JSONResponse({"detail": "bad v2 signature"}, status_code=403)

            # inject legacy x-signature
            v1 = _hmac_hex(SHARED_SECRET, body)
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
            scope = dict(request.scope)
            headers = [(k.decode() if isinstance(k, bytes) else k,
                        v.decode() if isinstance(v, bytes) else v) for k, v in request.headers.raw]
            headers = [(k, v) for (k, v) in headers if k.lower() != "x-signature"]
            headers.append(("x-signature", v1))
            scope["headers"] = [(k.encode(), v.encode()) for (k, v) in headers]
            request = Request(scope, receive)
        else:
            if V2_REQUIRED:
                return JSONResponse({"detail": "v2 signature required"}, status_code=403)

        # Pass to downstream route
        resp: Response = await call_next(request)
        return resp
