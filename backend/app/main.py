from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from app.routers import orders, shipping

app = FastAPI(title="Yamato Shipping Bot", version="0.1.0")

# Disable CORS. Do not remove this for full-stack development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.include_router(orders.router)
app.include_router(shipping.router)

qr_code_dir = Path("qr_codes")
qr_code_dir.mkdir(exist_ok=True)
app.mount("/qr_codes", StaticFiles(directory="qr_codes"), name="qr_codes")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
