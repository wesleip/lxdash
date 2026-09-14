# Arquitetura Técnica — LXD Manager

## Visão em camadas

```
┌─────────────────────────────────────────────────┐
│  Frontend (React + TypeScript)                  │
│  Vite · React Query · Zustand · xterm.js        │
│  TailwindCSS · shadcn/ui · Recharts             │
└──────────────┬──────────────┬───────────────────┘
               │ REST/HTTP    │ WebSocket / SSE
┌──────────────▼──────────────▼───────────────────┐
│  Backend (FastAPI + Python 3.12)                │
│  Uvicorn · pylxd · SQLAlchemy · Alembic         │
│  JWT Auth · Pydantic v2                         │
└──────────────────────┬──────────────────────────┘
                       │ Unix Socket (ou TLS)
┌──────────────────────▼──────────────────────────┐
│  Host LXD                                       │
│  LXD Daemon · Containers · Networks · Storage   │
└─────────────────────────────────────────────────┘
```

## Componentes do Frontend

### Módulos de tela

| Módulo | Rota | Responsabilidade |
|---|---|---|
| Dashboard | `/` | Listagem de containers com status, ações rápidas |
| Container Detail | `/containers/:name` | Métricas, logs, config, snapshots, console |
| Terminal | `/containers/:name/console` | Console interativo via xterm.js + WebSocket |
| Images | `/images` | Listar, importar, excluir imagens LXD |
| Networks | `/networks` | Criar e gerenciar redes virtuais |
| Storage | `/storage` | Pools, volumes, configurações |
| Settings | `/settings` | Configuração de hosts, usuários, tokens |

### Gerenciamento de estado

- **React Query:** toda comunicação com a API — cache, refetch, mutations, invalidação
- **Zustand:** estado de UI puro — sidebar aberta, tema, filtros locais, host ativo selecionado
- **Sem Redux:** não há complexidade que justifique; React Query + Zustand são suficientes

### Comunicação em tempo real

- **WebSocket:** console interativo (bidirecional) e streaming de logs
- **SSE (Server-Sent Events):** métricas de CPU/memória/rede a cada 2s
- **Polling via React Query:** listagem de containers (refetch a cada 5s no dashboard)

## Componentes do Backend

### Estrutura de diretórios

```
backend/
├── main.py                  # Entrypoint FastAPI
├── config.py                # Settings via pydantic-settings
├── database.py              # Engine SQLAlchemy, SessionLocal
├── models/                  # SQLAlchemy models
│   ├── user.py
│   ├── host.py
│   └── audit_log.py
├── schemas/                 # Pydantic schemas (request/response)
│   ├── container.py
│   ├── image.py
│   ├── network.py
│   └── user.py
├── routers/                 # FastAPI routers
│   ├── containers.py
│   ├── images.py
│   ├── networks.py
│   ├── storage.py
│   ├── console.py           # WebSocket endpoints
│   ├── metrics.py           # SSE endpoints
│   └── auth.py
├── services/                # Lógica de negócio
│   ├── lxd_client.py        # Wrapper sobre pylxd
│   ├── auth_service.py
│   └── audit_service.py
├── dependencies.py          # FastAPI Depends() reutilizáveis
└── migrations/              # Alembic migrations
```

### Camada de serviços LXD

O `lxd_client.py` é o único ponto de contato com o `pylxd`. Nenhum router deve importar pylxd diretamente. Isso:

- Facilita mock em testes
- Centraliza tratamento de erros do LXD
- Permite trocar o transporte (Unix socket → TLS) sem tocar nos routers

### Fluxo de uma requisição típica

```
Browser → HTTPS → Nginx → FastAPI Router
  → Depends(get_current_user)   # valida JWT
  → Depends(get_lxd_client)     # retorna cliente para o host correto
  → Service.operacao()          # lógica, validação
  → lxd_client.chamada()        # chamada ao LXD
  → audit_service.log()         # registra operação
  → Response schema             # serializa com Pydantic
```

### Fluxo WebSocket (console)

```
Browser (xterm.js) ←──WS──→ FastAPI /ws/containers/{name}/console
                              ↕
                         pylxd container.execute() com stdin/stdout/stderr
                              ↕
                         LXD Daemon (Unix socket)
                              ↕
                         Processo dentro do container
```

## Banco de dados

### O que fica no banco (SQLite/Postgres)

O banco **não** replica o estado do LXD. O LXD é a fonte da verdade para containers, imagens, redes. O banco guarda apenas o que o LXD não sabe:

| Tabela | Conteúdo |
|---|---|
| `users` | Usuários, senha hash, role |
| `hosts` | Endereço, TLS cert, nome amigável (fase multi-host) |
| `audit_logs` | Quem fez o quê, quando, em qual container |
| `api_tokens` | Tokens de acesso para automação |

### Nunca guardar no banco

- Estado de containers (running/stopped) — consultar o LXD
- Configuração de containers — consultar o LXD
- Métricas históricas (fase 2: usar Prometheus/VictoriaMetrics externos)

## Deploy

### Desenvolvimento local

```
docker-compose.dev.yml
├── backend  (FastAPI com hot reload, porta 8000)
├── frontend (Vite dev server, porta 5173)
└── Volume: /var/snap/lxd/common/lxd/unix.socket → container backend
```

### Produção (single host)

```
docker-compose.yml
├── backend   (Uvicorn, 2 workers)
├── frontend  (Nginx servindo build estático)
└── nginx     (reverse proxy, TLS termination)
```

O socket Unix do LXD é montado como volume read/write no container do backend:
```yaml
volumes:
  - /var/snap/lxd/common/lxd/unix.socket:/var/snap/lxd/common/lxd/unix.socket
```

O usuário que roda o processo FastAPI precisa estar no grupo `lxd` do host.

## Segurança

- Toda comunicação frontend ↔ backend via HTTPS (Nginx com TLS)
- JWT com expiração curta (15min) + refresh token (7 dias)
- Acesso ao Unix socket do LXD restrito ao processo backend
- Audit log imutável (append-only, sem DELETE na tabela)
- CORS configurado explicitamente — sem wildcard em produção
- Rate limiting no Nginx para endpoints de autenticação

## Observabilidade

- **Logs:** estruturados em JSON via `structlog`, escritos em stdout
- **Erros:** stack traces capturados, nunca expostos na resposta HTTP ao cliente
- **Health check:** `GET /health` retorna status do backend e conectividade com LXD
- **Métricas (fase 2):** expor `/metrics` no formato Prometheus