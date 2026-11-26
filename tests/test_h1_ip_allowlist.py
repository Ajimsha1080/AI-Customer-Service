import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from services.database.models import User, Organization, UserRole
from services.database.session import AsyncSessionLocal
from apps.api.auth import hash_password, create_access_token, is_ip_allowed

@pytest.mark.asyncio
async def test_h1_ip_allowlist_trusted_proxy_and_spoof_prevention(prepare_db):
    """
    H1 Regression Test:
    - Attacker attempts to spoof allowlisted IP by putting it first in X-Forwarded-For:
      'X-Forwarded-For': '198.51.100.5, 192.0.2.99'
      Old vulnerable code read [0] and allowed 198.51.100.5.
      New trusted-proxy code parses from the right and identifies 192.0.2.99, rejecting with 403.
    - Legitimate request from allowlisted IP '198.51.100.5' succeeds (200).
    - 'testclient' and 'localhost' have no special bypass in is_ip_allowed.
    """
    async with AsyncSessionLocal() as db:
        test_org = Organization(
            id="org_h1_test",
            name="H1 IP Test Corp",
            slug="h1-ip-test-corp",
            ip_allowlist="198.51.100.5, 203.0.113.0/24"
        )
        test_user = User(
            id="usr_h1_test",
            organization_id="org_h1_test",
            email="h1_user@testcorp.com",
            full_name="H1 User",
            hashed_password=hash_password("StrongPassword123!"),
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add_all([test_org, test_user])
        await db.commit()

    token = create_access_token({
        "sub": "usr_h1_test",
        "org_id": "org_h1_test",
        "role": "ADMIN"
    })

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Attacker attempts front-loaded XFF spoofing (first value is allowlisted, second is attacker IP)
        spoof_resp = await client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Forwarded-For": "198.51.100.5, 192.0.2.99"
            }
        )
        assert spoof_resp.status_code == 403, f"Expected 403 for spoofed IP, got {spoof_resp.status_code}"
        assert "not in the organization's allowlist" in spoof_resp.json()["detail"]

        # 2. Legitimate request with allowlisted IP
        legit_resp = await client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Forwarded-For": "198.51.100.5"
            }
        )
        assert legit_resp.status_code == 200, f"Expected 200 for allowlisted IP, got {legit_resp.status_code}: {legit_resp.text}"

        # 3. Legitimate request with allowlisted CIDR range (203.0.113.42)
        cidr_resp = await client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Forwarded-For": "203.0.113.42"
            }
        )
        assert cidr_resp.status_code == 200

        # 4. Request from non-allowlisted IP
        blocked_resp = await client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Forwarded-For": "192.0.2.1"
            }
        )
        assert blocked_resp.status_code == 403

    # 5. Verify unit level: 'testclient' and 'localhost' have no magical bypass
    assert not is_ip_allowed("testclient", "198.51.100.5, 203.0.113.0/24")
    assert not is_ip_allowed("localhost", "198.51.100.5, 203.0.113.0/24")
    assert not is_ip_allowed("127.0.0.1", "198.51.100.5, 203.0.113.0/24")
    assert is_ip_allowed("198.51.100.5", "198.51.100.5, 203.0.113.0/24")
    assert is_ip_allowed("203.0.113.50", "198.51.100.5, 203.0.113.0/24")
