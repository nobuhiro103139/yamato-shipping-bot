from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import get_settings
from app.routers import orders, shipping

app = FastAPI(title="Yamato Shipping Bot", version="0.1.0")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders.router)
app.include_router(shipping.router)

qr_code_dir = Path("qr_codes")
qr_code_dir.mkdir(exist_ok=True)
app.mount("/qr_codes", StaticFiles(directory="qr_codes"), name="qr_codes")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
