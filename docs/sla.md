# Enterprise Service Level Agreement (SLA)

## 1. Availability Commitment

| Plan Tier | Target Monthly Availability | Error Budget / Month |
| :--- | :---: | :---: |
| **Enterprise Plan** | **99.95%** | **~21.6 minutes** |
| **Business Plan** | **99.90%** | **~43.8 minutes** |
| **Starter / Professional** | **99.50%** | **~3.6 hours** |

Uptime is continuously monitored and reported via live public status at `https://status.yourdomain.com`.

---

## 2. Service Credit Schedule
If monthly availability falls below commitments:

- **< 99.95% to 99.0%**: 10% credit of monthly billing fees.
- **< 99.0% to 95.0%**: 25% credit of monthly billing fees.
- **< 95.0%**: 50% credit of monthly billing fees.

---

## 3. Support Response Severity Matrix

| Severity Level | Definition | First Response Time (Enterprise) | Target Resolution Time |
| :--- | :--- | :---: | :---: |
| **Severity 1 (Critical)** | Core guest conversation or reservation system completely unavailable with no workaround. | **< 15 minutes** (24/7/365) | **< 2 hours** |
| **Severity 2 (High)** | Major feature degraded (e.g. voice channel offline or webhook delay), but web chat functional. | **< 1 hour** (24/7/365) | **< 6 hours** |
| **Severity 3 (Medium)** | Minor feature impaired (e.g. report download slow, knowledge base ingestion queue delay). | **< 4 business hours** | **< 24 business hours** |
| **Severity 4 (Low)** | General question, enhancement request, or cosmetic issue. | **< 1 business day** | Scheduled release |

---

## 4. Maintenance Windows & Disaster Recovery
- **Planned Maintenance**: Performed during low-traffic windows (Sundays 02:00–04:00 UTC) with zero-downtime rolling deploys. Notice provided at least 5 business days in advance.
- **Disaster Recovery Targets**:
  - **Recovery Time Objective (RTO)**: < 15 minutes
  - **Recovery Point Objective (RPO)**: < 1 minute (Synchronous streaming replication with PITR)
