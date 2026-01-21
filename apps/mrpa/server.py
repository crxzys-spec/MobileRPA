from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.app import router, shutdown_event
from .constants import OUTPUTS_DIR, STUDIO_DIST_DIR
from .settings import ServerSettings

SETTINGS = ServerSettings()

app = FastAPI()
if SETTINGS.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=SETTINGS.cors_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(router)
app.add_event_handler("shutdown", shutdown_event)

OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
if SETTINGS.serve_studio and STUDIO_DIST_DIR.exists():
    app.mount(
        "/", StaticFiles(directory=str(STUDIO_DIST_DIR), html=True), name="static"
    )
