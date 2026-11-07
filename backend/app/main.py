from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.routers.payments import router as payments_router
from app.services.payments import PaymentError

app = FastAPI(title="DisputeSentinel")
app.include_router(payments_router)


@app.exception_handler(PaymentError)
async def payment_error_handler(request, error: PaymentError):
    return JSONResponse(status_code=error.status, content={"detail": {"code": error.code, "message": error.message}})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
