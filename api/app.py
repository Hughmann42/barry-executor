from fastapi import FastAPI, HTTPException, Header, Request, Query
from pydantic import BaseModel
import os, hmac, hashlib

app = FastAPI(title="Barry Executor API", version="1.0.0")

SECRET = os.getenv("BARRY_SHARED_SECRET", "")

def verify(sig: str | None, body: bytes):
    if not SECRET:
        raise HTTPException(500, detail="Server secret not set")
    if not sig:
        raise HTTPException(403, detail="Bad signature")
    expected = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(403, detail="Bad signature")

@app.get("/health")
def health():
    return {"ok": True, "dry_run": False}

@app.get("/snapshot")
def snapshot(symbol: str = Query(..., min_length=1)):
    # TODO: call your real snapshot() in the executor
    return {"symbol": symbol, "status": "stub"}

@app.get("/bars")
def bars(symbol: str = Query(..., min_length=1), tf: str = Query("15m"), limit: int = Query(50, ge=1, le=1000)):
    # TODO: call your real bars() in the executor
    return {"symbol": symbol, "tf": tf, "limit": limit, "status": "stub"}

class Intent(BaseModel):
    symbol: str
    side: str                # "buy" | "sell" | "cancel"
    type: str = "market"     # "market" | "limit"
    qty: int | None = None
    notional: float | None = None
    limit_price: float | None = None
    time_in_force: str = "day"
    dry_run: bool = False
    client_id: str | None = None
    meta: dict | None = None

@app.post("/intent")
async def post_intent(request: Request, x_signature: str | None = Header(default=None)):
    body = await request.body()
    verify(x_signature, body)
    try:
        data = Intent.model_validate_json(body)
    except Exception as e:
        raise HTTPException(422, detail=str(e))
    # TODO: hand off to your executor/queue here
    return {"accepted": True, "intent": data.model_dump()}
