# Data Processing Agreement (DPA) Template

**Effective Date**: September 18, 2026 (Updated for Enterprise Launch 2026.1)

This Data Processing Agreement ("DPA") governs the processing of Personal Data by **Hospitality Agent Cloud** ("Processor") on behalf of Subscriber ("Controller") in connection with the Hospitality Agent Cloud platform services.

---

## 1. Scope and Categories of Data
- **Categories of Data Subjects**: Hotel guests, resort residents, hospitality patrons, customer administrative staff.
- **Types of Personal Data**: Guest names, email addresses, telephone numbers, room numbers, reservation dates, chat interaction transcripts, voice audio transcripts, special guest preferences.

---

## 2. Processor Obligations
1. **Documented Instructions**: Processor shall process Personal Data solely on documented instructions from Controller, including with respect to transfers of personal data to third countries.
2. **Confidentiality & Access**: Processor ensures that persons authorized to process Personal Data have committed themselves to confidentiality or are under an appropriate statutory obligation of confidentiality.
3. **Technical & Organizational Security Measures**: Processor implements state-of-the-art security measures including:
   - Envelope encryption using AES-256-GCM with ephemeral Data Encryption Keys (DEKs).
   - Multi-tenant isolation enforced via PostgreSQL Row-Level Security (RLS) FORCE policies.
   - Zero-retention AI inference pipelines and automated real-time PII masking (`services/security/pii_masker.py`).
   - Append-only cryptographically hash-chained audit trails (`services/database/audit.py`).
4. **Sub-Processor Transparency**: Processor maintains an active, public sub-processor registry accessible at `GET /api/v1/compliance/subprocessors`. Processor shall notify Controller of any intended changes concerning the addition or replacement of sub-processors.
5. **Data Incident Notification**: Processor shall notify Controller without undue delay (and within 48 hours) upon becoming aware of a confirmed Personal Data breach.

---

## 3. Data Deletion, Portability & Audit Rights
1. **Data Portability**: Controller may at any time extract all tenant data via `POST /api/v1/compliance/organizations/{org_id}/export-bundle`.
2. **Data Subject Rights**: Controller may execute automated Data Subject Access Requests (DSAR) via `POST /api/v1/compliance/export` and erasure requests via `POST /api/v1/compliance/erase`.
3. **Termination Purge**: Upon termination of the SaaS agreement, Processor shall permanently purge Controller Personal Data via the retention purger engine (`POST /api/v1/compliance/retention/purge`).
4. **Audit Rights**: Processor shall make available to Controller all information necessary to demonstrate compliance with GDPR Article 28 obligations, including machine-verifiable audit logs via `GET /api/v1/compliance/audit-logs/export`.
