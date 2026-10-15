# SOC 2 Type II & HIPAA Compliance Control Matrix

## 1. Overview & Audit Disclaimer
This document specifies the technical and organizational security controls implemented within Hospitality Agent Cloud (HAC) to satisfy American Institute of CPAs (AICPA) SOC 2 Type II Trust Services Criteria (Security, Availability, Confidentiality) and the Health Insurance Portability and Accountability Act (HIPAA) Security Rule (§ 164.308, § 164.312).

> [!IMPORTANT]
> **External Audit Requirement**: Implementation of technical controls within the codebase provides technical readiness and evidence generation capability only. Formal SOC 2 Type II attestation, ISO/IEC 27001 certification, and HIPAA compliance require independent examination, verification, and audit sign-off by an accredited external CPA auditing firm over a formal 3- to 6-month observation period.

---

## 2. SOC 2 Type II Trust Services Criteria Mapping

| Criterion | Control Summary | Implementation Module | Verification Evidence |
| :--- | :--- | :--- | :--- |
| **CC6.1** | Envelope Encryption at Rest | `services/security/encryption.py` | AES-256-GCM envelope encryption, tenant BYOK store, DEK ephemeral key rotation. |
| **CC6.2** | Multi-Factor Authentication & Access Control | `apps/api/routers/mfa.py`, `services/security/password_policy.py` | TOTP (RFC 6238), backup recovery codes, account lockout after 5 failures, breach detection. |
| **CC6.3** | Least Privilege & Granular RBAC | `apps/api/auth.py`, `apps/api/routers/custom_roles.py` | Central permission check (`require_permission`), custom roles per tenant, audited support impersonation. |
| **CC6.6** | Edge & Transport Boundary Protection | `apps/api/middleware/security_headers.py` | HSTS `max-age=63072000`, strict CSP, nosniff, DENY frame options, Permissions-Policy. |
| **CC6.7** | Secure API & Integration Keys | `apps/api/routers/developer.py`, `services/integrations/webhooks.py` | Scoped API keys hashed with SHA-256, customer webhooks signed with HMAC-SHA256 (`t=...,v1=...`). |
| **CC7.1** | Append-Only Immutable Audit Trail | `services/database/audit.py`, `apps/api/routers/gdpr.py` | Append-only SHA-256 hash chaining (`prev_hash`, `hash`), cryptographic tamper detection before SIEM export. |
| **CC7.2** | Vulnerability Disclosure Policy | `apps/api/routers/health.py` | RFC 9116 `/.well-known/security.txt` published with contact and expiration. |
| **A1.2** | Disaster Recovery & Backup Integrity | `scripts/backup_restore_drill.py` | Encrypted snapshot replication, automated PITR restore drills (Target RTO < 15m, RPO < 5m on AWS RDS; drill verified in automated container runs). |

---

## 3. HIPAA Security Rule Mapping

| Standard | Description | HAC Technical Implementation |
| :--- | :--- | :--- |
| **§ 164.312(a)(1)** | Access Control & Unique User Identification | Per-user UUIDs, RFC 7519 `jti` uniqueness, idle timeout (60m) and absolute timeout (24h) via `user_sessions`. |
| **§ 164.312(a)(2)(iv)**| Encryption and Decryption | Envelope encryption AES-256-GCM for guest PII (names, phone numbers, reservation notes). |
| **§ 164.312(b)** | Audit Controls | Every authentication event, privilege escalation, data export, and erasure recorded in tamper-proof hash chain. |
| **§ 164.312(c)(1)** | Integrity Controls | Inbound requests deduplicated via `Idempotency-Key`; resource versions protected via ETag (`If-Match`). |
| **§ 164.312(e)(1)** | Transmission Security | TLS 1.3 only, HSTS preload, zero guest PII forwarded to third-party LLMs without zero-retention headers (`X-Zero-Data-Retention: true`). |
| **§ 164.502** | Minimum Necessary Disclosure | Automated PII redaction engine (`services/security/pii_masker.py`) removes credit cards, CVVs, SSNs from logs, traces, and LLM prompts. |

---

## 4. Automated Audit Procedure
Compliance auditors can verify platform controls at any time by running:
```bash
python scripts/compliance_evidence_collector.py
```
This produces the signed JSON evidence pack with live cryptographic validation results.
