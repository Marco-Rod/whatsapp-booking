from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.availability import router
from app.api.v1.appointments import router as appointments_router
from app.api.v1.whatsapp import router as whatsapp_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.google_integrations import (
    admin_router as google_admin_integrations_router,
    router as google_integrations_router,
    callback_router as google_callback_router,
)
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.admin_sessions import router as admin_sessions_router
from app.api.v1.google_admin_auth import router as google_admin_auth_router

app = FastAPI(title="Booking Core", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_allowed_origins,
                   allow_credentials=True,
                   allow_methods=["GET", "PUT", "POST", "DELETE"],
                   allow_headers=["Accept", "Content-Type", "Authorization"])
app.include_router(router, prefix="/api/v1")
app.include_router(appointments_router, prefix="/api/v1")
app.include_router(whatsapp_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(google_integrations_router, prefix="/api/v1")
app.include_router(google_admin_integrations_router, prefix="/api/v1")
app.include_router(google_callback_router, prefix="/api/v1")
app.include_router(onboarding_router, prefix="/api/v1")
app.include_router(admin_sessions_router, prefix="/api/v1")
app.include_router(google_admin_auth_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
