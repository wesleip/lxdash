# LXDash

A web-based management panel for LXD containers. Provides a clean interface for operations that normally require CLI access to the host, plus a REST API that extends the native LXD API with authentication and audit logging.

![Dashboard](https://raw.githubusercontent.com/wesleipp/lxdash/main/docs/screenshot-dashboard.png)

---

## Features

- **Container lifecycle** — create, start, stop, restart, delete, clone, snapshot
- **Real-time monitoring** — CPU, memory, and network metrics via SSE (updated every 2s)
- **Interactive console** — full terminal in the browser via xterm.js + WebSocket
- **Resource management** — networks, storage pools, and LXD images
- **JWT authentication** — access tokens (15 min) + refresh tokens (7 days)
- **Audit log** — immutable record of every mutating operation with user and timestamp
- **Multi-host ready** — architecture supports multiple LXD hosts from phase 3 (see roadmap)

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18 · TypeScript · Vite · TailwindCSS · shadcn/ui · React Query · Zustand |
| Backend | Python 3.12 · FastAPI · pylxd · SQLAlchemy · Alembic · structlog |
| Transport | REST · WebSocket (console) · SSE (metrics) |
| Database | SQLite (dev) → PostgreSQL (prod, same codebase) |
| Deploy | Docker · Docker Compose · Nginx |

## Getting started

### Requirements

- Docker and Docker Compose
- A Linux host with LXD installed (for production use)

### Development (no LXD required)

The dev environment runs with a mock LXD client that provides in-memory fake data so the full stack can be developed and tested without a real LXD daemon.

```bash
git clone https://github.com/wesleipp/lxdash
cd lxdash

# Start all services
docker compose -f docker-compose.dev.yml up --build

# In a separate terminal, create the initial admin user
docker compose -f docker-compose.dev.yml exec backend python seed.py
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

Default credentials: `admin` / `admin`

> **Change the default password and generate a proper `SECRET_KEY` before any production use.**  
> `openssl rand -hex 32`

### Production

```bash
cp backend/.env.example backend/.env
# Edit .env: set SECRET_KEY, DATABASE_URL, CORS_ORIGINS

docker compose up --build -d
```

The LXD Unix socket is mounted into the backend container. The process user must be a member of the `lxd` group on the host:

```bash
usermod -aG lxd $USER
```

## Project structure

```
lxdash/
├── backend/          # FastAPI application
│   ├── routers/      # HTTP + WebSocket endpoints
│   ├── services/     # Business logic (lxd_client.py is the only pylxd importer)
│   ├── models/       # SQLAlchemy models
│   ├── schemas/      # Pydantic request/response schemas
│   └── migrations/   # Alembic migrations
├── frontend/         # React application
│   └── src/
│       ├── pages/    # Route-level components
│       ├── store/    # Zustand stores (UI state only — server state lives in React Query)
│       └── lib/      # API client, query client, utilities
└── docker-compose.dev.yml
```

## Development commands

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev

# Regenerate TypeScript types after API changes
npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.ts
```

## License

[MIT](LICENSE)
