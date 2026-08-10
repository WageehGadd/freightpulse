from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings

EXEMPT_PATHS = ["/docs", "/redoc", "/openapi.json", "/api/v1/health"]

class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(path) for path in EXEMPT_PATHS):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")

        if not api_key or api_key != settings.API_KEY:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)