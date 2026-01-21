import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mrpa.settings import ServerSettings

from .api import app as api_app
from .settings import ClientServiceSettings
from .worker import ClientWorker

SETTINGS = ServerSettings()
CLIENT_SETTINGS = ClientServiceSettings()
WORKER = ClientWorker(CLIENT_SETTINGS, api_app.device_manager)

app = FastAPI()
if SETTINGS.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=SETTINGS.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_app.router)
app.add_event_handler("shutdown", api_app.shutdown_event)


@app.on_event("startup")
async def _start_worker() -> None:
    if CLIENT_SETTINGS.mrpa_ws_url:
        asyncio.create_task(WORKER.run())


@app.on_event("shutdown")
async def _stop_worker() -> None:
    await WORKER.shutdown()
