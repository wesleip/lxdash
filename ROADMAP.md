# Roadmap — LXD Manager

## Como usar este documento

Cada fase define o **escopo**, os **entregáveis concretos** e os **critérios de aceite**. Uma fase só está concluída quando todos os critérios de aceite forem atendidos. Não avançar para a próxima fase com itens pendentes — débito técnico nesta aplicação tem custo alto por causa da integração com estado real do host.

---

## Fase 1 — MVP: Gerenciamento Básico

**Objetivo:** conseguir fazer as operações mais comuns via UI sem precisar de CLI.

### Backend

- [ ] Estrutura inicial do projeto FastAPI com routers, services, schemas
- [ ] Conexão com LXD via Unix socket usando pylxd
- [ ] `GET /containers` — listar containers com status, IP, recursos básicos
- [ ] `GET /containers/{name}` — detalhes de um container
- [ ] `POST /containers` — criar container a partir de imagem
- [ ] `DELETE /containers/{name}` — excluir container
- [ ] `POST /containers/{name}/start` — iniciar
- [ ] `POST /containers/{name}/stop` — parar (com timeout configurável)
- [ ] `POST /containers/{name}/restart` — reiniciar
- [ ] `GET /images` — listar imagens disponíveis
- [ ] `POST /auth/login` — autenticação JWT
- [ ] `POST /auth/refresh` — renovar token
- [ ] Middleware de autenticação em todos os endpoints (exceto `/health` e `/auth/login`)
- [ ] Tabelas `users` e `audit_logs` com migrations Alembic
- [ ] Audit log registrando todas as mutações (criar/excluir/start/stop)
- [ ] `GET /health` retornando status e conectividade LXD
- [ ] Tratamento de erros do LXD com mensagens legíveis (não expor stack traces)

### Frontend

- [ ] Setup Vite + React + TypeScript + Tailwind + shadcn/ui
- [ ] Tela de login com JWT
- [ ] Dashboard: tabela de containers com status (running/stopped/frozen), IP, nome
- [ ] Ações por container: start, stop, restart, delete (com confirmação)
- [ ] Formulário "Criar container": nome, imagem, configuração básica
- [ ] Polling automático do dashboard a cada 5s
- [ ] Toast notifications para feedback de operações
- [ ] Estado de loading e erro tratados em todas as operações
- [ ] Layout responsivo (funcional em 1280px+)

### Critérios de aceite da Fase 1

- Criar, iniciar, parar e excluir um container sem abrir terminal
- Login com usuário/senha funcionando
- Toda operação de mutação registrada no audit log
- Nenhum stack trace exposto na UI ou na resposta da API
- Build Docker funcionando (backend + frontend)

---

## Fase 2 — Operacional: Métricas, Logs e Console

**Objetivo:** visibilidade completa do que acontece dentro dos containers.

### Backend

- [ ] `GET /containers/{name}/stats` — SSE com CPU%, memória, rede (atualização a cada 2s)
- [ ] `GET /containers/{name}/logs` — SSE com logs do container em tempo real
- [ ] `WS /ws/containers/{name}/console` — WebSocket bidirecional para console interativo
- [ ] `GET /containers/{name}/snapshots` — listar snapshots
- [ ] `POST /containers/{name}/snapshots` — criar snapshot
- [ ] `DELETE /containers/{name}/snapshots/{snapshot}` — excluir snapshot
- [ ] `POST /containers/{name}/snapshots/{snapshot}/restore` — restaurar snapshot
- [ ] `GET /networks` — listar redes LXD
- [ ] `POST /networks` — criar rede
- [ ] `DELETE /networks/{name}` — excluir rede
- [ ] `GET /storage` — listar storage pools e volumes
- [ ] `POST /storage/{pool}/volumes` — criar volume
- [ ] Endpoint para importar imagem por URL/fingerprint
- [ ] Endpoint para excluir imagem local

### Frontend

- [ ] Página de detalhes do container com abas: Overview, Console, Logs, Snapshots, Config
- [ ] Gráficos de CPU e memória em tempo real (Recharts + SSE)
- [ ] Gráfico de rede in/out em tempo real
- [ ] Console interativo integrado com xterm.js (resize automático, ctrl+c, ctrl+d)
- [ ] Viewer de logs com auto-scroll e botão de pause
- [ ] Gerenciamento de snapshots (listar, criar, restaurar, excluir)
- [ ] Página de Networks: listar, criar, excluir
- [ ] Página de Storage: listar pools e volumes
- [ ] Página de Images: listar, importar, excluir

### Critérios de aceite da Fase 2

- Abrir console de container em funcionamento e executar comandos
- Ver CPU e memória atualizando em tempo real sem refresh manual
- Criar e restaurar um snapshot com sucesso
- Criar uma nova rede bridge e associar a um container

---

## Fase 3 — Multi-host

**Objetivo:** gerenciar containers em múltiplos hosts LXD a partir de uma única interface.

### Backend

- [ ] Tabela `hosts` com endereço, tipo de conexão (socket/TLS), TLS cert, nome amigável
- [ ] `LXDClientManager`: pool de clientes, um por host registrado
- [ ] Todos os endpoints aceitam header `X-Host-ID` ou parâmetro `host_id`
- [ ] `GET /hosts` — listar hosts registrados e status de conectividade
- [ ] `POST /hosts` — registrar novo host (com validação de conectividade)
- [ ] `DELETE /hosts/{id}` — remover host
- [ ] `GET /hosts/{id}/health` — status detalhado do host
- [ ] Suporte a conexão via TLS (certificado cliente + servidor)
- [ ] Isolamento de operações: erro em um host não afeta os outros

### Frontend

- [ ] Seletor de host na sidebar (ou global no header)
- [ ] Dashboard unificado: opção de ver containers de todos os hosts ou filtrar por host
- [ ] Indicador visual de qual host está ativo
- [ ] Página de gerenciamento de hosts (adicionar, remover, testar conectividade)
- [ ] Breadcrumb mostrando host > container em páginas de detalhe

### Critérios de aceite da Fase 3

- Registrar 2 hosts LXD distintos e gerenciar containers de ambos sem trocar de interface
- Falha de conectividade em um host exibida claramente sem afetar o outro
- Console e métricas funcionando para hosts remotos via TLS

---

## Fase 4 — RBAC e Auditoria

**Objetivo:** permitir que equipes usem o sistema com controles de acesso granulares.

### Backend

- [ ] Roles: `admin`, `operator`, `viewer`
- [ ] `admin`: acesso total
- [ ] `operator`: pode operar containers existentes, não pode criar/excluir hosts
- [ ] `viewer`: apenas leitura (listar, ver métricas, ver logs — sem mutações)
- [ ] Permissões por host: um usuário pode ser operator em host-A e viewer em host-B
- [ ] Gerenciamento de usuários (criar, editar, desativar)
- [ ] API tokens para automação (sem expiração ou com TTL configurável)
- [ ] Interface de audit log com filtros (por usuário, por container, por tipo de operação, por período)
- [ ] Export do audit log em CSV

### Frontend

- [ ] Página de usuários (admin only)
- [ ] Página de audit log com filtros e paginação
- [ ] UI adaptada ao role do usuário logado (ocultar ações não permitidas)
- [ ] Gerenciamento de API tokens

### Critérios de aceite da Fase 4

- Usuário com role `viewer` não consegue executar nenhuma mutação (nem via API direta)
- Audit log registra todas as operações com usuário, timestamp e resultado
- Desativar um usuário invalida todos os seus tokens imediatamente

---

## Backlog (sem fase definida)

- Notificações por webhook (Slack, Discord, generic HTTP) para eventos de container
- Suporte a LXD clustering nativo (membros do cluster como uma unidade)
- Métricas históricas com Prometheus + Grafana (ou VictoriaMetrics)
- Template de containers (profiles como templates nomeados)
- Agendamento de operações (start às 08h, stop às 22h)
- Dark/light mode na UI
- Mobile-friendly (abaixo de 768px)
- i18n (pt-BR por padrão, en como segunda língua)

---

## Decisão de "pronto para próxima fase"

Antes de iniciar uma nova fase:
1. Todos os critérios de aceite da fase atual marcados
2. Sem erros conhecidos P0 ou P1 em aberto
3. Cobertura de testes nos services do backend ≥ 70%
4. CHANGELOG atualizado com o que foi entregue