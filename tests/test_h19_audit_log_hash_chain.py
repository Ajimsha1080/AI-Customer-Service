import pytest
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from apps.api.main import app
from apps.api.auth import create_access_token, hash_password
from services.database.models import User, Organization, UserRole, UserSession, AuditLog
from services.database.audit import (
    record_audit_log_async, verify_audit_log_chain,
    compute_entry_hash, GENESIS_HASH
)

@pytest.mark.asyncio
async def test_h19_audit_log_hash_chain_hmac_and_tamper_detection(db_session):
    """H19:
    - Audit log chain uses tamper-evident HMAC-SHA256 hash chaining covering all fields including prev_hash.
    - Key rotation is supported.
    - Verification endpoint confirms valid chain integrity.
    - Tampering with an entry's content or breaking the link is detected and alerts.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(
            id=org_id,
            name="Audit Integrity Hotel",
            slug=f"audit-hotel-{uuid.uuid4().hex[:6]}",
            status="active"
        )
        db_session.add(org)

        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"audit_owner_{uuid.uuid4().hex[:6]}@audithotel.com",
            full_name="Audit Owner",
            hashed_password=hash_password("password123"),
            role=UserRole.OWNER,
            is_active=True,
            email_verified=True
        )
        db_session.add(user)
        await db_session.commit()

        user_token = create_access_token({"sub": user.id, "email": user.email, "role": "OWNER", "org_id": org_id, "is_login": True})
        session = UserSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            organization_id=org_id,
            session_token_hash=hashlib.sha256(user_token.encode()).hexdigest(),
            device_name="Test Device",
            ip_address="127.0.0.1",
            user_agent="pytest",
            last_activity_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_revoked=False
        )
        db_session.add(session)
        await db_session.commit()

        headers = {"Authorization": f"Bearer {user_token}"}

        # 1. Record a sequence of hash-chained audit logs
        log1 = await record_audit_log_async(
            org_id=org_id,
            user_id=user.id,
            action="ORGANIZATION_INITIALIZED",
            target_type="organization",
            target_id=org_id,
            details={"tier": "enterprise"},
            db=db_session
        )
        assert log1.prev_hash == GENESIS_HASH
        assert log1.hash.startswith("v1:")

        log2 = await record_audit_log_async(
            org_id=org_id,
            user_id=user.id,
            action="POLICY_UPDATED",
            target_type="organization",
            target_id=org_id,
            details={"mfa_enforced": True},
            db=db_session
        )
        assert log2.prev_hash == log1.hash
        assert log2.hash.startswith("v1:")

        log3 = await record_audit_log_async(
            org_id=org_id,
            user_id=user.id,
            action="MEMBER_INVITED",
            target_type="invitation",
            target_id="invite_123",
            details={"role": "STAFF", "email": "staff@audithotel.com"},
            db=db_session
        )
        assert log3.prev_hash == log2.hash
        assert log3.hash.startswith("v1:")

        await db_session.commit()

        # 2. Verify intact chain via endpoint
        res_verify_intact = await ac.post(f"/api/v1/organizations/{org_id}/audit-logs/verify", headers=headers)
        assert res_verify_intact.status_code == 200
        data_intact = res_verify_intact.json()
        assert data_intact["status"] == "VALID"
        assert data_intact["verified_count"] == 3

        # 3. Tamper with log2 details (e.g. attacker changes mfa_enforced to False directly in DB)
        log2.details_json = {"mfa_enforced": False}
        await db_session.commit()

        # Verify endpoint detects content tampering
        res_verify_tampered = await ac.post(f"/api/v1/organizations/{org_id}/audit-logs/verify", headers=headers)
        assert res_verify_tampered.status_code == 200
        data_tampered = res_verify_tampered.json()
        assert data_tampered["status"] == "COMPROMISED"
        assert "Tampered entry detected" in data_tampered["error"]
        assert data_tampered["verified_count"] == 1  # Fails at index 1 (log2)

        # Restore log2 details and break chain link by modifying prev_hash on log3
        log2.details_json = {"mfa_enforced": True}
        log3.prev_hash = "v1:fake_broken_previous_hash_00000000000000000000000000000000"
        await db_session.commit()

        # Verify endpoint detects broken chain link
        res_verify_broken = await ac.post(f"/api/v1/organizations/{org_id}/audit-logs/verify", headers=headers)
        assert res_verify_broken.status_code == 200
        data_broken = res_verify_broken.json()
        assert data_broken["status"] == "COMPROMISED"
        assert "Broken chain link" in data_broken["error"]
