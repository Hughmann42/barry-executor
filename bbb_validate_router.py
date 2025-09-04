from fastapi import APIRouter, HTTPException, Header
from typing import Optional, Dict, Any
import os, hmac
from zoneinfo import ZoneInfo
from datetime import datetime
import httpx

from bbb_contract import ValidatedResponse, LimitsResponse

router = APIRouter()

# shared knobs (read-only)
SHARED_SECRET = os.getenv("SHARED_SECRET", "")
APCA_API_BASE_URL = (os.getenv("APCA_API_BASE_URL") or "").rstrip("/")
APCA_API_KEY_ID = os.getenv("APCA_API_KEY_ID") or os.getenv("APCA_API_KEY")
APCA_API_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET")
SESSION_TZ = os.getenv("SESSION_TZ", "Europe/London")
SESSION_START = os.getenv("SESSION_START", "14:35")
SESSION_END = os.getenv("SESSION_END", "20:30")
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", "4"))
MAX_TRADES_DAY = int(os.getenv("MAX_TRADES_DAY", "8"))

def _verify_shared_secret_header(secret_header: Optional[str]):
    if not SHARED_SECRET:
        raise HTTPException(500, detail="Missing SHARED_SECRET")
    if not secret_header:
        raise HTTPException(403, detail="Missing X-Exec-Secret")
    if not hmac.compare_digest(secret_header, SHARED_SECRET):
        raise HTTPException(403, detail="Bad secret")

async def _positions_count() -> int:
    if not (APCA_API_BASE_URL and APCA_API_KEY_ID and APCA_API_SECRET_KEY):
        return 0
    url = f"{APCA_API_BASE_URL}/v2/positions"
    headers = {"APCA-API-KEY-ID": APCA_API_KEY_ID, "APCA-API-SECRET-KEY": APCA_API_SECRET_KEY}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers=headers)
        if r.status_code != 200: return 0
        data = r.json()
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0

def _session_ok() -> bool:
    tz = ZoneInfo(SESSION_TZ)
    now = datetime.now(tz)
    if now.weekday() > 4: return False
    sh, sm = map(int, SESSION_START.split(":"))
    eh, em = map(int, SESSION_END.split(":"))
    start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end   = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= now <= end

@router.post("/validate", response_model=ValidatedResponse)
async def validate_intent(intent: Dict[str, Any],
                          x_exec_secret: Optional[str] = Header(default=None, alias="X-Exec-Secret"),
                          x_correlation_id: Optional[str] = Header(default=None, alias="X-Correlation-Id")):
    """
    Dry validation: schema + session + caps. Does NOT place orders.
    Uses X-Exec-Secret auth (no HMAC needed here).
    """
    _verify_shared_secret_header(x_exec_secret)

    # --- Schema checks (minimal, mirrors what your handler expects)
    issues = {}
    symbol = intent.get("symbol")
    side   = intent.get("side")
    qty    = intent.get("qty")
    notional = intent.get("notional")
    dry_run = bool(intent.get("dry_run", False))

    schema_ok = True
    if not symbol or not isinstance(symbol, str):
        schema_ok = False; issues["symbol"] = "required"
    if side not in ("buy","sell"):
        schema_ok = False; issues["side"] = "must be 'buy' or 'sell'"
    if (qty is None and notional is None) or (qty is not None and notional is not None):
        schema_ok = False; issues["size"] = "either qty OR notional required"

    # --- Session & caps (informational; executor guard enforces on /intent)
    sess_ok = _session_ok()
    pos_count = await _positions_count()
    caps_ok = True
    if side == "buy" and not dry_run and pos_count >= MAX_POSITIONS:
        caps_ok = False

    checks = {
        "session": {"ok": sess_ok, "tz": SESSION_TZ, "window": f"{SESSION_START}-{SESSION_END}"},
        "caps": {"max_positions": MAX_POSITIONS, "max_trades_day": MAX_TRADES_DAY, "positions_now": pos_count},
        "schema_issues": issues
    }

    return ValidatedResponse(
        status="validated",
        schema_ok=schema_ok,
        session_ok=sess_ok,
        caps_ok=caps_ok,
        checks=checks,
        echo={"symbol": symbol, "side": side, "qty": qty, "notional": notional, "dry_run": dry_run},
        correlation_id=x_correlation_id
    )

# Surface current limits/counters (read-only)
try:
    # optional introspection from guard if present
    from bbb_intent_guard import MAX_POSITIONS as _MAX_POS, MAX_TRADES_DAY as _MAX_TD
    from bbb_intent_guard import _trades_today as _TD, _state_lock as _LOCK  # type: ignore
    @router.get("/limits", response_model=LimitsResponse)
    async def limits(x_exec_secret: Optional[str] = Header(default=None, alias="X-Exec-Secret")):
        _verify_shared_secret_header(x_exec_secret)
        date, cnt = "", 0
        try:
            async with _LOCK:
                date, cnt = _TD
        except Exception:
            pass
        return LimitsResponse(ok=True, caps={"max_positions": _MAX_POS, "max_trades_day": _MAX_TD},
                              counters={"trades_today": cnt, "date": date})
except Exception:
    @router.get("/limits", response_model=LimitsResponse)
    async def limits_fallback(x_exec_secret: Optional[str] = Header(default=None, alias="X-Exec-Secret")):
        _verify_shared_secret_header(x_exec_secret)
        return LimitsResponse(ok=True, caps={"max_positions": MAX_POSITIONS, "max_trades_day": MAX_TRADES_DAY},
                              counters={"trades_today": None, "date": None})
