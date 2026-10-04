import { useQuery } from '@tanstack/react-query'
import { hosts } from '@/lib/api'
import type { Host } from '@/types/api'
import { useUiStore } from '@/store/ui'

/**
 * Every LXD resource query is scoped to a host, so the host id is part of the
 * query key. Centralising the key here keeps the cache from serving one host's
 * containers after the operator switches to another.
 */
export const hostKeys = {
  all: ['hosts'] as const,
  list: () => [...hostKeys.all, 'list'] as const,
  health: (hostId: number) => [...hostKeys.all, 'health', hostId] as const,
}

/** Registered hosts, active or not.
 *
 * `refetchOnMount: 'always'` is deliberate: the hosts registry changes rarely
 * but each visit to the page must reflect the current database state. Without
 * it, a previous visit that landed while the DB was empty caches `[]` for the
 * 30s `staleTime` and a host registered in the meantime is invisible until the
 * cache goes stale.
 */
export function useHosts() {
  return useQuery({
    queryKey: hostKeys.list(),
    queryFn: ({ signal }) => hosts.list(signal),
    refetchOnMount: 'always',
  })
}

/** Hosts that can actually serve requests. */
export function useActiveHosts(): Host[] {
  const { data } = useHosts()
  return (data ?? []).filter((h) => h.is_active)
}

/**
 * The host the current view talks to.
 *
 * `null` when nothing is chosen, which the backend resolves to the single
 * registered host — and rejects with 422 as soon as there is more than one.
 * When a stored selection disappears (host removed, list not loaded yet) it
 * falls back to `null` instead of pinning a dead host id.
 */
export function useActiveHostId(): number | null {
  const activeHostId = useUiStore((s) => s.activeHostId)
  const { data, isLoading } = useHosts()

  if (isLoading || !data) return null
  if (activeHostId === null) return null
  return data.some((h) => h.id === activeHostId && h.is_active) ? activeHostId : null
}

/** The active host object, or null when none is chosen/available. */
export function useActiveHost(): Host | null {
  const activeHostId = useActiveHostId()
  const { data } = useHosts()
  if (!data || activeHostId === null) return null
  return data.find((h) => h.id === activeHostId && h.is_active) ?? null
}

/**
 * The host the UI should render as selected: the explicit choice, or — while
 * the choice is still "Automatic" (`activeHostId === null`) — the single
 * registered active host, which is exactly the host the backend would resolve
 * the request to.
 *
 * `null` only when there is genuinely nothing to point at: no hosts yet, or
 * several active hosts without a pick (the case that must ask the operator).
 */
export function useEffectiveHostId(): number | null {
  const selected = useActiveHostId()
  const { data, isLoading } = useHosts()

  if (selected !== null) return selected
  if (isLoading || !data) return null

  const active = data.filter((h) => h.is_active)
  return active.length === 1 ? active[0].id : null
}

/** Liveness probe for one host. Polled on its own so it cannot block the list. */
export function useHostHealth(hostId: number | null, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: hostKeys.health(hostId ?? 0),
    queryFn: ({ signal }) => hosts.health(hostId as number, signal),
    enabled: hostId !== null && options?.enabled !== false,
    refetchInterval: 30_000,
  })
}
