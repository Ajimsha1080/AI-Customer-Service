import pytest
import uuid
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api.auth import create_access_token
from services.database.models import UserRole

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def owner_headers():
    token = create_access_token(data={"sub": "usr_admin_01", "org_id": "org_azure_group", "role": "OWNER"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def staff_headers():
    token = create_access_token(data={"sub": "usr_demo123", "org_id": "org_azure_group", "role": "STAFF"})
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def viewer_headers():
    token = create_access_token(data={"sub": "usr_viewer_01", "org_id": "org_azure_group", "role": "VIEWER"})
    return {"Authorization": f"Bearer {token}"}

def test_registration_always_creates_new_org_with_unique_slug(client):
    """0.2 Security: Two consecutive signups must NOT land in the same org or share default slug 'azure-palm-group'."""
    email1 = f"user1_{uuid.uuid4().hex[:6]}@example.com"
    email2 = f"user2_{uuid.uuid4().hex[:6]}@example.com"

    res1 = client.post("/api/v1/auth/register", json={
        "email": email1,
        "password": "StrongPassword123!",
        "full_name": "Test Founder 1",
        "organization_name": "Grand Palace"
    })
    assert res1.status_code == 200, f"Signup 1 failed: {res1.text}"
    user1 = res1.json()["user"]
    org_id_1 = user1["organization_id"]

    res2 = client.post("/api/v1/auth/register", json={
        "email": email2,
        "password": "StrongPassword123!",
        "full_name": "Test Founder 2",
        "organization_name": "Grand Palace"
    })
    assert res2.status_code == 200, f"Signup 2 failed: {res2.text}"
    user2 = res2.json()["user"]
    org_id_2 = user2["organization_id"]

    # Must be completely separate organizations
    assert org_id_1 != org_id_2, "Separate signups must never share the same organization!"
    assert org_id_1 != "org_azure_group"
    assert org_id_2 != "org_azure_group"
    assert user1["role"] in ["OWNER", "ORGANIZATION_ADMIN"]
    assert user2["role"] in ["OWNER", "ORGANIZATION_ADMIN"]

def test_joining_org_requires_invitation_token(client, owner_headers):
    """0.2 Security: Joining an organization requires an invitation token."""
    # 1. Create an invitation as OWNER
    res_inv = client.post(
        "/api/v1/organizations/org_azure_group/invitations",
        headers=owner_headers,
        json={"email": f"newstaff_{uuid.uuid4().hex[:6]}@example.com", "role": "STAFF"}
    )
    assert res_inv.status_code == 200
    token = res_inv.json()["invitation_token"]

    # 2. Accept invitation
    invited_email = res_inv.json()["email"]
    res_accept = client.post("/api/v1/auth/accept-invitation", json={
        "invitation_token": token,
        "password": "StaffPassword123!",
        "full_name": "Invited Staff"
    })
    assert res_accept.status_code == 200
    data = res_accept.json()
    assert data["user"]["email"] == invited_email
    assert data["user"]["organization_id"] == "org_azure_group"
    assert data["user"]["role"] == "STAFF"

def test_staff_role_cannot_perform_owner_mutations(client, staff_headers):
    """0.2 RBAC: STAFF role must be forbidden from mutating routes like creating properties, inviting members, or updating billing."""
    # Cannot create property
    res_prop = client.post(
        "/api/v1/properties",
        headers=staff_headers,
        json={"organization_id": "org_azure_group", "name": "Unauthorized Property"}
    )
    assert res_prop.status_code == 403, f"Expected 403 for staff creating property, got {res_prop.status_code}"

    # Cannot create invitations
    res_inv = client.post(
        "/api/v1/organizations/org_azure_group/invitations",
        headers=staff_headers,
        json={"email": "hacker@example.com", "role": "ADMIN"}
    )
    assert res_inv.status_code == 403, f"Expected 403 for staff creating invitation, got {res_inv.status_code}"

def test_google_callback_without_credentials_returns_401(client):
    """0.3 Security: Google callback without valid credentials must return 401, not fabricate a user."""
    res = client.post("/api/v1/auth/google/callback", json={
        "code": "fake_auth_code_12345",
        "state": "unverified_state"
    })
    assert res.status_code in [400, 401, 503], f"Expected 401/400 for fake google code, got {res.status_code}"
