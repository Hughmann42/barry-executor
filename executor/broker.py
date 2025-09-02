import os
import httpx
from typing import Optional, Any

BASE = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")
KEY  = os.getenv("APCA_API_KEY_ID", "")
SEC  = os.getenv("APCA_API_SECRET_KEY", "")
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

HEADERS = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}

async def submit_order(
    symbol: str,
    side: str,
    qty: Optional[int] = None,
    notional: Optional[float] = None,
    order_type: str = "market",
    time_in_force: str = "day",
) -> Any:
    if qty is None and notional is None:
        raise ValueError("qty or notional required")

    payload = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if qty is not None:
        payload["qty"] = int(qty)
    if notional is not None:
        payload["notional"] = float(notional)

    if DRY_RUN:
        return {"dry_run": True, "submitted": payload}

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{BASE}/v2/orders", headers=HEADERS, json=payload)
        r.raise_for_status()
        return r.json()

async def get_account() -> Any:
    if DRY_RUN:
        return {"dry_run": True, "status": "DRY_RUN", "buying_power": "0"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{BASE}/v2/account", headers=HEADERS)
        r.raise_for_status()
        return r.json()

async def list_positions() -> Any:
    if DRY_RUN:
        return []
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{BASE}/v2/positions", headers=HEADERS)
        r.raise_for_status()
        return r.json()
