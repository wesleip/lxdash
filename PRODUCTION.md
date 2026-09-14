# Produção — Checklist de implantação

Guia para rodar o LXDash em uma máquina real, gerenciando containers LXD em produção.
O repositório hoje só tem o setup de desenvolvimento (mock LXD, SQLite, `--reload`).
Este documento enumera tudo o que precisa existir/mudar para ir para produção.

---

## 1. Pré-requisitos da máquina

- [ ] Linux com **LXD instalado e inicializado** (`lxd init`).
- [ ] Backend precisa acessar o socket LXD: usuario do container/processo deve estar no grupo `lxd`:
  ```bash
  usermod -aG lxd $USER
  ```
- [ ] Disco com espaço para os containers (thin-pool/zfs do LXD + crescimento).
- [ ] Portas abertas/firewall: 80/443 (web), 8000 (API, opcionalmente restrita ao Nginx).
- [ ] (Opcional) Postgres externo ou via container para persistência do banco.

---

## 2. Mudanças de código necessárias no repositório

### 2.1 Desligar o mock LXD
- `docker-compose.dev.yml:16` fixa `LXD_MOCK: "true"`. Em produção deve ser **false / removido**.
- Conferir `backend/config.py:55` (`LXD_MOCK: bool = False` é o default seguro).

### 2.2 Dockerfile de produção (backend)
- Só existe `backend/Dockerfile.dev` (roda `uvicorn --reload` e monta fonte via volume).
- Criar `backend/Dockerfile`:
  - Copiar código (sem bind-mount de volume);
  - Sem `--reload`;
  - `--workers` via `uvicorn` ou `gunicorn` + `uvicorn workers`;
  - Usuario não-root;
  - Instalar `psycopg2-binary` (já em `requirements.txt:13`).

### 2.3 Frente de servidor / Nginx
- Config ausente no repo (só citada no README).
- Os routers do backend ficam em `/auth`, `/users`, `/containers`, etc. (sem prefixo), e o frontend chama `/api` (`frontend/src/lib/api.ts:36`). No dev o proxy do Vite remove o prefixo.
- Criar `nginx.conf`/`nginx.dockerfile` que:
  - Sirva o build estático do frontend (`frontend/dist` de `npm run build`);
  - `location /api/ { proxy_pass http://backend:8000/; }` (remove o prefixo `/api`);
  - `location /ws { proxy_pass ... upgrade WebSocket }` (console em `routers/console.py`);
  - Termine TLS/HTTPS com o certificado.

### 2.4 Migrations no boot
- `main.py:94` cria tabelas com `Base.metadata.create_all`. Em produção usar:
  ```bash
  alembic upgrade head
  ```
  (deve rodar antes do uvicorn subir — entrypoint/init container).

### 2.5 Seed com credenciais reais
- `backend/seed.py:43-44` tem default `admin`/`admin`. Em produção passar usuário/senha fortes:
  ```bash
  python seed.py --username <usuario> --password <senha-forte> --email admin@dominio
  ```
- Ou criar um `seed` automatico apenas se nao existir usuário admin.

### 2.6 docker-compose.prod.yml
- Criar arquivo separado do dev com:
  - `backend` (imagem de produção, sem mock, com healthcheck `/health`);
  - `migrate` (one-shot `alembic upgrade head`);
  - `frontend` build estático + `nginx` (ou Nginx servindo ambos);
  - `db` (opcional) Postgres com volume persistente e secret;
  - mount do socket LXD: `/var/snap/lxd/common/lxd/unix.socket:/var/snap/lxd/common/lxd/unix.socket`.

---

## 3. Configuração `.env` de produção (`backend/.env`)

| Variável | Produção |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://user:pass@db/lxdash` (não SQLite) |
| `SECRET_KEY` | `openssl rand -hex 32` — **nunca** a que está no `.env` comitado (linha 17) |
| `CORS_ORIGINS` | `["https://lxdash.seudominio.com"]` (sem `localhost`) |
| `APP_ENV` | `production` (ativa log JSON em `main.py:48-53`) |
| `LOG_LEVEL` | `INFO` ou `WARNING` |
| `LXD_SOCKET_PATH` | caminho do socket LXD da maquina |
| `LXD_MOCK` | `false` |

> ⚠️ `backend/.env` já está commitado com um SECRET_KEY — regerar e garantir que
> `.gitignore:7` continue impedindo novo commit. Rotacionar a chave invalida tokens
> emitidos antes da troca (aceitavel no deploy inicial, nao em longas operações).

---

## 4. Passo a passo do deploy (resumo)

1. Aplicar as mudanças de código da seção 2.
2. Na maquina: `docker compose -f docker-compose.prod.yml build`.
3. Rodar migração: `docker compose ... run --rm migrate`.
4. Subir: `docker compose ... up -d`.
5. Criar admin real (se ainda não existe): `docker compose ... exec backend python seed.py --username ... --password ...`.
6. Validar: `curl https://dominio/health` → `{"status":"ok", ...}` e login no frontend.
7. Conferir que o painel **mostra os containers LXD reais da maquina** (não os mockados).

---

## 5. Backup e recuperação

- [ ] Backup do banco (Postgres dump / WAL) — usuários + audit log vivem aqui.
- [ ] Audit log é o único registro das mutações — garantir que sobreviva a restore.
- [ ] Volumes dos containers LXD são gerenciados pelo proprio LXD (backups via `lxc export`), fora do escopo do LXDash.

---

## 6. Segurança / hardening

- [ ] Senha do admin forte; mudar o default antes de expor.
- [ ] TLS termina no Nginx (HTTP/2, ciphers modernos).
- [ ] `JWT_SECRET` fora do código/imagem (env/secret do compose).
- [ ] Backend sem exposição pública se o Nginx estiver no mesmo host (bind 127.0.0.1 ou rede interna do compose).
- [ ] Restrigir acesso ao socket LXD (grupo `lxd` = praticamente root na maquina).
- [ ] Rever `CORS_ORIGINS` e `docs_url` (`/docs` pode ser restringido em produção).

---

## 7. Monitoramento e manutenção

- [ ] Healthcheck `/health` (ja existe em `main.py:159`) para o orquestrador.
- [ ] Logs JSON estruturados (`APP_ENV=production`) para coleta (Loki/ELK/etc.).
- [ ] Atualizações de dependencias pinadas (`requirements.txt`, `package.json`).
- [ ] Planejar upgrade: parar backend → `alembic upgrade head` → subir nova versao (rollback = down-grade via Alembic).

---

## 8. Pendências principais (resumo executivo)

1. **Remover o mock LXD** e apontar para o socket real. *(bloqueia tudo)*
2. **Criar Dockerfile + docker-compose de produção + Nginx com TLS.**
3. **Migrar banco para Postgres** e rodar `alembic upgrade head` no deploy.
4. **Regenerar `SECRET_KEY`** e forcar credenciais fortes no `seed.py`.
5. **Garantir usuario do backend no grupo `lxd`** da maquina host.