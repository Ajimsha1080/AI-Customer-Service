import logging
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.config import settings
from services.resilience.circuit_breaker import CircuitBreakerOpenError

logger = logging.getLogger("hospitality_agent_cloud.error_handler")

def build_error_envelope(
    code: str,
    message: str,
    request_id: str,
    details: Any = None
) -> Dict[str, Any]:
    """Generates consistent enterprise error envelope across all API endpoints."""
    return {
        "detail": message,
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id
        }
    }

async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    status_code = getattr(exc, "status_code", 400)
    raw_detail = getattr(exc, "detail", str(exc))
    message = str(raw_detail)
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")

    code = "HTTP_ERROR"
    if status_code == 400:
        code = "BAD_REQUEST"
    elif status_code == 401:
        code = "UNAUTHORIZED"
    elif status_code == 403:
        code = "FORBIDDEN"
    elif status_code == 404:
        code = "NOT_FOUND"
    elif status_code == 409:
        code = "CONFLICT"
    elif status_code == 422:
        code = "UNPROCESSABLE_ENTITY"
    elif status_code == 429:
        code = "RATE_LIMIT_EXCEEDED"
    elif status_code >= 500:
        code = "INTERNAL_SERVER_ERROR"

    resp_headers = {"X-Request-ID": request_id}
    exc_headers = getattr(exc, "headers", None)
    if exc_headers and isinstance(exc_headers, dict):
        resp_headers.update(exc_headers)

    content = build_error_envelope(code=code, message=message, request_id=request_id)
    return JSONResponse(status_code=status_code, headers=resp_headers, content=content)

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
    errors = exc.errors()
    content = build_error_envelope(
        code="VALIDATION_ERROR",
        message="Request validation failed. Verify input schema.",
        request_id=request_id,
        details=errors
    )
    content["detail"] = errors
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        headers={"X-Request-ID": request_id},
        content=content
    )

async def circuit_breaker_exception_handler(request: Request, exc: CircuitBreakerOpenError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
    content = build_error_envelope(
        code="CIRCUIT_BREAKER_OPEN",
        message=f"Service gateway temporarily unavailable: circuit '{exc.name}' is OPEN.",
        request_id=request_id,
        details={"circuit": exc.name, "recovery_time_left": exc.recovery_time_left}
    )
    headers = {
        "X-Request-ID": request_id,
        "Retry-After": str(max(1, int(exc.recovery_time_left)))
    }
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, headers=headers, content=content)

async def global_unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
    logger.error(f"[UnhandledException] request_id={request_id} error={exc}", exc_info=True)

    # In production: ZERO stack traces or internal exception detail leaks
    message = "An unexpected system error occurred. Please contact support with your request ID."
    details = None
    if not settings.is_production:
        details = str(exc)

    content = build_error_envelope(
        code="INTERNAL_SERVER_ERROR",
        message=message,
        request_id=request_id,
        details=details
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers={"X-Request-ID": request_id},
        content=content
    )

def register_error_handlers(app: FastAPI) -> None:
    """Registers unified error envelope handlers on the FastAPI application."""
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(CircuitBreakerOpenError, circuit_breaker_exception_handler)
    app.add_exception_handler(Exception, global_unhandled_exception_handler)
