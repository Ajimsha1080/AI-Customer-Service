import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.auth import create_access_token, create_user_session
from services.database.models import User, Organization, Property, UserRole

@pytest.mark.asyncio
async def test_h7_agent_creation_property_must_belong_to_caller_org(db_session):
    """
    H7: Agent creation: property_id must belong to the caller's org.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create Org A and Property A
        org_id_a = str(uuid.uuid4())
        prop_id_a = str(uuid.uuid4())
        org_a = Organization(id=org_id_a, name="Org A", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        prop_a = Property(id=prop_id_a, organization_id=org_id_a, name="Hotel Alpha")
        user_a = User(
            id=str(uuid.uuid4()),
            organization_id=org_id_a,
            email=f"admin_a_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pwd",
            full_name="Admin Alpha",
            role=UserRole.ADMIN,
            is_active=True
        )
        db_session.add(org_a)
        db_session.add(prop_a)
        db_session.add(user_a)

        # Create Org B and Property B
        org_id_b = str(uuid.uuid4())
        prop_id_b = str(uuid.uuid4())
        org_b = Organization(id=org_id_b, name="Org B", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        prop_b = Property(id=prop_id_b, organization_id=org_id_b, name="Hotel Beta")
        db_session.add(org_b)
        db_session.add(prop_b)
        await db_session.commit()

        token_a = create_access_token({"sub": user_a.id, "org_id": org_id_a, "role": "ADMIN", "is_login": True})
        await create_user_session(db=db_session, user_id=user_a.id, org_id=org_id_a, access_token=token_a)
        await db_session.commit()

        headers_a = {"Authorization": f"Bearer {token_a}"}

        # 1. Attempting to create agent in Org A with Property B (cross-tenant property reference) -> 404
        resp_cross_tenant = await ac.post("/api/v1/agents", json={
            "organization_id": org_id_a,
            "property_id": prop_id_b,
            "name": "Cross Tenant Agent",
            "agent_type": "CONCIERGE"
        }, headers=headers_a)
        assert resp_cross_tenant.status_code == 404
        assert "does not belong" in resp_cross_tenant.text.lower() or "not found" in resp_cross_tenant.text.lower()

        # 2. Attempting to create agent with non-existent property_id -> 404
        fake_prop_id = str(uuid.uuid4())
        resp_nonexistent = await ac.post("/api/v1/agents", json={
            "organization_id": org_id_a,
            "property_id": fake_prop_id,
            "name": "Ghost Property Agent",
            "agent_type": "CONCIERGE"
        }, headers=headers_a)
        assert resp_nonexistent.status_code == 404

        # 3. Creating agent with valid Property A (belongs to Org A) -> 200
        resp_valid = await ac.post("/api/v1/agents", json={
            "organization_id": org_id_a,
            "property_id": prop_id_a,
            "name": "Valid Concierge Agent",
            "agent_type": "CONCIERGE"
        }, headers=headers_a)
        assert resp_valid.status_code == 200
        assert resp_valid.json()["property_id"] == prop_id_a
