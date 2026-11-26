import secrets
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("hospitality_agent_cloud.middleware.security_headers")

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Enterprise HTTP Security Headers Middleware:
    Enforces HSTS, Strict CSP with dynamic cryptographic nonce, nosniff, DENY frame options,
    strict Referrer-Policy, and restricted Permissions-Policy (camera, microphone, geolocation).
    """
    async def dispatch(self, request: Request, call_next):
        # Generate cryptographic nonce for per-request CSP protection
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response: Response = await call_next(request)

        # 1. HTTP Strict Transport Security (HSTS) with at least 1-year duration and preload
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # 2. Content Security Policy (CSP) with dynamic per-request nonce
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            f"style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data: https:; "
            f"font-src 'self' data:; "
            f"connect-src 'self' https: wss:; "
            f"frame-ancestors 'none'; "
            f"base-uri 'self'; "
            f"form-action 'self'; "
            f"object-src 'none';"
        )

        # 3. MIME Sniffing Protection
        response.headers["X-Content-Type-Options"] = "nosniff"

        # 4. Clickjacking Protection
        response.headers["X-Frame-Options"] = "DENY"

        # 5. Referrer Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 6. Permissions Policy (Disables browser APIs: camera, microphone, geolocation)
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"

        # 7. Cross-Origin Protections
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        return response
