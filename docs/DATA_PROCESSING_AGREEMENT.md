# Data Processing Agreement (DPA) Template

**Effective Date**: September 18, 2026

This Data Processing Agreement ("DPA") governs the processing of Personal Data by **Hospitality Agent Cloud** ("Processor") on behalf of Subscriber ("Controller") in connection with the Hospitality Agent Cloud platform services.

---

## 1. Scope and Categories of Data
- **Categories of Data Subjects**: Hotel guests, resort residents, property visitors, customer employees.
- **Types of Personal Data**: Guest names, email addresses, phone numbers, room numbers, chat interaction history, voice audio transcripts, special guest preferences.

---

## 2. Processor Obligations
1. **Instruction**: Processor shall process Personal Data solely on documented instructions from Controller.
2. **Confidentiality**: Processor ensures personnel authorized to process Personal Data are committed to confidentiality.
3. **Security Measures**: Processor maintains technical and organizational measures (Argon2id auth, tenant scoping, SQL encryption, TLS 1.3).
4. **Data Incident Notification**: Processor shall notify Controller without undue delay (and within 48 hours) upon becoming aware of a confirmed Personal Data breach.

---

## 3. Data Deletion & Audit Rights
Upon termination of the SaaS agreement, Processor shall permanently purge Controller Personal Data via automated purge workflows (`DELETE /api/v1/organizations/{id}/purge-data`).
