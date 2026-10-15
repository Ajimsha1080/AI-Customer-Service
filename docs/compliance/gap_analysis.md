# Enterprise Compliance Gap Analysis & Control-to-Code Mapping

## 1. Executive Summary & External Audit Disclaimer

This document establishes the formal compliance posture and control-to-code mapping for **Hospitality Agent Cloud (HAC)**. 

> [!IMPORTANT]
> **Mandatory External Audit Disclaimer**:
> While all technical mechanisms and automated evidence collectors in this document are 100% implemented and programmatically verified in the codebase, **SOC 2 Type II, ISO/IEC 27001:2022, and HIPAA compliance cannot be achieved by software implementation alone**. Full attestation requires:
> 1. An independent examination by an accredited third-party CPA auditing firm (e.g., Schellman, A-LIGN, Coalfire) over a mandatory 3-to-6 month observation period.
> 2. Operational human policies, physical office controls, and annual third-party external penetration tests.
> 3. Bilateral execution of Business Associate Agreements (BAAs) and Data Processing Agreements (DPAs).

---

## 2. Comprehensive Control-to-Code Mapping Matrix

The following matrix maps regulatory standards (SOC 2 Type II Trust Services Criteria, HIPAA Security Rule, GDPR/DPDP, and ISO 27001:2022) directly to production source files and automated verification suites:

| Domain / Standard | Control Reference | Security Objective | Production Code Module | Verification Test Suite |
| :--- | :--- | :--- | :--- | :--- |
| **Identity & Access** | SOC 2 CC6.1, CC6.2<br>ISO 27001 A.9.2 | SAML 2.0 & OIDC SSO with XML Signature validation, cert pinning, and domain gating | `apps/api/routers/sso.py`<br>`apps/api/routers/auth.py` | `tests/test_phase0_launch_blockers.py`<br>`tests/test_phase_e2e_compliance.py` |
| **Authentication** | SOC 2 CC6.1<br>HIPAA §164.312(a)(1) | RFC 6238 TOTP MFA, single-use reset tokens, constant-time responses, brute-force lockout | `apps/api/routers/mfa.py`<br>`services/security/password_policy.py` | `tests/test_phase0_launch_blockers.py`<br>`tests/test_phase_e2e_compliance.py` |
| **Authorization** | SOC 2 CC6.3<br>ISO 27001 A.9.4 | Granular RBAC, custom roles, permission enforcement (`require_permission`) | `apps/api/auth.py`<br>`apps/api/routers/custom_roles.py` | `tests/test_phase_e2e_compliance.py`<br>`tests/test_phase_f5_integrations.py` |
| **Multi-Tenancy** | SOC 2 CC6.6<br>GDPR Art. 32 | Postgres Row-Level Security (RLS) FORCE policies, zero cross-tenant leakages | `services/database/session.py`<br>`alembic/versions/*.py` | `tests/test_phase3_infrastructure.py`<br>`tests/test_phase_tenant_isolation.py` |
| **Data Encryption** | SOC 2 CC6.1<br>HIPAA §164.312(a)(2)(iv) | Envelope encryption with AES-256-GCM, ephemeral DEKs, BYOK support, TLS 1.3 | `services/security/encryption.py` | `tests/test_phase_f5_integrations.py`<br>`tests/test_phase_e2e_compliance.py` |
| **Audit & Integrity** | SOC 2 CC7.1<br>HIPAA §164.312(b) | Append-only SHA-256 hash-chained audit logs, tamper verification, SIEM export | `services/database/audit.py`<br>`apps/api/routers/gdpr.py` | `tests/test_phase_e2e_compliance.py`<br>`tests/test_phase1_wired_modules.py` |
| **AI Safety** | ISO 42001<br>OWASP LLM01 | Prompt injection detection, banned topic enforcement, output PII leak check | `services/ai/guardrails.py` | `tests/test_phase1_wired_modules.py`<br>`tests/test_phase3_agent_behavior.py` |
| **Data Privacy** | GDPR Art. 5, 17<br>HIPAA §164.502 | Automated PII masking (credit cards, CVV, SSN) before logs, storage, or LLM egress | `services/security/pii_masker.py` | `tests/test_phase1_wired_modules.py` |
| **Data Residency** | GDPR Art. 44<br>DPDP Act 2023 | Sovereign tenant region gating (US, EU, IN, APAC) on DB, vector, and LLM endpoints | `services/security/data_residency.py` | `tests/test_phase1_wired_modules.py` |
| **Data Retention** | GDPR Art. 17<br>SOC 2 A1.2 | Automated retention purge honoring legal holds with cryptographic erasure proof | `services/compliance/retention_purger.py`<br>`apps/api/routers/gdpr.py` | `tests/test_phase1_wired_modules.py` |
| **Resilience & Fair Use** | SOC 2 A1.1<br>ISO 27001 A.12.1 | Per-tenant token-bucket rate limiting (Redis 429 Retry-After), SlowAPI middleware | `services/resilience/tenant_limiter.py`<br>`apps/api/main.py` | `tests/test_phase1_wired_modules.py`<br>`tests/test_phase3_infrastructure.py` |
| **Fault Tolerance** | SOC 2 A1.2<br>ISO 27001 A.17.1 | Circuit breakers, automatic multi-provider LLM failover, graceful degradation | `services/ai/resilience_router.py`<br>`services/resilience/circuit_breaker.py` | `tests/test_phase1_wired_modules.py`<br>`tests/test_phase3_infrastructure.py` |
| **Data Portability** | GDPR Art. 15, 20<br>DPDP Act 2023 | Machine-readable DSAR export, full tenant data bundle export | `apps/api/routers/gdpr.py`<br>`services/operations/tenant_export.py` | `tests/test_phase_e2e_compliance.py` |
| **Boundary Protection** | SOC 2 CC6.6<br>ISO 27001 A.13.1 | AWS WAFv2, Security headers (HSTS, CSP, nosniff, DENY), K8s NetworkPolicies | `apps/api/middleware/security_headers.py`<br>`infra/terraform/main.tf` | `tests/test_phase3_infrastructure.py` |
| **Disaster Recovery** | SOC 2 A1.2<br>ISO 27001 A.12.3 | AES-256-GCM encrypted snapshot backups, automated PITR restore drills | `scripts/backup_restore_drill.py` | `tests/test_phase3_infrastructure.py` |

---

## 3. Compliance Gap List & External Audit Roadmap

### Section A: Technical Controls Implemented & Verified (Done)
- [x] **0.1 SAML 2.0 & OIDC SSO**: Full XML digital signature verification against IdP X.509 certificates, replay protection, domain verification, and tenant isolation.
- [x] **0.2 Credential Protection**: Single-use tokens, PBKDF2/Argon2id password hashing, timing-safe anti-enumeration verification.
- [x] **0.3 Audited Email Delivery**: Provider abstraction supporting AWS SES, SendGrid, and SMTP with automatic retries and webhook processing.
- [x] **1.0 Enterprise Middleware Wiring**: All 10 security and operations modules wired to active runtime paths with unit and integration tests.
- [x] **2.1 Billing & Entitlements**: Concurrency-safe row-level locking (`with_for_update()`) on usage counters reset on billing period boundaries.
- [x] **2.2 Database Migrations & RLS**: Alembic forward migrations for pgvector, HNSW indexing, and RLS FORCE policies on multi-tenant tables.
- [x] **2.3 Real-Time Health & Telemetry**: Dynamic `/ready` and `/platform/telemetry` verifying active DB, Redis, and vector store connections (503 on degradation).
- [x] **3.1 Cloud Infrastructure as Code**: Production Terraform specifications for AWS WAF, HTTPS 443 listeners, ECS autoscaling, and S3 public access blocks.
- [x] **3.3 Hardened Containers**: Minimal Python 3.12-slim and Node 20 LTS Alpine base images with non-root security contexts (`appuser`/`nextjs`).
- [x] **3.4 CI/CD Verification**: Automated security scanning pipelines (Gitleaks, pip-audit, npm audit, Trivy, Ruff, Mypy, ESLint, TypeScript).

### Section B: Operational & External Prerequisites (Roadmap to Attestation)

The following operational milestones require human execution, legal engagement, and external third-party auditors:

| Requirement | Category | Responsible Party | Estimated Timeline | Status |
| :--- | :--- | :--- | :--- | :--- |
| **CPA SOC 2 Type II Audit** | External Audit | AICPA Accredited CPA Firm (e.g. Schellman) | 3–6 Month Observation Window | Pending Audit Engagement |
| **ISO/IEC 27001:2022 Certification** | External Audit | Accredited Registrar (e.g. BSI, TÜV SÜD) | Stage 1 & Stage 2 Audits (2–4 months) | Ready for Stage 1 Review |
| **CREST External Penetration Test** | Security Attestation | Independent CREST-certified testing firm | Annual (2 weeks) | Scheduled Pre-Launch |
| **Enterprise BAA Sign-Off** | Legal / Operational | Legal Counsel & Customer Compliance Officers | On-demand per Enterprise Contract | Legal Template Ready |
| **Employee Security Training** | Operational | Human Resources / Security Operations | Continuous / Annual Recertification | Platform Selected (KnowBe4) |
| **Background Checks** | Operational | Human Resources / Checkr | Prior to personnel onboarding | Operational Policy Enacted |
