import pytest
import uuid
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from jose import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.routers.sso import generate_sso_state
from services.security.oidc_service import (
    validate_id_token,
    generate_pkce_pair,
    OIDCValidationError
)
from services.database.models import User, Organization, SSOConfig, UserRole

# Generate RSA Keypair for testing RS256 ID tokens
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
).decode()

_public_key = _private_key.public_key()
_public_pem = _public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode()

# Construct matching JWK
from jose.jwk import RSAKey
_jwk = RSAKey(key=_public_pem, algorithm="RS256").to_dict()
_jwk["kid"] = "valid-kid-1"
_test_jwks = {"keys": [_jwk]}

def test_h8_rejects_hs256_algorithm():
    """H8: RS256/ES256 only. Reject HS256 algorithm on ID tokens."""
    token = jwt.encode({"sub": "123", "email": "test@example.com"}, "secret", algorithm="HS256")
    with pytest.raises(OIDCValidationError) as exc:
        validate_id_token(
            id_token=token,
            expected_client_id="client_123",
            expected_issuer="https://idp.example.com",
            jwks=_test_jwks
        )
    assert "disallowed algorithm" in str(exc.value).lower()

def test_h8_strict_kid_match_no_keys0_fallback():
    """H8: Strict kid match (no keys[0] fallback)."""
    # Create token with mismatched kid
    token = jwt.encode(
        {"sub": "123", "email": "test@example.com", "aud": "client_123", "iss": "https://idp.example.com"},
        _private_pem,
        algorithm="RS256",
        headers={"kid": "unknown-kid-999"}
    )
    with pytest.raises(OIDCValidationError) as exc:
        validate_id_token(
            id_token=token,
            expected_client_id="client_123",
            expected_issuer="https://idp.example.com",
            jwks=_test_jwks
        )
    assert "no key matching kid" in str(exc.value).lower()

def test_h8_claim_validation_nonce_aud_iss_exp():
    """H8: Strict claim validation for nonce, aud, iss, exp."""
    now = int(time.time())
    
    # 1. Nonce mismatch
    claims = {
        "sub": "user_1",
        "email": "user@example.com",
        "aud": "client_123",
        "iss": "https://idp.example.com",
        "nonce": "good-nonce",
        "exp": now + 3600,
        "iat": now
    }
    token = jwt.encode(claims, _private_pem, algorithm="RS256", headers={"kid": "valid-kid-1"})
    with pytest.raises(OIDCValidationError) as exc:
        validate_id_token(
            id_token=token,
            expected_client_id="client_123",
            expected_issuer="https://idp.example.com",
            expected_nonce="different-nonce",
            jwks=_test_jwks
        )
    assert "nonce mismatch" in str(exc.value).lower()

    # 2. Audience mismatch
    with pytest.raises(OIDCValidationError):
        validate_id_token(
            id_token=token,
            expected_client_id="wrong_client",
            expected_issuer="https://idp.example.com",
            expected_nonce="good-nonce",
            jwks=_test_jwks
        )

    # 3. Expired token
    expired_claims = dict(claims)
    expired_claims["exp"] = now - 100
    expired_token = jwt.encode(expired_claims, _private_pem, algorithm="RS256", headers={"kid": "valid-kid-1"})
    with pytest.raises(OIDCValidationError):
        validate_id_token(
            id_token=expired_token,
            expected_client_id="client_123",
            expected_issuer="https://idp.example.com",
            expected_nonce="good-nonce",
            jwks=_test_jwks
        )

    # 4. Valid token succeeds
    valid_res = validate_id_token(
        id_token=token,
        expected_client_id="client_123",
        expected_issuer="https://idp.example.com",
        expected_nonce="good-nonce",
        jwks=_test_jwks
    )
    assert valid_res["email"] == "user@example.com"
    assert valid_res["sub"] == "user_1"

@pytest.mark.asyncio
async def test_h8_callback_pkce_code_exchange(db_session):
    """H8: Callback exchanges auth code using PKCE code_verifier (does not treat code as ID token)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="OIDC Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        sso_config = SSOConfig(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            provider_type="OIDC",
            idp_sso_url="https://idp.example.com",
            idp_entity_id="https://idp.example.com",
            client_id="hotel_client_1",
            client_secret_encrypted="secret",
            domain_verified=True,
            domains=["hotel.com"],
            default_role="STAFF",
            jit_provisioning_enabled=True
        )
        db_session.add(org)
        db_session.add(sso_config)
        await db_session.commit()

        code_verifier, code_challenge = generate_pkce_pair()
        nonce = "test-nonce-123"
        state = generate_sso_state(
            org_id=org_id,
            provider="OIDC",
            code_verifier=code_verifier,
            nonce=nonce
        )

        # Mock token endpoint exchange and jwks fetch
        now = int(time.time())
        id_token_claims = {
            "sub": "sso_user_456",
            "email": "concierge@hotel.com",
            "name": "Concierge Staff",
            "aud": "hotel_client_1",
            "iss": "https://idp.example.com",
            "nonce": nonce,
            "exp": now + 3600,
            "iat": now
        }
        signed_id_token = jwt.encode(id_token_claims, _private_pem, algorithm="RS256", headers={"kid": "valid-kid-1"})

        with patch("apps.api.routers.sso.fetch_oidc_discovery", new_callable=AsyncMock) as mock_disc, \
             patch("apps.api.routers.sso.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
             patch("apps.api.routers.sso.fetch_jwks", new_callable=AsyncMock) as mock_jwks:
            
            mock_disc.return_value = {
                "token_endpoint": "https://idp.example.com/token",
                "jwks_uri": "https://idp.example.com/jwks",
                "issuer": "https://idp.example.com"
            }
            mock_exchange.return_value = {"id_token": signed_id_token, "access_token": "at_123"}
            mock_jwks.return_value = _test_jwks

            callback_resp = await ac.post("/api/v1/auth/sso/oidc/callback", json={
                "code": "auth_code_from_idp_789",
                "state": state
            })

            assert callback_resp.status_code == 200, callback_resp.text
            data = callback_resp.json()
            assert data["user"]["email"] == "concierge@hotel.com"

            # Assert code_verifier was passed into code exchange
            mock_exchange.assert_called_once()
            _, kwargs = mock_exchange.call_args
            assert kwargs["code"] == "auth_code_from_idp_789"
            assert kwargs["code_verifier"] == code_verifier
