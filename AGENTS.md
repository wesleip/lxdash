# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project

LXD Manager — a web panel for managing LXD containers. See `PROJECT.md`, `ARCHITECTURE.md`, `STACK.md`, and `ROADMAP.md` for full context. No source code exists yet; `ROADMAP.md` defines the phase-by-phase build plan.

## Development commands

### Backend (FastAPI)

```bash
# Run dev server (from backend/)
uvicorn main:app --reload --port 8000

# Run tests
pytest

# Run a single test file
pytest tests/test_containers.py

# Generate DB migration after model changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

### Frontend (React + Vite)

```bash
# Dev server (from frontend/)
npm run dev

# Build
npm run build

# Type check
npx tsc --noEmit

# Regenerate TypeScript types from live API (requires backend running)
npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.ts
```

### Docker

```bash
# Development (hot reload)
docker-compose -f docker-compose.dev.yml up

# Production build
docker-compose up --build
```

## Architecture constraints

### Backend

- **`services/lxd_client.py` is the only file that imports `pylxd`**. Routers must never import pylxd directly. This is enforced to enable mocking in tests and to allow transport changes (Unix socket ↔ TLS) without touching routers.
- `pylxd` is synchronous internally — wrap all pylxd calls in `asyncio.to_thread()` to avoid blocking the FastAPI event loop.
- The database stores only what LXD doesn't know: users, hosts, audit_logs, api_tokens. Never replicate LXD state (container status, config, metrics) into the DB.
- `alembic upgrade head` is the only acceptable migration path in production — never use `Base.metadata.create_all()`.
- Audit log table is append-only; never issue DELETE on it.
- Never expose Python stack traces in HTTP responses.

### Frontend

- **React Query owns all server state.** Never store API data (containers, images, etc.) in Zustand.
- **Zustand owns only UI state** (sidebar open, active host, local filters, theme).
- Never use `fetch` or `axios` directly in components — go through the React Query query/mutation layer.
- TypeScript types for API responses come from `src/types/api.ts`, generated via `openapi-typescript`. Never type API responses manually.
- shadcn/ui components are copied into the project (not installed as a package) — edit them directly.

### Real-time patterns

- **SSE:** metrics (CPU/memory/network) pushed every 2s from `GET /containers/{name}/stats`
- **WebSocket:** interactive console (`WS /ws/containers/{name}/console`) and log streaming
- **Polling:** container list on the dashboard refetches every 5s via React Query `refetchInterval`

## Security rules

- JWT: 15-minute access token + 7-day refresh token
- CORS: explicit origins only — no wildcard in production
- The LXD Unix socket is mounted as a volume into the backend container; the FastAPI process user must be in the `lxd` group
- Rate limiting on auth endpoints is handled by Nginx, not the app

## Key stack decisions (see `STACK.md` for full rationale)

Do not introduce: Redis, Celery, GraphQL, Axios, MobX, Webpack. These were explicitly rejected. The table in `STACK.md` documents the reasons.
