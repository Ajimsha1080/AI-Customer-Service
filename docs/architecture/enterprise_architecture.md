# Enterprise System Architecture

## 1. High-Level System Topology

```mermaid
flowchart TD
    subgraph Clients["Enterprise Ingress Clients"]
        GuestChat["Guest Web Widget & Mobile"]
        WhatsAppClient["WhatsApp Business App"]
        AdminPortal["Next.js 14 Admin Portal"]
        PublicAPI["Public REST API Consumer"]
    end

    subgraph Edge["Edge & Security Layer"]
        WAF["Edge WAF & DDoS Shield"]
        SecHeaders["Security Headers Middleware (HSTS, CSP)"]
        RateLimiter["Redis Token Bucket Rate Limiter"]
        Idempotency["Idempotency Key Middleware"]
    end

    subgraph AppCluster["Application Tier (Multi-AZ FastAPI)"]
        APINode1["FastAPI Node 1 (AZ-A)"]
        APINode2["FastAPI Node 2 (AZ-B)"]
        APINode3["FastAPI Node 3 (AZ-C)"]
    end

    subgraph ServiceMesh["Resilience & Core Services"]
        RBAC["Central RBAC Policy Engine"]
        PIIMasker["PII Masker & Guardrails"]
        CircuitBreakers["Outbound Circuit Breakers"]
        ResilienceRouter["LLM Resilience & Routing"]
    end

    subgraph Workers["Asynchronous Worker Tier"]
        WorkerPool["Background Celery/Redis Worker"]
        DLQ["Dead-Letter Queue (DLQ) & Replay Engine"]
    end

    subgraph DataStorage["Data & State Tier (Multi-AZ)"]
        PostgresPrimary[("PostgreSQL Primary (Multi-AZ)")]
        PgVectorStore[("pgvector Embeddings")]
        RedisCluster[("Redis Cluster / PubSub")]
        KMS["KMS Envelope Encryption (BYOK)"]
    end

    subgraph External["External Integrations"]
        OpenAI["OpenAI API (Primary)"]
        Anthropic["Anthropic API (Failover)"]
        Stripe["Stripe Metered Billing"]
        WhatsAppBSP["Meta WhatsApp BSP Cloud API"]
    end

    Clients --> WAF --> SecHeaders --> RateLimiter --> Idempotency
    Idempotency --> AppCluster
    AppCluster --> ServiceMesh
    ServiceMesh --> Workers
    ServiceMesh --> DataStorage
    ServiceMesh --> External
    Workers --> DLQ
```

---

## 2. Data Residency Boundary Routing

```mermaid
flowchart LR
    TenantReq["Tenant Request (org_id)"] --> CheckRegion{"Tenant Region Setting"}
    CheckRegion -->|Region: EU| EUBoundary["EU DB & EU LLM Endpoint (Frankfurt)"]
    CheckRegion -->|Region: US| USBoundary["US DB & US LLM Endpoint (Virginia)"]
    CheckRegion -->|Region: IN| INBoundary["IN DB & IN LLM Endpoint (Mumbai)"]
    CheckRegion -->|Cross-Border Attempt| Blocked["HTTP 403 DATA_RESIDENCY_VIOLATION"]
```

---

## 3. Resilience & Circuit Breaker State Machine

```mermaid
stateDiagram-v2
    [*] --> Closed: Normal Operation
    Closed --> Open: 3 Consecutive Failures
    Open --> Open: Outbound Calls Fast-Failed (CircuitBreakerOpenError)
    Open --> HalfOpen: Cool-down Window (30s) Expired
    HalfOpen --> Closed: Probe Request Succeeds
    HalfOpen --> Open: Probe Request Fails
```

---

## 4. Multi-AZ High Availability Strategy
- **Database (PostgreSQL 16 + pgvector)**: Active-passive multi-AZ setup with synchronous streaming replication to AZ-B and asynchronous cross-region copy for DR.
- **In-Memory Cache (Redis 7)**: Multi-node cluster with automated sentinel failover and append-only file (AOF) persistence.
- **Stateless Compute (FastAPI & Next.js)**: Horizontal pod autoscaling (HPA) responding to request rate and queue lag, distributed across at least 3 availability zones.
