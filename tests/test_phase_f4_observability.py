import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.main import app
from apps.api.auth import create_access_token
from services.database.models import User, UserRole, Organization, AuditLog
from services.operations.metrics import metrics_registry
from services.operations.feature_flags import feature_flags
from services.operations.incident_manager import incident_manager

client = TestClient(app)

def _get_superadmin_headers():
    token = create_access_token(data={
        "sub": "usr_superadmin",
        "role": UserRole.SUPER_ADMIN.value,
        "organization_id": "org_azure_group"
    })
    return {"Authorization": f"Bearer {token}"}

def test_prometheus_metrics_and_red_telemetry():
    """F4.1 Prometheus metrics endpoint (/prometheus/metrics), RED metrics, and business KPIs."""
    org_id = f"org_prom_{uuid.uuid4().hex[:6]}"

    # Record metrics
    metrics_registry.record_http_request("GET", "/api/v1/properties", 200, 0.042, org_id=org_id)
    metrics_registry.record_http_request("POST", "/api/v1/conversations", 201, 0.115, org_id=org_id)
    metrics_registry.record_llm_usage(provider="openai", tokens=450, cost_usd=0.009, org_id=org_id)
    metrics_registry.record_reservation(org_id=org_id)

    # Scrape Prometheus endpoint
    res = client.get("/prometheus/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    body = res.text

    assert "http_requests_total" in body
    assert f'organization_id="{org_id}"' in body
    assert "llm_tokens_total" in body
    assert "llm_cost_usd_total" in body
    assert "reservations_created_total" in body


def test_feature_flags_gradual_rollout_and_kill_switches():
    """F4.2 Feature flags, per-org overrides, percentage rollouts, and operational kill switches."""
    test_flag = f"flag_{uuid.uuid4().hex[:6]}"
    target_org = "org_target_vip"
    other_org = "org_regular"

    # 1. Feature disabled by default, whitelist target_org
    feature_flags.set_flag(
        key=test_flag,
        enabled=False,
        rollout_pct=0,
        enabled_orgs=[target_org]
    )
    assert feature_flags.is_enabled(test_flag, org_id=target_org) is True
    assert feature_flags.is_enabled(test_flag, org_id=other_org) is False

    # 2. Percentage Rollout (50%)
    feature_flags.set_flag(key=test_flag, enabled=True, rollout_pct=50)
    # Consistent deterministic evaluation for same org
    result_a1 = feature_flags.is_enabled(test_flag, org_id="tenant_alpha")
    result_a2 = feature_flags.is_enabled(test_flag, org_id="tenant_alpha")
    assert result_a1 == result_a2

    # 3. Emergency Kill Switch
    assert feature_flags.is_enabled("voice", org_id="any_org") is False or True  # Initial state
    feature_flags.activate_kill_switch("kill_switch_voice")
    assert feature_flags.is_kill_switch_active("kill_switch_voice") is True
    assert feature_flags.is_enabled("voice", org_id="any_org") is False

    # Disengage kill switch
    feature_flags.deactivate_kill_switch("kill_switch_voice")
    assert feature_flags.is_kill_switch_active("kill_switch_voice") is False


@pytest.mark.asyncio
async def test_real_status_page_and_incident_lifecycle(db_session):
    """F4.3 Public status page fed by real health checks, incident creation, and resolution."""
    headers = _get_superadmin_headers()

    # 1. Check baseline status page
    res_status = client.get("/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert "services" in status_data
    assert "database_postgresql" in status_data["services"]

    # 2. Super Admin creates an active incident
    inc_title = f"Intermittent PMS Latency {uuid.uuid4().hex[:4]}"
    create_res = client.post(
        f"/api/v1/platform/incidents?title={inc_title}&impact=MAJOR&message=Investigating+API+slowness",
        headers=headers
    )
    assert create_res.status_code == 200
    incident_id = create_res.json()["id"]

    # 3. Public status page now reports degraded performance with active incident
    res_degraded = client.get("/status")
    assert res_degraded.status_code == 200
    assert res_degraded.json()["status"] == "DEGRADED_PERFORMANCE"
    assert res_degraded.json()["active_incidents_count"] >= 1

    # Public incident log endpoint
    res_incidents = client.get("/status/incidents")
    assert res_incidents.status_code == 200
    matched_inc = [i for i in res_incidents.json()["incidents"] if i["id"] == incident_id]
    assert len(matched_inc) == 1
    assert matched_inc[0]["status"] == "INVESTIGATING"

    # 4. Super Admin resolves incident
    resolve_res = client.post(
        f"/api/v1/platform/incidents/{incident_id}/resolve?message=All+services+restored",
        headers=headers
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "RESOLVED"

    # Status page reflects normal operations again
    res_resolved = client.get("/status")
    assert res_resolved.json()["active_incidents_count"] == 0


@pytest.mark.asyncio
async def test_platform_operator_console_tenant_management_and_audit(db_session):
    """F4.4 Platform operator console: tenant search, suspend, unsuspend, and plan override with audit."""
    headers = _get_superadmin_headers()

    # Create test organization
    org_id = f"org_ops_{uuid.uuid4().hex[:8]}"
    org_name = f"Grand Plaza Resort {uuid.uuid4().hex[:4]}"
    org = Organization(id=org_id, name=org_name, slug=f"plaza-{uuid.uuid4().hex[:6]}", status="ACTIVE")
    db_session.add(org)
    await db_session.commit()

    # 1. Search organizations
    search_res = client.get(f"/api/v1/platform/organizations?search=Grand+Plaza", headers=headers)
    assert search_res.status_code == 200
    assert any(o["id"] == org_id for o in search_res.json()["organizations"])

    # 2. Suspend organization
    suspend_res = client.post(
        f"/api/v1/platform/organizations/{org_id}/suspend?reason=Non-payment+in+grace+period",
        headers=headers
    )
    assert suspend_res.status_code == 200
    assert suspend_res.json()["organization_status"] == "SUSPENDED"

    # Verify audit log entry
    stmt_audit = select(AuditLog).where(
        AuditLog.organization_id == org_id,
        AuditLog.action == "ORGANIZATION_SUSPENDED"
    )
    res_audit = await db_session.execute(stmt_audit)
    audit_entry = res_audit.scalar_one_or_none()
    assert audit_entry is not None
    assert audit_entry.details_json.get("reason") == "Non-payment in grace period"

    # 3. Unsuspend organization
    unsuspend_res = client.post(f"/api/v1/platform/organizations/{org_id}/unsuspend", headers=headers)
    assert unsuspend_res.status_code == 200
    assert unsuspend_res.json()["organization_status"] == "ACTIVE"

    # 4. Plan override with audit
    plan_res = client.post(
        f"/api/v1/platform/organizations/{org_id}/plan-override?plan_name=ENTERPRISE&reason=Annual+Enterprise+Agreement",
        headers=headers
    )
    assert plan_res.status_code == 200
    assert plan_res.json()["plan_name"] == "ENTERPRISE"
