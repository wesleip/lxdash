# LXD Manager — Visão Geral do Projeto

## O que é este projeto

Uma aplicação web para gerenciar containers LXC/LXD em um ou mais hosts Linux. Fornece uma interface gráfica intuitiva para operações que normalmente exigem acesso CLI ao host, além de uma API que abstrai e estende a API nativa do LXD.

## Objetivos

- Gerenciar o ciclo de vida de containers (criar, iniciar, parar, excluir, clonar, snapshot)
- Monitorar recursos em tempo real (CPU, memória, rede, disco)
- Acessar o console interativo de containers via browser
- Gerenciar redes virtuais, storage pools e imagens LXD
- Suportar múltiplos hosts LXD (fase 3 em diante)
- Controle de acesso por usuário com auditoria (fase 4 em diante)

## O que este projeto NÃO é

- Não é um substituto completo do LXD CLI para administradores avançados
- Não é uma solução de orquestração (Kubernetes, Nomad, etc.)
- Não gerencia VMs (apenas containers LXC)
- Não tem responsabilidade pelo provisionamento do host LXD em si

## Princípios de design

1. **API-first:** toda funcionalidade existe na API antes de existir na UI
2. **Progressivo:** começar simples, evoluir sem quebrar o que funciona
3. **Transparente:** operações refletem exatamente o que acontece no LXD — sem mágica escondida
4. **Seguro por padrão:** autenticação obrigatória, audit log desde o início
5. **Observável:** logs estruturados, erros com contexto, métricas expostas

## Stakeholders e usuários

| Perfil | Necessidade principal |
|---|---|
| Sysadmin solo | Gerenciar containers sem abrir SSH toda hora |
| Equipe pequena | Delegar operações básicas sem dar acesso root ao host |
| Dev/homelab | Interface visual para experimentação rápida |

## Links importantes

- [Arquitetura técnica](./ARCHITECTURE.md)
- [Stack e decisões técnicas](./STACK.md)
- [Roadmap e fases](./ROADMAP.md)
- [Padrões de código](./CODING_STANDARDS.md)
- [Integração com LXD](./LXD_INTEGRATION.md)
- [API Reference](./API.md)