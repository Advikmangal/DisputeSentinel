from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.routers.payments import router as payments_router
from app.services.payments import PaymentError
from app.routers.auth import router as auth_router
from app.services.auth import require_api_auth
from app.config import Settings, get_settings
from app.seed_merchant import seed_on_startup
from app.routers.workspace import router as workspace_router
from app.routers.webhooks import router as webhooks_router
from app.db import get_engine
from sqlalchemy import text


def ready():
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT id FROM merchants LIMIT 1"))
            connection.execute(text("SELECT id FROM transactions LIMIT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}

async def payment_error_handler(request, error: PaymentError):
    return JSONResponse(status_code=error.status, content={"detail": {"code": error.code, "message": error.message}})


def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.validate_production()
        if settings.environment == "production":
            seed_on_startup(settings)
        yield

    application = FastAPI(title="PayoutSentinel", lifespan=lifespan,
                          dependencies=[Depends(require_api_auth)])
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    application.include_router(auth_router)
    application.include_router(payments_router)
    application.include_router(workspace_router)
    application.include_router(webhooks_router)
    application.add_exception_handler(PaymentError, payment_error_handler)
    application.add_api_route("/health", health, methods=["GET", "HEAD"])
    application.add_api_route("/ready", ready, methods=["GET", "HEAD"])
    return application


app = create_app()
