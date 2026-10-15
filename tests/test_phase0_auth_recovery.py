import uuid
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from jose import jwt

from apps.api.main import app
from apps.api.config import settings
from apps.api.auth import create_access_token

client = TestClient(app)

@pytest.mark.asyncio
async def test_forgot_password_anti_enumeration_and_timing_safety():
    """Phase 0.2: forgot_password must not raise NameError, and must return the identical response
    for unknown emails as registered emails (no user enumeration).
    """
    domain = f"corp_{uuid.uuid4().hex[:8]}.test"
    known_email = f"user@{domain}"
    unknown_email = f"nonexistent_{uuid.uuid4().hex[:8]}@{domain}"

    # Register user
    reg = client.post("/api/v1/auth/register", json={
        "email": known_email,
        "password": "StrongPassword_2026!",
        "full_name": "Known User"
    })
    assert reg.status_code == 200

    # Call forgot_password for registered email
    res_known = client.post("/api/v1/auth/forgot-password", json={"email": known_email})
    assert res_known.status_code == 200
    assert "If this email exists in our system" in res_known.json()["message"]

    # Call forgot_password for non-existent email
    res_unknown = client.post("/api/v1/auth/forgot-password", json={"email": unknown_email})
    assert res_unknown.status_code == 200
    assert res_unknown.json()["message"] == res_known.json()["message"]

@pytest.mark.asyncio
async def test_password_reset_flow_end_to_end_and_single_use():
    """Phase 0.2: Password reset works end to end, updates hash, and enforces single-use token invalidation."""
    email = f"reset_{uuid.uuid4().hex[:8]}@example.com"
    old_password = "OldPassword_12345!"
    new_password = "NewStrongPassword_67890!"

    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": old_password,
        "full_name": "Reset Test User"
    })
    assert reg.status_code == 200
    user_id = reg.json()["user"]["id"]

    # Issue password reset token
    reset_token = create_access_token(
        {"sub": user_id, "email": email, "scope": "password_reset", "jti": uuid.uuid4().hex},
        expires_delta=timedelta(hours=1)
    )

    # 1. Reset password with token
    res_reset = client.post("/api/v1/auth/reset-password", json={
        "token": reset_token,
        "new_password": new_password
    })
    assert res_reset.status_code == 200
    assert "successfully reset" in res_reset.json()["message"].lower()

    # 2. Verify login with old password fails
    old_login = client.post("/api/v1/auth/login", json={"email": email, "password": old_password})
    assert old_login.status_code == 401

    # 3. Verify login with new password succeeds
    new_login = client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    assert new_login.status_code == 200
    assert "access_token" in new_login.json()

    # 4. SINGLE-USE TEST: Reusing the same reset token MUST fail with 400
    res_reuse = client.post("/api/v1/auth/reset-password", json={
        "token": reset_token,
        "new_password": "YetAnotherPassword_123!"
    })
    assert res_reuse.status_code == 400
    assert "already been used" in res_reuse.json()["detail"].lower()

@pytest.mark.asyncio
async def test_password_reset_expired_token_rejected():
    """Phase 0.2: Expired password reset tokens must return 400."""
    email = f"exp_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "InitialPassword_12345!",
        "full_name": "Expired Reset User"
    })
    assert reg.status_code == 200
    user_id = reg.json()["user"]["id"]

    # Generate expired token
    expired_token = create_access_token(
        {"sub": user_id, "email": email, "scope": "password_reset", "jti": uuid.uuid4().hex},
        expires_delta=timedelta(seconds=-10)
    )

    res = client.post("/api/v1/auth/reset-password", json={
        "token": expired_token,
        "new_password": "NewValidPassword_12345!"
    })
    assert res.status_code == 400
    assert "invalid or expired" in res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_email_verification_flow_and_single_use():
    """Phase 0.2: Email verification flow works and enforces single-use token revocation."""
    email = f"verify_{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "Password_Verify_12345!",
        "full_name": "Verify User"
    })
    assert reg.status_code == 200
    user_id = reg.json()["user"]["id"]

    # Issue email verification token
    verify_token = create_access_token(
        {"sub": user_id, "email": email, "scope": "email_verification"},
        expires_delta=timedelta(hours=24)
    )

    # 1. Verify email succeeds
    res_ver = client.post("/api/v1/auth/verify-email", json={"token": verify_token})
    assert res_ver.status_code == 200
    assert "verified successfully" in res_ver.json()["message"].lower()

    # 2. SINGLE-USE TEST: Reusing verification token MUST return 400
    res_reuse = client.post("/api/v1/auth/verify-email", json={"token": verify_token})
    assert res_reuse.status_code == 400
    assert "already been used" in res_reuse.json()["detail"].lower()
