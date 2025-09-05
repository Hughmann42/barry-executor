import os, requests
from fastapi import APIRouter, Header, HTTPException

router = APIRouter()

ALPACA_BASE = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
ALPACA_KEY  = os.getenv("APCA_API_KEY")
ALPACA_SEC  = os.getenv("APCA_SECRET_KEY")
SHARED      = os.getenv("SHARED_SECRET")

def _alp_headers():
    if not (ALPACA_KEY and ALPACA_SEC):
        raise HTTPException(status_code=500, detail="Alpaca keys not set")
    return {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SEC}

@router.get("/account")
def get_account(x_shared_secret: str = Header(None, alias="X-Shared-Secret")):
    if not SHARED or x_shared_secret != SHARED:
        raise HTTPException(status_code=401, detail="unauthorized")
    r = requests.get(f"{ALPACA_BASE}/v2/account", headers=_alp_headers(), timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()
