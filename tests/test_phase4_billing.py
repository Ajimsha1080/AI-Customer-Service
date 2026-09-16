import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from apps.api.main import app, get_db, metering_service
from apps.api.auth import create_access_token
from services.database.models import User, UserRole, Organization, Property, Agent, Subscription, UsageEvent, Document
from services.database.session import AsyncSessionLocal

@pytest.fixture
def api_client():
    return TestClient(app)

@pytest.fixture
def auth_headers():
    token = create_access_token(data={"sub": "usr_demo123", "org_id": "org_azure_group", "role": "ORGANIZATION_ADMIN"})
    return {"Authorization": f"Bearer {token}"}

@pytest.mark.asyncio
async def test_subscription_status_retrieval_and_upgrade(api_client, auth_headers):
    """Phase 4 Requirement: Fetch subscription status/limits and test tier upgrade."""
    res = api_client.get("/api/v1/billing/subscription", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "subscription" in data
    assert "usage_summary" in data
    assert data["subscription"]["plan_name"] in ["BUSINESS", "STARTER", "FREE", "PROFESSIONAL", "ENTERPRISE"]

    # Upgrade plan to ENTERPRISE
    upgrade_res = api_client.post(
        "/api/v1/billing/subscription/upgrade",
        headers=auth_headers,
        json={"plan_name": "ENTERPRISE"}
    )
    assert upgrade_res.status_code == 200
    up_data = upgrade_res.json()
    assert up_data["plan_name"] == "ENTERPRISE"
    assert up_data["max_agents"] == 999

    # Re-fetch subscription to confirm DB persistence
    res_after = api_client.get("/api/v1/billing/subscription", headers=auth_headers)
    assert res_after.status_code == 200
    assert res_after.json()["subscription"]["plan_name"] == "ENTERPRISE"

@pytest.mark.asyncio
async def test_agent_creation_quota_enforcement(api_client, auth_headers):
    """Phase 4 Requirement: Enforce agent creation quota limits (returns 402 when exceeded)."""
    # Downscale org to FREE tier (max 1 agent)
    api_client.post("/api/v1/billing/subscription/upgrade", headers=auth_headers, json={"plan_name": "FREE"})

    # Attempt creating agents until FREE tier limit (1 agent) is exceeded
    res1 = api_client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_azure_palm_resort",
            "name": "Quota Agent 1",
            "agent_type": "CONCIERGE"
        }
    )
    res2 = api_client.post(
        "/api/v1/agents",
        headers=auth_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_azure_palm_resort",
            "name": "Quota Agent 2",
            "agent_type": "CONCIERGE"
        }
    )
    failed_res = res1 if res1.status_code == 402 else res2
    assert "Billing quota exceeded" in failed_res.json()["detail"]

    # Restore to BUSINESS tier
    api_client.post("/api/v1/billing/subscription/upgrade", headers=auth_headers, json={"plan_name": "BUSINESS"})

@pytest.mark.asyncio
async def test_document_upload_quota_enforcement(api_client, auth_headers):
    """Phase 4 Requirement: Enforce document upload storage limits (returns 402 when exceeded)."""
    # Upgrade org to STARTER tier (max 10 documents)
    api_client.post("/api/v1/billing/subscription/upgrade", headers=auth_headers, json={"plan_name": "STARTER"})

    async with AsyncSessionLocal() as session:
        # Seed 10 dummy documents for org_azure_group
        for i in range(10):
            session.add(Document(
                id=f"doc_quota_{i}_{uuid.uuid4().hex[:6]}",
                organization_id="org_azure_group",
                property_id="prop_azure_palm_resort",
                agent_id="agt_001",
                title=f"Quota Doc {i}",
                document_type="PDF",
                content_raw="Sample content"
            ))
        await session.commit()

    # Attempt to upload 11th document
    res = api_client.post(
        "/api/v1/knowledge/documents",
        headers=auth_headers,
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_azure_palm_resort",
            "title": "Exceeded Quota Doc",
            "content": "This document exceeds the plan quota limit.",
            "document_type": "TXT"
        }
    )
    assert res.status_code == 402
    assert "Document upload storage limit reached" in res.json()["detail"]

    # Restore to BUSINESS tier
    api_client.post("/api/v1/billing/subscription/upgrade", headers=auth_headers, json={"plan_name": "BUSINESS"})

@pytest.mark.asyncio
async def test_usage_event_db_persistence(api_client):
    """Phase 4 Requirement: Meter usage on every agent turn and record UsageEvent in database."""
    async with AsyncSessionLocal() as session:
        count_before = (await session.execute(
            select(func.count(UsageEvent.id)).where(UsageEvent.organization_id == "org_azure_group")
        )).scalar() or 0

    res = api_client.post(
        "/api/v1/agents/agt_hostel_01/chat",
        json={
            "organization_id": "org_azure_group",
            "property_id": "prop_azure_palm_resort",
            "message": "What is the Wi-Fi password?"
        }
    )
    assert res.status_code == 200

    async with AsyncSessionLocal() as session:
        count_after = (await session.execute(
            select(func.count(UsageEvent.id)).where(UsageEvent.organization_id == "org_azure_group")
        )).scalar() or 0

    assert count_after == count_before + 1
