import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from scripts.compliance_evidence_collector import collect_compliance_evidence

client = TestClient(app)

def test_enterprise_security_headers_and_csp():
    """F7.1 Enterprise HTTP security headers: HSTS, strict CSP, nosniff, DENY frame options, and Permissions-Policy."""
    response = client.get("/health")
    assert response.status_code == 200

    headers = response.headers

    # 1. HSTS with preload
    assert "Strict-Transport-Security" in headers
    assert "max-age=63072000" in headers["Strict-Transport-Security"]
    assert "includeSubDomains" in headers["Strict-Transport-Security"]
    assert "preload" in headers["Strict-Transport-Security"]

    # 2. Content Security Policy (CSP)
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp

    # 3. MIME sniffing protection
    assert headers.get("X-Content-Type-Options") == "nosniff"

    # 4. Clickjacking protection
    assert headers.get("X-Frame-Options") == "DENY"

    # 5. Referrer Policy
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    # 6. Permissions Policy
    assert "Permissions-Policy" in headers
    assert "camera=()" in headers["Permissions-Policy"]
    assert "geolocation=()" in headers["Permissions-Policy"]


def test_rfc9116_security_txt():
    """F7.2 RFC 9116 Vulnerability Disclosure Policy at /.well-known/security.txt."""
    response = client.get("/.well-known/security.txt")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

    body = response.text
    assert "Contact: mailto:security@hospitalitycloud.com" in body
    assert "Expires:" in body
    assert "Preferred-Languages: en" in body
    assert "Canonical:" in body


@pytest.mark.asyncio
async def test_soc2_hipaa_compliance_evidence_collector():
    """F7.3 Automated SOC 2 Type II and HIPAA control evidence collection script."""
    evidence = await collect_compliance_evidence()
    assert evidence["report_id"] == "SOC2_HIPAA_EVIDENCE_PACK_2026"
    assert "generated_at" in evidence

    controls = evidence["controls"]
    # CC6.1 Encryption at rest
    assert controls["CC6.1_ENCRYPTION_AT_REST"]["status"] == "PASS"
    assert controls["CC6.1_ENCRYPTION_AT_REST"]["algorithm"] == "AES-256-GCM"

    # CC6.2 MFA Enforcement
    assert controls["CC6.2_MFA_ENFORCEMENT"]["status"] == "PASS"

    # CC6.3 Granular RBAC
    assert controls["CC6.3_GRANULAR_RBAC"]["status"] == "PASS"

    # CC7.1 Append-only Immutable Audit Trail
    assert controls["CC7.1_IMMUTABLE_AUDIT_TRAIL"]["status"] == "PASS"
    assert controls["CC7.1_IMMUTABLE_AUDIT_TRAIL"]["integrity_mechanism"] == "Cryptographic SHA-256 Hash Chaining"

    # A1.2 Backups and DR
    assert controls["A1.2_BACKUPS_AND_PITR"]["status"] == "PASS"

    # HIPAA Transmission Security & Zero Retention
    assert controls["HIPAA_164.312_TRANSMISSION_SECURITY"]["status"] == "PASS"
    assert controls["HIPAA_164.502_AI_ZERO_RETENTION"]["status"] == "PASS"
    assert controls["HIPAA_164.502_AI_ZERO_RETENTION"]["upstream_zero_retention_flag"] == "X-Zero-Data-Retention: true"
