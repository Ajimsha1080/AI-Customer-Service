# Enterprise STRIDE Threat Model

## 1. System Overview
Hospitality Agent Cloud is a multi-tenant AI concierge SaaS built with FastAPI, Next.js 14, PostgreSQL (pgvector), and Redis. It operates across multiple geographic regions with strict tenant isolation, envelope encryption, and customer data segregation.

---

## 2. Threat Analysis (STRIDE Model)

| Threat Category | Target Asset / Component | Threat Description | Implemented Mitigation | Verification / Test |
| :--- | :--- | :--- | :--- | :--- |
| **Spoofing** | API Endpoints & Auth Tokens | An attacker attempts to forge tenant identities or session JWTs to access another organization. | - Centralized cryptographic JWT verification (`HS256`/`RS256`).<br>- Scoped developer API keys prefixed with `hac_`, hashed with SHA-256.<br>- Remote session invalidation and token revocation table in DB and Redis. | `tests/test_phase_f1_identity.py`<br>`tests/test_phase_f5_integrations.py` |
| **Tampering** | Inbound Webhooks & Audit Trail | An attacker replays webhook events or alters administrative audit logs to conceal malicious activity. | - HMAC-SHA256 signature verification with 300-second timestamp tolerance on all outbound and inbound webhooks.<br>- Append-only, SHA-256 hash-chained audit log with runtime tampering detection (`prev_hash` validation). | `tests/test_phase_f2_data_protection.py`<br>`tests/test_phase_f5_integrations.py` |
| **Repudiation** | Operator Actions & Tenant Support | An operator or tenant denies performing critical actions (user deprovisioning, billing override, tenant data wipe). | - Immutable audit logging covering all user, admin, and platform operator events.<br>- Customer-approved support impersonation tokens time-boxed to 60m with mandatory `X-Support-Impersonation` banner. | `tests/test_phase_f1_identity.py`<br>`tests/test_phase_f4_observability.py` |
| **Information Disclosure** | PII, Guest Data & Vectors | Guest credit card details, phone numbers, or cross-tenant vectors leaking into logs, third-party LLMs, or other tenants. | - Automated PII masking (credit card PAN, CVV, phone, SSN, email) in logs, traces, and LLM prompts.<br>- Upstream LLM zero-retention headers (`X-Zero-Data-Retention: true`).<br>- KMS envelope encryption (AES-256-GCM) with optional BYOK.<br>- Tenant data residency boundary enforcement (`US`, `EU`, `IN`). | `tests/test_phase_f2_data_protection.py`<br>`tests/test_phase_f5_integrations.py` |
| **Denial of Service** | Public APIs & Worker Queues | A malicious or noisy tenant overwhelms endpoints or LLM provider rate limits, degrading service for other tenants. | - Atomic Lua Redis token bucket rate limiting per tenant and per API key, returning HTTP 429 with explicit `Retry-After`.<br>- Circuit breakers on all outbound dependencies (LLM, Stripe, WhatsApp).<br>- Background task worker with Dead-Letter Queue (DLQ) and exponential backoff retry. | `tests/test_phase_f3_reliability.py` |
| **Elevation of Privilege** | RBAC & Tenant Boundaries | A tenant staff member elevates privileges to organization admin, or a tenant accesses resources belonging to another tenant. | - Centralized RBAC policy layer (`require_permission`) and custom role definitions.<br>- Tenant ownership enforcement on every DB query filtering by `organization_id`. | `tests/test_phase_f1_identity.py`<br>`tests/test_tenant_security.py` |

---

## 3. AI Safety & LLM Specific Threats
1. **Prompt Injection & Jailbreaks**: User input is pre-screened with rule-based regex and pattern scanners (`services/ai/guardrails.py`) blocking instruction overrides, system prompt extraction, and role inversion.
2. **Cross-Tenant Vector Pollution**: pgvector similarity searches strictly filter on `organization_id == current_user.organization_id`.
3. **Hallucinated Bookings**: Model tool definitions strictly validate room availability and reservation dates server-side before persisting transactions.
