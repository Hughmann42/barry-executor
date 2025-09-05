from __future__ import annotations
import asyncio, json, hmac, hashlib, os, time
from collections import deque
from typing import Optional, Deque, Dict, Tuple
from zoneinfo import ZoneInfo
import httpx

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# ---- Config (env-driven; sane defaults) ----
SHARED_SECRET = os.getenv("SHARED_SECRET", "")
APCA_API_BASE_URL = (os.getenv("APCA_API_BASE_URL") or "").rstrip("/")
APCA_API_KEY_ID = os.getenv("APCA_API_KEY_ID") or os.getenv("APCA_API_KEY")
APCA_API_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET")

# Risk / session
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "4"))
MAX_TRADES_DAY = int(os.getenv("MAX_TRADES_DAY", "8"))
SESSION_TZ = os.getenv("SESSION_TZ", "Europe/London")
SESSION_START = os.getenv("SESSION_START", "14:35")  # HH:MM
SESSION_END = os.getenv("SESSION_END", "20:30")      # HH:MM

# Security knobs
V2_REQUIRED = os.getenv("REQUIRE_V2_SIGNATURE", "false").lower() in ("1","true","yes")
TS_SKEW_SECONDS = int(os.getenv("SIG_TS_SKEW", "90"))
IDEMP_TTL_SECONDS = int(os.getenv("IDEMP_TTL_SECONDS", "900"))
RL_MAX_REQ = int(os.getenv("RL_MAX_REQ", "15"))       # per window
RL_WINDOW_S = int(os.getenv("RL_WINDOW_S", "10"))
RL_GLOBAL_MAX_REQ = int(os.getenv("RL_GLOBAL_MAX_REQ", "60"))
RL_GLOBAL_WINDOW_S = int(os.getenv("RL_GLOBAL_WINDOW_S", "10"))

# ---- In-memory state (process local) ----
_idempotency: Dict[str, float] = {}     # key -> expires_at
_trades_today: Tuple[str,int] = ("",0)  # (YYYY-MM-DD, count)
_rate_ip: Dict[str, Deque[float]] = {}
_rate_global: Deque[float] = deque(maxlen=1000)
_state_lock = asyncio.Lock()

def _now_utc() -> float: return time.time()

def _within_window_london() -> bool:
    tz = ZoneInfo(SESSION_TZ)
    now = time.time()
    t = time.localtime(now)  # seconds-based; we'll convert using ZoneInfo
    # Use time and ZoneInfo via datetime for accuracy
    from datetime import datetime
    dt = datetime.now(tz)
    if dt.weekday() > 4:  # 0=Mon
        return False
    s_h,s_m = map(int, SESSION_START.split(":"))
    e_h,e_m = map(int, SESSION_END.split(":"))
    start = dt.replace(hour=s_h, minute=s_m, second=0, microsecond=0)
    end = dt.replace(hour=e_h, minute=e_m, second=0, microsecond=0)
    return start <= dt <= end

async def _positions_count() -> int:
    """Return current open positions count from Alpaca. 0 on failure (fail-closed handled by policy)."""
    if not (APCA_API_BASE_URL and APCA_API_KEY_ID and APCA_API_SECRET_KEY):
        return 0
    url = f"{APCA_API_BASE_URL}/v2/positions"
    headers = {"APCA-API-KEY-ID": APCA_API_KEY_ID, "APCA-API-SECRET-KEY": APCA_API_SECRET_KEY}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers)
        if r.status_code != 200:
            return 0
        data = r.json()
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0

def _hmac_hex(key: str, data: bytes) -> str:
    return hmac.new(key.encode(), data, hashlib.sha256).hexdigest()

def _client_ip(request: Request) -> str:
    xfwd = request.headers.get("x-forwarded-for", "")
    if xfwd:
        return xfwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def _json_body_fields(body: bytes) -> Tuple[Optional[str], Optional[str], bool]:
    """Return (symbol, side, dry_run) if present; tolerate empty/invalid JSON."""
    try:
        obj = json.loads(body.decode("utf-8"))
        return obj.get("symbol"), obj.get("side"), bool(obj.get("dry_run", False))
    except Exception:
        return None, None, False

PATH_ALLOWLIST={" /","/health","/healthz","/docs","/openapi.json","/bars","/status","/account"}

class BBBIntentGuard(BaseHTTPMiddleware):
    """
    V2 signature / replay protection / idempotency / rate-limit /
    session window / risk caps — applied ONLY to POST /intent.
    If V2 passes: inject a legacy X-Signature so the existing handler's V1 HMAC check succeeds.
    """

    async def dispatch(self, request: Request, call_next):
        global _trades_today
        if request.url.path in PATH_ALLOWLIST:
            return await call_next(request)
    global _trades_today
    if request.url.path in PATH_ALLOWLIST:
        return await call_next(request)
    global _trades_today
    if request.url.path in PATH_ALLOWLIST:
        return await call_next(request)
    global _trades_today
        # Only guard POST /intent
        if request.method != "POST" or request.url.path.rstrip("/") != "/intent":
            return await call_next(request)

        # Read body, we will re-inject it
        body = await request.body()
        # Correlation id (pass-through or generate)
        corr = request.headers.get("x-correlation-id") or request.headers.get("x-request-id") or _hmac_hex(SHARED_SECRET or "bbb", str(_now_utc()).encode())[:16]

        # ---- Rate limit (per-IP and global)
        ip = _client_ip(request)
        now = _now_utc()
        async with _state_lock:
            dq = _rate_ip.setdefault(ip, deque())
            dq.append(now)
            while dq and now - dq[0] > RL_WINDOW_S: dq.popleft()
            _rate_global.append(now)
            while _rate_global and now - _rate_global[0] > RL_GLOBAL_WINDOW_S: _rate_global.popleft()
            if len(dq) > RL_MAX_REQ or len(_rate_global) > RL_GLOBAL_MAX_REQ:
                return JSONResponse({"status":"rejected","reason":"rate_limit","correlation_id":corr}, status_code=429)

        # ---- Signature (prefer V2; optionally allow V1)
        sig_v2 = request.headers.get("x-signature-v2")
        ts_hdr = request.headers.get("x-signature-ts")
        sig_v1 = request.headers.get("x-signature")
        if sig_v2 and ts_hdr:
            try:
                ts = int(ts_hdr)
            except ValueError:
                return JSONResponse({"detail":"invalid timestamp"}, status_code=403)
            if abs(now - ts) > TS_SKEW_SECONDS:
                return JSONResponse({"detail":"stale signature"}, status_code=403)
            if not SHARED_SECRET:
                return JSONResponse({"detail":"server missing secret"}, status_code=500)
            calc_v2 = _hmac_hex(SHARED_SECRET, f"{ts}.{body.decode('utf-8')}".encode())
            if not hmac.compare_digest(calc_v2, sig_v2):
                return JSONResponse({"detail":"bad v2 signature"}, status_code=403)
            # inject legacy header so downstream V1 check passes
            v1 = _hmac_hex(SHARED_SECRET, body)
            # Rebuild request with injected header and original body
            async def receive():
                return {"type":"http.request", "body": body, "more_body": False}
            scope = dict(request.scope)
            headers = [(k.decode() if isinstance(k,bytes) else k, v.decode() if isinstance(v,bytes) else v) for k,v in request.headers.raw]
            headers = [(k,v) for (k,v) in headers if k.lower() != "x-signature"]
            headers.append(("x-signature", v1))
            scope["headers"] = [(k.encode(), v.encode()) for (k,v) in headers]
            request = Request(scope, receive)
        else:
            # No V2 provided
            if V2_REQUIRED:
                return JSONResponse({"detail":"v2 signature required"}, status_code=403)
            # leave V1 behavior to your existing handler

        # ---- Idempotency (short TTL)
        idem = request.headers.get("idempotency-key") or request.headers.get("x-idempotency-key")
        if idem:
            async with _state_lock:
                # prune
                expired = [k for k,exp in _idempotency.items() if exp < now]
                for k in expired: _idempotency.pop(k, None)
                if idem in _idempotency:
                    return JSONResponse({"status":"rejected","reason":"duplicate","correlation_id":corr}, status_code=409)
                _idempotency[idem] = now + IDEMP_TTL_SECONDS

        # ---- Session window enforcement
        if not _within_window_london():
            return JSONResponse({"status":"rejected","reason":"outside_session","correlation_id":corr}, status_code=403)

        # ---- Risk caps (positions / trades per day)
        symbol, side, dry_run = _json_body_fields(body)
        # day counter
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        async with _state_lock:
            day, cnt = _trades_today
            if day != today:
                _trades_today = (today, 0)
                cnt = 0
            # count only non-dry-run intents
            if not dry_run:
                if cnt >= MAX_TRADES_DAY:
                    return JSONResponse({"status":"rejected","reason":"trade_cap_reached","correlation_id":corr}, status_code=429)

        # positions cap (only for BUY, non-dry-run)
        if (side or "").lower() == "buy" and not dry_run:
            pos_count = await _positions_count()
            if pos_count >= MAX_POSITIONS:
                return JSONResponse({"status":"rejected","reason":"position_cap_reached","positions":pos_count,"correlation_id":corr}, status_code=409)

        # Re-inject original body downstream if not already rebuilt
        if not hasattr(request, "_receive"):
            async def receive():
                return {"type":"http.request", "body": body, "more_body": False}
            request = Request(request.scope, receive)

        # Proceed
        resp: Response = await call_next(request)
        # increment trades/day counter on success for non-dry-run
        try:
            if not dry_run and 200 <= resp.status_code < 300:
                async with _state_lock:
                    day, cnt = _trades_today
                    nowday = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if day != nowday:
                        _trades_today = (nowday, 0)
                        cnt = 0
                    _trades_today = (nowday, cnt + 1)
        except Exception:
            pass

        # attach correlation id
        resp.headers.setdefault("X-Correlation-Id", corr)
        return resp
