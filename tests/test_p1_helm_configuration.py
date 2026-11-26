import pytest
import yaml
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from apps.api.main import app

HELM_DIR = Path(__file__).parent.parent / "infra" / "helm" / "hospitality-agent"
VALUES_FILE = HELM_DIR / "values.yaml"
DEPLOYMENT_FILE = HELM_DIR / "templates" / "deployment.yaml"
PDB_FILE = HELM_DIR / "templates" / "pdb.yaml"
NETPOL_FILE = HELM_DIR / "templates" / "networkpolicy.yaml"

def test_p1_helm_values_configuration():
    assert VALUES_FILE.exists(), "values.yaml must exist in Helm chart"
    with open(VALUES_FILE, "r", encoding="utf-8") as f:
        values = yaml.safe_load(f)

    # API Replicas
    assert values.get("replicaCount") == 3, "Production Helm chart must run 3 API replicas"
    
    # Worker Replicas & Resources
    worker = values.get("worker", {})
    assert worker.get("replicaCount") == 3, "Worker deployment must run 3 replicas"
    assert worker.get("resources", {}).get("limits", {}).get("memory") == "2Gi"
    assert worker.get("resources", {}).get("requests", {}).get("cpu") == "250m"

    # Security Context: Non-root user 10001
    sec_ctx = values.get("securityContext", {})
    assert sec_ctx.get("runAsNonRoot") is True, "Must enforce runAsNonRoot"
    assert sec_ctx.get("runAsUser") == 10001, "Must run as dedicated non-root UID 10001"
    assert sec_ctx.get("allowPrivilegeEscalation") is False, "Must forbid privilege escalation"

    # PodDisruptionBudget minAvailable >= 2
    pdb = values.get("podDisruptionBudget", {})
    assert pdb.get("minAvailable") == 2, "PodDisruptionBudget minAvailable must be at least 2"

    # HPA metrics
    hpa = values.get("autoscaling", {})
    assert hpa.get("minReplicas") == 3
    assert hpa.get("targetCPUUtilizationPercentage") == 70
    assert hpa.get("targetMemoryUtilizationPercentage") == 80

    # Health Probes
    probes = values.get("probes", {})
    assert probes.get("liveness", {}).get("path") == "/health/live"
    assert probes.get("readiness", {}).get("path") == "/health/ready"
    assert probes.get("startup", {}).get("path") == "/health/startup"

def test_p1_helm_deployment_templates():
    with open(DEPLOYMENT_FILE, "r", encoding="utf-8") as f:
        deploy_yaml = f.read()

    assert "hospitality-agent-api" in deploy_yaml
    assert "hospitality-agent-worker" in deploy_yaml
    assert "HorizontalPodAutoscaler" in deploy_yaml
    assert "runAsNonRoot" in deploy_yaml
    assert "allowPrivilegeEscalation" in deploy_yaml
    assert "startupProbe" in deploy_yaml
    assert "livenessProbe" in deploy_yaml
    assert "readinessProbe" in deploy_yaml

def test_p1_helm_network_policy():
    with open(NETPOL_FILE, "r", encoding="utf-8") as f:
        netpol_yaml = f.read()

    assert "NetworkPolicy" in netpol_yaml
    assert "5432" in netpol_yaml  # Postgres
    assert "6379" in netpol_yaml  # Redis
    assert "443" in netpol_yaml   # HTTPS external egress

@pytest.mark.asyncio
async def test_p1_health_probe_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Liveness probe
        res_live = await client.get("/health/live")
        assert res_live.status_code == 200
        assert res_live.json().get("status") == "alive"

        # Startup probe
        res_startup = await client.get("/health/startup")
        assert res_startup.status_code == 200
        assert res_startup.json().get("status") == "started"

        # Readiness probe
        res_ready = await client.get("/health/ready")
        assert res_ready.status_code in [200, 503]
