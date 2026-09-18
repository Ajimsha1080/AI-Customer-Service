# Production Secrets Management & Security Guide

## Overview

This repository enforces strict secrets isolation. No sensitive environment variables or production secrets (`.env.production`, private keys, database credentials) should ever be committed to version control.

---

## Recommended Secrets Managers

### 1. AWS Secrets Manager / Parameter Store (SSM)
When deploying to AWS (ECS, EKS, or EC2):
- Store secrets under path `/hospitality-agent-cloud/production/`
  - `DATABASE_URL`
  - `REDIS_URL`
  - `JWT_SECRET_KEY`
  - `STRIPE_SECRET_KEY`
  - `STRIPE_WEBHOOK_SECRET`
  - `SARVAM_API_KEY`
- Inject secrets into ECS Task Definitions directly from Secrets Manager ARN:
  ```json
  "secrets": [
    { "name": "JWT_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:production/JWT_SECRET_KEY" }
  ]
  ```

### 2. Doppler (Multi-Cloud / Platform Agnostic)
- Create a project `hospitality-agent-cloud` with config `prd`.
- Inject at runtime:
  ```bash
  doppler run -- python -m uvicorn apps.api.main:app --port 8000
  ```

### 3. HashiCorp Vault
- Store secrets at `secret/data/hospitality-agent-cloud/prod`.
- Use Vault Agent or Kubernetes Vault Sidecar Injector to mount `/vault/secrets/config.env`.

---

## Local Development vs. Production Setup

- **Local Development**: Copy `.env.example` to `.env` (git-ignored).
- **Production**: Never store raw `.env` files on persistent disk. Load directly into container process environment memory via Secrets Manager.
