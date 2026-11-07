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
    application.add_exception_handler(PaymentError, payment_error_handler)
    application.add_api_route("/health", health, methods=["GET"])
    return application


app = create_app()
