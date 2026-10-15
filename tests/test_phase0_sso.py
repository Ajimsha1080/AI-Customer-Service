import uuid
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography import x509
from jose import jwt

from apps.api.main import app
from apps.api.config import settings
from services.security.saml_service import create_signed_saml_response
from services.security.oidc_service import generate_pkce_pair

client = TestClient(app)

def generate_test_idp_keypair(common_name: str = "idp.test"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = x509.CertificateBuilder().subject_name(
        x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, common_name)])
    ).issuer_name(
        x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, common_name)])
    ).public_key(key.public_key()).serial_number(1).not_valid_before(
        datetime.now(timezone.utc) - timedelta(days=1)
    ).not_valid_after(
        datetime.now(timezone.utc) + timedelta(days=365)
    ).sign(key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return key_pem, cert_pem

@pytest.mark.asyncio
async def test_saml_regression_forged_unsigned_expired_replayed_wrong_audience():
    """Phase 0.1: Regression test for SAML authentication bypass and cryptographic validation.
    Proves:
    - Unsigned assertions are rejected with 401
    - Forged assertions (signed with untrusted key) are rejected with 401
    - Expired assertions (NotOnOrAfter in past) are rejected with 401
    - Replayed assertions are rejected with 401
    - Wrong audience assertions are rejected with 401
    - Cross-org email assertions are rejected with 403
    - SSO cannot issue SUPER_ADMIN session
    - Valid signed assertion succeeds
    """
    domain = f"corp_{uuid.uuid4().hex[:8]}.test"
    email = f"owner@{domain}"
    password = "StrongPassword_2026!"

    # 1. Register tenant
    reg_res = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "SAML Owner"
    })
    assert reg_res.status_code == 200
    token = reg_res.json()["access_token"]
    org_id = reg_res.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Generate IdP keypair
    key_pem, cert_pem = generate_test_idp_keypair(f"idp.{domain}")
    # Generate an alternate attacker keypair
    attacker_key_pem, attacker_cert_pem = generate_test_idp_keypair("attacker.evil.com")

    # 2. Configure SAML SSO
    idp_entity_id = f"https://idp.{domain}/saml"
    cfg_res = client.put("/api/v1/auth/sso/config", headers=headers, json={
        "provider_type": "SAML",
        "idp_entity_id": idp_entity_id,
        "idp_sso_url": f"https://idp.{domain}/sso/login",
        "idp_x509_cert": cert_pem,
        "domains": [domain],
        "enforce_sso": True,
        "jit_provisioning_enabled": True,
        "default_role": "STAFF"
    })
    assert cfg_res.status_code == 200

    # Verify domain
    client.post("/api/v1/auth/sso/verify-domain", headers=headers, json={"domain": domain})

    # Initiate SSO login to get valid relay state
    init_res = client.get(f"/api/v1/auth/sso/{org_id}/login")
    assert init_res.status_code == 200
    relay_state = init_res.json()["state"]
    in_response_to = init_res.json()["in_response_to"]
    recipient = "http://testserver/api/v1/auth/sso/saml/callback"

    # TEST A: Unsigned Assertion -> MUST RETURN 401
    unsigned_assertion = create_signed_saml_response(
        issuer=idp_entity_id,
        audience=idp_entity_id,
        recipient=recipient,
        in_response_to=in_response_to,
        email=f"user@{domain}",
        full_name="Unsigned User",
        private_key_pem=key_pem,
        cert_pem=cert_pem,
        sign=False
    )
    res_unsigned = client.post("/api/v1/auth/sso/saml/callback", json={
        "saml_response": unsigned_assertion,
        "relay_state": relay_state
    })
    assert res_unsigned.status_code == 401
    assert "verification failed" in res_unsigned.json()["detail"].lower()

    # TEST B: Forged Assertion (signed with attacker key) -> MUST RETURN 401
    forged_assertion = create_signed_saml_response(
        issuer=idp_entity_id,
        audience=idp_entity_id,
        recipient=recipient,
        in_response_to=in_response_to,
        email=f"user@{domain}",
        full_name="Forged User",
        private_key_pem=attacker_key_pem,
        cert_pem=attacker_cert_pem,
        sign=True
    )
    res_forged = client.post("/api/v1/auth/sso/saml/callback", json={
        "saml_response": forged_assertion,
        "relay_state": relay_state
    })
    assert res_forged.status_code == 401

    # TEST C: Expired Assertion -> MUST RETURN 401
    expired_assertion = create_signed_saml_response(
        issuer=idp_entity_id,
        audience=idp_entity_id,
        recipient=recipient,
        in_response_to=in_response_to,
        email=f"user@{domain}",
        full_name="Expired User",
        private_key_pem=key_pem,
        cert_pem=cert_pem,
        not_before_delta_seconds=-600,
        not_on_or_after_delta_seconds=-300,  # expired 5 minutes ago
        sign=True
    )
    res_expired = client.post("/api/v1/auth/sso/saml/callback", json={
        "saml_response": expired_assertion,
        "relay_state": relay_state
    })
    assert res_expired.status_code == 401

    # TEST D: Wrong Audience Assertion -> MUST RETURN 401
    wrong_aud_assertion = create_signed_saml_response(
        issuer=idp_entity_id,
        audience="https://different-sp.evil.com",
        recipient=recipient,
        in_response_to=in_response_to,
        email=f"user@{domain}",
        full_name="Wrong Aud User",
        private_key_pem=key_pem,
        cert_pem=cert_pem,
        sign=True
    )
    res_wrong_aud = client.post("/api/v1/auth/sso/saml/callback", json={
        "saml_response": wrong_aud_assertion,
        "relay_state": relay_state
    })
    assert res_wrong_aud.status_code == 401

    # TEST E: Cross-Org Email (User with another domain not verified for org) -> MUST RETURN 403
    cross_org_assertion = create_signed_saml_response(
        issuer=idp_entity_id,
        audience=idp_entity_id,
        recipient=recipient,
        in_response_to=in_response_to,
        email="attacker@otherdomain.com",
        full_name="Attacker",
        private_key_pem=key_pem,
        cert_pem=cert_pem,
        sign=True
    )
    res_cross_org = client.post("/api/v1/auth/sso/saml/callback", json={
        "saml_response": cross_org_assertion,
        "relay_state": relay_state
    })
    assert res_cross_org.status_code == 403
    assert "not authorized" in res_cross_org.json()["detail"].lower()

    # TEST F: Valid SAML Assertion -> MUST RETURN 200
    valid_assertion_id = f"assertion_{uuid.uuid4().hex}"
    valid_assertion = create_signed_saml_response(
        issuer=idp_entity_id,
        audience=idp_entity_id,
        recipient=recipient,
        in_response_to=in_response_to,
        email=f"legit_user@{domain}",
        full_name="Legit Employee",
        private_key_pem=key_pem,
        cert_pem=cert_pem,
        assertion_id=valid_assertion_id,
        sign=True
    )
    res_valid = client.post("/api/v1/auth/sso/saml/callback", json={
        "saml_response": valid_assertion,
        "relay_state": relay_state
    })
    assert res_valid.status_code == 200
    data = res_valid.json()
    assert data["user"]["email"] == f"legit_user@{domain}"
    assert data["user"]["organization_id"] == org_id
    assert data["user"]["role"] != "SUPER_ADMIN"
    assert "access_token" in data

    # TEST G: Replay Protection -> Re-sending the same valid assertion MUST RETURN 401
    res_replay = client.post("/api/v1/auth/sso/saml/callback", json={
        "saml_response": valid_assertion,
        "relay_state": relay_state
    })
    assert res_replay.status_code == 401
    assert "replay detected" in res_replay.json()["detail"].lower()

@pytest.mark.asyncio
async def test_oidc_authorization_flow_with_pkce_and_nonce():
    """Phase 0.1: OIDC authorization-code flow with PKCE, state, and nonce validation."""
    domain = f"corp_oidc_{uuid.uuid4().hex[:8]}.test"
    email = f"oidc_admin@{domain}"
    password = "StrongPassword_2026!"

    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "OIDC Admin"
    })
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    org_id = reg.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    client_id = f"client_{uuid.uuid4().hex[:8]}"
    client_secret = f"secret_{uuid.uuid4().hex[:16]}"
    issuer = f"https://idp.{domain}"

    # Configure OIDC
    cfg_res = client.put("/api/v1/auth/sso/config", headers=headers, json={
        "provider_type": "OIDC",
        "idp_entity_id": issuer,
        "idp_sso_url": f"{issuer}/oauth/authorize",
        "client_id": client_id,
        "client_secret": client_secret,
        "domains": [domain],
        "enforce_sso": True,
        "jit_provisioning_enabled": True,
        "default_role": "STAFF"
    })
    assert cfg_res.status_code == 200

    # Verify domain
    client.post("/api/v1/auth/sso/verify-domain", headers=headers, json={"domain": domain})

    # Initiate OIDC login
    init_res = client.get(f"/api/v1/auth/sso/{org_id}/login")
    assert init_res.status_code == 200
    init_data = init_res.json()
    assert init_data["provider"] == "OIDC"
    assert "code_challenge=" in init_data["redirect_url"]
    assert "nonce=" in init_data["redirect_url"]
    state = init_data["state"]

    # Decode state to get nonce
    from apps.api.routers.sso import decode_sso_state
    state_payload = decode_sso_state(state)
    nonce = state_payload["nonce"]

    # Generate signed ID token from IdP
    now = datetime.now(timezone.utc)
    id_token_payload = {
        "iss": issuer,
        "sub": f"usr_{uuid.uuid4().hex[:8]}",
        "aud": client_id,
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "iat": int(now.timestamp()),
        "nonce": nonce,
        "email": f"oidc_employee@{domain}",
        "name": "OIDC Employee"
    }
    signed_id_token = jwt.encode(id_token_payload, client_secret, algorithm="HS256")

    # TEST A: Valid OIDC callback
    cb_res = client.post("/api/v1/auth/sso/oidc/callback", json={
        "code": signed_id_token,
        "state": state
    })
    assert cb_res.status_code == 200
    cb_data = cb_res.json()
    assert cb_data["user"]["email"] == f"oidc_employee@{domain}"
    assert cb_data["user"]["organization_id"] == org_id
    assert "access_token" in cb_data

    # TEST B: Invalid nonce in ID token -> 401
    bad_nonce_payload = dict(id_token_payload, nonce="tampered_nonce")
    bad_nonce_token = jwt.encode(bad_nonce_payload, client_secret, algorithm="HS256")
    bad_res = client.post("/api/v1/auth/sso/oidc/callback", json={
        "code": bad_nonce_token,
        "state": state
    })
    assert bad_res.status_code == 401
    assert "nonce mismatch" in bad_res.json()["detail"].lower()
