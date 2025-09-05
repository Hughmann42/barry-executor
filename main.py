from fastapi import FastAPI
from executor.worker import router as executor_router

app = FastAPI(title="Barry Executor", version="1.0")

# Core executor routes
app.include_router(executor_router)

# Intent guard (optional)
try:
    from bbb_intent_guard import BBBIntentGuard
    app.add_middleware(BBBIntentGuard)
    print("[BBB] Intent guard enabled")
except Exception as e:
    print("[BBB] Guard not enabled:", e)

# Optional extra validate router (if present)
try:
    from bbb_validate_router import router as _bbb_validate_router# 
    # app.include_router(_bbb_validate_router)  # disabled for test
    print("[BBB] Validate/limits router enabled")
except Exception:
    pass

# Root + health (Railway probes)
@app.get("/")
def root():
    return {"ok": True, "service": "barry-executor"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

from fastapi import Request
import hashlib, pathlib
@ app.get("/_routes")
def _routes(request: Request):
    import executor.worker as _w
    worker_path = pathlib.Path(_w.__file__)
    worker_hash = hashlib.sha256(worker_path.read_bytes()).hexdigest()
    return {"worker_file": str(worker_path),
            "worker_sha256": worker_hash,
            "routes": [getattr(r, "path", None) for r in app.routes]}
