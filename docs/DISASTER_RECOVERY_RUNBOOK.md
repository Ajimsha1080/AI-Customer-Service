# Disaster Recovery & Database Backup Runbook

## 🎯 SLA Recovery Targets
- **Recovery Time Objective (RTO)**: < 1 Hour (Target time to restore full platform availability).
- **Recovery Point Objective (RPO)**: < 5 Minutes (Maximum acceptable data loss window via Postgres WAL archiving / Point-In-Time Recovery).

---

## 💾 Automated Postgres Backup Strategy

### 1. Daily Full Database Backups
Automated AWS RDS snapshot taken daily at 02:00 UTC, retained for 30 days.

### 2. Continuous Transaction Log Archiving (WAL / PITR)
Point-In-Time Recovery enabled on Aurora PostgreSQL / AWS RDS with 7-day continuous restore capability to any second.

---

## 🛠️ Step-by-Step Restoration Procedure

```bash
# 1. Restore PostgreSQL database to a new instance from PITR timestamp
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier hospitality-agent-db-production \
  --target-db-instance-identifier hospitality-agent-db-restored \
  --restore-time 2026-09-18T12:00:00.000Z

# 2. Update Database URL secret in Secrets Manager
aws secretsmanager update-secret \
  --secret-id /hospitality-agent-cloud/production/DATABASE_URL \
  --secret-string "postgresql+asyncpg://postgres:secret@hospitality-agent-db-restored:5432/hospitality_agent_cloud"

# 3. Trigger ECS Task Definition redeployment to pick up restored database connection
aws ecs update-service \
  --cluster hospitality-agent-cluster \
  --service api-service \
  --force-new-deployment
```
