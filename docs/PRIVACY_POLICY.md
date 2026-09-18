# Privacy Policy & Data Protection Compliance

**Last Updated**: September 18, 2026

---

## 🌐 Global Data Protection Overview

Hospitality Agent Cloud respects the privacy of our subscribers and guest end-users. This policy details our processing of Personally Identifiable Information (PII) under international regulations, specifically the **Digital Personal Data Protection (DPDP) Act, 2023 (India)** and the **General Data Protection Regulation (GDPR - EU)**.

---

## 🇮🇳 DPDP Act 2023 (India) Compliance
Because Hospitality Agent Cloud processes Indic-language guest data (Malayalam, Hindi, Tamil, Telugu, Kannada) for hospitality properties operating in India:
1. **Data Fiduciary & Processor Roles**: Hospitality properties act as Data Fiduciaries; Hospitality Agent Cloud acts as Data Processor.
2. **Consent & Purpose Limitation**: Guest data (name, phone number, chat transcripts, voice audio) is processed solely for assisting guest stays, bookings, and customer service.
3. **Data Principal Rights**: Guests retain rights to access, correction, and erasure of personal data upon request to the property.

---

## 🇪🇺 GDPR (EU) Compliance
For European hospitality properties and EU guests:
1. **Lawful Basis for Processing**: Processing is necessary for the performance of hospitality booking contracts and legitimate business operations.
2. **Data Export & Deletion**: Tenant admins can invoke `GET /api/v1/organizations/{id}/export-data` and `DELETE /api/v1/organizations/{id}/purge-data` at any time.
3. **Sub-processors**: Infrastructure sub-processors include AWS (Cloud hosting/RDS), Stripe (Payment processing), and Sarvam AI / OpenAI (AI model execution).

---

## 🔐 Security Standards
- **Encryption in Transit**: TLS 1.3 across all REST APIs and webhooks.
- **Encryption at Rest**: AES-256 for database volumes and vector stores.
