import structlog
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


from app.routers import (
    alerts,
    auth,
    bunker,
    carriers,
    dashboard,
    evaluations,
    exchange_rate,
    health,
    ports,
    rates,
    route_brief,
    route_intelligence,
    scenarios,
    websocket,
)

try:
    from app.routers import ai_admin
except ImportError:
    try:
        from app.routers import ai as ai_admin
    except ImportError:
        ai_admin = None

try:
    from app.routers import forecasts, decisions
    has_forecast_routers = True
except ImportError:
    has_forecast_routers = False

from app.config import settings

logger = structlog.get_logger()

app = FastAPI(
    title="FreightPulse API",
    description="AI-Powered Freight & Logistics Intelligence Platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)





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
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(dashboard.router, prefix="/api/v1", tags=["Dashboard"])
app.include_router(rates.router, prefix="/api/v1", tags=["Rates"])
app.include_router(ports.router, prefix="/api/v1", tags=["Ports"])
app.include_router(carriers.router, prefix="/api/v1", tags=["Carriers"])
app.include_router(exchange_rate.router, prefix="/api/v1", tags=["Exchange Rate"])
app.include_router(bunker.router, prefix="/api/v1", tags=["Bunker"])
app.include_router(route_brief.router, prefix="/api/v1", tags=["Route Briefs"])
app.include_router(alerts.router, prefix="/api/v1", tags=["Alerts"])
if ai_admin:
    app.include_router(ai_admin.router, prefix="/api/v1", tags=["AI Management"])
app.include_router(websocket.router, prefix="/api/v1", tags=["WebSockets"])
# Root path mount retained for backward compatibility with existing clients/tests
app.include_router(websocket.router, tags=["WebSockets"])
app.include_router(scenarios.router, prefix="/api/v1", tags=["Scenarios"])
app.include_router(route_intelligence.router, prefix="/api/v1", tags=["Route Intelligence"])
app.include_router(evaluations.router, prefix="/api/v1", tags=["Forecast Evaluations"])

if has_forecast_routers:
    app.include_router(forecasts.router, prefix="/api/v1", tags=["Forecasts"])
    app.include_router(decisions.router, prefix="/api/v1", tags=["Decisions"])

