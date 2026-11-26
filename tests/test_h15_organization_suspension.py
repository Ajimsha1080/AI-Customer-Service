import pytest
import uuid
import hashlib
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.auth import create_access_token, hash_password
from services.database.models import (
    User, Organization, UserRole, ApiKey, SCIMToken, Agent, AgentStatus, Property, SSOConfig
)
from apps.api.routers.sso import generate_sso_state

@pytest.mark.asyncio
async def test_h15_user_auth_and_api_key_blocked_for_suspended_org(db_session):
    """H15: User login, authenticated requests, and API keys are blocked for suspended organizations."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create a suspended organization
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="Suspended Tenant Inc", slug=f"slug-{uuid.uuid4().hex[:6]}", status="SUSPENDED")
        user = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"user_susp_{uuid.uuid4().hex[:6]}@suspended.com",
            full_name="Suspended User",
            hashed_password=hash_password("password123"),
            role=UserRole.ADMIN,
            is_active=True
        )
        # Create API key for this organization
        raw_key = f"ak_live_{uuid.uuid4().hex}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        api_key = ApiKey(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name="Suspended Tenant Key",
            key_hash=key_hash,
            key_prefix=raw_key[:12],
            is_active=True
        )
        db_session.add(org)
        db_session.add(user)
        db_session.add(api_key)
        await db_session.commit()

        # 1. Login attempt is rejected with 403 Forbidden
        res_login = await ac.post("/api/v1/auth/login", json={"email": user.email, "password": "password123"})
        assert res_login.status_code == 403
        assert "ORGANIZATION_SUSPENDED" in res_login.json()["detail"]

        # 2. Existing access token used against protected endpoint is rejected with 403
        token = create_access_token({"sub": user.id, "org_id": org_id, "role": "ADMIN", "test_synthetic": True})
        res_auth = await ac.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res_auth.status_code == 403
        assert "ORGANIZATION_SUSPENDED" in res_auth.json()["detail"]

        # 3. API key request is rejected with 403
        res_apikey = await ac.get("/api/v1/auth/me", headers={"x-api-key": raw_key})
        assert res_apikey.status_code == 403
        assert "ORGANIZATION_SUSPENDED" in res_apikey.json()["detail"]

@pytest.mark.asyncio
async def test_h15_scim_and_sso_blocked_for_suspended_org(db_session):
    """H15: SCIM directory sync and SSO callbacks are blocked for suspended organizations."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="SCIM Suspended Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="SUSPENDED")
        raw_scim_token = f"scim_{uuid.uuid4().hex}"
        scim_hash = hashlib.sha256(raw_scim_token.encode("utf-8")).hexdigest()
        scim_token = SCIMToken(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            name="Okta SCIM",
            token_hash=scim_hash
        )
        db_session.add(org)
        db_session.add(scim_token)
        await db_session.commit()

        # 1. SCIM request is rejected with 403 Forbidden
        res_scim = await ac.get("/api/v1/scim/v2/Users", headers={"Authorization": f"Bearer {raw_scim_token}"})
        assert res_scim.status_code == 403
        assert "ORGANIZATION_SUSPENDED" in res_scim.json()["detail"]

        # 2. SSO callback for suspended org is rejected with 403 Forbidden
        sso_state = generate_sso_state(provider="SAML", org_id=org_id, in_response_to="req_123")
        res_saml = await ac.post("/api/v1/auth/sso/saml/callback", json={
            "saml_response": "dummy_response",
            "relay_state": sso_state
        })
        assert res_saml.status_code == 403
        assert "ORGANIZATION_SUSPENDED" in res_saml.json()["detail"]

@pytest.mark.asyncio
async def test_h15_guest_chat_blocked_for_suspended_org(db_session):
    """H15: Guest chat and public agent endpoints are blocked for suspended organizations."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="Hotel Suspended Group", slug=f"slug-{uuid.uuid4().hex[:6]}", status="SUSPENDED")
        prop = Property(id=str(uuid.uuid4()), organization_id=org_id, name="Grand Hotel")
        agent = Agent(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop.id,
            name="Concierge Agent",
            status=AgentStatus.ACTIVE
        )
        db_session.add(org)
        db_session.add(prop)
        db_session.add(agent)
        await db_session.commit()

        # 1. Public agent profile returns 404 for suspended org
        res_pub = await ac.get(f"/api/v1/public/agents/{agent.id}")
        assert res_pub.status_code == 404

        # 2. Guest chat returns 403 Forbidden
        res_chat = await ac.post(f"/api/v1/agents/{agent.id}/chat", json={
            "message": "Hello, is the restaurant open?"
        })
        assert res_chat.status_code == 403
        assert "ORGANIZATION_SUSPENDED" in res_chat.json()["detail"]
