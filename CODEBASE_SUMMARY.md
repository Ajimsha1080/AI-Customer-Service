# Codebase Architecture & Raw Access Guide

> **Note for AI Assistant / External Web Tools**: If you are trying to fetch or inspect this repository via external URL fetchers (e.g. Claude Web, ChatGPT), use **`raw.githubusercontent.com`** raw links to bypass GitHub WAF anti-bot blocks and JavaScript rendering requirements:
> - Raw Summary: `https://raw.githubusercontent.com/Ajimsha1080/Agent-as-a-Service---P1/main/CODEBASE_SUMMARY.md`
> - Raw README: `https://raw.githubusercontent.com/Ajimsha1080/Agent-as-a-Service---P1/main/README.md`
> - Raw API Main: `https://raw.githubusercontent.com/Ajimsha1080/Agent-as-a-Service---P1/main/apps/api/main.py`

---

## 🏗️ Repository Overview

**Hospitality Agent Cloud (Agent-as-a-Service - P1)** is a multi-tenant enterprise AI digital concierge and booking assistant platform built for hotels, resorts, hostels, and hospitality groups.

### Core Stack & Architecture
- **Backend API (`apps/api`)**: Python 3.12+ FastAPI application with CORS regex matching, JWT authentication with Argon2id password hashing, and 25+ REST endpoints.
- **Frontend App (`apps/web`)**: Next.js 14 application using React, Tailwind CSS, Lucide icons, and Clean White YC Light Mode design system. Contains 3 distinct web applications:
  1. Main Customer SaaS Portal (`/app/*`)
  2. Super Admin Operator Console (`/platform/*`)
  3. Luxury Guest Digital Concierge (`/guest/*`)
- **Agent Execution Engine (`services/agent_runtime`)**: LiteLLM multi-turn tool execution loop, injection guardrails, fallback synthesis, and Indic voice STT/TTS support.
- **RAG & Vector Storage (`services/rag`)**: SentenceTransformers embeddings (`all-MiniLM-L6-v2`) and PostgreSQL `pgvector` store (`PostgresPgVectorStore`).
- **Database & Persistence (`services/database`)**: SQLAlchemy async models with SQLite fallback / PostgreSQL backend, Alembic migrations, tenant isolation scoping.
- **Billing & Quotas (`services/billing`)**: Multi-tenant quota enforcement with HTTP 402 tier limits (`FREE`, `STARTER`, `PROFESSIONAL`, `BUSINESS`, `ENTERPRISE`).
- **Automated Tests (`tests/`)**: Pytest suite covering all 15 test modules with 100% pass rate (45/45 tests passing).

---

## 📁 Key File Paths & Structure

```
.
├── CODEBASE_SUMMARY.md          # Comprehensive AI-friendly architectural summary
├── README.md                    # Project README & Quick Start Guide
├── requirements.txt             # Python dependencies
├── docker-compose.yml           # Postgres, pgvector & Redis services setup
├── alembic.ini                  # Database migration configuration
├── apps/
│   ├── api/
│   │   ├── main.py              # FastAPI main application entrypoint & middleware configuration
│   │   ├── auth.py              # JWT authentication & Argon2 routes
│   │   ├── dependencies.py      # Dependency injection & tenant boundary verifiers
│   │   └── routes/              # Endpoints for agents, properties, RAG, billing, admin
│   ├── web/                     # Next.js 14 frontend monorepo app
│   │   └── src/app/             # Clean White YC Light Mode UI pages
│   └── widget/                  # Client-side embeddable JavaScript widget
├── services/
│   ├── agent_runtime/           # Agent execution loop, tool registry, moderation
│   ├── billing/                 # Metering and subscription tier quota checker
│   ├── database/                # Database session management and models
│   └── rag/                     # Chunking, embedding, vector store integrations
├── scripts/
│   └── seed_demo.py             # Demo data population script
└── tests/                       # 15 pytest modules (45 test cases)
```

---

## 🧪 Verification & Health Checks

- **Run Pytest Suite**: `python -m pytest tests/`
- **Backend Service URL**: `http://127.0.0.1:8000` (OpenAPI Docs: `/docs`, Health Probe: `/health`)
- **Frontend Service URL**: `http://localhost:3001`

---

## 💡 Fetching Raw Files via GitHub

When fetching files using HTTP tools, always target the raw content URL:
`https://raw.githubusercontent.com/Ajimsha1080/Agent-as-a-Service---P1/main/<relative-path-to-file>`
