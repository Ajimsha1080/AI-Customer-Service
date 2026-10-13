import pytest
import uuid
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.auth import create_access_token
from services.database.models import User, UserRole, Organization, Subscription, Invitation
from services.billing.entitlements import entitlements_service

client = TestClient(app)

def _get_owner_headers():
    token = create_access_token(data={
        "sub": "usr_admin_01",
        "role": UserRole.OWNER.value,
        "organization_id": "org_azure_group"
    })
    return {"Authorization": f"Bearer {token}"}

@pytest.mark.asyncio
async def test_unified_entitlements_and_feature_gating(db_session):
    """F6.1 Unified entitlements service: feature gates (SSO, BYOK, Voice) and plan tiers."""
    org_id = f"org_ent_{uuid.uuid4().hex[:6]}"
    org = Organization(id=org_id, name="Entitlement Org", slug=f"ent-{uuid.uuid4().hex[:4]}")
    db_session.add(org)

    # 1. STARTER Plan: Voice and SSO SAML must be disabled
    sub_starter = Subscription(
        id=f"sub_{uuid.uuid4().hex[:8]}",
        organization_id=org_id,
        plan_name="STARTER",
        status="ACTIVE"
    )
    db_session.add(sub_starter)
    await db_session.commit()

    assert await entitlements_service.can_access_feature(org_id, "voice_enabled", db=db_session) is False
    assert await entitlements_service.can_access_feature(org_id, "sso_saml", db=db_session) is False

    # 2. Upgrade to ENTERPRISE: Voice, SSO SAML, and BYOK enabled
    sub_starter.plan_name = "ENTERPRISE"
    await db_session.commit()

    assert await entitlements_service.can_access_feature(org_id, "voice_enabled", db=db_session) is True
    assert await entitlements_service.can_access_feature(org_id, "sso_saml", db=db_session) is True
    assert await entitlements_service.can_access_feature(org_id, "byok_encryption", db=db_session) is True


@pytest.mark.asyncio
async def test_seat_based_licensing_and_seat_reclaim(db_session):
    """F6.2 Seat licensing: max seat enforcement across active users + pending invites, and seat reclaim."""
    org_id = f"org_seats_{uuid.uuid4().hex[:6]}"
    org = Organization(id=org_id, name="Seat Org", slug=f"seat-{uuid.uuid4().hex[:4]}")
    db_session.add(org)

    # STARTER Plan allows exactly 2 seats
    sub = Subscription(
        id=f"sub_{uuid.uuid4().hex[:8]}",
        organization_id=org_id,
        plan_name="STARTER",
        status="ACTIVE"
    )
    db_session.add(sub)

    # Seat 1: Owner user
    u1 = User(
        id=f"u_{uuid.uuid4().hex[:8]}",
        organization_id=org_id,
        email=f"owner_{uuid.uuid4().hex[:4]}@seats.test",
        hashed_password="hash",
        full_name="Owner User",
        role=UserRole.OWNER.value,
        is_active=True
    )
    db_session.add(u1)
    await db_session.commit()

    # 1 seat allocated out of 2 -> 1 seat available
    has_seat, alloc, max_s = await entitlements_service.check_seat_availability(org_id, db_session)
    assert has_seat is True
    assert alloc == 1
    assert max_s == 2

    # Seat 2: Pending invitation
    inv = Invitation(
        id=f"inv_{uuid.uuid4().hex[:8]}",
        organization_id=org_id,
        email="colleague@seats.test",
        token=uuid.uuid4().hex,
        invited_by_user_id=u1.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7)
    )
    db_session.add(inv)
    await db_session.commit()

    # 2 seats allocated out of 2 -> 0 seats available
    has_seat2, alloc2, max_s2 = await entitlements_service.check_seat_availability(org_id, db_session)
    assert has_seat2 is False
    assert alloc2 == 2
    assert max_s2 == 2

    # Seat Reclaim: Revoke/delete pending invitation -> seat freed immediately
    await db_session.delete(inv)
    await db_session.commit()

    has_seat3, alloc3, max_s3 = await entitlements_service.check_seat_availability(org_id, db_session)
    assert has_seat3 is True
    assert alloc3 == 1


def test_spend_alerts_and_dunning_grace_period():
    """F6.3 Proactive spend alert tiers (80%/100%/120%) and dunning soft degrade vs hard suspend."""
    # 1. Spend Alerts
    limit = 1000
    assert entitlements_service.calculate_spend_alert_level(750, limit) is None
    assert entitlements_service.calculate_spend_alert_level(820, limit) == "NOTICE_80_PERCENT_APPROACHING"
    assert entitlements_service.calculate_spend_alert_level(1005, limit) == "WARNING_100_PERCENT_REACHED"
    assert entitlements_service.calculate_spend_alert_level(1250, limit) == "CRITICAL_120_PERCENT_EXCEEDED"

    # 2. Dunning Lifecycle:
    # A: Active healthy subscription
    d_healthy = entitlements_service.evaluate_dunning_status("active", None)
    assert d_healthy["status"] == "HEALTHY"
    assert d_healthy["access_mode"] == "FULL_ACCESS"

    # B: Payment failed, but within 7-day grace period -> Soft degrade (guest AI continues)
    now = datetime.now(timezone.utc)
    grace_future = now + timedelta(days=4)
    d_grace = entitlements_service.evaluate_dunning_status("past_due", grace_future)
    assert d_grace["status"] == "IN_DUNNING_GRACE_PERIOD"
    assert d_grace["access_mode"] == "SOFT_DEGRADE_GUEST_ACTIVE"

    # C: Grace period expired (> 7 days) -> Hard suspend
    grace_past = now - timedelta(days=2)
    d_suspended = entitlements_service.evaluate_dunning_status("past_due", grace_past)
    assert d_suspended["status"] == "DUNNING_GRACE_PERIOD_EXPIRED"
    assert d_suspended["access_mode"] == "HARD_SUSPEND"


def test_billing_entitlements_and_dunning_api():
    """F6.4 Billing API endpoints: /api/v1/billing/entitlements and /api/v1/billing/dunning-status."""
    headers = _get_owner_headers()

    # 1. Entitlements status endpoint
    ent_res = client.get("/api/v1/billing/entitlements", headers=headers)
    assert ent_res.status_code == 200
    ent_data = ent_res.json()
    assert "plan" in ent_data
    assert "seats" in ent_data
    assert "has_available_seat" in ent_data["seats"]
    assert "limits" in ent_data
    assert "features" in ent_data

    # 2. Dunning status endpoint
    dun_res = client.get("/api/v1/billing/dunning-status", headers=headers)
    assert dun_res.status_code == 200
    dun_data = dun_res.json()
    assert "dunning" in dun_data
    assert "portal_recovery_url" in dun_data
