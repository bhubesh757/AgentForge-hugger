# Target Architecture (Platform 1.0.1)

- **Control plane**: FastAPI modular monolith (`backend/app`), API v1 at `/api/v1`, JWT + refresh rotation, org-scoped RBAC via `X-Organization-ID`, Postgres 16 + pgvector, Alembic migrations, Fernet-encrypted BYOK secrets behind `SecretCipher`.
- **Data plane**: Python workers (`workers/`) consuming Kafka (single-node KRaft locally) via consumer groups; LangGraph runtime (`backend/app/orchestrator`) compiled from React Flow JSON; tools run only in hardened, network-less, non-root Docker sandbox containers launched by the trusted tool-worker.
- **Reliability**: transactional outbox → Kafka; idempotent consumers; 3 retries with backoff → DLQ; Postgres is source of truth; cancellation via Redis flag; checkpoints per node.
- **Streaming**: workers append `execution_events` (Postgres) + Redis pub/sub → API SSE → UI.
- **Frontend**: React 18 + TS + Tailwind, React Flow, Monaco; real mode against API or demo mode (in-browser mock) for GitHub Pages.
- **Delivery**: Docker Compose with profiles (`workers`, `kafka`, `monitoring`), GitHub Actions CI, GHCR images tagged by SHA/semver, GitHub Pages for the static UI. Kubernetes manifests are reference-only (future).

Contracts: `docs/development/API_CONTRACTS.md`.
