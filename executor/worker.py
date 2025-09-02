import os, hmac, hashlib, json
from fastapi import APIRouter, Request, HTTPException
from httpx import HTTPStatusError
from .broker import submit_order, get_account, list_positions, DRY_RUN

SECRET = os.getenv("SHARED_SECRET", "")
router = APIRouter()

@router.get("/health")
def health():
    return {"ok": True, "dry_run": DRY_RUN}

def _verify_signature(sig: str | None, body: bytes):
    if not SECRET:
        raise HTTPException(500, "Missing SHARED_SECRET")
    calc = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(calc, sig):
        raise HTTPException(403, "Bad signature")

@router.get("/status")
async def status():
    try:
        acct = await get_account()
        pos  = await list_positions()
        return {"ok": True, "account": acct, "positions": pos}
    except HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, f"status error: {e}")

@router.post("/intent")
async def intent(request: Request):
    body = await request.body()
    _verify_signature(request.headers.get("X-Signature"), body)
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

    if not symbol:
        raise HTTPException(400, "symbol required")
    if side not in ("buy", "sell"):
        raise HTTPException(400, "side must be 'buy' or 'sell'")
    if qty is None and notional is None:
        raise HTTPException(400, "qty or notional required")

    try:
        res = await submit_order(symbol, side, qty=qty, notional=notional,
                                 order_type=otype, time_in_force=tif)
        return {"status": "ok", "result": res}
    except HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, f"executor error: {e}")
