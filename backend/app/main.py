from fastapi import FastAPI
from app.api.v1.availability import router
from app.api.v1.appointments import router as appointments_router

app = FastAPI(title="Booking Core", version="0.1.0")
app.include_router(router, prefix="/api/v1")
app.include_router(appointments_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
