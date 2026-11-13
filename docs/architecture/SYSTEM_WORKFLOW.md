# System Workflow

1. User registers/logs in → selects organization (header `X-Organization-ID`).
2. Connects Gemini or Azure OpenAI key (BYOK) → validate → activate (org default).
3. Creates agents (manual or AI-generated draft → review → save) and tools (AI-generated code → AST static analysis → sandbox test → publish).
4. Builds workflow in Workflow Studio → JSON (contract §8.1) → server validation → save version → publish.
5. Executes via Chat, API, CLI or Studio → API creates `Execution(queued)` + outbox row in one transaction.
6. Outbox relay publishes to `*.execution.requested` → matching worker consumes (idempotent) → LangGraph runtime runs nodes (LLM, RAG, API, condition, tool→sandbox).
7. Every node emits `execution_events` → Redis pub/sub → SSE `/executions/{id}/stream` → UI updates canvas/chat live.
8. Final status/output persisted; lifecycle events to Kafka; failures retried then DLQ; metrics on `/metrics`.
