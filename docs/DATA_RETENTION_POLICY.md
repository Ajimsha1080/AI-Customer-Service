# Data Retention & GDPR Compliance Policy

## 📋 Overview

Hospitality Agent Cloud maintains strict multi-tenant isolation and GDPR compliance across data ingestion, storage, and processing.

---

## ⏳ Data Retention Schedule

| Data Category | Storage Location | Retention Period | Purge Trigger / Schedule |
|---|---|---|---|
| **Guest Conversation Logs** | PostgreSQL `conversations` & `messages` | 90 Days (Active), 365 Days (Archived) | Automated TTL job / Customer manual request |
| **RAG Knowledge Base Documents** | S3 / Local Disk & PGVector `document_chunks` | Perpetual until updated or deleted by Tenant | Deleted immediately upon Document/Agent deletion |
| **Audit Log History** | PostgreSQL `audit_logs` | 7 Years (Compliance & Security) | Immutable write-only append |
| **Telemetry & Usage Events** | PostgreSQL `usage_events` | 24 Months | Summarized monthly for billing |

---

## ⚖️ GDPR Rights & Data Control

1. **Right to Access / Data Portability**:  
   Tenant admins can invoke `GET /api/v1/organizations/{org_id}/export-data` at any time to receive a full structured archive of properties, agents, RAG documents, and conversation history.

2. **Right to Erasure (Right to be Forgotten)**:  
   Tenant admins can invoke `DELETE /api/v1/organizations/{org_id}/purge-data` to permanently hard-delete all properties, documents, embeddings, and conversation histories associated with their organization.
