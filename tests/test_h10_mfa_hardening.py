import pytest
import uuid
import time
import pyotp
from httpx import AsyncClient, ASGITransport
from passlib.hash import argon2

from apps.api.main import app
from apps.api.auth import hash_password, create_access_token
from services.database.models import User, Organization, UserRole
from services.security.encryption import encrypt_value

@pytest.mark.asyncio
async def test_h10_recovery_codes_80_bits_argon2_hashed(db_session):
    """H10: Recovery codes have >= 80 bits of entropy and are stored with Argon2id hashes."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="MFA Hardened Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        pwd = "SecureUserPassword123!"
        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"mfa_h10_{uuid.uuid4().hex[:6]}@hotel.com",
            full_name="MFA Admin",
            hashed_password=hash_password(pwd),
            role=UserRole.ADMIN,
            is_active=True,
            mfa_enabled=False
        )
        db_session.add(org)
        db_session.add(user)
        await db_session.commit()

        token = create_access_token({"sub": user.id, "org_id": org_id, "role": "ADMIN"})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Setup initiates enrollment and stores pending secret server-side
        setup_resp = await ac.post("/api/v1/auth/mfa/setup", headers=headers)
        assert setup_resp.status_code == 200
        secret = setup_resp.json()["secret"]

        # 2. Enable MFA with re-auth password and valid TOTP code
        totp = pyotp.TOTP(secret)
        code = totp.now()
        enable_resp = await ac.post("/api/v1/auth/mfa/enable", headers=headers, json={
            "password": pwd,
            "code": code
        })
        assert enable_resp.status_code == 200
        recovery_codes = enable_resp.json()["recovery_codes"]
        assert len(recovery_codes) == 10

        # Check >= 80 bits entropy: 20 hex chars = 10 bytes = 80 bits
        for r_code in recovery_codes:
            clean_code = r_code.replace("-", "")
            assert len(clean_code) >= 20

        # Check DB stores Argon2 hashes, not plain recovery codes
        await db_session.refresh(user)
        assert user.mfa_enabled is True
        for h in user.mfa_recovery_codes:
            assert h.startswith("$argon2id$")

@pytest.mark.asyncio
async def test_h10_lock_ticket_after_5_failures_and_rate_limit(db_session):
    """H10: Lock MFA ticket after 5 failures with HTTP 429 Too Many Requests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="MFA Lock Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        pwd = "Password123!"
        totp_secret = pyotp.random_base32()
        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"mfa_lock_{uuid.uuid4().hex[:6]}@hotel.com",
            full_name="Locked User",
            hashed_password=hash_password(pwd),
            role=UserRole.STAFF,
            is_active=True,
            mfa_enabled=True,
            mfa_secret=encrypt_value(totp_secret, org_id=org_id)
        )
        db_session.add(org)
        db_session.add(user)
        await db_session.commit()

        # Login generates MFA challenge ticket
        login_resp = await ac.post("/api/v1/auth/login", json={"email": user.email, "password": pwd})
        assert login_resp.status_code == 200
        mfa_ticket = login_resp.json()["mfa_ticket"]

        # 4 failed verification attempts return 401
        for _ in range(4):
            fail_resp = await ac.post("/api/v1/auth/mfa/verify", json={
                "mfa_ticket": mfa_ticket,
                "code": "000000"
            })
            assert fail_resp.status_code == 401

        # 5th failed verification attempt locks the ticket (429)
        lock_resp = await ac.post("/api/v1/auth/mfa/verify", json={
            "mfa_ticket": mfa_ticket,
            "code": "000000"
        })
        assert lock_resp.status_code == 429
        assert "locked" in lock_resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_h10_block_totp_code_reuse(db_session):
    """H10: Block TOTP code reuse within the time window."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="TOTP Reuse Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        pwd = "Password123!"
        totp_secret = pyotp.random_base32()
        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"mfa_reuse_{uuid.uuid4().hex[:6]}@hotel.com",
            full_name="Reuse User",
            hashed_password=hash_password(pwd),
            role=UserRole.STAFF,
            is_active=True,
            mfa_enabled=True,
            mfa_secret=encrypt_value(totp_secret, org_id=org_id)
        )
        db_session.add(org)
        db_session.add(user)
        await db_session.commit()

        login_resp = await ac.post("/api/v1/auth/login", json={"email": user.email, "password": pwd})
        assert login_resp.status_code == 200
        mfa_ticket = login_resp.json()["mfa_ticket"]

        totp = pyotp.TOTP(totp_secret)
        valid_code = totp.now()

        # First verification succeeds
        v1_resp = await ac.post("/api/v1/auth/mfa/verify", json={
            "mfa_ticket": mfa_ticket,
            "code": valid_code
        })
        assert v1_resp.status_code == 200

        # Login again to get new ticket
        login_resp2 = await ac.post("/api/v1/auth/login", json={"email": user.email, "password": pwd})
        mfa_ticket2 = login_resp2.json()["mfa_ticket"]

        # Reusing the exact same TOTP code is rejected
        v2_resp = await ac.post("/api/v1/auth/mfa/verify", json={
            "mfa_ticket": mfa_ticket2,
            "code": valid_code
        })
        assert v2_resp.status_code == 400
        assert "already been used" in v2_resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_h10_super_admin_mfa_mandatory_and_cannot_be_disabled(db_session):
    """H10: MFA is strictly mandatory for SUPER_ADMIN and cannot be disabled."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="SuperAdmin MFA Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        pwd = "SuperSecretPassword123!"
        totp_secret = pyotp.random_base32()
        super_admin = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"superadmin_{uuid.uuid4().hex[:6]}@platform.local",
            full_name="Platform SuperAdmin",
            hashed_password=hash_password(pwd),
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            mfa_enabled=True,
            mfa_secret=encrypt_value(totp_secret, org_id=org_id)
        )
        db_session.add(org)
        db_session.add(super_admin)
        await db_session.commit()

        # Super admin login ALWAYS requires MFA challenge
        login_resp = await ac.post("/api/v1/auth/login", json={"email": super_admin.email, "password": pwd})
        assert login_resp.status_code == 200
        assert login_resp.json().get("mfa_required") is True

        # Super admin attempting to disable MFA is strictly rejected with 403
        token = create_access_token({"sub": super_admin.id, "org_id": org_id, "role": "SUPER_ADMIN"})
        headers = {"Authorization": f"Bearer {token}"}

        totp = pyotp.TOTP(totp_secret)
        disable_resp = await ac.post("/api/v1/auth/mfa/disable", headers=headers, json={
            "password": pwd,
            "code": totp.now()
        })
        assert disable_resp.status_code == 403
        assert "mandatory for super admin" in disable_resp.json()["detail"].lower()
