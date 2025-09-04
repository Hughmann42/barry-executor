from fastapi import FastAPI
from executor.worker import router as executor_router

app = FastAPI(title="Barry Executor", version="1.0")
app.include_router(executor_router)

# --- [Barry Big Brain] intent guard middleware (Phase 2) ---
try:
    from bbb_intent_guard import BBBIntentGuard
    app.add_middleware(BBBIntentGuard)
    print("[BBB] Intent guard v2 enabled")
except Exception as _bbb_guard_exc:
    print("[BBB] Failed to enable intent guard:", _bbb_guard_exc)
# --- [end inject] ---
