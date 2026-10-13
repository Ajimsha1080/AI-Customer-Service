import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("hospitality_agent_cloud.middleware.security_headers")

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Enterprise HTTP Security Headers Middleware:
    Enforces HSTS, Strict CSP, nosniff, DENY frame options, Referrer-Policy, and Permissions-Policy.
    """
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # 1. HTTP Strict Transport Security (HSTS) with 2-year duration and preload
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

        # 2. Content Security Policy (CSP)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' https: wss:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )

        # 3. MIME Sniffing Protection
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 4. Clickjacking Protection
        response.headers["X-Frame-Options"] = "DENY"

        # 5. Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 6. Permissions Policy (Disables browser APIs not required)
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), payment=()"

        return response
