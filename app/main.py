from fastapi import FastAPI
from app.routes.auth import router as auth_router

app = FastAPI(title="Sarbaz API")

app.include_router(auth_router)


@app.get("/")
def root():
    return {"status": "ok"}