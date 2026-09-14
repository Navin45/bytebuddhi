"""Reject oversized HTTP request bodies before application logic runs."""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_413_CONTENT_TOO_LARGE

from app.infrastructure.config.settings import settings


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Honor Content-Length against max_request_body_bytes."""

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("content-length")
        if header:
            try:
                length = int(header)
            except ValueError:
                length = -1
            if length > settings.max_request_body_bytes:
                return JSONResponse(
                    status_code=HTTP_413_CONTENT_TOO_LARGE,
                    content={"error": "payload_too_large", "message": "Request body exceeds the configured limit"},
                )
        return await call_next(request)
