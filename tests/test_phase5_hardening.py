import pytest
from fastapi.testclient import TestClient
from apps.api.main import app

@pytest.fixture
def api_client():
    return TestClient(app)

def test_request_id_header_generation_and_propagation(api_client):
    """Phase 5 Requirement: Request ID middleware generates and propagates X-Request-ID header."""
    # Case 1: No request ID supplied -> middleware generates one
    res1 = api_client.get("/health")
    assert res1.status_code == 200
    assert "X-Request-ID" in res1.headers
    assert res1.headers["X-Request-ID"].startswith("req_")

    # Case 2: Custom request ID supplied -> middleware preserves and propagates it
    custom_id = "req_custom_trace_9999"
    res2 = api_client.get("/health", headers={"X-Request-ID": custom_id})
    assert res2.status_code == 200
    assert res2.headers["X-Request-ID"] == custom_id

def test_standardized_error_format(api_client):
    """Phase 5 Requirement: Exception handlers return standardized JSON error response with request_id."""
    res = api_client.get("/api/v1/non_existent_endpoint_404")
    assert res.status_code == 404
    assert "X-Request-ID" in res.headers
    data = res.json()
    assert "error" in data
    assert data["error"]["status_code"] == 404
    assert "request_id" in data["error"]
    assert data["error"]["request_id"] == res.headers["X-Request-ID"]

def test_health_readiness_metrics_probes(api_client):
    """Phase 5 Requirement: Validate production health probes /health, /ready, and /metrics."""
    # Health Probe
    res_h = api_client.get("/health")
    assert res_h.status_code == 200
    h_data = res_h.json()
    assert h_data["status"] == "healthy"
    assert "timestamp" in h_data

    # Readiness Probe
    res_r = api_client.get("/ready")
    assert res_r.status_code == 200
    r_data = res_r.json()
    assert r_data["status"] == "ready"
    assert r_data["database"] == "connected"

    # Observability Metrics Probe
    res_m = api_client.get("/metrics")
    assert res_m.status_code == 200
    m_data = res_m.json()
    assert "active_agents" in m_data
    assert m_data["system_status"] == "OPERATIONAL"
