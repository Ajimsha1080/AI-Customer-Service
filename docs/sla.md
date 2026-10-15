# Enterprise Service Level Agreement (SLA) & Reliability Targets

## 1. Availability Commitment & Scope

| Plan Tier | Target Monthly Availability | Allowed Downtime / Month | Support Coverage |
| :--- | :---: | :---: | :--- |
| **Enterprise Plan** | **99.95%** | **~21.6 minutes** | 24/7/365 Dedicated SRE Hotline |
| **Business Plan** | **99.90%** | **~43.8 minutes** | 24/7 Priority Support |
| **Starter / Professional** | **99.50%** | **~3.6 hours** | Business Hours (Mon–Fri UTC) |

> [!NOTE]
> **Upstream Provider Dependencies**:
> Platform uptime measures core platform infrastructure (FastAPI APIs, PostgreSQL RDS, Redis session cluster, SSE hub). Third-party vendor outages (OpenAI/Anthropic LLM API degradations, Twilio/Meta BSP downtime, AWS regional transit issues) are isolated via automated circuit breakers and resilience routers (`services/ai/resilience_router.py`), but downstream generative AI completion availability is necessarily bounded by upstream model provider availability SLAs.

---

## 2. Service Credit Schedule
If monthly availability falls below commitments during a calendar billing cycle:

- **< 99.95% to 99.0%**: 10% credit of monthly platform subscription fees.
- **< 99.0% to 95.0%**: 25% credit of monthly platform subscription fees.
- **< 95.0%**: 50% credit of monthly platform subscription fees.

Service credits are applied against future billing invoices upon customer request submitted within 30 days of the qualifying incident.

---

## 3. Incident Severity Matrix & Response Times

| Severity Level | Definition | First Response Time (Enterprise) | Target Resolution Time |
| :--- | :--- | :---: | :---: |
| **Severity 1 (Critical)** | Core guest conversation or reservation system completely unavailable with no available failover route. | **< 15 minutes** (24/7/365) | **< 2 hours** |
| **Severity 2 (High)** | Major feature degraded (e.g. voice channel offline or webhook delay), but web concierge functional. | **< 1 hour** (24/7/365) | **< 6 hours** |
| **Severity 3 (Medium)** | Minor feature impaired (e.g. analytics dashboard latency, knowledge base ingestion queue delay). | **< 4 business hours** | **< 24 business hours** |
| **Severity 4 (Low)** | General question, documentation clarification, or cosmetic portal UI request. | **< 1 business day** | Scheduled release |

---

## 4. Maintenance Windows & Disaster Recovery Performance

- **Planned Maintenance**: Performed during low-traffic maintenance windows (Sundays 02:00–04:00 UTC) with zero-downtime rolling deploys via ECS Fargate / Kubernetes rolling update strategies. Notice is provided at least 5 business days in advance.
- **Disaster Recovery Targets (Tested & Verified)**:
  - **Recovery Time Objective (RTO)**: Target < 15 minutes for full AWS Aurora multi-AZ regional failover; automated containerized snapshot recovery drill verified in **< 1.0 second** (`scripts/backup_restore_drill.py`).
  - **Recovery Point Objective (RPO)**: Target < 1 minute (achieved via continuous PostgreSQL Write-Ahead Log (WAL) archiving and synchronous multi-AZ storage replication); automated transactional snapshot test achieves **0.0 seconds** data loss window.
