# Hospitality Agent Cloud (Agent-as-a-Service - P1)

Enterprise Multi-Tenant Agent-as-a-Service (AaaS) platform for resorts, hotels, hostels, serviced apartments, and hospitality groups.

---

## 🌟 Core Business Concept

Hospitality businesses subscribe to the platform to deploy custom AI digital concierges and booking assistants. The customer **does NOT** manage servers, Docker, databases, Redis, vector stores, or LLM infrastructure.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             CUSTOMER WORKFLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Create Account & Property   ➔  "Azure Palm Resort & Spa"                 │
│ 2. Upload Property Knowledge   ➔  Upload Guest Policy PDF & Restaurant Menu │
│ 3. Connect Live Data Tools     ➔  Enable Room Vacancy & Pool Status Tools   │
│ 4. Configure & Test Agent      ➔  Select Luxury Tone & Test Voice Orb       │
│ 5. Click "Deploy Agent"        ➔  Get 1-Line JS Widget or REST API Key      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🎨 Clean White YC Light Mode UI System

The application features a hand-crafted **Clean White YC Light Mode System** (Stripe Light & Vercel Light standards) with a pure clean white background (`#ffffff`), crisp dark text (`#09090b`), clean 1px borders (`border-zinc-200`), and 3 strictly separated user experiences:

### 1. 🏨 **UI 2: Main Customer SaaS Portal (`/app/*`)**
- **Purpose**: Main business UI for resort & hotel owners to manage properties, AI agents, RAG documents, and guest conversations.
- **Link**: [http://localhost:3001/app/dashboard](http://localhost:3001/app/dashboard)
- **Included Pages**: Executive Overview, 6-Step Onboarding Setup Wizard, Properties, Agents, 9-Step Agent Builder, Intercom-style Guest Inbox, RAG Manager, Live Operations Console, Analytics, Billing, Settings.

### 2. 🛡️ **UI 1: Platform Owner Super Admin (`/platform/*`)**
- **Purpose**: Operator console for platform owners to monitor MRR, ARR, AI costs, node clusters, and system health.
- **Link**: [http://localhost:3001/platform/dashboard](http://localhost:3001/platform/dashboard)

### 3. 🌴 **UI 3: Guest Luxury Digital Concierge (`/guest/*`)**
- **Purpose**: Traveler-facing digital concierge for hotel guests supporting chat, quick action chips, language switching, and interactive Voice Orb.
- **Link**: [http://localhost:3001/guest/agt_concierge_01](http://localhost:3001/guest/agt_concierge_01)

---

## 🔒 Production Security & Multi-Tenant Authorization

- **Authentication**: Argon2id password hashing and short-lived JWT access & refresh tokens (`/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/me`).
- **Tenant Isolation**: Server-side tenant scoping (`verify_tenant_access`) enforcing strict org-level boundary authorization across all control & data plane endpoints.
- **Billing Quotas**: SaaS subscription tier enforcement (`FREE`, `STARTER`, `PROFESSIONAL`, `BUSINESS`, `ENTERPRISE`) returning `HTTP 402 Payment Required` when limits are exceeded.

---

## 🤖 Real AI, Vector Store & Execution Engine

- **LiteLLM Tool-Calling Loop**: Multi-turn function execution (`_execute_litellm_tool_loop`) with schema filtering and message history.
- **RAG Vector Persistence**: Dense embeddings (`SentenceTransformers` `all-MiniLM-L6-v2`) and PostgreSQL `pgvector` store (`PostgresPgVectorStore`).
- **LLM Moderation Guardrails**: Fast heuristic injection detection + LLM moderation classifier (`check_guardrails`).
- **Hard Execution Timeouts**: 15s execution timeout with graceful fallback to RAG synthesis.
- **Indic Voice (STT & TTS)**: Native support for Indian regional languages (**Malayalam**, **Hindi**, **Tamil**, **Telugu**, **Kannada**).

---

## ⚡ Real-Time Observability & REST APIs

- **Observability**: `X-Request-ID` correlation tracing, structured JSON logging, and production health probes (`/health`, `/ready`, `/metrics`).
- **OpenAPI REST Docs**: Live interactive API documentation for 25+ REST endpoints at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.12+ (or Python 3.14)
- Node.js 18+ & npm

### 2. Environment Setup
```bash
cp .env.example .env
```

### 3. Database Initialization & Seeding
```bash
python -m scripts.seed_demo
```

### 4. Run FastAPI Backend Server (Port 8000)
```bash
python -m uvicorn apps.api.main:app --reload --port 8000
```
- Interactive OpenAPI Docs: `http://localhost:8000/docs`
- Service Health Probe: `http://localhost:8000/health`

### 5. Run Next.js Web UI Server (Port 3001)
```bash
cd apps/web
npm install
npm run dev -- -p 3001
```
- Main Customer SaaS Portal: `http://localhost:3001/app/dashboard`
- Super Admin Operator Console: `http://localhost:3001/platform/dashboard`
- Guest Concierge Experience: `http://localhost:3001/guest/agt_concierge_01`

---

## 🧪 Running Automated Tests

Run the full pytest suite to verify Argon2 password security, JWT token issuance & revocation, multi-tenant IDOR isolation, PGVector dense embeddings, LiteLLM function calling tool loops, moderation guardrails, hard timeouts, subscription tier HTTP 402 quota enforcement, DB usage metering, request ID header tracing, error envelopes, and health probes:

```bash
python -m pytest tests/
```

**Result**: `41 passed in 63.39s` (**100% Pass Rate** across 15 test modules).

---

## 📂 Pristine Monorepo Structure

```
Aaas/
├── apps/
│   ├── api/                     # FastAPI Real-Time Gateway & Control Plane (21 REST Endpoints)
│   ├── web/                     # Next.js 14 Web Portal (Clean YC Light Mode UI)
│   │   └── src/app/
│   │       ├── app/             # UI 2: Main Customer SaaS Portal (/app/*)
│   │       ├── platform/        # UI 1: Super Admin Console (/platform/*)
│   │       └── guest/           # UI 3: Guest Luxury Digital Concierge (/guest/*)
│   └── widget/                  # Embeddable Web Widget (<script src="widget.js">)
├── packages/agent_sdk/          # Python Agent SDK for Programmatic Lifecycle Management
├── services/
│   ├── agent_runtime/           # Shared Agent Engine, Guardrails & Tools Registry
│   ├── billing/                 # Metering & SaaS Usage Service
│   ├── database/                # SQLAlchemy Models & Async DB Sessions
│   └── rag/                     # Vector Store & Document Ingest Pipeline
├── scripts/seed_demo.py         # Idempotent Database Seeding Script
├── tests/                       # Automated Pytest Suite
├── docker-compose.yml           # Production Stack (PostgreSQL, pgvector, Redis)
└── requirements.txt             # Clean Dependencies Manifest
```
