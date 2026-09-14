# Stack e Decisões Técnicas

Este documento registra **o quê**, **por quê** e **o que foi descartado** para cada escolha técnica. Consultar antes de propor substituições.

---

## Backend

### Python 3.12 + FastAPI

**Escolhido porque:**
- `pylxd` (cliente oficial do LXD) é Python — evita criar bindings em outra linguagem
- FastAPI tem suporte nativo a async, WebSocket e SSE
- Pydantic v2 garante validação e serialização com performance adequada
- Ecossistema rico para autenticação (python-jose, passlib), ORM (SQLAlchemy) e migrations (Alembic)
- Curva de aprendizado baixa para novos colaboradores

**Descartado:**
- *Go:* mais performático, mas o ecossistema LXD em Go (lxd/client) é menos maduro para wrapping e o ganho de performance não justifica o custo
- *Node.js/Express:* sem cliente LXD nativo maduro; comunicação via Unix socket mais verbosa
- *Django:* overhead desnecessário para uma API; FastAPI resolve com menos código

**Versão mínima:** Python 3.12 (typing melhorado, performance de async)

---

### pylxd

**Escolhido porque:**
- Biblioteca oficial mantida pela Canonical
- Abstrai o protocolo REST do LXD incluindo operações assíncronas nativas do LXD (operations polling)
- Suporte a Unix socket e TLS transparentemente
- Cobre 95% dos endpoints necessários

**Cuidados:**
- pylxd usa `requests` (síncrono) internamente — wrappear chamadas bloqueantes em `asyncio.to_thread()` para não bloquear o event loop do FastAPI
- Para streaming de eventos do LXD (WebSocket nativo do daemon), usar `httpx` diretamente sobre o socket quando pylxd não suportar

---

### SQLAlchemy + Alembic + SQLite → PostgreSQL

**Escolhido porque:**
- SQLite: zero configuração, adequado para deploy single-host, arquivo único fácil de fazer backup
- SQLAlchemy: ORM maduro com suporte a SQLite e PostgreSQL sem trocar código de aplicação
- Alembic: migrations versionadas desde o dia 1 — nunca usar `create_all()` em produção

**Migração SQLite → PostgreSQL:**
Trocar apenas a connection string no `.env`. O código da aplicação não muda.

**Quando migrar:** quando houver mais de 1 instância do backend rodando simultaneamente (SQLite não suporta escritas concorrentes bem).

---

### Uvicorn

- Servidor ASGI padrão para FastAPI
- Em produção: `uvicorn main:app --workers 2` (ou Gunicorn com worker Uvicorn para process management)

---

## Frontend

### React 18 + TypeScript

**Escolhido porque:**
- Ecossistema mais maduro para os componentes críticos deste projeto: xterm.js (console), Recharts (gráficos), shadcn/ui (componentes)
- TypeScript garante contrato com os schemas da API — gerar tipos a partir do OpenAPI do FastAPI
- React Query resolve elegantemente o polling e cache do estado do LXD

**Descartado:**
- *Vue 3:* tecnicamente equivalente, mas xterm.js e os componentes de terminal têm integrações React mais maduras
- *Svelte/SvelteKit:* ecossistema ainda pequeno para os requisitos específicos deste projeto

---

### Vite

- Build tool padrão para projetos React modernos
- Dev server com HMR rápido
- Sem configuração complexa de webpack

---

### React Query (TanStack Query)

**Responsabilidade:** toda comunicação com a API — fetching, cache, refetch automático, mutações, invalidação de cache.

```typescript
// Padrão de uso — nunca usar fetch/axios diretamente nos componentes
const { data: containers } = useQuery({
  queryKey: ['containers'],
  queryFn: () => api.containers.list(),
  refetchInterval: 5000,  // polling para status em tempo real
})
```

---

### Zustand

**Responsabilidade:** apenas estado de UI que não vem da API.

```typescript
// Correto: estado de UI
const useUIStore = create(set => ({
  sidebarOpen: true,
  activeHost: null,
  toggleSidebar: () => set(s => ({ sidebarOpen: !s.sidebarOpen })),
}))

// Errado: não guardar estado do LXD no Zustand
// containers: [] ← isso é papel do React Query
```

---

### xterm.js

- Terminal emulator para browser, padrão da indústria (usado pelo VS Code, GitHub Codespaces)
- Integração: WebSocket bidirecional com o backend
- Addon `FitAddon` para redimensionamento automático
- Addon `WebLinksAddon` para links clicáveis no terminal

---

### TailwindCSS + shadcn/ui

- Tailwind: classes utilitárias, sem CSS customizado na maioria dos casos
- shadcn/ui: componentes acessíveis (Radix UI por baixo), copiados para o projeto (não instalados como dependência — permite customização total)
- Tema: dark mode suportado desde o início via CSS variables

---

### Recharts

- Biblioteca de charts baseada em React e D3
- Usada para: CPU usage (AreaChart), memória (AreaChart), rede in/out (LineChart)
- Alternativa considerada: Chart.js — descartado por integração mais verbosa com React

---

## Infraestrutura e Deploy

### Docker + Docker Compose

- Desenvolvimento: `docker-compose.dev.yml` com volumes para hot reload
- Produção: `docker-compose.yml` com build otimizado
- O socket Unix do LXD é montado como volume no container do backend

### Nginx

- Serve o build estático do frontend
- Reverse proxy para o backend FastAPI
- Termina TLS (certificado via Let's Encrypt ou self-signed para uso interno)
- Rate limiting nos endpoints de autenticação

---

## O que NÃO usar (e por quê)

| Tecnologia | Motivo para não usar |
|---|---|
| Redis | Sem necessidade de cache distribuído ou filas na fase atual |
| Celery | WebSocket/async do FastAPI resolve tasks em background sem overhead |
| GraphQL | Over-engineering para este caso de uso — REST é suficiente |
| Kubernetes | O projeto gerencia LXC, não precisa rodar em k8s |
| Webpack | Vite é mais rápido e simples |
| Axios | `fetch` nativo + React Query é suficiente; reduz dependências |
| MobX | Zustand resolve com 1/10 do boilerplate |

---

## Geração de tipos TypeScript a partir da API

O FastAPI gera OpenAPI schema automaticamente em `/openapi.json`. Usar `openapi-typescript` para gerar os tipos:

```bash
npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.ts
```

Executar sempre que a API mudar. Nunca tipar manualmente os responses da API.