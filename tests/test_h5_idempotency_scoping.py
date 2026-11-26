import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.auth import create_access_token, create_user_session
from services.database.models import User, Organization, Property, UserRole

@pytest.mark.asyncio
async def test_h5_idempotency_scoping_and_different_body_422(db_session):
    """
    H5: The idempotency key uses authenticated principal + method + path + body hash.
    Same key with a different body -> 422.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create User 1 and Property 1
        org_id_1 = str(uuid.uuid4())
        prop_id_1 = str(uuid.uuid4())
        user_id_1 = str(uuid.uuid4())
        org1 = Organization(id=org_id_1, name="Org 1", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        prop1 = Property(id=prop_id_1, organization_id=org_id_1, name="Prop 1")
        user1 = User(
            id=user_id_1,
            organization_id=org_id_1,
            email=f"user1_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pwd",
            full_name="User One",
            role=UserRole.ADMIN,
            is_active=True
        )
        db_session.add(org1)
        db_session.add(prop1)
        db_session.add(user1)

        # Create User 2 and Property 2
        org_id_2 = str(uuid.uuid4())
        prop_id_2 = str(uuid.uuid4())
        user_id_2 = str(uuid.uuid4())
        org2 = Organization(id=org_id_2, name="Org 2", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        prop2 = Property(id=prop_id_2, organization_id=org_id_2, name="Prop 2")
        user2 = User(
            id=user_id_2,
            organization_id=org_id_2,
            email=f"user2_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pwd",
            full_name="User Two",
            role=UserRole.ADMIN,
            is_active=True
        )
        db_session.add(org2)
        db_session.add(prop2)
        db_session.add(user2)
        await db_session.commit()

        token1 = create_access_token({"sub": user1.id, "org_id": org_id_1, "role": "admin", "is_login": True})
        await create_user_session(db=db_session, user_id=user1.id, org_id=org_id_1, access_token=token1)
        token2 = create_access_token({"sub": user2.id, "org_id": org_id_2, "role": "admin", "is_login": True})
        await create_user_session(db=db_session, user_id=user2.id, org_id=org_id_2, access_token=token2)
        await db_session.commit()

        idemp_key = f"key-{uuid.uuid4().hex}"
        endpoint = "/api/v1/live-updates"
        body_initial_1 = {
            "organization_id": org_id_1,
            "property_id": prop_id_1,
            "title": "Welcome Announcement",
            "content": "Welcome to our hotel!",
            "type": "MAINTENANCE",
            "priority": "LOW"
        }

        headers1 = {
            "Authorization": f"Bearer {token1}",
            "Idempotency-Key": idemp_key
        }

        # 1. User 1 submits initial request
        resp1 = await ac.post(endpoint, json=body_initial_1, headers=headers1)
        assert resp1.status_code == 200, resp1.text

        # 2. User 1 resubmits with identical body -> replayed response (HIT)
        resp2 = await ac.post(endpoint, json=body_initial_1, headers=headers1)
        assert resp2.status_code == 200
        assert resp2.headers.get("Idempotency-Replayed") == "true"
        assert resp2.headers.get("X-Cache-Lookup") == "HIT"

        # 3. User 1 resubmits same key with DIFFERENT body -> 422 Unprocessable Entity
        body_different_1 = {
            "organization_id": org_id_1,
            "property_id": prop_id_1,
            "title": "Different Announcement",
            "content": "A different message body",
            "type": "GENERAL",
            "priority": "HIGH"
        }
        resp3 = await ac.post(endpoint, json=body_different_1, headers=headers1)
        assert resp3.status_code == 422
        assert "different request payload" in resp3.text.lower() or "mismatch" in resp3.text.lower()

        # 4. User 2 using the same idempotency key is NOT affected by User 1's key (scoped by principal)
        body_initial_2 = {
            "organization_id": org_id_2,
            "property_id": prop_id_2,
            "title": "Welcome Announcement",
            "content": "Welcome to our hotel!",
            "type": "MAINTENANCE",
            "priority": "LOW"
        }
        headers2 = {
            "Authorization": f"Bearer {token2}",
            "Idempotency-Key": idemp_key
        }
        resp4 = await ac.post(endpoint, json=body_initial_2, headers=headers2)
        assert resp4.status_code == 200
        # It's a fresh creation for User 2, not replayed from User 1
        assert resp4.headers.get("Idempotency-Replayed") != "true"
