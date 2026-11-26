import pytest
import uuid
from httpx import AsyncClient, ASGITransport
from fastapi.routing import APIRoute

from apps.api.main import app
from apps.api.auth import (
    create_access_token,
    create_user_session,
    get_current_user,
    require_permission,
    require_role,
    get_super_admin_user,
    get_current_org_user,
    security_scheme,
    PERMISSION_CATALOGUE
)
from services.database.models import User, Organization, Property, Agent, Conversation, ConversationStatus, UserRole

PUBLIC_ROUTE_ALLOWLIST = {
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/healthz",
    "/metrics",
    "/prometheus/metrics",
    "/api/v1/public/agents/{agent_id}",
    "/api/v1/agents/{agent_id}/chat",
    "/api/v1/agents/{agent_id}/chat/stream",
    "/api/v1/agents/{agent_id}/voice",
    "/api/v1/agents/{agent_id}/voice/session",
    "/api/v1/live-updates/events",
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/invitations/accept",
    "/api/v1/auth/google/url",
    "/api/v1/auth/google/callback",
    "/api/v1/auth/saml/metadata",
    "/api/v1/auth/saml/acs",
    "/api/v1/auth/sso/callback",
    "/api/v1/auth/mfa/challenge",
    "/api/v1/integrations/whatsapp/webhook",
    "/api/v1/integrations/email/webhooks/bounces",
    "/api/v1/integrations/stripe/webhook",
    "/api/v1/billing/api/v1/billing/webhook",
    "/api/v1/voice/tts",
    "/api/v1/voice/sessions",
    "/api/v1/email/bounce",
    "/api/v1/email/complaint",
    "/api/v1/sso/saml/callback",
    "/api/v1/sso/oidc/callback"
}

def _has_auth_dependency(dependant) -> bool:
    AUTH_FUNCS = {
        get_current_user,
        get_super_admin_user,
        get_current_org_user,
        security_scheme
    }
    # Check current call
    call = getattr(dependant, "call", None)
    if call in AUTH_FUNCS or getattr(call, "__name__", "") in ("permission_checker", "role_checker"):
        return True

    # Check child dependencies recursively
    for sub in getattr(dependant, "dependencies", []):
        if _has_auth_dependency(sub):
            return True
    return False

def test_h6_route_enumeration_asserts_auth():
    """
    H6: Enumerate all routes and assert each has an auth dependency unless explicitly allowlisted.
    """
    missing_auth = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            path = route.path
            # Check if path is allowlisted
            if path in PUBLIC_ROUTE_ALLOWLIST or any(path.startswith(prefix) for prefix in ("/static", "/favicon", "/widget")):
                continue

            if not _has_auth_dependency(route.dependant):
                missing_auth.append(f"{route.methods} {path}")

    assert not missing_auth, f"Routes missing authentication dependencies: {missing_auth}"

@pytest.mark.asyncio
async def test_h6_takeover_and_agent_creation_permissions(db_session):
    """
    H6: Conversation takeover and agent creation require granular permissions.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        prop_id = str(uuid.uuid4())
        agent_id = str(uuid.uuid4())
        conv_id = str(uuid.uuid4())

        org = Organization(id=org_id, name="Test Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")
        prop = Property(id=prop_id, organization_id=org_id, name="Test Prop")
        agent = Agent(id=agent_id, organization_id=org_id, property_id=prop_id, name="Test Agent", agent_type="CONCIERGE", status="ACTIVE")
        conv = Conversation(
            id=conv_id,
            organization_id=org_id,
            property_id=prop_id,
            agent_id=agent_id,
            channel="web_widget",
            channel_user_id="guest_1",
            status=ConversationStatus.AI_ACTIVE
        )

        # Viewer user without agent:write or conversations:write
        viewer = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"viewer_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pwd",
            full_name="Viewer User",
            role=UserRole.VIEWER,
            is_active=True
        )

        db_session.add(org)
        db_session.add(prop)
        db_session.add(agent)
        db_session.add(conv)
        db_session.add(viewer)
        await db_session.commit()

        token_viewer = create_access_token({"sub": viewer.id, "org_id": org_id, "role": "VIEWER", "is_login": True})
        await create_user_session(db=db_session, user_id=viewer.id, org_id=org_id, access_token=token_viewer)
        await db_session.commit()

        headers_viewer = {"Authorization": f"Bearer {token_viewer}"}

        # 1. Viewer attempts agent creation -> 403 Forbidden (requires agent:write)
        resp_agent = await ac.post("/api/v1/agents", json={
            "organization_id": org_id,
            "property_id": prop_id,
            "name": "New Agent"
        }, headers=headers_viewer)
        assert resp_agent.status_code == 403
        assert "agent:write" in resp_agent.text

        # 2. Viewer attempts conversation takeover -> 403 Forbidden (requires conversations:write)
        resp_takeover = await ac.post(f"/api/v1/conversations/{conv_id}/takeover", json={"reason": "Test"}, headers=headers_viewer)
        assert resp_takeover.status_code == 403
        assert "conversations:write" in resp_takeover.text

@pytest.mark.asyncio
async def test_h6_custom_roles_catalogue_and_hierarchy_enforcement(db_session):
    """
    H6: Custom roles reject wildcards and unknown permissions (422) and
    cannot grant permissions above the creator's own (403).
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        org_id = str(uuid.uuid4())
        org = Organization(id=org_id, name="Test Org", slug=f"slug-{uuid.uuid4().hex[:6]}", status="active")

        # Organization Admin user with roles:manage, but NOT billing:write
        admin = User(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email=f"admin_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="pwd",
            full_name="Admin User",
            role=UserRole.ORGANIZATION_ADMIN,
            is_active=True
        )

        db_session.add(org)
        db_session.add(admin)
        await db_session.commit()

        token_admin = create_access_token({"sub": admin.id, "org_id": org_id, "role": "ORGANIZATION_ADMIN", "is_login": True})
        await create_user_session(db=db_session, user_id=admin.id, org_id=org_id, access_token=token_admin)
        await db_session.commit()

        headers_admin = {"Authorization": f"Bearer {token_admin}"}

        # 1. Reject wildcard "*" -> 422
        resp_wildcard = await ac.post("/api/v1/roles", json={
            "name": "Super Admin Clone",
            "permissions": ["*"]
        }, headers=headers_admin)
        assert resp_wildcard.status_code == 422
        assert "catalogue" in resp_wildcard.text.lower() or "wildcard" in resp_wildcard.text.lower()

        # 2. Reject arbitrary unknown permission -> 422
        resp_unknown = await ac.post("/api/v1/roles", json={
            "name": "Hacker Role",
            "permissions": ["arbitrary:hack"]
        }, headers=headers_admin)
        assert resp_unknown.status_code == 422

        # 3. Creator lacks billing:write -> attempting to grant billing:write -> 403
        resp_exceed = await ac.post("/api/v1/roles", json={
            "name": "Billing Role",
            "permissions": ["billing:write"]
        }, headers=headers_admin)
        assert resp_exceed.status_code == 403
        assert "exceeds" in resp_exceed.text.lower()

        # 4. Creator grants permissions within own scope (e.g. agent:write, conversations:read) -> 201
        resp_valid = await ac.post("/api/v1/roles", json={
            "name": "Valid Agent Operator",
            "permissions": ["agent:write", "conversations:read"]
        }, headers=headers_admin)
        assert resp_valid.status_code == 201
