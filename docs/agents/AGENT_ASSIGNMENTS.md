# Agent Assignments & File Ownership

Shared contract: `docs/development/API_CONTRACTS.md` (authoritative). No agent edits files owned by another agent. Agents only edit their own row in `AGENT_STATUS.md` and their own section in `AGENT_HANDOFFS.md`.

| Agent | Owns (exclusive write) |
|---|---|
| 1 Frontend | `frontend/**` (except `frontend/Dockerfile`, `frontend/nginx.conf`), `docs/development/FRONTEND_IMPLEMENTATION.md` |
| 2 Backend | `backend/**` except `backend/app/orchestrator/**`, `backend/app/messaging/**`, `backend/Dockerfile`; `migrations` live at `backend/migrations/`; `docs/development/{DATABASE_DESIGN,BACKEND_IMPLEMENTATION}.md`; `postman/` |
| 3 Runtime | `backend/app/orchestrator/**`, `backend/app/messaging/**`, `workers/**` (except Dockerfile), `sandbox/**`, `infrastructure/docker/kafka/**`, `docs/development/WORKERS_IMPLEMENTATION.md`, `docs/architecture/KAFKA_ARCHITECTURE.md` |
| 4 DevOps | `docker-compose*.yml`, all `Dockerfile`s except `sandbox/Dockerfile`, `frontend/nginx.conf`, `.github/**`, `infrastructure/**` (except kafka), `.env.example`, `.gitignore`, `.dockerignore`, `Makefile`, `docs/deployment/**` |
| 5 QA | `tests/**` (root, cross-module), `docs/{TESTING_STRATEGY,INTEGRATION_REPORT,KNOWN_ISSUES,IMPLEMENTATION_STATUS}.md` |
| Orchestrator | `PROJECT.md`, `docs/architecture/{CURRENT,TARGET}_ARCHITECTURE.md`, `SYSTEM_WORKFLOW.md`, `docs/development/{REPOSITORY_ANALYSIS,DEVELOPMENT_PLAN,API_CONTRACTS}.md`, `CHANGELOG.md`, `RELEASE_NOTES.md` |
