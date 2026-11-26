import json
import hashlib
import base64
import secrets
import logging
from typing import Tuple, Optional, Dict, Any
from datetime import datetime, timezone
import httpx
from jose import jwt, JWTError

from services.common.redis_service import get_redis_client

logger = logging.getLogger("hospitality_agent_cloud.security.oidc")

ALLOWED_OIDC_ALGORITHMS = {"RS256", "ES256"}

class OIDCValidationError(Exception):
    """Raised when OIDC token or flow fails validation."""
    pass

def generate_pkce_pair() -> Tuple[str, str]:
    """Generates PKCE (code_verifier, code_challenge) using S256."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge

def build_oidc_authorization_url(
    idp_auth_url: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str
) -> str:
    """Builds OIDC authorization redirect URL with PKCE and nonce parameters."""
    delimiter = "&" if "?" in idp_auth_url else "?"
    params = (
        f"response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=openid%20email%20profile"
        f"&state={state}"
        f"&nonce={nonce}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    return f"{idp_auth_url}{delimiter}{params}"

async def fetch_oidc_discovery(issuer_or_url: str) -> Dict[str, Any]:
    """Fetches OIDC discovery document from /.well-known/openid-configuration with Redis caching."""
    if not issuer_or_url:
        return {}

    url = issuer_or_url.rstrip("/")
    if not url.endswith("/.well-known/openid-configuration"):
        url = f"{url}/.well-known/openid-configuration"

    cache_key = f"hac:oidc:discovery:{hashlib.sha256(url.encode()).hexdigest()[:16]}"
    redis = await get_redis_client()
    cached = await redis.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        if resp.status_code >= 400:
            raise OIDCValidationError(f"OIDC discovery failed from {url}: HTTP {resp.status_code}")
        data = resp.json()
        await redis.set(cache_key, json.dumps(data), ex=3600)
        return data

async def fetch_jwks(jwks_uri: str, force_refresh: bool = False) -> Dict[str, Any]:
    """Fetches and caches IdP public JWKS with Redis caching."""
    if not jwks_uri:
        raise OIDCValidationError("Missing jwks_uri.")

    cache_key = f"hac:oidc:jwks:{hashlib.sha256(jwks_uri.encode()).hexdigest()[:16]}"
    redis = await get_redis_client()

    if not force_refresh:
        cached = await redis.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(jwks_uri)
        if resp.status_code >= 400:
            raise OIDCValidationError(f"Failed to fetch JWKS from {jwks_uri}: HTTP {resp.status_code}")
        data = resp.json()
        await redis.set(cache_key, json.dumps(data), ex=3600)
        return data

async def exchange_code_for_tokens(
    token_endpoint: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: Optional[str] = None
) -> Dict[str, Any]:
    """Exchanges authorization code + PKCE code_verifier for ID and access tokens at token_endpoint."""
    if not token_endpoint:
        raise OIDCValidationError("Missing token_endpoint.")

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier
    }
    if client_secret:
        payload["client_secret"] = client_secret

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(token_endpoint, data=payload)
        if resp.status_code >= 400:
            raise OIDCValidationError(f"OIDC code exchange failed: HTTP {resp.status_code} - {resp.text}")
        return resp.json()

def validate_id_token(
    id_token: str,
    expected_client_id: str,
    expected_issuer: Optional[str] = None,
    expected_nonce: Optional[str] = None,
    jwks: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Validates an OIDC ID Token against JWKS with strict security controls:
    1. Algorithm restricted strictly to RS256 or ES256 (no HS256/none).
    2. Strict 'kid' matching (NO keys[0] fallback).
    3. Full claim verification: aud, iss, exp, nonce, and email.
    """
    if not id_token:
        raise OIDCValidationError("Missing ID Token.")

    try:
        header = jwt.get_unverified_header(id_token)
    except Exception as e:
        raise OIDCValidationError(f"Invalid ID token format: {e}")

    alg = header.get("alg")
    if alg not in ALLOWED_OIDC_ALGORITHMS:
        raise OIDCValidationError(
            f"Disallowed algorithm '{alg}'. Only {sorted(list(ALLOWED_OIDC_ALGORITHMS))} are permitted."
        )

    kid = header.get("kid")
    if not kid:
        raise OIDCValidationError("ID token header is missing required 'kid' property.")

    if not jwks or "keys" not in jwks:
        raise OIDCValidationError("JWKS keyset is missing or empty.")

    matching_key = None
    for k in jwks["keys"]:
        if k.get("kid") == kid:
            matching_key = k
            break

    # Strict kid matching: NO keys[0] fallback!
    if not matching_key:
        raise OIDCValidationError(f"No key matching kid '{kid}' found in JWKS.")

    try:
        claims = jwt.decode(
            id_token,
            matching_key,
            algorithms=[alg],
            audience=expected_client_id,
            issuer=expected_issuer,
            options={
                "verify_aud": bool(expected_client_id),
                "verify_iss": bool(expected_issuer),
                "verify_exp": True
            }
        )
    except JWTError as e:
        raise OIDCValidationError(f"ID Token cryptographic or claim validation failed: {e}")

    # Verify nonce if expected
    if expected_nonce:
        token_nonce = claims.get("nonce")
        if token_nonce != expected_nonce:
            raise OIDCValidationError(
                f"ID Token nonce mismatch: expected '{expected_nonce}', got '{token_nonce}'."
            )

    email = claims.get("email")
    if not email:
        raise OIDCValidationError("ID Token does not contain an 'email' claim.")

    full_name = claims.get("name") or claims.get("preferred_username") or email.split("@")[0]

    return {
        "email": email.lower().strip(),
        "full_name": full_name,
        "sub": claims.get("sub"),
        "claims": claims
    }
