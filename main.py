from fastapi import FastAPI
from executor.worker import router as executor_router

app = FastAPI(title="Barry Executor", version="1.0")
app.include_router(executor_router)

# --- [Barry Big Brain] validate/limits router (Phase 3) ---
try:
    from bbb_validate_router import router as _bbb_validate_router
    app.include_router(_bbb_validate_router)
    print("[BBB] Validate/limits router enabled")
except Exception as _bbb_v_exc:
    print("[BBB] Failed to enable validate router:", _bbb_v_exc)
# --- [end inject] ---
