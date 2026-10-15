import base64
import json
import pytest
import pyotp
import uuid
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.main import app
from apps.api.config import settings
from services.database.models import User, Organization, UserRole, SSOConfig, SCIMToken, UserSession, CustomRole
from apps.api.auth import hash_password, create_access_token, require_permission

client = TestClient(app, base_url="http://testserver")

@pytest.mark.asyncio
async def test_password_policy_and_breach_detection(db_session):
    """F1.4 Password complexity policy (>=12 chars, upper, lower, digit, symbol, breach check)."""
    # 1. Too short
    res = client.post("/api/v1/auth/register", json={
        "email": f"short_{uuid.uuid4().hex[:8]}@enterprise.test",
        "password": "Short1!",
        "full_name": "Short Pass"
    })
    assert res.status_code == 400
    assert "at least 12 characters" in res.json()["detail"]

    # 2. Missing uppercase
    res = client.post("/api/v1/auth/register", json={
        "email": f"noupper_{uuid.uuid4().hex[:8]}@enterprise.test",
        "password": "validpassword1!",
        "full_name": "No Upper"
    })
    assert res.status_code == 400
    assert "uppercase" in res.json()["detail"]

    # 3. Known breached password
    res = client.post("/api/v1/auth/register", json={
        "email": f"breached_{uuid.uuid4().hex[:8]}@enterprise.test",
        "password": "BreachedPassword123!",
        "full_name": "Breached Pass"
    })
    assert res.status_code == 400
    assert "breach" in res.json()["detail"].lower()

    # 4. Valid strong password passes
    email = f"strong_{uuid.uuid4().hex[:8]}@enterprise.test"
    res = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "SuperSecureP@ssw0rd2026!",
        "full_name": "Strong User",
        "organization_name": "Strong Hospitality Org"
    })
    assert res.status_code == 200
    assert "access_token" in res.json()

@pytest.mark.asyncio
async def test_totp_mfa_flow_and_recovery_codes(db_session):
    """F1.3 TOTP Enrollment, Login Challenge, Recovery Code Consumption, and Org Enforcement."""
    email = f"mfa_{uuid.uuid4().hex[:8]}@enterprise.test"
    password = "StrongPassword_MFA_2026!"
    # Register user
    reg_res = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "MFA Test User"
    })
    assert reg_res.status_code == 200
    token = reg_res.json()["access_token"]
    user_id = reg_res.json()["user"]["id"]
    org_id = reg_res.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: MFA Setup
    setup_res = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup_res.status_code == 200
    secret = setup_res.json()["secret"]
    assert "otpauth_url" in setup_res.json()

    # Step 2: MFA Enable with valid TOTP code
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()
    enable_res = client.post("/api/v1/auth/mfa/enable", headers=headers, json={
        "secret": secret,
        "code": valid_code
    })
    assert enable_res.status_code == 200
    recovery_codes = enable_res.json()["recovery_codes"]
    assert len(recovery_codes) == 10

    # Step 3: Login triggers MFA challenge ticket
    login_res = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data.get("mfa_required") is True
    mfa_ticket = login_data["mfa_ticket"]

    # Step 4: Verify with invalid code fails
    fail_verify = client.post("/api/v1/auth/mfa/verify", json={
        "mfa_ticket": mfa_ticket,
        "code": "000000"
    })
    assert fail_verify.status_code == 401

    # Step 5: Verify with valid TOTP succeeds
    curr_code = totp.now()
    succ_verify = client.post("/api/v1/auth/mfa/verify", json={
        "mfa_ticket": mfa_ticket,
        "code": curr_code
    })
    assert succ_verify.status_code == 200
    assert "access_token" in succ_verify.json()

    # Step 6: Verify with recovery code (single use)
    # Trigger another login challenge
    login_res2 = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    mfa_ticket2 = login_res2.json()["mfa_ticket"]
    used_rec_code = recovery_codes[0]

    rec_verify = client.post("/api/v1/auth/mfa/verify", json={
        "mfa_ticket": mfa_ticket2,
        "code": used_rec_code
    })
    assert rec_verify.status_code == 200
    assert "access_token" in rec_verify.json()

    # Reusing the consumed recovery code must fail
    login_res3 = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    mfa_ticket3 = login_res3.json()["mfa_ticket"]
    reuse_verify = client.post("/api/v1/auth/mfa/verify", json={
        "mfa_ticket": mfa_ticket3,
        "code": used_rec_code
    })
    assert reuse_verify.status_code == 401

@pytest.mark.asyncio
async def test_session_management_and_remote_revocation(db_session):
    """F1.4 Session listing, remote individual revoke, and revoke-all."""
    email = f"session_{uuid.uuid4().hex[:8]}@enterprise.test"
    password = "StrongPassword_SESS_2026!"
    # Register
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "Session User"
    })
    assert reg.status_code == 200
    token1 = reg.json()["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    # Simulate second session login
    log = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    assert log.status_code == 200
    token2 = log.json()["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    # List active sessions
    sess_res = client.get("/api/v1/auth/sessions", headers=headers2)
    assert sess_res.status_code == 200
    sessions = sess_res.json()
    assert len(sessions) >= 2

    # Find session 1 and terminate remotely from session 2
    session1_id = [s["id"] for s in sessions if not s["is_current"]][0]
    term_res = client.delete(f"/api/v1/auth/sessions/{session1_id}", headers=headers2)
    assert term_res.status_code == 200

    # Token 1 must now be immediately blocked (401 revoked)
    check_t1 = client.get("/api/v1/auth/me", headers=headers1)
    assert check_t1.status_code == 401
    assert "revoked" in check_t1.json()["detail"].lower()

    # Token 2 is still valid
    check_t2 = client.get("/api/v1/auth/me", headers=headers2)
    assert check_t2.status_code == 200

@pytest.mark.asyncio
async def test_organization_ip_allowlist_enforcement(db_session):
    """F1.4 Per-organization IP allowlist (matching IP succeeds, external blocked)."""
    email = f"ip_{uuid.uuid4().hex[:8]}@enterprise.test"
    password = "StrongPassword_IP_2026!"
    # Register tenant
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "IP Allowlist Admin"
    })
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    org_id = reg.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Set organization IP allowlist to strict enterprise office IP
    sec_res = client.patch(f"/api/v1/organizations/{org_id}/security-policy", headers=headers, json={
        "ip_allowlist": "198.51.100.5, 203.0.113.0/24"
    })
    assert sec_res.status_code == 200
    assert "198.51.100.5" in sec_res.json()["ip_allowlist"]

    # Request from unauthorized IP
    unauth_headers = {
        "Authorization": f"Bearer {token}",
        "X-Forwarded-For": "192.0.2.99"
    }
    blocked_res = client.get("/api/v1/auth/me", headers=unauth_headers)
    assert blocked_res.status_code == 403
    assert "not in the organization's allowlist" in blocked_res.json()["detail"]

    # Request from authorized IP
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "X-Forwarded-For": "198.51.100.5"
    }
    allowed_res = client.get("/api/v1/auth/me", headers=auth_headers)
    assert allowed_res.status_code == 200

    # Request from authorized CIDR range (203.0.113.42)
    cidr_headers = {
        "Authorization": f"Bearer {token}",
        "X-Forwarded-For": "203.0.113.42"
    }
    cidr_res = client.get("/api/v1/auth/me", headers=cidr_headers)
    assert cidr_res.status_code == 200

@pytest.mark.asyncio
async def test_sso_config_domain_verification_enforcement_and_jit(db_session):
    """F1.1 SAML/OIDC Config, Domain Verification, Enforced SSO block, and JIT Provisioning."""
    suffix = uuid.uuid4().hex[:8]
    domain = f"corp_{suffix}.test"
    email = f"sso_owner@{domain}"
    password = "StrongPassword_SSO_2026!"
    # Register org
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "SSO Owner"
    })
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    org_id = reg.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Generate test IdP certificate and private key
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography import x509
    from datetime import datetime, timezone, timedelta
    from services.security.saml_service import create_signed_saml_response

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = x509.CertificateBuilder().subject_name(
        x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, f"idp.{domain}")])
    ).issuer_name(
        x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, f"idp.{domain}")])
    ).public_key(key.public_key()).serial_number(1).not_valid_before(
        datetime.now(timezone.utc) - timedelta(days=1)
    ).not_valid_after(
        datetime.now(timezone.utc) + timedelta(days=365)
    ).sign(key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()

    # Step 1: Configure SSO with real IdP certificate
    cfg_res = client.put("/api/v1/auth/sso/config", headers=headers, json={
        "provider_type": "SAML",
        "idp_entity_id": f"https://idp.{domain}/saml",
        "idp_sso_url": f"https://idp.{domain}/sso/login",
        "idp_x509_cert": cert_pem,
        "domains": [domain],
        "enforce_sso": True,
        "jit_provisioning_enabled": True,
        "default_role": "STAFF"
    })
    assert cfg_res.status_code == 200

    # Step 2: Domain Verification
    dom_res = client.post("/api/v1/auth/sso/verify-domain", headers=headers, json={
        "domain": domain
    })
    assert dom_res.status_code == 200
    assert dom_res.json()["domain_verified"] is True

    # Step 3: Password login blocked when SSO is enforced
    pw_res = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    assert pw_res.status_code == 403
    assert "SSO_REQUIRED" in pw_res.json()["detail"]

    # Step 4: Initiate SSO
    init_res = client.get(f"/api/v1/auth/sso/{org_id}/login")
    assert init_res.status_code == 200
    relay_state = init_res.json()["state"]
    in_response_to = init_res.json()["in_response_to"]

    # Step 5: SAML Callback with Just-In-Time (JIT) provisioning for a new employee using signed XML assertion
    jit_email = f"new_jit_employee@{domain}"
    signed_assertion = create_signed_saml_response(
        issuer=f"https://idp.{domain}/saml",
        audience=f"https://idp.{domain}/saml",
        recipient="http://testserver/api/v1/auth/sso/saml/callback",
        in_response_to=in_response_to,
        email=jit_email,
        full_name="New JIT Employee",
        private_key_pem=key_pem,
        cert_pem=cert_pem
    )

    cb_res = client.post("/api/v1/auth/sso/saml/callback", json={
        "saml_response": signed_assertion,
        "relay_state": relay_state
    })
    assert cb_res.status_code == 200
    jit_data = cb_res.json()
    assert jit_data["user"]["email"] == jit_email
    assert jit_data["user"]["role"] == "STAFF"
    assert "access_token" in jit_data

@pytest.mark.asyncio
async def test_scim2_provisioning_and_immediate_deprovisioning(db_session):
    """F1.2 SCIM 2.0 Automated User Provisioning and Immediate Deprovisioning (Sessions Revoked)."""
    email = f"scim_{uuid.uuid4().hex[:8]}@enterprise.test"
    password = "StrongPassword_SCIM_2026!"
    # Register org
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "SCIM Admin"
    })
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    org_id = reg.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Generate SCIM Directory Token
    tok_res = client.post("/api/v1/scim/v2/tokens", headers=headers, json={
        "name": "Azure AD SCIM"
    })
    assert tok_res.status_code == 200
    scim_token = tok_res.json()["token"]
    scim_headers = {"Authorization": f"Bearer {scim_token}"}

    # Step 2: SCIM 2.0 User Provisioning (POST /Users)
    prov_email = f"prov_{uuid.uuid4().hex[:8]}@enterprise.test"
    prov_res = client.post("/api/v1/scim/v2/Users", headers=scim_headers, json={
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": prov_email,
        "name": {
            "formatted": "Provisioned Employee",
            "familyName": "Employee",
            "givenName": "Provisioned"
        },
        "emails": [{"value": prov_email, "primary": True}],
        "active": True
    })
    assert prov_res.status_code == 201
    scim_user_id = prov_res.json()["id"]

    # Step 3: Simulate provisioned user login / token generation
    user_access_token = create_access_token({
        "sub": scim_user_id,
        "org_id": org_id,
        "role": UserRole.STAFF.value
    })
    user_headers = {"Authorization": f"Bearer {user_access_token}"}
    check_user_active = client.get("/api/v1/auth/me", headers=user_headers)
    assert check_user_active.status_code == 200

    # Step 4: SCIM 2.0 Immediate Deprovisioning (DELETE /Users/{id})
    deprov_res = client.delete(f"/api/v1/scim/v2/Users/{scim_user_id}", headers=scim_headers)
    assert deprov_res.status_code == 204

    # Step 5: Verify deprovisioned user immediately loses all access
    blocked_check = client.get("/api/v1/auth/me", headers=user_headers)
    assert blocked_check.status_code == 401
    assert "deactivated" in blocked_check.json()["detail"].lower()

@pytest.mark.asyncio
async def test_granular_rbac_custom_roles_and_policy_enforcement(db_session):
    """F1.5 Permission-based RBAC, Custom Roles, and central require_permission enforcement."""
    email = f"rbac_{uuid.uuid4().hex[:8]}@enterprise.test"
    password = "StrongPassword_RBAC_2026!"
    # Register org
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "RBAC Admin"
    })
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    org_id = reg.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Create Custom Role with limited permissions ("property:read", "audit:read")
    role_res = client.post("/api/v1/roles", headers=headers, json={
        "name": f"Custom Auditor {uuid.uuid4().hex[:6]}",
        "description": "Read-only access to audit logs and properties",
        "permissions": ["property:read", "audit:read"]
    })
    assert role_res.status_code == 201
    custom_role_id = role_res.json()["id"]

    # Step 2: Assign custom role to a user
    assigned_user = User(
        id=f"usr_auditor_{uuid.uuid4().hex[:6]}",
        organization_id=org_id,
        email=f"auditor_{uuid.uuid4().hex[:8]}@enterprise.test",
        full_name="Auditor User",
        role=UserRole.VIEWER,
        custom_role_id=custom_role_id,
        is_active=True,
        email_verified=True,
        hashed_password=""
    )
    db_session.add(assigned_user)
    await db_session.commit()

    auditor_token = create_access_token({
        "sub": assigned_user.id,
        "org_id": org_id,
        "role": UserRole.VIEWER.value
    })
    auditor_headers = {"Authorization": f"Bearer {auditor_token}"}

    # Verify custom role has property:read -> list properties succeeds
    prop_res = client.get("/api/v1/properties", headers=auditor_headers)
    assert prop_res.status_code == 200

    # Verify custom role does NOT have property:write -> create property returns 403
    create_prop_res = client.post("/api/v1/properties", headers=auditor_headers, json={
        "organization_id": org_id,
        "name": "Unauthorized Property"
    })
    assert create_prop_res.status_code == 403

@pytest.mark.asyncio
async def test_platform_support_impersonation_time_box_and_banner(db_session):
    """F1.6 Customer-approved, time-boxed Platform Support Impersonation with banner header."""
    # 1. Register Customer Tenant
    email = f"cust_{uuid.uuid4().hex[:8]}@enterprise.test"
    cust_res = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "StrongPassword_CUST_2026!",
        "full_name": "Customer Admin"
    })
    assert cust_res.status_code == 200
    cust_token = cust_res.json()["access_token"]
    cust_org_id = cust_res.json()["user"]["organization_id"]
    cust_headers = {"Authorization": f"Bearer {cust_token}"}

    # 2. Super Admin User (using seeded platform superadmin from conftest)
    admin_token = create_access_token({
        "sub": "usr_superadmin",
        "org_id": "org_azure_group",
        "role": UserRole.SUPER_ADMIN.value
    })
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Super Admin attempts impersonation BEFORE customer approval -> Rejected 403
    unauth_imp = client.post(f"/api/v1/platform/support/impersonate/{cust_org_id}", headers=admin_headers)
    assert unauth_imp.status_code == 403
    assert "not granted" in unauth_imp.json()["detail"].lower()

    # 4. Customer Admin grants support access for 2 hours
    grant_res = client.post(
        f"/api/v1/organizations/{cust_org_id}/support-access/grant",
        headers=cust_headers,
        json={"duration_hours": 2}
    )
    assert grant_res.status_code == 200

    # 5. Super Admin initiates support impersonation -> Succeeds
    imp_res = client.post(f"/api/v1/platform/support/impersonate/{cust_org_id}", headers=admin_headers)
    assert imp_res.status_code == 200
    imp_token = imp_res.json()["impersonation_token"]
    imp_headers = {"Authorization": f"Bearer {imp_token}"}

    # 6. Request made with impersonation token receives X-Support-Impersonation: Active banner header
    check_imp = client.get(f"/api/v1/organizations/{cust_org_id}", headers=imp_headers)
    assert check_imp.status_code == 200
    assert check_imp.headers.get("X-Support-Impersonation") == "Active"

    # 7. Customer Admin revokes support access
    rev_res = client.post(f"/api/v1/organizations/{cust_org_id}/support-access/revoke", headers=cust_headers)
    assert rev_res.status_code == 200

    # 8. Impersonation token immediately blocked following customer revocation
    rev_check = client.get(f"/api/v1/organizations/{cust_org_id}", headers=imp_headers)
    assert rev_check.status_code == 403
    assert "expired" in rev_check.json()["detail"].lower() or "not granted" in rev_check.json()["detail"].lower()
