from fastapi import FastAPI
from app.routes.auth import router as auth_router
from app.routes.system import router as system_router
from app.routes.ai import router as ai_router
from app.routes.profile import router as profile_router
from app.routes import billing

app = FastAPI(title="Sarbaz API")

app.include_router(auth_router)
app.include_router(system_router)
app.include_router(ai_router)
app.include_router(profile_router)
app.include_router(billing.router)


# --------------------------------------------------
# ROOT
# --------------------------------------------------
@app.get("/")
def root():
    return {"status": "ok"}


# --------------------------------------------------
# HEALTH CHECK (для Render)
# --------------------------------------------------
@app.get("/health")
def health():
    return {"status": "healthy"}