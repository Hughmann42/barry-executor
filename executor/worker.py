import os, hmac, hashlib, json, typing
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Query
import httpx

# ---- Config / Env ----
SECRET = os.getenv("SHARED_SECRET", "")
APCA_API_BASE_URL = (os.getenv("APCA_API_BASE_URL") or "").rstrip("/")
APCA_API_KEY_ID = os.getenv("APCA_API_KEY_ID") or os.getenv("APCA_API_KEY") or ""
APCA_API_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY") or os.getenv("APCA_API_SECRET") or ""
APCA_DATA_URL = (os.getenv("APCA_DATA_URL") or "https://data.alpaca.markets").rstrip("/")

# Dry run flag (optional)
DRY_RUN = os.getenv("DRY_RUN", "0") in ("1","true","yes")

router = APIRouter()

def _require_secret():
    if not SECRET:
        raise HTTPException(500, "Missing SHARED_SECRET")

def _verify_signature(sig: typing.Optional[str], body: bytes):
    _require_secret()
    calc = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(calc, sig):
        raise HTTPException(403, "Bad signature")

def _alp_headers() -> dict:
    if not (APCA_API_KEY_ID and APCA_API_SECRET_KEY):
        raise HTTPException(500, "Missing Alpaca credentials")
    return {
        "APCA-API-KEY-ID": APCA_API_KEY_ID,
        "APCA-API-SECRET-KEY": APCA_API_SECRET_KEY,
        "Accept": "application/json",
    }

@router.get("/health")
def health():
    return {"ok": True, "dry_run": DRY_RUN}

@router.get("/status")
async def status():
    acct = await _get_account()
    pos = await _list_positions()
    return {"ok": True, "account": acct, "positions": pos}

# ---- Minimal Alpaca helpers ----
async def _get_account():
    if not APCA_API_BASE_URL:
        raise HTTPException(500, "APCA_API_BASE_URL not set")
    url = f"{APCA_API_BASE_URL}/v2/account"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=_alp_headers())
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return r.json()

async def _list_positions():
    if not APCA_API_BASE_URL:
        raise HTTPException(500, "APCA_API_BASE_URL not set")
    url = f"{APCA_API_BASE_URL}/v2/positions"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=_alp_headers())
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    data = r.json()
    return data if isinstance(data, list) else []

_timeframe_map = {
    "1Min": "1Min", "5Min": "5Min", "15Min":"15Min", "30Min":"30Min",
    "1Hour":"1Hour", "1Day":"1Day",
    "1m":"1Min","5m":"5Min","15m":"15Min","30m":"30Min","1h":"1Hour","1d":"1Day"
}

@router.get("/account")
async def account():
    return await _get_account()

@router.get("/bars")
async def bars(
    symbol: str = Query(..., min_length=1),
    timeframe: str = Query("15Min"),
    limit: int = Query(50, ge=1, le=1000),
    start: str | None = None,
    end: str | None = None,
):
    tf = _timeframe_map.get(timeframe, "15Min")
    url = f"{APCA_DATA_URL}/v2/stocks/{symbol.upper()}/bars"
    params = {"timeframe": tf, "limit": limit}
    if start: params["start"] = start
    if end: params["end"] = end
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=_alp_headers(), params=params)
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return r.json()

# ---- Order submission (intents) ----
async def _submit_order(symbol: str, side: str, qty=None, notional=None, order_type="market", time_in_force="day"):
    if DRY_RUN:
        return {
            "dry_run": True, "symbol": symbol, "side": side,
            "qty": qty, "notional": notional, "type": order_type, "tif": time_in_force,
            "ts": datetime.utcnow().isoformat()+"Z"
        }
    if not APCA_API_BASE_URL:
        raise HTTPException(500, "APCA_API_BASE_URL not set")
    url = f"{APCA_API_BASE_URL}/v2/orders"
    payload = {
        "symbol": symbol.upper(),
        "side": side.lower(),
        "type": order_type.lower(),
        "time_in_force": time_in_force.lower(),
    }
    if qty is not None: payload["qty"] = qty
    if notional is not None: payload["notional"] = notional
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, headers=_alp_headers(), json=payload)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

@router.post("/intent")
async def intent(request: Request):
    body = await request.body()
    # Accept either V1: X-Signature HMAC(body) or V2 injected by guard
    _verify_signature(request.headers.get("x-signature"), body)
    try:
        data = json.loads(body.decode())
    except Exception as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    symbol   = (data.get("symbol") or "").upper().strip()
    side     = str(data.get("side", "")).lower().strip()
    qty      = data.get("qty")
    notional = data.get("notional")
    otype    = data.get("type", "market")
    tif      = data.get("time_in_force", "day")
    dry_run  = bool(data.get("dry_run", False))

    if not symbol:
        raise HTTPException(400, "symbol required")
    if side not in ("buy", "sell"):
        raise HTTPException(400, "side must be 'buy' or 'sell'")
    if qty is None and notional is None:
        raise HTTPException(400, "qty or notional required")

    if dry_run:
        return {"status":"dry_run_ok","would_submit":{
            "symbol":symbol,"side":side,"qty":qty,"notional":notional,"type":otype,"time_in_force":tif
        }}

    res = await _submit_order(symbol, side, qty=qty, notional=notional, order_type=otype, time_in_force=tif)
    return {"status":"ok","result":res}
