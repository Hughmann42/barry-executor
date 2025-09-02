from fastapi import FastAPI
from executor.worker import router as executor_router

app = FastAPI(title="Barry Executor", version="1.0")
app.include_router(executor_router)
