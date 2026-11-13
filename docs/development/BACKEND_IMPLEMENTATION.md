# Backend Implementation (AgentForge AI API v1)

FastAPI (async) + SQLAlchemy 2 (asyncpg) + Alembic + Redis. Python 3.12, managed with `uv`. Contract: `docs/development/API_CONTRACTS.md` (§17 decisions are authoritative).

## Layout (`backend/app/`)
| Module | Purpose |
|---|---|
| `core/` | config (env), errors (contract error envelope), JWT + password hashing, deps (`OrgContext`, `require(permission)`, `get_owned`, `org_select`), RBAC permissions, rate limiting, request-id/logging middleware |
| `auth/` | register/login/refresh (rotation + reuse detection revokes token family)/logout/me |
| `organizations/` | orgs, members, roles |
| `llm/` | providers (Azure OpenAI, Gemini, mock), connect/test/models; `LLM_MOCK_MODE` or `mock-` keys use the mock client; keys are never echoed |
| `credentials/` | Fernet cipher, CRUD router, `service.resolve_credential(session, org_id, credential_id)` (§17) |
| `agents/`, `tools/`, `workflows/` | CRUD + versioning; tools run AST static analysis (`tools/static_analysis.py`: import allowlist, banned builtins/dunders, `run()` required), code is never executed by the API; workflows validated by `orchestrator.validator` + DB reference checks |
| `executions/` | create/list/get/cancel, events, SSE stream; `events.set_status` sets timing fields (§17) |
| `chat/`, `rag/`, `guardrails/`, `deployments/`, `audit/`, `monitoring/` | chat sessions (execution input `{session_id, message}`), document ingest/search, PII redaction/truncation, deployments, audit log, `/health`, `/ready`, `/metrics`, summary |
| `orchestrator/`, `messaging/` | Agent 3 (LangGraph runtime, Kafka/outbox, dispatch) |

## Run
```bash
cd backend
export DATABASE_URL=postgresql+asyncpg://agentforge:agentforge@localhost:55432/agentforge_test
export REDIS_URL=redis://localhost:56379/0 LLM_MOCK_MODE=true
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```
- Swagger UI: http://localhost:8000/docs
- OpenAPI: http://localhost:8000/openapi.json
- Liveness: http://localhost:8000/health (also `/api/v1/health`); readiness: `/api/v1/ready` (checks DB, Redis, Kafka; 503 if a required dependency is down)

## Tests
```bash
uv run pytest -q                 # tests/api: unit + DB-backed API tests (DB tests skip if Postgres unavailable)
uv run pytest tests/orchestrator -q
uv run ruff check app tests && uv run ruff format --check app tests
```
`tests/conftest.py` migrates `TEST_DATABASE_URL`, forces `LLM_MOCK_MODE=true`, truncates tenant tables per test and monkeypatches `dispatch.enqueue_execution`.
Covered: auth refresh rotation + reuse detection, org membership, cross-tenant 404, viewer 403, provider connect with `mock-` key never echoed, tool static analysis (`import os` rejected), workflow CRUD + validate + execute, agent execute + chat, health/ready/openapi.
