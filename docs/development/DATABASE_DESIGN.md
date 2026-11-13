# Database Design (AgentForge AI API v1)

PostgreSQL 16 + pgvector. Models: `backend/app/database/models.py`. Single Alembic revision: `backend/migrations/versions/0001_initial_schema.py` (creates the `vector` extension and seeds roles/permissions).

## Conventions
- UUID primary keys, `created_at`/`updated_at` timestamps (tz-aware).
- Multi-tenancy: every tenant-owned table has `organization_id` (FK, indexed). All queries go through `org_select` / `get_owned` (`app/core/deps.py`); a row belonging to another org returns **404**, never 403.
- Flexible config lives in JSONB (`AgentVersion.config` = `AgentConfig` per contract §6/§17; workflow graph JSON; tool input schemas).
- Secrets are never stored in plaintext: `credentials.encrypted_value` (Fernet, `CREDENTIAL_ENCRYPTION_KEY`), passwords argon2id, refresh tokens/API keys stored as hashes.

## Tables
| Area | Tables |
|---|---|
| Identity / tenancy | `organizations`, `users`, `memberships` (user↔org↔role), `roles`, `permissions`, `role_permissions` (seeded: owner/admin/developer/viewer) |
| Auth | `refresh_tokens` (hashed, `family_id` for rotation + reuse detection), `api_keys` |
| LLM | `llm_providers` (azure_openai/gemini/mock, `credential_id`), `credentials` |
| Building blocks | `agents`, `agent_versions` (JSONB `config`), `tools`, `tool_versions` (code + static-analysis result) |
| Workflows | `workflows`, `workflow_versions` (validated graph snapshot) |
| Runtime | `executions` (status, `input` JSONB, `started_at`, `finished_at`, `duration_ms`), `execution_events` (ordered seq for SSE replay), `outbox_events` (transactional outbox; org id inside payload, §17) |
| Chat | `chat_sessions`, `chat_messages` |
| RAG | `documents`, `document_chunks` (`embedding vector(EMBEDDING_DIM)`) |
| Ops | `deployments`, `audit_logs` (`organization_id` nullable for login events; index `(organization_id, created_at)`), `usage_records` |

## Migrations
```bash
cd backend
export DATABASE_URL=postgresql+asyncpg://agentforge:agentforge@localhost:55432/agentforge_test
uv run alembic upgrade head
```
