# Data Retention & GDPR Compliance Policy

## 1. Overview & Architectural Principles

Hospitality Agent Cloud maintains strict multi-tenant isolation, cryptographic auditability, and data subject rights enforcement in accordance with the EU General Data Protection Regulation (GDPR Art. 15 & 17) and the India Digital Personal Data Protection (DPDP) Act 2023.

---

## 2. Data Retention Schedule

| Data Category | Storage Location | Retention Period | Purge Trigger & Implementation |
| :--- | :--- | :--- | :--- |
| **Guest Conversations & Messages** | PostgreSQL `conversations` & `messages` | 90 Days (Active), 365 Days (Archived) | Automated retention purger job (`services/compliance/retention_purger.py`) |
| **RAG Knowledge Base & Embeddings** | S3 bucket & PGVector `document_chunks` | Perpetual until updated or removed | Hard-deleted immediately upon Document deletion |
| **Audit Log Trail** | PostgreSQL `audit_logs` | 7 Years (Compliance & Security) | Immutable write-only append with SHA-256 hash chaining |
| **Telemetry & Usage Events** | PostgreSQL `usage_events` | 24 Months | Summarized monthly for billing period verification |

---

## 3. Data Subject Rights & Programmatic Endpoints

All regulatory operations are exposed via authenticated, permission-gated REST API endpoints:

1. **Right to Access / Data Portability (GDPR Art. 15 / DPDP)**:
   - Endpoint: `POST /api/v1/compliance/export`
   - Authorization: `audit:read` permission required.
   - Behavior: Returns a complete, machine-readable JSON archive (`JSON-DSAR-v2`) of all guest conversations, messages, support tickets, and reservations linked to the requested phone number or email address.

2. **Right to Erasure / Right to be Forgotten (GDPR Art. 17)**:
   - Endpoint: `POST /api/v1/compliance/erase`
   - Authorization: `org:write` permission and explicit boolean confirmation required.
   - Behavior: Permanently hard-deletes all conversation messages, customer inquiries, and support tickets, while cryptographically anonymizing historical reservation records to preserve financial reporting without retaining personal identity.

3. **Tenant Data Export Bundle**:
   - Endpoint: `POST /api/v1/compliance/organizations/{org_id}/export-bundle`
   - Authorization: `org:write` permission for the specific tenant organization (or `SUPER_ADMIN`).
   - Behavior: Produces a cryptographically signed, complete export of tenant properties, agents, documents, and historical settings for customer offboarding or compliance audits.

4. **Retention Policy Purge with Legal Hold Protection**:
   - Endpoint: `POST /api/v1/compliance/retention/purge`
   - Authorization: `org:write` permission.
   - Behavior: Executes retention schedule purge across conversations and chunks older than the configured threshold (e.g. 90 days). If `legal_hold` is active on the organization or request, deletion is strictly aborted and logged to the tamper-evident audit trail.
