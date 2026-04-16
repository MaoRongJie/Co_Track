from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from socketio import ASGIApp

from app.api import auth, rtc, sessions
from app.core.config import get_settings
from app.db.init_db import init_db
from app.model_processing import NORMALIZED_MODEL_DIR, TEXTURE_MAP_DIR, UV_TEMPLATE_DIR
from app.routes.workflow import ai_router, model_router
from app.socket.server import create_socket_server

settings = get_settings()

fastapi_app = FastAPI(title=settings.app_name)

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fastapi_app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
fastapi_app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
fastapi_app.include_router(rtc.router, prefix="/api/rtc", tags=["rtc"])
fastapi_app.include_router(ai_router, prefix="/api/ai", tags=["ai"])
fastapi_app.include_router(model_router, prefix="/api/models", tags=["models"])
fastapi_app.mount("/files/models", StaticFiles(directory=NORMALIZED_MODEL_DIR), name="files-models")
fastapi_app.mount("/files/uv", StaticFiles(directory=UV_TEMPLATE_DIR), name="files-uv")
fastapi_app.mount("/files/textures", StaticFiles(directory=TEXTURE_MAP_DIR), name="files-textures")

# Ensure database schema is ready in unit-test/import scenarios where startup hooks
# may not run before the first request.
init_db()


@fastapi_app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@fastapi_app.on_event("startup")
def on_startup() -> None:
    init_db()


sio = create_socket_server()
app = ASGIApp(socketio_server=sio, other_asgi_app=fastapi_app)

