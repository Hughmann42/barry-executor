from pydantic import BaseModel, Field
from typing import Optional, Literal, Union, Dict, Any

class AckResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
    symbol: str
    side: Literal["buy","sell"]
    qty: Optional[int] = None
    notional: Optional[float] = None
    dry_run: bool = False
    order_id: Optional[str] = None
    ts: Optional[str] = None
    correlation_id: Optional[str] = None

class RejectResponse(BaseModel):
    status: Literal["rejected"] = "rejected"
    reason: str
    detail: Optional[str] = None
    correlation_id: Optional[str] = None

class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    detail: str
    correlation_id: Optional[str] = None

class ValidatedResponse(BaseModel):
    status: Literal["validated"] = "validated"
    schema_ok: bool = True
    session_ok: bool
    caps_ok: bool
    checks: Dict[str, Any] = Field(default_factory=dict)
    echo: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None

class LimitsResponse(BaseModel):
    ok: bool = True
    caps: Dict[str, Any]
    counters: Dict[str, Any]
