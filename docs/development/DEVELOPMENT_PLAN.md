# Development Plan

1. **Discovery** (done) → `REPOSITORY_ANALYSIS.md`.
2. **Contracts** (done) → `API_CONTRACTS.md` (REST, workflow JSON, Python interfaces, Kafka envelope, env vars, Compose service names).
3. **Parallel build** (Agents 1–4, exclusive file ownership per `docs/agents/AGENT_ASSIGNMENTS.md`):
   - A1 Frontend UI 1.0.0 incl. GitHub-Pages demo mode.
   - A2 FastAPI API v1, models, Alembic, auth/RBAC, BYOK, SSE.
   - A3 LangGraph compiler/runtime, outbox→Kafka, workers, Docker sandbox.
   - A4 Dockerfiles, Compose (profiles), GitHub Actions incl. Pages deploy, deployment docs.
4. **Integration** (Orchestrator): review diffs, run migrations, backend tests, frontend build, compose up, fix seams.
5. **QA** (A5): cross-module API tests (pytest + HTTPX), integration report, known issues, implementation status.
6. **Release prep**: CHANGELOG, RELEASE_NOTES. No tag/push without user approval.

Token governance: 100k/agent (report 80k, hold 85k), program cap 800–900k → if exceeded, hold all agents and move to testing.
