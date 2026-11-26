import pytest
import json
import logging
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.middleware.tracing import (
    extract_trace_id,
    extract_tenant_id,
    setup_opentelemetry
)

@pytest.mark.asyncio
async def test_p6_structured_json_logging_and_trace_headers(caplog):
    transport = ASGITransport(app=app)
    caplog.set_level(logging.INFO, logger="hospitality_agent_cloud.access")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request with explicit W3C traceparent and tenant header
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        res = await client.get(
            "/health/live",
            headers={
                "traceparent": traceparent,
                "X-Tenant-ID": "org_p6_tenant_test"
            }
        )

        assert res.status_code == 200
        assert "X-Trace-ID" in res.headers
        assert res.headers["X-Trace-ID"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert "X-Request-ID" in res.headers

        # Verify structured JSON log contains trace_id and tenant_id
        matching_logs = []
        for record in caplog.records:
            if record.name == "hospitality_agent_cloud.access":
                try:
                    data = json.loads(record.message)
                    matching_logs.append(data)
                except Exception:
                    pass

        assert len(matching_logs) > 0, "Access log must be emitted in JSON"
        latest_log = matching_logs[-1]
        assert latest_log.get("trace_id") == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert latest_log.get("tenant_id") == "org_p6_tenant_test"
        assert latest_log.get("method") == "GET"
        assert latest_log.get("path") == "/health/live"
        assert latest_log.get("status_code") == 200
        assert "latency_ms" in latest_log

def test_p6_opentelemetry_setup():
    res = setup_opentelemetry(app, service_name="test-hac-observability")
    assert isinstance(res, bool)

@pytest.mark.asyncio
async def test_p6_health_endpoints_and_metrics_access():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Live probe
        r_live = await client.get("/health/live")
        assert r_live.status_code == 200
        assert r_live.json().get("status") == "alive"

        # 2. Startup probe
        r_start = await client.get("/health/startup")
        assert r_start.status_code == 200
        assert r_start.json().get("status") == "started"

        # 3. Ready probe
        r_ready = await client.get("/health/ready")
        assert r_ready.status_code in [200, 503]

        # 4. Internal /metrics allows loopback/internal client
        r_metrics = await client.get("/metrics")
        assert r_metrics.status_code == 200
