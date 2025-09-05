from fastapi import FastAPI, Request
from executor.worker import router as executor_router

app = FastAPI(title="Barry Executor", version="1.0")

# Core routes
app.include_router(executor_router)

# Intent guard (safe + minimal)
try:
    from bbb_intent_guard import BBBIntentGuard
    app.add_middleware(BBBIntentGuard)
    print("[BBB] Intent guard enabled")
except Exception as e:
    print("[BBB] Guard not enabled:", e)

# Health + root
@app.get("/")
def root():
    return {"ok": True, "service": "barry-executor"}

@app.get("/healthz")
def healthz():
    return {"ok": True}

# Introspection (helps us verify deployed code)
import hashlib, pathlib
@app.get("/_routes")
def _routes(request: Request):
    import executor.worker as _w
    worker_path = pathlib.Path(_w.__file__)
    worker_hash = hashlib.sha256(worker_path.read_bytes()).hexdigest()
    return {
        "worker_file": str(worker_path),
        "worker_sha256": worker_hash,
        "routes": [getattr(r, "path", None) for r in app.routes],
    }
