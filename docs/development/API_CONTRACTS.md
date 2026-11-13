# API & Shared Contracts — AgentForge AI (API v1)

**Status:** APPROVED by orchestrator (Stage 2). All agents MUST follow this file. Changes require an orchestrator-approved edit plus an entry in `docs/agents/AGENT_HANDOFFS.md`.

Versions: UI `1.0.0` · API `v1` (base path `/api/v1`) · Platform milestone `1.0.1`.

---

## 1. General conventions

| Topic | Rule |
|---|---|
| IDs | UUID v4 strings |
| Timestamps | ISO-8601 UTC, e.g. `2026-11-13T10:00:00Z` |
| JSON casing | `snake_case` on the wire (frontend types mirror it) |
| Auth header | `Authorization: Bearer <access_token>` |
| Tenant header | `X-Organization-ID: <uuid>` — **required** on every org-scoped endpoint (everything except `/auth/*`, `GET/POST /organizations`, `/health`, `/ready`, `/metrics`). Missing → `400 ORG_HEADER_REQUIRED`; not a member → `403 ORG_FORBIDDEN`. For `/organizations/{organization_id}/...` the path id is authoritative. |
| Correlation | Client may send `X-Request-ID`; server always returns `X-Request-ID` (generated if absent) and propagates it as `correlation_id` into Kafka events and logs. |
| Pagination | Query `page` (≥1, default 1), `page_size` (1–100, default 20). Response envelope below. |
| Cross-tenant access | Resources of another org return **404** (not 403) to avoid existence leaks. |

### Paginated envelope
```json
{ "items": [], "total": 0, "page": 1, "page_size": 20 }
```

### Error envelope (all non-2xx)
```json
{ "error": { "code": "VALIDATION_ERROR", "message": "Human readable", "details": {}, "request_id": "..." } }
```
Codes: `VALIDATION_ERROR` (422), `UNAUTHENTICATED` (401), `TOKEN_EXPIRED` (401), `FORBIDDEN` (403), `ORG_HEADER_REQUIRED` (400), `ORG_FORBIDDEN` (403), `NOT_FOUND` (404), `CONFLICT` (409), `RATE_LIMITED` (429), `PROVIDER_ERROR` (502), `INTERNAL_ERROR` (500).

---

## 2. Authentication

- Passwords: Argon2id (`argon2-cffi`). Min length 10.
- Access token: JWT HS256, 15 min, claims `sub` (user id), `type: "access"`, `exp`, `iat`, `jti`.
- Refresh token: opaque random 32-byte urlsafe string, 7 days, stored **hashed** (SHA-256) in `refresh_tokens`, rotated on every refresh (old one revoked; reuse of revoked token revokes the whole family).
- Frontend stores access token in memory and refresh token in `localStorage` (documented trade-off; httpOnly cookie mode is a tracked follow-up).

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/auth/register` | `{email, password, full_name, organization_name?}` | `201 TokenPair` (+ creates org with caller as `owner` if `organization_name` given) |
| POST | `/auth/login` | `{email, password}` | `200 TokenPair` |
| POST | `/auth/refresh` | `{refresh_token}` | `200 TokenPair` |
| POST | `/auth/logout` | `{refresh_token}` | `204` |
| GET | `/auth/me` | — | `200 Me` |

```ts
TokenPair = { access_token: string, refresh_token: string, token_type: "bearer", expires_in: number }
User      = { id, email, full_name, status: "active"|"disabled", created_at }
Me        = User & { memberships: { organization_id, organization_name, organization_slug, role: Role }[] }
Role      = "owner" | "admin" | "developer" | "operator" | "viewer"
```

### RBAC permission matrix
| Permission | owner | admin | developer | operator | viewer |
|---|---|---|---|---|---|
| `org.manage` (update org, members) | ✔ | ✔ | | | |
| `llm.manage` (connect/activate/delete providers, credentials) | ✔ | ✔ | | | |
| `resource.write` (agents/tools/workflows create/update/generate/publish) | ✔ | ✔ | ✔ | | |
| `execution.run` (execute/test/cancel, chat) | ✔ | ✔ | ✔ | ✔ | |
| `resource.read` | ✔ | ✔ | ✔ | ✔ | ✔ |

---

## 3. Organizations

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/organizations` | `{name, slug?}` | `201 Organization` (caller becomes owner) |
| GET | `/organizations` | — | `200 Page<Organization & {role}>` (only caller's orgs) |
| GET | `/organizations/{organization_id}` | — | `200 Organization` |
| PUT | `/organizations/{organization_id}` | `{name?}` | `200 Organization` |
| GET | `/organizations/{organization_id}/members` | — | `200 Page<Member>` |
| POST | `/organizations/{organization_id}/members` | `{email, role}` (user must exist) | `201 Member` |
| DELETE | `/organizations/{organization_id}/members/{user_id}` | — | `204` (cannot remove last owner → 409) |

```ts
Organization = { id, name, slug, status: "active", created_at }
Member       = { user_id, email, full_name, role: Role, joined_at }
```

---

## 4. LLM providers (BYOK) — org-scoped

Secrets are encrypted at rest with **Fernet** using `CREDENTIAL_ENCRYPTION_KEY` (local/dev) behind a `SecretCipher` interface (`app/credentials/cipher.py`) so AWS KMS can replace it later. API keys are **never** returned; only `key_hint` (last 4 chars, e.g. `••••abcd`).

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/llm/providers` | — | `200 Page<LLMProvider>` |
| POST | `/llm/providers/connect` | `ConnectProvider` | `201 LLMProvider` (status `pending_validation`, validation is attempted immediately; result reflected in status) |
| POST | `/llm/providers/{provider_id}/validate` | — | `200 {valid: bool, message: string, provider: LLMProvider}` |
| GET | `/llm/providers/{provider_id}/models` | — | `200 {models: {id: string, display_name: string}[]}` |
| POST | `/llm/providers/{provider_id}/activate` | `{default_model?}` | `200 LLMProvider` (must be `valid`; makes it the org default, deactivates other defaults) |
| POST | `/llm/providers/{provider_id}/deactivate` | — | `200 LLMProvider` |
| DELETE | `/llm/providers/{provider_id}` | — | `204` |

```ts
ConnectProvider =
  | { provider: "gemini", name?: string, api_key: string, default_model?: string }
  | { provider: "azure_openai", name?: string, api_key: string, endpoint: string, deployment_name: string, api_version: string, default_model?: string }
LLMProvider = { id, provider: "gemini"|"azure_openai", name, status: "pending_validation"|"valid"|"invalid"|"active"|"inactive",
                is_default: boolean, default_model: string|null, key_hint: string, config: {endpoint?, deployment_name?, api_version?},
                last_validated_at: string|null, created_at }
```

Mock provider: when env `LLM_MOCK_MODE=true`, any key starting with `mock-` validates successfully and generation returns deterministic text. Used by tests/CI. Never enabled in production compose.

## 5. Credentials (generic secrets for tools/API nodes) — org-scoped

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/credentials` | `{name, kind: "api_key"|"bearer_token"|"basic_auth"|"generic", value: string, description?}` | `201 Credential` |
| GET | `/credentials` | — | `200 Page<Credential>` |
| POST | `/credentials/{credential_id}/validate` | — | `200 {valid, message}` (format check only) |
| POST | `/credentials/{credential_id}/rotate` | `{value}` | `200 Credential` |
| DELETE | `/credentials/{credential_id}` | — | `204` |

`Credential = { id, name, kind, description, key_hint, created_at, rotated_at|null }` — value never returned. Workflow/agent configs reference credentials as `{"credential_ref": "<credential_id>"}`.

---

## 6. Agents — org-scoped

```ts
AgentConfig = {
  instructions: string, provider_id: string|null /* null = org default */, model: string|null,
  temperature: number /*0..2, default 0.2*/, tool_ids: string[], memory: "none"|"conversation",
  max_retries: number /*0..5*/, timeout_seconds: number /*1..600*/,
  guardrails: { block_pii: boolean, max_output_chars: number|null },
  input_schema: object|null, output_schema: object|null
}
Agent = { id, name, description, status: "draft"|"configured"|"testing"|"approved"|"published"|"archived",
          current_version: number, config: AgentConfig, created_by, created_at, updated_at }
AgentVersion = { id, agent_id, version: number, config: AgentConfig, created_at, created_by }
```

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/agents` | `{name, description?, config}` | `201 Agent` (version 1) |
| GET | `/agents` | `?search=&status=` + pagination | `200 Page<Agent>` |
| GET | `/agents/{agent_id}` | — | `200 Agent` |
| PUT | `/agents/{agent_id}` | `{name?, description?, config?}` | `200 Agent` (config change creates new version) |
| POST | `/agents/generate` | `{prompt, provider_id?}` | `200 {draft: {name, description, config}}` (NOT saved; user reviews then POST /agents) |
| POST | `/agents/{agent_id}/test` | `{input: object|string}` | `202 Execution` (kind `agent_test`) |
| POST | `/agents/{agent_id}/execute` | `{input, stream?: bool}` | `202 Execution` (kind `agent`) |
| POST | `/agents/{agent_id}/publish` | — | `200 Agent` |
| GET | `/agents/{agent_id}/versions` | — | `200 Page<AgentVersion>` |
| POST | `/agents/{agent_id}/rollback` | `{version}` | `200 Agent` (creates new version copying target) |

## 7. Tools — org-scoped

```ts
Tool = { id, name /* python identifier */, description, status: "draft"|"tested"|"published"|"archived",
         current_version: number, source_code: string, input_schema: object, output_schema: object,
         requirements: string[], created_at, updated_at }
```
Generated tool code MUST define `def run(input: dict) -> dict:`. Requirements must be in the allowlist `SANDBOX_ALLOWED_PACKAGES` (default: `requests,httpx,pydantic,python-dateutil`).

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/tools/generate` | `{prompt, provider_id?}` | `200 {draft: {name, description, source_code, input_schema, output_schema, requirements, tests}}` + `static_analysis: {ok, issues: string[]}` |
| POST | `/tools` | `{name, description?, source_code, input_schema?, output_schema?, requirements?}` | `201 Tool` (static analysis runs; blocked imports → 422) |
| GET | `/tools` | pagination, `?search=` | `200 Page<Tool>` |
| GET | `/tools/{tool_id}` | — | `200 Tool` |
| PUT | `/tools/{tool_id}` | partial | `200 Tool` (new version) |
| POST | `/tools/{tool_id}/test` | `{input: object}` | `202 Execution` (kind `tool_test`, runs in sandbox via tool-worker) |
| POST | `/tools/{tool_id}/publish` | — | `200 Tool` |
| GET | `/tools/{tool_id}/versions` | — | `200 Page<{id, version, source_code, created_at}>` |

## 8. Workflows — org-scoped

### 8.1 Workflow definition JSON (React Flow ⇄ backend) — **canonical**
```json
{
  "schema_version": "1.0",
  "nodes": [
    { "id": "start-1", "type": "start", "position": {"x": 0, "y": 0}, "data": {"label": "Start", "config": {}} },
    { "id": "agent-1", "type": "agent", "position": {"x": 250, "y": 0},
      "data": {"label": "Incident Agent", "config": {"agent_id": "<uuid>", "agent_version": null, "input_template": "{{input}}"}} },
    { "id": "cond-1", "type": "condition", "position": {"x": 500, "y": 0},
      "data": {"label": "Severe?", "config": {"expression": "state['last_output'].get('severity') == 'high'"}} },
    { "id": "end-1", "type": "end", "position": {"x": 750, "y": 0}, "data": {"label": "End", "config": {}} }
  ],
  "edges": [
    { "id": "e1", "source": "start-1", "target": "agent-1" },
    { "id": "e2", "source": "agent-1", "target": "cond-1" },
    { "id": "e3", "source": "cond-1", "target": "end-1", "source_handle": "true" },
    { "id": "e4", "source": "cond-1", "target": "end-1", "source_handle": "false" }
  ],
  "viewport": {"x": 0, "y": 0, "zoom": 1}
}
```
Node `type` ∈ `start | end | agent | tool | llm | rag | api | condition`. Per-type `data.config`:

| type | config |
|---|---|
| start | `{input_schema?: object}` |
| end | `{output_key?: string}` |
| agent | `{agent_id, agent_version?: number|null, input_template?: string}` |
| tool | `{tool_id, tool_version?: number|null, input_mapping?: object}` |
| llm | `{provider_id?: string|null, model?: string|null, prompt_template: string, temperature?: number}` |
| rag | `{query_template: string, top_k?: number /*default 5*/}` |
| api | `{method: "GET"|"POST"|"PUT"|"PATCH"|"DELETE", url: string, headers?: object, body_template?: string, credential_ref?: string, timeout_seconds?: number}` |
| condition | `{expression: string}` — evaluated by a **restricted safe evaluator** (no `eval`): comparisons, boolean ops, literals, `state[...]` / `.get()` access only. Outgoing edges must use `source_handle` `"true"` / `"false"`. |

Validation rules (backend is authoritative; frontend mirrors for UX): exactly one `start`; ≥1 `end`; all edge endpoints exist; every node reachable from start; every non-end node has ≥1 outgoing edge; condition nodes have exactly one `true` and one `false` edge; referenced agents/tools exist in the same org; no cycles (loops are a tracked P2 item).

Runtime state (LangGraph `TypedDict`): `{input, last_output, outputs: {node_id: any}, execution_id, organization_id}`; templates use `{{input}}`, `{{last_output}}`, `{{outputs.<node_id>}}`.

### 8.2 Endpoints
```ts
Workflow = { id, name, description, status: "draft"|"valid"|"published"|"archived", current_version: number,
             definition: WorkflowDefinition, created_at, updated_at }
ValidationResult = { valid: boolean, issues: { node_id: string|null, edge_id: string|null, code: string, message: string }[] }
```
| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/workflows` | `{name, description?, definition}` | `201 Workflow` |
| GET | `/workflows` | pagination, `?search=` | `200 Page<Workflow>` |
| GET | `/workflows/{workflow_id}` | — | `200 Workflow` |
| PUT | `/workflows/{workflow_id}` | `{name?, description?, definition?}` | `200 Workflow` (definition change → new version) |
| POST | `/workflows/{workflow_id}/validate` | `{definition?}` (omit → stored) | `200 ValidationResult` |
| POST | `/workflows/{workflow_id}/publish` | — | `200 Workflow` (must validate) |
| POST | `/workflows/{workflow_id}/execute` | `{input}` | `202 Execution` (kind `workflow`; invalid → 422 with issues) |
| GET | `/workflows/{workflow_id}/versions` | — | `200 Page<{id, version, definition, created_at}>` |

## 9. Executions — org-scoped

```ts
Execution = { id, kind: "agent"|"agent_test"|"workflow"|"tool_test"|"chat", status: ExecStatus,
              resource_id: string, resource_version: number, input: any, output: any|null, error: string|null,
              correlation_id: string, created_by, created_at, started_at|null, finished_at|null, duration_ms|null }
ExecStatus = "queued"|"running"|"succeeded"|"failed"|"cancelled"
ExecutionEvent = { id, execution_id, sequence: number, event_type: string, node_id: string|null, payload: object, created_at }
```
`event_type` ∈ `execution.queued | execution.started | node.started | node.completed | node.failed | llm.token | log | execution.completed | execution.failed | execution.cancelled`.

| Method | Path | Notes |
|---|---|---|
| GET | `/executions` | pagination, `?status=&kind=&resource_id=` |
| GET | `/executions/{execution_id}` | |
| GET | `/executions/{execution_id}/events` | `?after_sequence=` → `{items: ExecutionEvent[]}` |
| GET | `/executions/{execution_id}/logs` | `{items: {timestamp, level, message, node_id}[]}` (derived from `log`/`node.failed` events) |
| GET | `/executions/{execution_id}/stream` | **SSE** (`text/event-stream`). Each message: `id: <sequence>`, `event: <event_type>`, `data: <ExecutionEvent JSON>`. Honors `Last-Event-ID` / `?after_sequence=`. Closes after terminal event. Auth via normal headers (frontend uses `fetch` streaming, not `EventSource`). Heartbeat comment `: ping` every 15 s. |
| POST | `/executions/{execution_id}/cancel` | `200 Execution`; sets cancel flag (Redis key `exec:cancel:<id>`) + status `cancelled` if queued |

## 10. Chat — org-scoped
```ts
ChatSession = { id, title, target_type: "agent"|"workflow", target_id, created_at, updated_at }
ChatMessage = { id, session_id, role: "user"|"assistant"|"system", content: string, execution_id: string|null, created_at }
```
| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/chat/sessions` | `{target_type, target_id, title?}` | `201 ChatSession` |
| GET | `/chat/sessions` | pagination | `200 Page<ChatSession>` |
| GET | `/chat/sessions/{session_id}/messages` | pagination | `200 Page<ChatMessage>` |
| POST | `/chat/sessions/{session_id}/messages` | `{content}` | `202 {user_message: ChatMessage, execution: Execution}` — the assistant message is persisted by the worker on completion; client streams `/executions/{id}/stream` (`llm.token` events carry `{"text": "..."}`) |

## 11. Deployments & audit (P1/P2, minimal)
- `GET /deployments`, `POST /deployments` `{resource_type: "agent"|"workflow", resource_id, environment: "dev"|"staging"|"production"}`, `GET /deployments/{id}` — records only (no cloud provisioning in 1.0.1).
- `GET /audit-logs` (requires `org.manage`) → `Page<{id, actor_id, action, resource_type, resource_id, metadata, created_at}>`.

## 12. Monitoring (no auth for health)
- `GET /health` → `200 {"status":"ok","version":"1.0.1","api_version":"v1"}` (liveness, no deps).
- `GET /ready` → `200|503 {"status":"ready"|"not_ready","checks":{"database":"ok","redis":"ok","kafka":"ok|disabled"}}`.
- `GET /metrics` → Prometheus text format (also mounted at root `/metrics` for scraping).
- `GET /monitoring/summary` (org-scoped) → `{executions_24h, succeeded_24h, failed_24h, avg_duration_ms, by_status: {..}, by_kind: {..}, agents, tools, workflows, active_provider: LLMProvider|null}`.

These three health paths are served under `/api/v1/*`; `/health` and `/ready` are also mounted at root for container probes.

---

## 13. Python interfaces between Backend (Agent 2) and Runtime (Agent 3)

The codebase is a modular monolith: workers import `app.*` from `backend/`. Ownership: **Agent 2** owns `backend/app/**` EXCEPT `backend/app/orchestrator/**`, `backend/app/messaging/**`, which **Agent 3** owns.

Agent 2 provides (Agent 3 consumes):
```python
# app/database/session.py
async_session_factory: async_sessionmaker[AsyncSession]
async def get_session() -> AsyncIterator[AsyncSession]           # FastAPI dependency
# app/database/models.py  — SQLAlchemy 2.0 models incl. Execution, ExecutionEvent, OutboxEvent, Agent, AgentVersion,
#                           Tool, ToolVersion, Workflow, WorkflowVersion, ChatMessage, DocumentChunk, LLMProvider
# app/executions/events.py
async def append_event(session, execution_id: UUID, event_type: str, payload: dict, node_id: str | None = None) -> ExecutionEvent
    # assigns next sequence, inserts row, then (after commit by caller) Redis PUBLISH "execution-events:<execution_id>" JSON
async def set_status(session, execution_id: UUID, status: str, *, output=None, error=None) -> None
# app/llm/manager.py
async def get_chat_model(session, organization_id: UUID, provider_id: UUID | None = None, model: str | None = None) -> BaseChatModel
    # LangChain chat model built from decrypted BYOK creds; returns FakeListChatModel-like mock when LLM_MOCK_MODE and key starts "mock-"
async def get_embeddings(session, organization_id: UUID) -> Embeddings
# app/core/config.py
settings: Settings   # pydantic-settings, env vars in section 15
```

Agent 3 provides (Agent 2 consumes):
```python
# app/orchestrator/validator.py
def validate_definition(definition: dict) -> list[ValidationIssue]     # pure, structural (no DB)
# app/orchestrator/safe_eval.py
def evaluate_condition(expression: str, state: dict) -> bool
# app/orchestrator/runtime.py
async def run_execution(execution_id: UUID) -> None   # loads execution, compiles LangGraph, runs, emits events, sets status
# app/messaging/dispatch.py
async def enqueue_execution(session, execution: Execution) -> None
    # Writes OutboxEvent row in the SAME transaction (caller commits). If settings.EXECUTION_DISPATCH == "inline",
    # schedules run_execution as an asyncio background task after commit (agent/workflow/chat only; tool_test → failed "sandbox requires tool-worker").
# app/messaging/outbox_relay.py
async def start_relay() -> None ; async def stop_relay() -> None    # called from FastAPI lifespan when EXECUTION_DISPATCH=="kafka"
```
`ValidationIssue` is a Pydantic model `{node_id, edge_id, code, message}` defined in `app/orchestrator/schemas.py` (Agent 3), along with Pydantic models for the workflow definition. Agent 2 imports them.

## 14. Kafka event contract

Envelope (JSON, UTF-8, key = `execution_id`):
```json
{ "event_id": "uuid", "event_type": "agent.execution.requested", "schema_version": "1.0",
  "organization_id": "uuid", "execution_id": "uuid", "correlation_id": "uuid",
  "resource_type": "agent|workflow|tool", "resource_id": "uuid", "resource_version": 1,
  "kind": "agent|agent_test|workflow|tool_test|chat", "timestamp": "ISO-8601", "attempt": 1, "payload": {} }
```
| Topic | Producer | Consumer group |
|---|---|---|
| `agent.execution.requested` | outbox relay (kinds agent, agent_test, chat-with-agent) | `agentforge-agent-worker` |
| `workflow.execution.requested` *(added; documented)* | outbox relay (kind workflow, chat-with-workflow) | `agentforge-workflow-worker` |
| `tool.execution.requested` *(added; documented)* | outbox relay (kind tool_test) and workflow runtime for tool nodes | `agentforge-tool-worker` |
| `agent.execution.started` / `.completed` / `.failed` | workers | (observability / future consumers) |
| `workflow.execution.events` | workflow worker (node lifecycle) | — |
| `tool.execution.events` | tool worker | — |
| `security.audit.events` | API audit logger | — |
| `<topic>.dlq` | consumer after max retries (3, exponential backoff 1s/4s/16s) | — |

Idempotency: consumers skip events whose `execution_id` is not `queued` (or already processed `event_id` recorded in Redis `evt:done:<event_id>` 24h TTL). Kafka is NOT the source of truth — Postgres is.

## 15. Environment variables (single source; `.env.example` mirrors this)
| Var | Default (dev) | Used by |
|---|---|---|
| `APP_ENV` | `development` | all |
| `DATABASE_URL` | `postgresql+asyncpg://agentforge:agentforge@postgres:5432/agentforge` | backend, workers |
| `REDIS_URL` | `redis://redis:6379/0` | backend, workers |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | backend, workers |
| `EXECUTION_DISPATCH` | `kafka` (`inline` for tests/no-Kafka) | backend |
| `JWT_SECRET` | *(required, no default in prod)* | backend |
| `ACCESS_TOKEN_TTL_SECONDS` / `REFRESH_TOKEN_TTL_SECONDS` | `900` / `604800` | backend |
| `CREDENTIAL_ENCRYPTION_KEY` | *(required; Fernet key)* | backend, workers |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | backend |
| `LLM_MOCK_MODE` | `false` (`true` in CI/tests) | backend, workers |
| `SANDBOX_IMAGE` | `agentforge-sandbox:1.0.1` | tool-worker |
| `SANDBOX_TIMEOUT_SECONDS` / `SANDBOX_MEMORY_MB` / `SANDBOX_CPUS` | `30` / `256` / `0.5` | tool-worker |
| `SANDBOX_ALLOWED_PACKAGES` | `requests,httpx,pydantic,python-dateutil` | backend, tool-worker |
| `SANDBOX_NETWORK` | `none` | tool-worker |
| `LOG_LEVEL` | `INFO` | all |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *(empty = disabled)* | backend, workers |
| `EMBEDDING_DIM` | `768` | backend (pgvector column) |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | frontend (build-time) |
| `VITE_DEMO_MODE` | `false` (`true` for GitHub Pages without backend) | frontend |
| `VITE_BASE_PATH` | `/` (`/<repo>/` for Pages) | frontend |
| `VITE_ROUTER_MODE` | `browser` (`hash` for Pages) | frontend |

## 16. Docker Compose service names (fixed)
`frontend` (:3000), `backend` (:8000), `postgres` (:5432, image `pgvector/pgvector:pg16`), `redis` (:6379), `kafka` (:9092, KRaft single node, profile `kafka`), `agent-worker`, `workflow-worker`, `tool-worker` (profile `workers`), `migrate` (one-shot `alembic upgrade head`), `prometheus` (:9090), `grafana` (:3001), `loki` (:3100) (profile `monitoring`).
Images: `ghcr.io/<owner>/agentforge-ai-frontend`, `-backend`, `-worker` (worker image = backend code + `workers/` + different entrypoint), `-sandbox`.

## 17. Contract decisions (orchestrator, 2026-11-13, after first build round)
- `AgentVersion.config` is a JSONB `AgentConfig` (§6) — runtime reads `version.config["instructions"]`, `["model"]`, `["provider_id"]`, `["tool_ids"]`, etc. No flattened columns.
- `OutboxEvent` fields: `id, topic, key, payload (JSONB envelope §14), created_at, published_at, attempts, last_error`. No `organization_id` column (it's inside payload).
- Chat executions carry the session id in `Execution.input = {"session_id": "<uuid>", "message": "<text>"}`.
- Credential resolution helper: `app.credentials.service.resolve_credential(session, organization_id, credential_id) -> str | None` (backend moves it from router.py to service.py; router re-imports it).
- `set_status` sets `started_at` on `running`, `finished_at` + `duration_ms` on terminal statuses.
- `audit_logs.organization_id` nullable (login events). Validator rejects fan-out from non-condition nodes (no parallel branches in 1.0.1) — frontend mirrors this rule.
- Extra env vars: `EXECUTION_TIMEOUT_SECONDS` (default 300), `LANGGRAPH_CHECKPOINTER` (`memory`|`postgres`, default `memory`).
