import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.middlewares.api_key import ApiKeyMiddleware
from app.routers import bunker, carriers, dashboard, exchange_rate, health, ports, rates

logger = structlog.get_logger()

app = FastAPI(
    title="FreightPulse API",
    description="AI-Powered Freight & Logistics Intelligence Platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(ApiKeyMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """Wrap any HTTPException in the standardized error envelope."""
    code_map = {401: "UNAUTHORIZED", 404: "NOT_FOUND", 422: "VALIDATION_ERROR", 429: "RATE_LIMITED"}
    code = code_map.get(exc.status_code, "ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": exc.detail, "details": {}}},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    logger.error("unhandled_exception", error=str(exc), path=str(request.url.path))
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred", "details": {}}},
    )


app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(dashboard.router, prefix="/api/v1", tags=["Dashboard"])
app.include_router(rates.router, prefix="/api/v1", tags=["Rates"])
app.include_router(ports.router, prefix="/api/v1", tags=["Ports"])
app.include_router(carriers.router, prefix="/api/v1", tags=["Carriers"])
app.include_router(exchange_rate.router, prefix="/api/v1", tags=["Exchange Rate"])
app.include_router(bunker.router, prefix="/api/v1", tags=["Bunker"])