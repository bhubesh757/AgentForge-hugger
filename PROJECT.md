# AgentForge AI — Project

Versions: **UI 1.0.0** · **API v1** (`/api/v1`) · **Platform milestone 1.0.1**

Full product spec: [Readme.md](Readme.md). Shared contracts: [docs/development/API_CONTRACTS.md](docs/development/API_CONTRACTS.md).

## Architecture (1.0.1)
Modular monolith control plane (FastAPI) + independently scalable Python workers (data plane).

```
React UI (Vite, React Flow, Monaco) ──HTTPS/SSE──▶ FastAPI /api/v1 ──▶ PostgreSQL + pgvector
                                                     │  outbox
                                                     ▼
                                                   Kafka ──▶ agent / workflow / tool workers ──▶ LangGraph runtime
                                                                                     │              ├─ LLM (Gemini / Azure OpenAI, BYOK)
                                                                                     │              └─ Docker sandbox (tools)
                                                     Redis ◀── execution events (pub/sub) ─┘
```

| Layer | Location |
|---|---|
| Frontend | `frontend/` |
| API, DB models, migrations | `backend/app`, `backend/migrations` |
| Orchestrator runtime & messaging | `backend/app/orchestrator`, `backend/app/messaging` |
| Workers | `workers/` |
| Tool sandbox | `sandbox/` |
| Compose, CI/CD, infra | `docker-compose*.yml`, `.github/workflows`, `infrastructure/` |
| Docs | `docs/` |

## Roadmap
| Priority | Scope | Milestone |
|---|---|---|
| P0 | Docs, UI 1.0.0, API v1, Postgres, auth, orgs/RBAC, Compose, GitHub Actions, API tests | 1.0.1 |
| P1 | Agent/tool registry, Gemini + Azure BYOK, React Flow studio, LangGraph execution, chat, workers, Kafka | 1.0.1 |
| P2 | Sandbox hardening (gVisor), Prometheus/Grafana/Loki dashboards, OpenTelemetry, advanced guardrails, loops, Kubernetes, AWS KMS | 1.1+ |

Deployment: local Docker Compose → GHCR images → GitHub Pages (static frontend only) → future Kubernetes. No cloud spend without approval.

Status: see [docs/agents/AGENT_STATUS.md](docs/agents/AGENT_STATUS.md) and [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).
