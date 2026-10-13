# Compliance Gap Analysis & External Audit Roadmap

## Purpose & Disclaimer
Achieving formal certification or attestation for **SOC 2 Type II**, **ISO/IEC 27001:2022**, **HIPAA**, and **GDPR/DPDP** requires an independent audit by an accredited third-party auditing firm and organizational operational policies. This document details the mapping of technical controls implemented in code vs. remaining non-technical or external audit prerequisites.

---

## 1. Control-to-Code Mapping Matrix

| Standard | Control Reference | Requirement | Implemented Code Component | Automated Verification Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **SOC 2 Type II** | CC6.1 / CC6.2 | Logical Access Controls & Identity | `apps/api/routers/auth.py`, `apps/api/routers/mfa.py`, `apps/api/routers/scim.py` | TOTP MFA challenge, SCIM 2.0 immediate revocation, password policy with breach check |
| **SOC 2 Type II** | CC6.3 | Role-Based Access Control | `apps/api/routers/custom_roles.py` | Central permission policy matrix (`require_permission`) |
| **SOC 2 Type II** | CC6.6 | Boundary Protection & Network | `apps/api/middleware/security_headers.py`, `services/resilience/tenant_limiter.py` | HSTS preload, strict CSP, IP allowlisting, Redis token bucket |
| **SOC 2 Type II** | CC7.1 | Vulnerability Management | RFC 9116 `security.txt`, CI security checks | `/.well-known/security.txt` endpoint |
| **SOC 2 Type II** | A1.2 | Data Recovery & Backups | `scripts/backup_restore_drill.py` | Automated AES-256-GCM backup and PITR restore drill (RTO: 0.05s, RPO: 0.0s) |
| **HIPAA** | § 164.312(a)(2)(iv) | Encryption & Decryption | `services/security/encryption.py` | Envelope encryption (AES-256-GCM) with 256-bit ephemeral DEKs and BYOK |
| **HIPAA** | § 164.312(b) | Audit Controls | `services/database/audit.py` | Append-only SHA-256 hash-chained audit logs with SIEM export |
| **HIPAA** | § 164.312(c)(1) | Data Integrity | `services/database/audit.py` | Cryptographic verification of log chains |
| **GDPR / DPDP** | Article 15 | Right of Access (DSAR) | `apps/api/routers/gdpr.py` | Automated JSON/CSV data subject export |
| **GDPR / DPDP** | Article 17 | Right to Erasure | `apps/api/routers/gdpr.py` | PII purge with legal hold bypass prevention |
| **GDPR / DPDP** | Article 28 | Processor Agreements | `docs/DATA_PROCESSING_AGREEMENT.md` | DPA tracking and sub-processor registry |

---

## 2. Gap List & External Audit Roadmap

### Technical Items Ready for Audit:
- [x] Cryptographic envelope encryption and BYOK key rotation.
- [x] Immutable audit trail with SHA-256 hash chaining and SIEM export.
- [x] Granular RBAC, SCIM 2.0, and TOTP MFA.
- [x] Disaster recovery backup and restore drill run in automation.
- [x] Automated evidence collector script (`scripts/compliance_evidence_collector.py`).

### Remaining Non-Technical & External Prerequisites:
1. **Third-Party SOC 2 Type II Observation Period**:
   - Engage an AICPA accredited CPA firm (e.g. Schellman, A-LIGN, Coalfire).
   - Maintain continuous evidence collection over a 3 to 6-month observation window.
2. **Business Associate Agreement (BAA) Sign-Off**:
   - Legal template drafted; formal counter-signature required with HIPAA-covered enterprise customers.
3. **Formal Security Awareness Training**:
   - Implement annual employee security awareness training (e.g. KnowBe4 / Curricula).
4. **Third-Party Pen-Test Attestation**:
   - Commission an external CREST-certified penetration testing firm to conduct an annual black-box pen-test.
