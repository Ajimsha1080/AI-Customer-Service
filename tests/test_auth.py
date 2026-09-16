import pytest
from datetime import timedelta
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_access_token, decode_refresh_token
)

@pytest.mark.asyncio
async def test_argon2_password_hashing():
    """Verify password hashing with Argon2id and correct verification behavior."""
    raw_password = "SecretPassword123!"
    hashed = hash_password(raw_password)

    assert hashed != raw_password
    assert hashed.startswith("$argon2id$")
    assert verify_password(raw_password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False

@pytest.mark.asyncio
async def test_jwt_token_issuance_and_decoding():
    """Verify JWT access and refresh token encoding, decoding, and type validation."""
    data = {"sub": "usr_test123", "org_id": "org_test", "role": "ORGANIZATION_ADMIN"}
    
    access_token = create_access_token(data)
    decoded_access = decode_access_token(access_token)
    assert decoded_access["sub"] == "usr_test123"
    assert decoded_access["token_type"] == "access"

    refresh_token = create_refresh_token({"sub": "usr_test123"})
    decoded_refresh = decode_refresh_token(refresh_token)
    assert decoded_refresh["sub"] == "usr_test123"
    assert decoded_refresh["token_type"] == "refresh"

@pytest.mark.asyncio
async def test_auth_full_api_flow():
    """Verify registration, login, refresh token, and /me endpoint flow via API."""
    import time
    unique_email = f"newadmin_{int(time.time()*1000)}@hospitalitygroup.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Register a new user
        reg_payload = {
            "email": unique_email,
            "password": "SecurePassword123!",
            "full_name": "New Admin User",
            "organization_name": "New Hospitality Group",
            "organization_slug": f"new-hospitality-group-{int(time.time()*1000)}"
        }
        reg_res = await ac.post("/api/v1/auth/register", json=reg_payload)
        assert reg_res.status_code == 200
        reg_data = reg_res.json()
        assert "access_token" in reg_data
        assert "refresh_token" in reg_data
        assert reg_data["user"]["email"] == unique_email

        # 2. Login with registered credentials
        login_payload = {
            "email": unique_email,
            "password": "SecurePassword123!"
        }
        login_res = await ac.post("/api/v1/auth/login", json=login_payload)
        assert login_res.status_code == 200
        login_data = login_res.json()
        access_token = login_data["access_token"]
        refresh_token = login_data["refresh_token"]

        # 3. Access GET /api/v1/auth/me with Bearer token
        headers = {"Authorization": f"Bearer {access_token}"}
        me_res = await ac.get("/api/v1/auth/me", headers=headers)
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["email"] == unique_email
        assert me_data["role"] == "ORGANIZATION_ADMIN"

        # 4. Refresh access token using refresh_token
        ref_res = await ac.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert ref_res.status_code == 200
        ref_data = ref_res.json()
        assert "access_token" in ref_data

@pytest.mark.asyncio
async def test_invalid_login_credentials_privacy():
    """Verify login with wrong password returns 401 without exposing email existence."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Existing email with wrong password
        res_wrong_pw = await ac.post("/api/v1/auth/login", json={"email": "admin@azurehostel.com", "password": "WrongPassword!"})
        assert res_wrong_pw.status_code == 401
        assert res_wrong_pw.json()["detail"] == "Invalid credentials"

        # Non-existent email
        res_non_exist = await ac.post("/api/v1/auth/login", json={"email": "nonexistent@domain.com", "password": "WrongPassword!"})
        assert res_non_exist.status_code == 401
        assert res_non_exist.json()["detail"] == "Invalid credentials"

@pytest.mark.asyncio
async def test_logout_and_token_revocation():
    """Verify /api/v1/auth/logout invalidates refresh token."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        login_res = await ac.post("/api/v1/auth/login", json={"email": "admin@azurehostel.com", "password": "admin123"})
        assert login_res.status_code == 200
        refresh_token = login_res.json()["refresh_token"]

        # Logout
        logout_res = await ac.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
        assert logout_res.status_code == 200

        # Attempt to use revoked refresh token -> 401
        ref_res = await ac.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert ref_res.status_code == 401
        assert "revoked" in ref_res.json()["detail"].lower() or "invalid" in ref_res.json()["detail"].lower()

@pytest.mark.asyncio
async def test_expired_token_rejection():
    """Verify expired JWT token returns 401 Unauthorized."""
    expired_token = create_access_token({"sub": "usr_demo123"}, expires_delta=timedelta(seconds=-10))
    headers = {"Authorization": f"Bearer {expired_token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/auth/me", headers=headers)
        assert res.status_code == 401
