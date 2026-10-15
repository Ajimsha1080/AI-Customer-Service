import hashlib
import base64
import secrets
import logging
from typing import Tuple, Optional, Dict, Any
from datetime import datetime, timezone
from jose import jwt, JWTError

logger = logging.getLogger("hospitality_agent_cloud.security.oidc")

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

def validate_id_token(
    id_token: str,
    expected_client_id: str,
    expected_issuer: Optional[str] = None,
    expected_nonce: Optional[str] = None,
    jwks: Optional[dict] = None,
    client_secret: Optional[str] = None
) -> Dict[str, Any]:
    """Validates an OIDC ID Token against JWKS or symmetric key, with claim verification."""
    if not id_token:
        raise OIDCValidationError("Missing ID Token.")

    # Get header without verification to determine algorithm and key id
    try:
        header = jwt.get_unverified_header(id_token)
    except Exception as e:
        raise OIDCValidationError(f"Invalid ID token format: {e}")

    alg = header.get("alg", "RS256")
    key = None

    if jwks and "keys" in jwks:
        kid = header.get("kid")
        for k in jwks["keys"]:
            if kid and k.get("kid") == kid:
                key = k
                break
        if not key and jwks["keys"]:
            key = jwks["keys"][0]

    if not key and client_secret and alg.startswith("HS"):
        key = client_secret

    if not key:
        # If no JWKS provided and no secret, attempt decoding with JWKS or raise
        raise OIDCValidationError("No matching key found to verify ID token signature.")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[alg],
            audience=expected_client_id,
            issuer=expected_issuer,
            options={"verify_aud": bool(expected_client_id), "verify_exp": True}
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
