import pytest
import io
import json
import zipfile
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from apps.api.main import app
from apps.api.auth import create_access_token
from services.database.session import AsyncSessionLocal
from services.database.models import (
    User, Organization, Property, Agent, Conversation, Message, Reservation,
    AuditLog, UserRole, UserSession
)
from services.operations.retention import (
    anonymize_analytics_pii,
    generate_gdpr_export_zip,
    retention_service,
    GUEST_CHAT_RETENTION_DAYS,
    AUDIT_LOG_RETENTION_DAYS,
    DELETED_TENANT_HARD_DELETE_DAYS
)

def test_p9_retention_policy_constants():
    assert GUEST_CHAT_RETENTION_DAYS == 90, "Guest chat logs retention policy must be 90 days"
    assert AUDIT_LOG_RETENTION_DAYS == 365, "Audit log retention policy must be 365 days"
    assert DELETED_TENANT_HARD_DELETE_DAYS == 30, "Deleted tenant hard delete policy must be 30 days"

def test_p9_anonymize_analytics_pii():
    raw_event = {
        "event": "guest_inquiry",
        "email": "sarah.connor@cyberdyne.com",
        "phone": "+1 (555) 234-5678",
        "client_ip": "198.51.100.42",
        "nested": {
            "contact": "Reach me at john.doe@domain.org or +44 7911 123456"
        }
    }
    anonymized = anonymize_analytics_pii(raw_event)
    assert "[REDACTED_EMAIL]" in anonymized["email"]
    assert "[REDACTED_PHONE]" in anonymized["phone"]
    assert "[REDACTED_IP]" in anonymized["client_ip"]
    assert "[REDACTED_EMAIL]" in anonymized["nested"]["contact"]
    assert "[REDACTED_PHONE]" in anonymized["nested"]["contact"]
    assert "sarah.connor" not in str(anonymized)

def test_p9_generate_gdpr_export_zip():
    sample_data = {
        "conversations": [{"id": "conv_1", "channel": "web"}],
        "messages": [{"id": "msg_1", "content": "Hello concierge"}],
        "reservations": [{"id": "res_1", "customer_name": "Test Guest"}]
    }
    zip_bytes = generate_gdpr_export_zip(sample_data)
    assert len(zip_bytes) > 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "conversations.json" in names
        assert "messages.json" in names
        assert "reservations.json" in names

        conv_content = json.loads(zf.read("conversations.json"))
        assert conv_content[0]["id"] == "conv_1"

@pytest.mark.asyncio
async def test_p9_retention_purge_and_gdpr_endpoints():
    org_id = f"org_p9_{uuid.uuid4().hex[:6]}"
    prop_id = f"prop_p9_{uuid.uuid4().hex[:6]}"
    agent_id = f"agt_p9_{uuid.uuid4().hex[:6]}"
    user_id = f"user_p9_{uuid.uuid4().hex[:6]}"
    guest_email = f"guest_{uuid.uuid4().hex[:6]}@example.com"

    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=100)  # > 90 days old

    async with AsyncSessionLocal() as session:
        org = Organization(id=org_id, name="P9 Hotel", slug=f"p9-{uuid.uuid4().hex[:6]}", status="ACTIVE")
        session.add(org)

        prop = Property(
            id=prop_id,
            organization_id=org_id,
            name="P9 Property",
            currency="USD",
            timezone="UTC"
        )
        session.add(prop)

        agent = Agent(
            id=agent_id,
            organization_id=org_id,
            property_id=prop_id,
            name="P9 Concierge",
            agent_type="FRONT_DESK",
            status="ACTIVE"
        )
        session.add(agent)

        user = User(
            id=user_id,
            organization_id=org_id,
            email=f"{user_id}@test.com",
            full_name="Compliance Officer",
            hashed_password="pw",
            role=UserRole.OWNER,
            is_active=True,
            email_verified=True
        )
        session.add(user)

        # 1. Old conversation (> 90 days)
        old_conv = Conversation(
            id=f"conv_old_{uuid.uuid4().hex[:6]}",
            organization_id=org_id,
            property_id=prop_id,
            agent_id=agent_id,
            channel="web",
            channel_user_id=guest_email,
            created_at=old_date
        )
        session.add(old_conv)

        # 2. Recent conversation
        recent_conv = Conversation(
            id=f"conv_recent_{uuid.uuid4().hex[:6]}",
            organization_id=org_id,
            property_id=prop_id,
            agent_id=agent_id,
            channel="web",
            channel_user_id=guest_email,
            created_at=now
        )
        session.add(recent_conv)

        # 3. Reservation with PII
        resv = Reservation(
            id=f"resv_{uuid.uuid4().hex[:6]}",
            organization_id=org_id,
            property_id=prop_id,
            customer_name="Alice Smith",
            customer_email=guest_email,
            check_in=(now + timedelta(days=5)).date().isoformat(),
            check_out=(now + timedelta(days=7)).date().isoformat(),
            total_amount=250.0,
            status="CONFIRMED"
        )
        session.add(resv)
        await session.commit()

    token = create_access_token(data={"sub": user_id, "org": org_id, "role": "owner"})
    async with AsyncSessionLocal() as session:
        sess = UserSession(
            id=f"sess_p9_{uuid.uuid4().hex[:6]}",
            user_id=user_id,
            organization_id=org_id,
            session_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            is_revoked=False,
            expires_at=now + timedelta(hours=2)
        )
        session.add(sess)
        await session.commit()

    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test GDPR ZIP export endpoint
        res_zip = await client.post(
            "/api/v1/compliance/export/zip",
            json={"guest_identifier": guest_email},
            headers=headers
        )
        assert res_zip.status_code == 200
        assert res_zip.headers["content-type"] == "application/zip"
        assert len(res_zip.content) > 0

        with zipfile.ZipFile(io.BytesIO(res_zip.content)) as zf:
            assert "conversations.json" in zf.namelist()
            assert "reservations.json" in zf.namelist()

        # 2. Test GDPR Right to be Forgotten (/erase)
        res_erase = await client.post(
            "/api/v1/compliance/erase",
            json={"guest_identifier": guest_email, "confirmation": True},
            headers=headers
        )
        assert res_erase.status_code == 200

        # Verify reservation customer PII was redacted
        async with AsyncSessionLocal() as session:
            stmt = select(Reservation).where(Reservation.organization_id == org_id)
            res = await session.execute(stmt)
            r = res.scalar_one_or_none()
            assert r.customer_name == "[ERASED GUEST]"
            assert r.customer_email == "erased@compliance.invalid"

        # 3. Test automated 90-day retention purge with separate un-erased records
        other_guest = f"other_{uuid.uuid4().hex[:6]}@example.com"
        old_other_conv_id = f"conv_old_other_{uuid.uuid4().hex[:6]}"
        recent_other_conv_id = f"conv_rec_other_{uuid.uuid4().hex[:6]}"
        async with AsyncSessionLocal() as session:
            conv_expired = Conversation(
                id=old_other_conv_id,
                organization_id=org_id,
                property_id=prop_id,
                agent_id=agent_id,
                channel="web",
                channel_user_id=other_guest,
                created_at=old_date
            )
            conv_fresh = Conversation(
                id=recent_other_conv_id,
                organization_id=org_id,
                property_id=prop_id,
                agent_id=agent_id,
                channel="web",
                channel_user_id=other_guest,
                created_at=now
            )
            session.add_all([conv_expired, conv_fresh])
            await session.commit()

        async with AsyncSessionLocal() as session:
            purge_res = await retention_service.purge_guest_chat_logs(session, org_id=org_id)
            await session.commit()
            assert purge_res["purged_conversations"] >= 1

            # Confirm expired conv is gone, fresh conv remains
            res_c = await session.execute(select(Conversation).where(Conversation.organization_id == org_id))
            remaining_ids = [c.id for c in res_c.scalars().all()]
            assert old_other_conv_id not in remaining_ids
            assert recent_other_conv_id in remaining_ids
