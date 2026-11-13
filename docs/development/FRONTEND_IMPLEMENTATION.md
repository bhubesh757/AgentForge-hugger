# Frontend Implementation — AgentForge AI UI 1.0.0

## Stack
React 18 + TypeScript (strict) + Vite, React Router v6, TanStack Query, Tailwind CSS, React Flow (workflow canvas), Monaco (lazy-loaded code editor), Vitest + Testing Library. Package manager: `pnpm@12.18.0` (`packageManager` in `frontend/package.json`).

## Layout (`frontend/src`)
| Path | Purpose |
|---|---|
| `config.ts` | `UI_VERSION = '1.0.0'`, API version `v1`, env-derived settings |
| `api/client.ts` | fetch wrapper: base URL, bearer token, refresh-on-401, JSON error parsing |
| `api/errors.ts` | `ApiError` built from the contract error envelope (`docs/development/API_CONTRACTS.md`) |
| `api/endpoints.ts` | typed functions for every `/api/v1` endpoint |
| `api/sse.ts` | SSE client for execution event streams (`components/useExecutionStream.ts`) |
| `api/mock/` | in-browser demo backend (`db.ts` seed data, `adapter.ts` route handlers) |
| `api/session.ts`, `state/auth.tsx` | token storage and auth context / route guard |
| `types/` | contract DTO types |
| `features/workflow/` | node definitions, `serialize.ts` (React Flow <-> contract definition), `validate.ts` |
| `components/` | layout/nav, UI primitives, error boundary, event timeline, editor |
| `pages/` | route screens (below) |

## Pages / routes
`/login`, `/register`; inside the authenticated layout: dashboard, `agents`, `agents/:id`, `tools`, `workflows` (Workflow Studio), `chat`, `playground`, `cli`, `executions`, `executions/:id` (live SSE timeline), `monitoring`, `logs` (Ops), and admin screens `guardrails`, `credentials`, `deployments`, `organizations`, `users`, `providers`, `settings`.

## Workflow validation
`validateDefinition` returns issues with codes such as `NO_START`, `NO_END`, `DANGLING_EDGE`, `UNREACHABLE`, `CYCLE`, `CONDITION_BRANCHES` (condition needs both `true`/`false` handles), `FANOUT` (only condition nodes may have more than one outgoing edge), `MISSING_CONFIG`, `UNKNOWN_AGENT`. Save/run is blocked while errors exist.

## Demo mode
`VITE_DEMO_MODE=true` routes all API calls to the mock adapter (no backend required), with latency and seeded data per org. Demo login: `demo@agentforge.ai` / `demo-password`. Executions are simulated, including streamed events.

## Environment variables
| Var | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | Backend base URL |
| `VITE_DEMO_MODE` | `false` | Use in-browser mock backend |
| `VITE_ROUTER_MODE` | `browser` | `hash` for static hosting (GitHub Pages) |
| `VITE_BASE_PATH` | `/` | Vite `base` (asset prefix) |

## Commands (run in `frontend/`)
```bash
pnpm install
pnpm dev
pnpm typecheck
pnpm lint
pnpm test            # vitest run (non-watch)
pnpm build
# GitHub Pages demo build
VITE_DEMO_MODE=true VITE_ROUTER_MODE=hash VITE_BASE_PATH=/agentforge-ai/ pnpm build
```

## Tests (`src/test/`)
- `workflow.test.ts` — serializer round-trip and validator rules, including fan-out from non-condition nodes (9 tests)
- `api.test.ts` — API error parsing and mock adapter basics (6 tests)
- `render.test.tsx` — render smoke tests, auth redirect (4 tests)

## Known notes
- The Monaco chunk (`CodeEditor-*.js`, about 3.3 MB, 860 KB gzip) is lazy-loaded, so it is not part of the initial bundle.
- React Router v7 future-flag warnings show up in test output. They are harmless.
