# Hospitality Agent Cloud — Deployment Architecture & Targets

## 1. Primary Deployment Target: AWS ECS Fargate
The primary, canonical production deployment target for Hospitality Agent Cloud is **AWS ECS Fargate**, configured and provisioned declaratively via Terraform in [main.tf](file:///c:/Users/91730/Downloads/Aaas%20deplo/infra/terraform/main.tf).

### Core Components
- **Orchestration**: AWS ECS Cluster with Fargate Serverless Compute.
  - **API Service**: `api-service` running 3–20 replicas with CPU-based TargetTracking autoscaling (70% utilization target).
  - **Worker Service**: `worker-service` running 2 background worker replicas executing asynchronous data retention purges, email dispatch queues, and quota audits.
- **Ingress & Load Balancing**: AWS Application Load Balancer (ALB).
  - HTTP (Port 80) automatically redirects to HTTPS (Port 443) with HTTP 301.
  - HTTPS (Port 443) terminates TLS 1.3 (`ELBSecurityPolicy-TLS13-1-2-2021-06`) via AWS Certificate Manager (ACM).
  - Health checks route to `/ready` with interval 15s and 30s timeout.
- **Security & Perimeter**:
  - AWS WAFv2 regional Web ACL (`AWSManagedRulesCommonRuleSet` + IP-based rate limiting of 2000 requests / 5 min).
  - VPC Flow Logs enabled with 90-day retention in Amazon CloudWatch.
  - Private subnet isolation for database, Redis cache, and ECS tasks.
  - Least-privilege IAM Task and Execution roles (scoped Secrets Manager and S3 bucket access).
- **Storage & Databases**:
  - Multi-AZ Amazon RDS PostgreSQL 16 with `pgvector` extension, 30-day automated PITR backup retention.
  - Multi-AZ Amazon ElastiCache for Redis 7 with at-rest and transit encryption.
  - Amazon S3 bucket with Public Access Block, default AES-256 server-side encryption, and Object Versioning enabled.

---

## 2. Tested Multi-Cloud / Kubernetes Target: Helm
The repository also maintains a fully tested Helm chart in [infra/helm/hospitality-agent](file:///c:/Users/91730/Downloads/Aaas%20deplo/infra/helm/hospitality-agent) for enterprise clients operating in multi-cloud (GCP GKE, Azure AKS) or sovereign on-premises environments.

### Capabilities Included
- **Pod Lifecycle**: Configured with `startupProbe` (initial model load protection), `livenessProbe`, `readinessProbe`, and `preStop` lifecycle hooks with 30s graceful termination.
- **Scaling & Disruption**: `HorizontalPodAutoscaler` (HPA) scaling between 3 and 20 pods; `PodDisruptionBudget` (PDB) guaranteeing `minAvailable: 2`.
- **Zero-Trust Network Isolation**: Kubernetes `NetworkPolicy` restricting ingress to NGINX Ingress Controller and egress strictly to DNS, Postgres, Redis, and outbound HTTPS.
- **Enterprise Secrets Management**: Integration with `external-secrets.io` syncing runtime secrets from cloud secret stores directly to Kubernetes Secrets.
- **Automated Schema Migrations**: Pre-upgrade Helm hook executing `alembic upgrade head` before pod rollouts.
